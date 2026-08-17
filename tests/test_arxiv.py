from __future__ import annotations

import unittest
import urllib.parse
from datetime import UTC, date, datetime
from pathlib import Path

from research_digest import __version__
from research_digest.models import Article, ArxivSourceConfig, DateSelection
from research_digest.sources.arxiv import (
    DEFAULT_USER_AGENT,
    ArxivSource,
    build_arxiv_date_url,
    build_arxiv_url,
    parse_arxiv_atom,
    stable_arxiv_id,
)

FIXTURE = Path(__file__).parent / "fixtures" / "arxiv_sample.xml"


def article(source_article_id: str, published_at: datetime, *, title: str | None = None) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title=title or f"Paper {source_article_id}",
        authors=["Ada Lovelace"],
        abstract=f"Abstract for {source_article_id}.",
        categories=["hep-th"],
        published_at=published_at,
        updated_at=published_at,
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


class PagingArxivSource(ArxivSource):
    def __init__(self, pages: list[list[Article]]) -> None:
        super().__init__(endpoint="https://example.invalid")
        self.pages = pages
        self.urls: list[str] = []

    def _fetch_page(self, url: str) -> list[Article]:
        self.urls.append(url)
        if len(self.urls) > len(self.pages):
            return []
        return list(self.pages[len(self.urls) - 1])


