import base64
import json
import os
import subprocess
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .i18n import t

WHAM = "https://chatgpt.com/backend-api/wham"
IMAGE_LIMIT_IDS = ("imagegen_premium", "image_gen")
# keyring 이 막히면 agy 가 HOME 아래 파일에 토큰을 저장한다. 추가 계정을 시스템 계정과 분리하는 유일한 방법이다.
NO_KEYRING = {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent"}


class LoginExpired(RuntimeError):
    pass


class RateLimited(RuntimeError):
    pass


def now():
    return datetime.now(timezone.utc)


def from_epoch(value):
    return datetime.fromtimestamp(float(value), timezone.utc) if value not in (None, "") else None


def from_iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) and value else None


def window(label, used, reset_at):
    if not isinstance(used, (int, float)):
        raise RuntimeError(t("사용률 값이 올바르지 않습니다: {v0}", v0=label))
    return {"label": label, "used": max(0.0, min(100.0, float(used))), "reset_at": reset_at}


def http_json(url, headers, data=None, method=None):
    request = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": "agent-usage", **headers})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response), response.headers
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise LoginExpired(t("로그인 만료")) from error
        if error.code == 429:
            raise RateLimited(t("대기")) from error
        raise RuntimeError(f"HTTP {error.code}: {url}") from error


def window_label(seconds):
    return {18000: "5h", 86400: "24h", 604800: t("주간")}.get(seconds) or (f"{seconds // 86400}d" if seconds % 86400 == 0 else f"{seconds // 3600}h")


# Codex

def jwt_claims(token):
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def codex_identity(home):
    tokens = json.loads((Path(home) / "auth.json").read_text())["tokens"]
    claims = jwt_claims(tokens["id_token"])
    email = claims.get("email") or claims.get("https://api.openai.com/profile", {}).get("email")
    return tokens["account_id"], email


def codex_headers(home):
    path = Path(home) / "auth.json"
    if not path.exists():
        raise LoginExpired(t("로그인 필요"))
    tokens = json.loads(path.read_text()).get("tokens") or {}
    if not tokens.get("access_token"):
        raise LoginExpired(t("로그인 필요"))
    return {"Authorization": f"Bearer {tokens['access_token']}", "ChatGPT-Account-Id": tokens["account_id"], "originator": "codex_cli_rs"}


