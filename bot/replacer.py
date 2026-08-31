"""Keyword replacement + multi-pair parser."""

from __future__ import annotations

import re
import unicodedata
from typing import List, Sequence, Tuple


class RuleLike:
    old_keyword: str
    new_keyword: str
    enabled: bool


def _compile_pattern(keyword: str, case_sensitive: bool, match_mode: str) -> re.Pattern:
    flags = 0 if case_sensitive else re.IGNORECASE
    if match_mode == "word":
        pattern = r"(?<!\w)" + re.escape(keyword) + r"(?!\w)"
    else:
        pattern = re.escape(keyword)
    return re.compile(pattern, flags)


def apply_replacements(
    text: str,
    rules: Sequence,
    case_sensitive: bool = False,
    match_mode: str = "contains",
) -> Tuple[str, bool]:
    if not text or not rules:
        return text or "", False
    original = unicodedata.normalize("NFC", text)
    result = original
    for rule in rules:
        if not getattr(rule, "enabled", True) or not rule.old_keyword:
            continue
        old_k = unicodedata.normalize("NFC", rule.old_keyword)
        new_k = unicodedata.normalize("NFC", rule.new_keyword)
        pattern = _compile_pattern(old_k, case_sensitive, match_mode)
        result = pattern.sub(new_k, result)
    result = unicodedata.normalize("NFC", result)
    return result, result != original


def parse_multi_keywords(text: str) -> List[Tuple[str, str]]:
    """
    Parse: Mk&Sk,xyz&SK,1&2
    Also supports lines and " | " single pair.
    """
    text = (text or "").strip()
    if not text:
        return []
    # strip bot command if present
    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        text = parts[1].strip() if len(parts) > 1 else ""
    if not text:
        return []

    pairs: List[Tuple[str, str]] = []

    # Single pair with pipe
    if " | " in text and "&" not in text and "," not in text:
        a, b = text.split(" | ", 1)
        a, b = a.strip(), b.strip()
        if a:
            pairs.append((a, b))
        return pairs

    # Comma-separated old&new
    chunks = re.split(r"[,;\n]+", text)
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if "&" in chunk:
            old, new = chunk.split("&", 1)
            old, new = old.strip(), new.strip()
            if old:
                pairs.append((old, new))
        elif " | " in chunk:
            old, new = chunk.split(" | ", 1)
            old, new = old.strip(), new.strip()
            if old:
                pairs.append((old, new))
        elif "|" in chunk:
            old, new = chunk.split("|", 1)
            old, new = old.strip(), new.strip()
            if old:
                pairs.append((old, new))
    return pairs
