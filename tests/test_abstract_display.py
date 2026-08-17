from __future__ import annotations

import unittest

from research_digest.ui.abstracts import (
    ArticleIdentity,
    abstract_button_key,
    abstract_is_visible,
    abstract_state_key,
    abstract_toggle_label,
    displayable_abstract,
    toggle_abstract_visibility,
)


class AbstractDisplayTests(unittest.TestCase):
    def test_state_key_is_stable_for_article_identity(self) -> None:
        identity = ArticleIdentity(source="arxiv", source_article_id="2608.00001")

        self.assertEqual(abstract_state_key(identity), abstract_state_key(identity))
        self.assertTrue(abstract_state_key(identity).startswith("article_abstract_visible_"))

    def test_different_articles_have_independent_visibility_state(self) -> None:
        first = ArticleIdentity(source="arxiv", source_article_id="2608.00001")
        second = ArticleIdentity(source="arxiv", source_article_id="2608.00002")
        state: dict[str, object] = {}

        self.assertTrue(toggle_abstract_visibility(state, first))

        self.assertTrue(abstract_is_visible(state, first))
        self.assertFalse(abstract_is_visible(state, second))

    def test_button_key_includes_context_without_changing_state_key(self) -> None:
        identity = ArticleIdentity(source="arxiv", source_article_id="2608.00001")

        self.assertNotEqual(
            abstract_button_key(identity, context="today:1:relevant"),
            abstract_button_key(identity, context="history:1"),
        )
        self.assertEqual(abstract_state_key(identity), abstract_state_key(identity))

    def test_toggle_label_and_displayable_abstract(self) -> None:
        self.assertEqual(abstract_toggle_label(False), "Show abstract")
        self.assertEqual(abstract_toggle_label(True), "Hide abstract")
        self.assertEqual(displayable_abstract("  Line one.\nLine two.  "), "Line one.\nLine two.")
        self.assertIsNone(displayable_abstract(""))
        self.assertIsNone(displayable_abstract(None))


if __name__ == "__main__":
    unittest.main()
