"""Unit tests for the keyword replacement engine."""

import pytest

from bot.database import KeywordRule
from bot.replacer import apply_replacements


def make_rule(old: str, new: str, enabled: bool = True) -> KeywordRule:
    rule = KeywordRule(
        chat_id=1,
        old_keyword=old,
        new_keyword=new,
        enabled=enabled,
    )
    return rule


class TestReplacer:
    def test_simple_replace(self):
        rules = [make_rule("OLDNAME", "@NewChannel")]
        text, changed = apply_replacements("Watch OLDNAME Movie", rules)
        assert changed is True
        assert text == "Watch @NewChannel Movie"

    def test_case_insensitive(self):
        rules = [make_rule("oldname", "@NewChannel")]
        text, changed = apply_replacements(
            "Watch OLDNAME Movie", rules, case_sensitive=False
        )
        assert changed is True
        assert text == "Watch @NewChannel Movie"

    def test_case_sensitive(self):
        rules = [make_rule("OLDNAME", "@NewChannel")]
        text, changed = apply_replacements(
            "Watch oldname Movie", rules, case_sensitive=True
        )
        assert changed is False
        assert text == "Watch oldname Movie"

    def test_multiple_rules(self):
        rules = [
            make_rule("ABC", "XYZ"),
            make_rule("OLDNAME", "NEWNAME"),
        ]
        text, changed = apply_replacements(
            "ABC and OLDNAME are here.", rules
        )
        assert changed is True
        assert text == "XYZ and NEWNAME are here."

    def test_no_match(self):
        rules = [make_rule("XYZ", "ABC")]
        text, changed = apply_replacements("Hello world", rules)
        assert changed is False
        assert text == "Hello world"

    def test_empty_text(self):
        rules = [make_rule("A", "B")]
        text, changed = apply_replacements("", rules)
        assert changed is False
        assert text == ""

    def test_unicode_hindi(self):
        rules = [make_rule("पुराना", "नया")]
        text, changed = apply_replacements("यह पुराना नाम है", rules)
        assert changed is True
        assert text == "यह नया नाम है"

    def test_emoji_and_special(self):
        rules = [make_rule("OLD", "🆕")]
        text, changed = apply_replacements("Download OLD 🔥 now", rules)
        assert changed is True
        assert text == "Download 🆕 🔥 now"

    def test_url_safe(self):
        rules = [make_rule("example.com", "newsite.com")]
        text, changed = apply_replacements(
            "Visit https://example.com/page", rules
        )
        assert changed is True
        assert "newsite.com" in text

    def test_word_mode(self):
        rules = [make_rule("cat", "dog")]
        text, changed = apply_replacements(
            "The cat and category", rules, match_mode="word"
        )
        assert changed is True
        assert text == "The dog and category"

    def test_contains_mode(self):
        rules = [make_rule("cat", "dog")]
        text, changed = apply_replacements(
            "The cat and category", rules, match_mode="contains"
        )
        assert changed is True
        assert text == "The dog and dogegory"

    def test_disabled_rule_ignored(self):
        rules = [make_rule("OLD", "NEW", enabled=False)]
        text, changed = apply_replacements("Hello OLD", rules)
        assert changed is False
        assert text == "Hello OLD"

    def test_empty_replacement(self):
        rules = [make_rule("REMOVE", "")]
        text, changed = apply_replacements("Please REMOVE this", rules)
        assert changed is True
        assert text == "Please  this"

    def test_identical_result_no_change_flag(self):
        rules = [make_rule("A", "A")]
        text, changed = apply_replacements("A test", rules)
        # After replacement it is the same
        assert text == "A test"
        # Depending on implementation, changed may be False
        # Our engine compares final vs original
        assert changed is False