class ArxivTests(unittest.TestCase):
    def test_default_user_agent_tracks_package_version(self) -> None:
        self.assertIn(f"ResearchDigest/{__version__}", DEFAULT_USER_AGENT)

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

    def test_date_url_uses_submitted_date_range_in_gmt(self) -> None:
        config = ArxivSourceConfig(categories=["hep-th", "gr-qc"])
        url = build_arxiv_date_url(
            config,
            start=500,
            max_results=250,
            selected_dates=(date(2026, 8, 14), date(2026, 8, 16)),
        )
        params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)

        self.assertEqual(params["start"], ["500"])
        self.assertEqual(params["max_results"], ["250"])
        self.assertEqual(params["sortBy"], ["submittedDate"])
        self.assertEqual(params["sortOrder"], ["descending"])
        self.assertEqual(
            params["search_query"],
            ["(cat:hep-th OR cat:gr-qc) AND submittedDate:[202608140000 TO 202608162359]"],
        )

    def test_fetch_single_date_covers_exact_utc_boundaries(self) -> None:
        source = PagingArxivSource(
            [
                [
                    article("2608.boundary2", datetime(2026, 8, 14, 23, 59, tzinfo=UTC)),
                    article("2608.boundary1", datetime(2026, 8, 14, 0, 0, tzinfo=UTC)),
                    article("2608.outside", datetime(2026, 8, 13, 23, 59, tzinfo=UTC)),
                ]
            ]
        )

        result = source.fetch_date_selection(
            ArxivSourceConfig(categories=["hep-th"]),
            DateSelection.single_date(date(2026, 8, 14)),
            page_size=10,
            safety_limit=10,
        )

        self.assertTrue(result.complete)
        self.assertEqual(result.requested_dates, (date(2026, 8, 14),))
        self.assertEqual(result.covered_dates, (date(2026, 8, 14),))
        self.assertEqual(result.empty_dates, ())
        self.assertEqual(result.incomplete_dates, ())
        self.assertEqual(
            [item.source_article_id for item in result.articles],
            ["2608.boundary2", "2608.boundary1"],
        )

    def test_fetch_multiple_explicit_dates_normalizes_and_orders_results(self) -> None:
        source = PagingArxivSource(
            [
                [article("2608.15001", datetime(2026, 8, 15, 12, 0, tzinfo=UTC))],
                [article("2608.17001", datetime(2026, 8, 17, 12, 0, tzinfo=UTC))],
            ]
        )

        result = source.fetch_date_selection(
            ArxivSourceConfig(categories=["hep-th"]),
            DateSelection.explicit_dates(
                [date(2026, 8, 15), date(2026, 8, 17), date(2026, 8, 15)]
            ),
            page_size=10,
            safety_limit=10,
        )

        self.assertEqual(result.requested_dates, (date(2026, 8, 15), date(2026, 8, 17)))
        self.assertEqual(
            [item.source_article_id for item in result.articles],
            ["2608.17001", "2608.15001"],
        )

    def test_fetch_date_range_marks_no_submission_dates_empty(self) -> None:
        source = PagingArxivSource(
            [[article("2608.14001", datetime(2026, 8, 14, 12, 0, tzinfo=UTC))]]
        )

        result = source.fetch_date_selection(
            ArxivSourceConfig(categories=["hep-th"]),
            DateSelection.date_range(date(2026, 8, 14), date(2026, 8, 16)),
            page_size=10,
            safety_limit=10,
        )

        self.assertEqual(
            result.covered_dates,
            (date(2026, 8, 14), date(2026, 8, 15), date(2026, 8, 16)),
        )
        self.assertEqual(result.empty_dates, (date(2026, 8, 15), date(2026, 8, 16)))

    def test_fetch_latest_available_resolves_to_date_with_source_material(self) -> None:
        latest = article("2608.latest", datetime(2026, 8, 17, 9, 0, tzinfo=UTC))
        source = PagingArxivSource([[latest], [latest]])

        result = source.fetch_date_selection(
            ArxivSourceConfig(categories=["hep-th"]),
            DateSelection.latest_available(),
            page_size=10,
            safety_limit=10,
        )

        self.assertEqual(result.latest_available_date, date(2026, 8, 17))
        self.assertEqual(result.requested_dates, (date(2026, 8, 17),))
        self.assertEqual(result.covered_dates, (date(2026, 8, 17),))
        self.assertEqual(result.retrieved_count, 1)

    def test_resolve_latest_available_date_uses_source_material(self) -> None:
        latest = article("2608.latest", datetime(2026, 8, 16, 23, 30, tzinfo=UTC))
        source = PagingArxivSource([[latest]])

        resolved = source.resolve_latest_available_date(ArxivSourceConfig(categories=["hep-th"]))

        self.assertEqual(resolved, date(2026, 8, 16))
        params = urllib.parse.parse_qs(urllib.parse.urlparse(source.urls[0]).query)
        self.assertEqual(params["max_results"], ["1"])
        self.assertEqual(params["sortBy"], ["submittedDate"])
        self.assertEqual(params["sortOrder"], ["descending"])

    def test_resolve_latest_available_date_returns_none_when_no_material_exists(self) -> None:
        source = PagingArxivSource([[]])

        self.assertIsNone(source.resolve_latest_available_date(ArxivSourceConfig(categories=["hep-th"])))

    def test_pagination_fetches_until_exhausted(self) -> None:
        source = PagingArxivSource(
            [
                [
                    article("2608.page3", datetime(2026, 8, 14, 12, 0, tzinfo=UTC)),
                    article("2608.page2", datetime(2026, 8, 14, 11, 0, tzinfo=UTC)),
                ],
                [article("2608.page1", datetime(2026, 8, 14, 10, 0, tzinfo=UTC))],
            ]
        )

        result = source.fetch_date_selection(
            ArxivSourceConfig(categories=["hep-th"]),
            DateSelection.single_date(date(2026, 8, 14)),
            page_size=2,
            safety_limit=10,
        )

        self.assertTrue(result.complete)
        self.assertEqual(result.retrieved_count, 3)
        self.assertEqual(len(source.urls), 2)
        starts = [
            urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["start"][0]
            for url in source.urls
        ]
        self.assertEqual(starts, ["0", "2"])

    def test_safety_cap_marks_coverage_incomplete(self) -> None:
        source = PagingArxivSource(
            [
                [
                    article("2608.cap2", datetime(2026, 8, 14, 12, 0, tzinfo=UTC)),
                    article("2608.cap1", datetime(2026, 8, 14, 11, 0, tzinfo=UTC)),
                ]
            ]
        )

        result = source.fetch_date_selection(
            ArxivSourceConfig(categories=["hep-th"]),
            DateSelection.single_date(date(2026, 8, 14)),
            page_size=2,
            safety_limit=2,
        )

        self.assertFalse(result.complete)
        self.assertTrue(result.safety_limit_reached)
        self.assertEqual(result.retrieved_count, 2)
        self.assertEqual(result.safety_limit, 2)
        self.assertEqual(result.covered_dates, ())
        self.assertEqual(result.incomplete_dates, (date(2026, 8, 14),))

    def test_duplicate_arxiv_entries_across_pages_are_deduplicated(self) -> None:
        duplicate = article("2608.duplicate", datetime(2026, 8, 14, 12, 0, tzinfo=UTC))
        source = PagingArxivSource(
            [
                [duplicate, article("2608.unique2", datetime(2026, 8, 14, 11, 0, tzinfo=UTC))],
                [duplicate, article("2608.unique1", datetime(2026, 8, 14, 10, 0, tzinfo=UTC))],
            ]
        )

        result = source.fetch_date_selection(
            ArxivSourceConfig(categories=["hep-th"]),
            DateSelection.single_date(date(2026, 8, 14)),
            page_size=2,
            safety_limit=10,
        )

        self.assertEqual(result.retrieved_count, 3)
        self.assertEqual(
            [item.source_article_id for item in result.articles],
            ["2608.duplicate", "2608.unique2", "2608.unique1"],
        )

    def test_sparse_explicit_dates_do_not_scan_intervening_off_dates(self) -> None:
        source = PagingArxivSource(
            [
                [article("2608.start", datetime(2026, 8, 14, 12, 0, tzinfo=UTC))],
                [article("2608.end", datetime(2026, 8, 17, 12, 0, tzinfo=UTC))],
            ]
        )

        result = source.fetch_date_selection(
            ArxivSourceConfig(categories=["hep-th"]),
            DateSelection.explicit_dates([date(2026, 8, 14), date(2026, 8, 17)]),
            page_size=10,
            safety_limit=10,
        )

        self.assertTrue(result.complete)
        self.assertEqual(len(source.urls), 2)
        queries = [
            urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["search_query"][0]
            for url in source.urls
        ]
        self.assertEqual(
            queries,
            [
                "(cat:hep-th) AND submittedDate:[202608140000 TO 202608142359]",
                "(cat:hep-th) AND submittedDate:[202608170000 TO 202608172359]",
            ],
        )
        self.assertEqual(
            [item.source_article_id for item in result.articles],
            ["2608.end", "2608.start"],
        )

    def test_explicit_date_global_safety_cap_marks_remaining_dates_incomplete(self) -> None:
        source = PagingArxivSource(
            [
                [
                    article("2608.cap2", datetime(2026, 8, 14, 12, 0, tzinfo=UTC)),
                    article("2608.cap1", datetime(2026, 8, 14, 11, 0, tzinfo=UTC)),
                ]
            ]
        )

        result = source.fetch_date_selection(
            ArxivSourceConfig(categories=["hep-th"]),
            DateSelection.explicit_dates([date(2026, 8, 14), date(2026, 8, 17)]),
            page_size=2,
            safety_limit=2,
        )

        self.assertFalse(result.complete)
        self.assertTrue(result.safety_limit_reached)
        self.assertEqual(result.retrieved_count, 2)
        self.assertEqual(result.covered_dates, ())
        self.assertEqual(result.incomplete_dates, (date(2026, 8, 14), date(2026, 8, 17)))
        self.assertEqual(len(source.urls), 1)

    def test_duplicate_arxiv_entries_across_category_queries_are_deduplicated(self) -> None:
        first = article(
            "2608.crosscat",
            datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
            title="Cross category paper",
        )
        duplicate = Article(
            id=None,
            source=first.source,
            source_article_id=first.source_article_id,
            title=first.title,
            authors=first.authors,
            abstract=first.abstract,
            categories=["gr-qc"],
            published_at=first.published_at,
            updated_at=first.updated_at,
            abstract_url=first.abstract_url,
            pdf_url=first.pdf_url,
        )
        source = PagingArxivSource([[first, duplicate]])

        result = source.fetch_date_selection(
            ArxivSourceConfig(categories=["hep-th", "gr-qc"]),
            DateSelection.single_date(date(2026, 8, 14)),
            page_size=10,
            safety_limit=10,
        )

        self.assertEqual(result.retrieved_count, 1)
        self.assertEqual(result.articles[0].source_article_id, "2608.crosscat")


if __name__ == "__main__":
    unittest.main()
