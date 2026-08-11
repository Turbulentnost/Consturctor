from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.I)
_COMMON_ENDINGS = (
    "ыми",
    "ими",
    "ого",
    "ему",
    "ами",
    "ями",
    "иях",
    "ого",
    "его",
    "ому",
    "ему",
    "ой",
    "ий",
    "ый",
    "ая",
    "ое",
    "ые",
    "ых",
    "их",
    "ам",
    "ям",
    "ом",
    "ем",
    "ах",
    "ях",
    "у",
    "ю",
    "а",
    "я",
    "ы",
    "и",
    "е",
)


def tokens(value: str) -> list[str]:
    return [_stem(match.group(0).lower().replace("ё", "е")) for match in _TOKEN_RE.finditer(value or "")]


def normalized(value: str) -> str:
    return " ".join(tokens(value))


def contains_phrase(text: str, phrase: str) -> bool:
    haystack = normalized(text)
    needle = normalized(phrase)
    return bool(needle) and needle in haystack


def token_similarity(left: str, right: str) -> float:
    a = set(tokens(left))
    b = set(tokens(right))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _stem(token: str) -> str:
    if len(token) <= 4:
        return token
    for ending in _COMMON_ENDINGS:
        if token.endswith(ending) and len(token) - len(ending) >= 4:
            return token[: -len(ending)]
    return token
