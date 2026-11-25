import json
import os
import shutil
import subprocess
import re
import uuid
from pathlib import Path

from . import providers
from .i18n import t

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "agent-usage"
STATE_PATH = CONFIG_DIR / "accounts.json"
ORCA_CODEX = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "orca" / "codex-accounts"
PROVIDERS = ("codex", "claude", "antigravity")
URL = re.compile(r"https://[^\s\x1b\x07]+")
ANSI = re.compile(r"\x1b\][^\x07\x1b]*(\x07|\x1b\\)|\x1b\[[0-9;?]*[A-Za-z]")


def load_state():
    if not STATE_PATH.exists():
        return {"accounts": [], "selected": {}}
    return json.loads(STATE_PATH.read_text())


def save_state(state):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    temporary.replace(STATE_PATH)


def system_accounts():
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    yield {"provider": "codex", "id": "system", "label": t("시스템 기본값"), "home": str(codex_home), "source": "system"}
    for home in sorted(ORCA_CODEX.glob("*/home")):
        if (home / "auth.json").exists():
            yield {"provider": "codex", "id": f"orca:{home.parent.name}", "label": None, "home": str(home), "source": "orca"}
    yield {"provider": "claude", "id": "system", "label": t("시스템 기본값"), "home": os.environ.get("CLAUDE_CONFIG_DIR"), "source": "system"}
    yield {"provider": "antigravity", "id": "system", "label": t("시스템 기본값"), "home": None, "source": "system"}


def account_email(account):
    try:
        if account["provider"] == "codex":
            return providers.codex_identity(account["home"])[1]
        if account["provider"] == "claude":
            return providers.claude_email(account["home"])
    except (OSError, KeyError, ValueError, IndexError):
        return None
    return None


def list_accounts(state):
    seen = set()
    result = []
    for account in [*system_accounts(), *({**item, "source": "own"} for item in state["accounts"])]:
        email = account_email(account)
        if account["provider"] == "codex":
            try:
                key = ("codex", *providers.codex_identity(account["home"]))
            except (OSError, KeyError, ValueError, IndexError):
                key = ("codex", account["id"])
            if key in seen:
                continue
            seen.add(key)
        result.append({**account, "label": account.get("label") or email or t("이름 없는 계정"), "email": email})
    return result


class LoginSession:
    """로그인 CLI 를 터미널 없이 실행한다. CLI 가 직접 브라우저를 열고, 붙여 넣을 코드는 pty 로 넘긴다."""

    def __init__(self, provider, home, label):
        self.provider, self.label = provider, label
        self.url = None
        self.cancelled = False
        self.lines = []
        env = providers.LOGIN_ENV[provider](home) if home else {}
        # agy 는 stdin 이 파이프면 로그인을 거부해서 pty 를 stdin 으로 준다.
        self.master, slave = os.openpty()
        self.process = subprocess.Popen(providers.LOGIN_COMMANDS[provider], stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        env={**os.environ, **env}, text=True, errors="replace")
        os.close(slave)

    def read(self, on_change):
        for line in self.process.stdout:
            clean = ANSI.sub("", line).strip()
            if clean:
                self.lines.append(clean)
            if self.url is None and (match := URL.search(line)):
                self.url = match.group(0)
                on_change()
        self.process.wait()
        os.close(self.master)

    def send_code(self, code):
        os.write(self.master, code.encode() + b"\n")

    def cancel(self):
        self.cancelled = True
        self.process.terminate()

    def result(self):
        return self.process.returncode == 0 or self.cancelled, self.lines[-1] if self.lines else ""


def start_login(provider, home, label):
    return LoginSession(provider, home, label)


def add_account(state, provider, label):
    if provider not in PROVIDERS:
        raise ValueError(provider)
    account_id = str(uuid.uuid4())
    home = CONFIG_DIR / "homes" / provider / account_id
    home.mkdir(parents=True, mode=0o700)
    state["accounts"].append({"provider": provider, "id": account_id, "label": label or None, "home": str(home)})
    save_state(state)
    return start_login(provider, home, label or provider)


def relogin(account):
    if account["source"] == "orca":
        raise RuntimeError(t("Orca 계정은 Orca에서 다시 로그인하세요."))
    return start_login(account["provider"], account["home"], account["label"])


def rename_account(state, account_id, label):
    for item in state["accounts"]:
        if item["id"] == account_id:
            item["label"] = label or None
    save_state(state)


def remove_account(state, account_id):
    item = next(item for item in state["accounts"] if item["id"] == account_id)
    home = Path(item["home"])
    if home.parent.parent != CONFIG_DIR / "homes":
        raise RuntimeError(t("이 위젯이 만든 계정만 지울 수 있습니다."))
    state["accounts"].remove(item)
    save_state(state)
    shutil.rmtree(home)
