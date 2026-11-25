import json
import locale
import os
from pathlib import Path

ENGLISH = json.loads(Path(__file__).with_name("translations.json").read_text(encoding="utf-8"))
LANGUAGE = "ko"


def set_language(choice):
    """choice 는 system, ko, en. AGENT_USAGE_LANGUAGE 환경 변수가 있으면 그것이 이긴다."""
    global LANGUAGE
    choice = os.environ.get("AGENT_USAGE_LANGUAGE") or choice
    if choice not in ("system", "ko", "en"):
        raise ValueError(f"language must be system, ko or en: {choice}")
    if choice == "system":
        system = os.environ.get("LANGUAGE", "").split(":")[0] or locale.getlocale()[0] or "en"
        choice = "ko" if system.lower().startswith("ko") else "en"
    LANGUAGE = choice


def t(message, **values):
    text = ENGLISH[message] if LANGUAGE == "en" else message
    return text.format(**values) if values else text


set_language("system")
