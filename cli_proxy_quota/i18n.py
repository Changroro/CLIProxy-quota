import json
import locale
import os
from pathlib import Path

ENGLISH = json.loads(Path(__file__).with_name("translations.json").read_text(encoding="utf-8"))
LANGUAGE = "ko"


def set_language(choice):
    global LANGUAGE
    if choice not in ("system", "en", "ko"):
        raise ValueError("language must be system, en or ko")
    if choice == "system":
        language = os.environ.get("LANGUAGE", "").split(":")[0] or locale.getlocale()[0] or "en"
        choice = "ko" if language.lower().startswith("ko") else "en"
    LANGUAGE = choice


def t(message, **values):
    text = ENGLISH[message] if LANGUAGE == "en" else message
    return text.format(**values) if values else text


set_language(os.environ.get("CLIPROXY_LANGUAGE", "system"))
