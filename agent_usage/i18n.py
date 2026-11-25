import json
import locale
import os
from pathlib import Path

ENGLISH = json.loads(Path(__file__).with_name("translations.json").read_text(encoding="utf-8"))
LANGUAGE = os.environ.get("LANGUAGE", "").split(":")[0] or locale.getlocale()[0] or "en"
LANGUAGE = os.environ.get("AGENT_USAGE_LANGUAGE") or ("ko" if LANGUAGE.lower().startswith("ko") else "en")


def t(message, **values):
    text = ENGLISH[message] if LANGUAGE == "en" else message
    return text.format(**values) if values else text
