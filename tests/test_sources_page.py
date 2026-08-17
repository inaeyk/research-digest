from __future__ import annotations

import unittest

from research_digest.models import ArxivSourceConfig
from research_digest.ui.pages.sources import _parse_categories, updated_arxiv_config


class SourcesPageTests(unittest.TestCase):
    def test_parse_categories_accepts_commas_and_newlines(self) -> None:
        self.assertEqual(
            _parse_categories("hep-th, gr-qc\nmath-ph"),
            ["hep-th", "gr-qc", "math-ph"],
        )

    def test_updated_arxiv_config_preserves_legacy_retrieval_limits(self) -> None:
        existing = ArxivSourceConfig(
            enabled=True,
            categories=["hep-th"],
            lookback_hours=72,
            max_results=125,
        )

        updated = updated_arxiv_config(existing, False, "gr-qc\nhep-ph")

        self.assertFalse(updated.enabled)
        self.assertEqual(updated.categories, ["gr-qc", "hep-ph"])
        self.assertEqual(updated.lookback_hours, 72)
        self.assertEqual(updated.max_results, 125)

    def test_updated_arxiv_config_presents_categories_in_canonical_order(self) -> None:
        existing = ArxivSourceConfig(categories=["hep-th"])

        updated = updated_arxiv_config(existing, True, "hep-th\n gr-qc \nhep-th")

        self.assertEqual(updated.categories, ["gr-qc", "hep-th"])


if __name__ == "__main__":
    unittest.main()
