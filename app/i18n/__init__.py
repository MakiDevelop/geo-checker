"""Simple server-side i18n loader."""
from __future__ import annotations

import json
from pathlib import Path

SUPPORTED = {
    "zh-tw": "zh-TW",
    "zh-hant": "zh-TW",
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
    "en": "en-US",
    "en-us": "en-US",
    "ja": "ja-JP",
    "ja-jp": "ja-JP",
    "ko": "ko-KR",
    "ko-kr": "ko-KR",
}

_CACHE: dict[str, dict[str, str]] = {}


def _load_bundle(locale: str) -> dict[str, str]:
    if locale in _CACHE:
        return _CACHE[locale]
    path = Path(__file__).parent / f"{locale}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    _CACHE[locale] = data
    return data


def _pick_locale(accept_language: str | None) -> str:
    if not accept_language:
        return "en-US"
    for part in accept_language.split(","):
        code = part.split(";")[0].strip().lower()
        if code in SUPPORTED:
            return SUPPORTED[code]
        if "-" in code:
            base = code.split("-")[0]
            if base in SUPPORTED:
                return SUPPORTED[base]
    return "en-US"


def get_translations(request) -> dict[str, str]:
    locale = _pick_locale(request.headers.get("accept-language"))
    return _load_bundle(locale)
