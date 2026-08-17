from __future__ import annotations

import unittest

from research_digest.models import TagOrigin
from research_digest.ui.tag_controls import (
    ai_tag_generation_label,
    collection_action_key,
    tag_action_key,
)


class TagUiHelperTests(unittest.TestCase):
    def test_tag_action_keys_are_stable_per_article_origin_and_tag(self) -> None:
        first = tag_action_key(
            article_id=1,
            action="remove",
            origin=TagOrigin.USER,
            normalized_name="black branes",
        )
        same = tag_action_key(
            article_id=1,
            action="remove",
            origin=TagOrigin.USER,
            normalized_name="black branes",
        )
        different_origin = tag_action_key(
            article_id=1,
            action="remove",
            origin=TagOrigin.AI,
            normalized_name="black branes",
        )
        different_article = tag_action_key(
            article_id=2,
            action="remove",
            origin=TagOrigin.USER,
            normalized_name="black branes",
        )

        self.assertEqual(first, same)
        self.assertNotEqual(first, different_origin)
        self.assertNotEqual(first, different_article)

    def test_tag_action_key_rejects_missing_article_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            tag_action_key(article_id=0, action="remove", origin=TagOrigin.USER)

    def test_ai_generation_label_reflects_existing_state(self) -> None:
        self.assertEqual(ai_tag_generation_label(has_ai_tags=False), "Generate AI tags")
        self.assertEqual(ai_tag_generation_label(has_ai_tags=True), "Regenerate AI tags")

    def test_collection_action_keys_are_stable_per_action_collection_and_article(self) -> None:
        first = collection_action_key(
            action="add_membership",
            collection_id=1,
            article_id=2,
        )
        same = collection_action_key(
            action="add_membership",
            collection_id=1,
            article_id=2,
        )
        different = collection_action_key(
            action="remove_membership",
            collection_id=1,
            article_id=2,
        )

        self.assertEqual(first, same)
        self.assertNotEqual(first, different)


if __name__ == "__main__":
    unittest.main()
