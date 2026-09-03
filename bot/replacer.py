"""Keyword replace + multi-pair parse."""

from __future__ import annotations

import re
import unicodedata
from typing import List, Sequence, Tuple


def parse_pairs(text: str) -> List[Tuple[str, str]]:
    """Mk&Sk,xyz&SK  or  OLD | NEW  or  multiple lines."""
    text = (text or "").strip()
    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        text = parts[1].strip() if len(parts) > 1 else ""
    if not text:
        return []
    pairs: List[Tuple[str, str]] = []
    if " | " in text and "&" not in text and "," not in text.split(" | ", 1)[0]:
        a, b = text.split(" | ", 1)
        if a.strip():
            pairs.append((a.strip(), b.strip()))
        return pairs
    for chunk in re.split(r"[,;\n]+", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "&" in chunk:
            o, n = chunk.split("&", 1)
        elif " | " in chunk:
            o, n = chunk.split(" | ", 1)
        elif "|" in chunk:
            o, n = chunk.split("|", 1)
        else:
            continue
        o, n = o.strip(), n.strip()
        if o:
            pairs.append((o, n))
    return pairs


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
    flags = 0 if case_sensitive else re.IGNORECASE
    for rule in rules:
        if not getattr(rule, "enabled", True) or not rule.old_keyword:
            continue
        old = unicodedata.normalize("NFC", rule.old_keyword)
        new = unicodedata.normalize("NFC", rule.new_keyword)
        if match_mode == "word":
            pat = r"(?<!\w)" + re.escape(old) + r"(?!\w)"
        else:
            pat = re.escape(old)
        result = re.sub(pat, new, result, flags=flags)
    result = unicodedata.normalize("NFC", result)
    return result, result != original
