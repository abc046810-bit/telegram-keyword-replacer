"""Keyword replacement engine."""

from __future__ import annotations

import re
from typing import List, Sequence, Tuple

from bot.database import KeywordRule


def _compile_pattern(
    keyword: str, case_sensitive: bool, match_mode: str
) -> re.Pattern:
    flags = 0 if case_sensitive else re.IGNORECASE
    if match_mode == "word":
        # Word boundary matching (Unicode-aware as much as possible)
        pattern = r"(?<!\w)" + re.escape(keyword) + r"(?!\w)"
    else:
        # Simple substring (contains)
        pattern = re.escape(keyword)
    return re.compile(pattern, flags)


def apply_replacements(
    text: str,
    rules: Sequence[KeywordRule],
    case_sensitive: bool = False,
    match_mode: str = "contains",
) -> Tuple[str, bool]:
    """
    Apply all enabled keyword rules to the given text.

    Returns:
        (new_text, changed)
    """
    if not text or not rules:
        return text or "", False

    original = text
    result = text

    # Apply rules in order of addition (stable)
    for rule in rules:
        if not rule.enabled or not rule.old_keyword:
            continue
        pattern = _compile_pattern(rule.old_keyword, case_sensitive, match_mode)
        result = pattern.sub(rule.new_keyword, result)

    changed = result != original
    return result, changed


def preview_replacements(
    text: str,
    rules: Sequence[KeywordRule],
    case_sensitive: bool = False,
    match_mode: str = "contains",
) -> List[Tuple[str, str]]:
    """Return list of (old, new) that would be applied (for debugging)."""
    matches = []
    for rule in rules:
        if not rule.enabled:
            continue
        pattern = _compile_pattern(rule.old_keyword, case_sensitive, match_mode)
        if pattern.search(text):
            matches.append((rule.old_keyword, rule.new_keyword))
    return matches