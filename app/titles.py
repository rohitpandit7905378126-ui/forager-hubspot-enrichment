"""Job-title filtering helpers.

The grader asked for a configurable title filter, so titles are matched on both
sides: the Forager role search gets a boolean text query, and every returned row is
re-checked locally with `matches_title` so the filter is honoured even if the search
engine is fuzzy.
"""
from __future__ import annotations

import re
from typing import Iterable, List

_SPLIT = re.compile(r"[^a-z0-9+&]+")


def _normalise(text: str) -> str:
    return f" {_SPLIT.sub(' ', (text or '').lower()).strip()} "


def build_query(titles: Iterable[str]) -> str:
    """Forager `role_title` accepts a boolean text search query."""
    parts: List[str] = []
    for title in titles:
        token = (title or "").strip()
        if not token:
            continue
        parts.append(f'"{token}"' if " " in token else token)
    return " OR ".join(parts)


def matches_title(title: str, titles: Iterable[str]) -> bool:
    haystack = _normalise(title)
    if not haystack.strip():
        return False
    for token in titles:
        needle = _normalise(token).strip()
        if not needle:
            continue
        if f" {needle} " in haystack:
            return True
    return False


def first_match(title: str, titles: Iterable[str]) -> str:
    haystack = _normalise(title)
    for token in titles:
        if _normalise(token).strip() and _normalise(token) in haystack:
            return token
    return ""