def codex_refresh(home):
    # 토큰 갱신은 Codex 자신에게 맡긴다. 직접 갱신하면 CLI 가 쥔 refresh token 이 무효가 된다.
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "agent-usage", "version": "0.1.0"}}},
        {"jsonrpc": "2.0", "method": "initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read"},
    ]
    process = subprocess.Popen(["codex", "app-server"], env={**os.environ, "CODEX_HOME": str(home)},
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        process.stdin.write("".join(json.dumps(message) + "\n" for message in messages))
        process.stdin.flush()
        for line in process.stdout:
            reply = json.loads(line)
            if reply.get("id") == 2:
                return "result" in reply
    finally:
        process.kill()
    return False


def parse_reset_credits(payload):
    count = payload.get("available_count")
    credits = payload.get("credits")
    if not isinstance(count, int) or not isinstance(credits, list):
        raise RuntimeError(t("Codex 리셋권 응답 형식이 올바르지 않습니다."))
    expiries = sorted(from_iso(credit["expires_at"]) for credit in credits if credit.get("status") == "available")
    if len(expiries) != count:
        raise RuntimeError(t("Codex 리셋권 수와 만기일 수가 일치하지 않습니다."))
    return {"count": count, "expires": expiries}


def parse_image_headers(headers):
    if headers.get("x-codex-active-limit") not in IMAGE_LIMIT_IDS:
        raise RuntimeError(t("이미지 한도 헤더가 없습니다."))
    seconds = int(headers["x-codex-primary-window-minutes"]) * 60
    return window(t("이미지") + " · " + window_label(seconds), float(headers["x-codex-primary-used-percent"]),
                  from_epoch(headers.get("x-codex-primary-reset-at")))


def codex_image_limit(headers):
    # 빈 프롬프트는 서버가 400 으로 거절해 이미지를 만들지 않으면서 이미지 한도 헤더만 돌려준다.
    request = urllib.request.Request(f"https://chatgpt.com/backend-api/codex/images/generations", data=b'{"prompt":""}', method="POST",
                                     headers={"User-Agent": "agent-usage", "Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raise RuntimeError(t("이미지 한도 조회가 예상과 달리 성공했습니다: {v0}", v0=response.status))
    except urllib.error.HTTPError as error:
        if error.code != 400:
            raise RuntimeError(f"HTTP {error.code}: images/generations") from error
        return parse_image_headers(error.headers)


def parse_codex_usage(usage):
    rate = usage.get("rate_limit")
    if not isinstance(rate, dict):
        raise RuntimeError(t("Codex 사용량 정보가 없습니다."))
    windows = [window(window_label(source["limit_window_seconds"]), source.get("used_percent"), from_epoch(source.get("reset_at")))
               for source in (rate.get("primary_window"), rate.get("secondary_window")) if source]
    for extra in usage.get("additional_rate_limits") or []:
        for source in (extra.get("rate_limit") or {}).get("primary_window"), (extra.get("rate_limit") or {}).get("secondary_window"):
            if source:
                windows.append(window(f"{extra.get('limit_name')} · {window_label(source['limit_window_seconds'])}", source.get("used_percent"), from_epoch(source.get("reset_at"))))
    if not windows:
        raise RuntimeError(t("Codex 사용량 창이 없습니다."))
    return {"plan": usage.get("plan_type"), "windows": windows,
            "reset_count": (usage.get("rate_limit_reset_credits") or {}).get("available_count", 0)}


def fetch_codex(account):
    home = account["home"]
    headers = codex_headers(home)
    try:
        usage, _ = http_json(f"{WHAM}/usage", headers)
    except LoginExpired:
        if not codex_refresh(home):
            raise
        headers = codex_headers(home)
        usage, _ = http_json(f"{WHAM}/usage", headers)
    report = parse_codex_usage(usage)
    report["reset_credits"] = {"count": 0, "expires": []}
    if report.pop("reset_count"):
        report["reset_credits"] = parse_reset_credits(http_json(f"{WHAM}/rate-limit-reset-credits", headers)[0])
    try:
        report["image"] = codex_image_limit(headers)
    except RuntimeError as error:
        report["image_error"] = str(error)
    return report


def consume_reset_credit(account):
    payload, _ = http_json(f"{WHAM}/rate-limit-reset-credits/consume", {**codex_headers(account["home"]), "Content-Type": "application/json"},
                           data=json.dumps({"redeem_request_id": str(uuid.uuid4())}).encode(), method="POST")
    return payload.get("code")


# Claude

CLAUDE_PLANS = {"default_claude_max_20x": "Max 20x", "default_claude_max_5x": "Max 5x"}


def claude_paths(config_dir):
    if config_dir:
        return Path(config_dir) / ".credentials.json", Path(config_dir) / ".claude.json"
    return Path.home() / ".claude" / ".credentials.json", Path.home() / ".claude.json"


def antigravity_email(home):
    """시스템 계정만 키링에서 읽는다. 추가 계정은 HOME 아래 파일에 저장되는데 그 위치는 아직 확인하지 않았다."""
    if home:
        return None
    secret = subprocess.run(["secret-tool", "lookup", "service", "gemini", "username", "antigravity"], capture_output=True, text=True, timeout=5).stdout
    return json.loads(secret).get("id_token_email") if secret else None


def claude_email(config_dir):
    profile = claude_paths(config_dir)[1]
    return (json.loads(profile.read_text()).get("oauthAccount") or {}).get("emailAddress") if profile.exists() else None


def parse_claude_usage(usage):
    windows = [window(label, usage[key]["utilization"], from_iso(usage[key]["resets_at"]))
               for key, label in (("five_hour", "5h"), ("seven_day", t("주간"))) if usage.get(key)]
    for limit in usage.get("limits") or []:
        model = ((limit.get("scope") or {}).get("model") or {}).get("display_name")
        if limit.get("kind") == "weekly_scoped" and model:
            windows.append(window(f"{t('주간')} · {model}", limit.get("percent"), from_iso(limit.get("resets_at"))))
    if not windows:
        raise RuntimeError(t("Claude 사용량 창이 없습니다."))
    return windows


def fetch_claude(account):
    credentials = claude_paths(account.get("home"))[0]
    if not credentials.exists():
        raise LoginExpired(t("로그인 필요"))
    oauth = json.loads(credentials.read_text()).get("claudeAiOauth") or {}
    if not oauth.get("accessToken") or oauth.get("expiresAt", 0) / 1000 < now().timestamp():
        raise LoginExpired(t("로그인 만료"))
    usage, _ = http_json("https://api.anthropic.com/api/oauth/usage", {"Authorization": f"Bearer {oauth['accessToken']}", "anthropic-beta": "oauth-2025-04-20"})
    plan = CLAUDE_PLANS.get(oauth.get("rateLimitTier")) or (oauth.get("subscriptionType") or "").title() or None
    return {"plan": plan, "windows": parse_claude_usage(usage)}


# Antigravity

def antigravity_env(home):
    env = {**os.environ, "AGY_CLI_DISABLE_AUTO_UPDATE": "true"}
    return {**env, "HOME": str(home), **NO_KEYRING} if home else env


def parse_antigravity(stdout):
    if "Authentication required" in stdout:
        raise LoginExpired(t("로그인 필요"))
    for line in stdout.splitlines():
        if line.startswith("{") and '"command"' in line:
            groups = json.loads(line)["command"]["data"]["groups"]
            return [window(f"{group['name'].replace(' Models', '').replace(' models', '')} · {'5h' if bucket['window'] == '5h' else t('주간')}",
                           (1 - bucket["remaining_fraction"]) * 100, from_iso(bucket.get("reset_time")))
                    for group in groups for bucket in group["buckets"] if not bucket.get("disabled")]
    raise RuntimeError(t("agy 사용량 응답을 해석하지 못했습니다: {v0}", v0=stdout[:200]))


def fetch_antigravity(account):
    result = subprocess.run(["agy", "-p", "/usage", "--output-format", "json", "--print-timeout", "20s"], env=antigravity_env(account.get("home")),
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=40)
    return {"plan": None, "windows": parse_antigravity(result.stdout + result.stderr)}


FETCHERS = {"codex": fetch_codex, "claude": fetch_claude, "antigravity": fetch_antigravity}
LOGIN_ENV = {
    "codex": lambda home: {"CODEX_HOME": str(home)},
    "claude": lambda home: {"CLAUDE_CONFIG_DIR": str(home)},
    "antigravity": lambda home: {"HOME": str(home), **NO_KEYRING},
}
LOGIN_COMMANDS = {"codex": ["codex", "login"], "claude": ["claude", "auth", "login"], "antigravity": ["agy"]}


def fetch(account):
    try:
        return {**FETCHERS[account["provider"]](account), "status": "ok"}
    except LoginExpired as error:
        return {"status": "expired", "error": str(error), "windows": []}
    except RateLimited as error:
        return {"status": "limited", "error": str(error), "windows": []}
    except Exception as error:
        return {"status": "error", "error": str(error), "windows": []}
