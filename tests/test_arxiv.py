from __future__ import annotations

import unittest
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

from research_digest.models import ArxivSourceConfig
from research_digest.sources.arxiv import build_arxiv_url, parse_arxiv_atom, stable_arxiv_id

FIXTURE = Path(__file__).parent / "fixtures" / "arxiv_sample.xml"


class ArxivTests(unittest.TestCase):
    def test_build_query_supports_multiple_categories_with_encoding(self) -> None:
        config = ArxivSourceConfig(
            categories=["hep-th", "gr-qc"],
            lookback_hours=24,
            max_results=25,
        )
        url = build_arxiv_url(config)
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)

        self.assertEqual(params["search_query"], ["cat:hep-th OR cat:gr-qc"])
        self.assertEqual(params["max_results"], ["25"])
        self.assertEqual(params["sortBy"], ["submittedDate"])
        self.assertEqual(params["sortOrder"], ["descending"])

    def test_parse_filters_by_published_date_and_sorts_newest_first(self) -> None:
        payload = FIXTURE.read_bytes()
        articles = parse_arxiv_atom(
            payload,
            cutoff=datetime(2026, 8, 14, 8, 0, tzinfo=UTC),
        )

        self.assertEqual(
            [article.source_article_id for article in articles],
            ["2608.00001", "2608.00002"],
        )
        self.assertEqual(articles[0].title, "Warped compactifications and massive spin-2 spectra")
        self.assertIn("Kaluza-Klein spectrum", articles[0].abstract)
        self.assertEqual(articles[0].authors, ["Ada Lovelace", "Emmy Noether"])
        self.assertEqual(articles[0].categories, ["hep-th", "gr-qc"])
        self.assertEqual(articles[0].pdf_url, "http://arxiv.org/pdf/2608.00001v2")
        self.assertIsNone(articles[1].pdf_url)

    def test_parse_omits_old_entries(self) -> None:
        articles = parse_arxiv_atom(
            FIXTURE.read_bytes(),
            cutoff=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
        )

        self.assertEqual(articles, [])

    def test_stable_arxiv_id_strips_version(self) -> None:
        self.assertEqual(stable_arxiv_id("http://arxiv.org/abs/hep-th/9901001v3"), "hep-th/9901001")
        self.assertEqual(stable_arxiv_id("http://arxiv.org/abs/2608.00001v2"), "2608.00001")


if __name__ == "__main__":
    unittest.main()
