from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest import mock

from streamlit.testing.v1 import AppTest

from research_digest.models import Article
from research_digest.ui.article_header import (
    MAX_VISIBLE_AUTHORS,
    format_article_metadata,
    format_authors,
)


def _article(authors: list[str]) -> Article:
    return Article(
        id=1,
        source="arxiv",
        source_article_id="2608.author-header",
        title="Author header paper",
        authors=authors,
        abstract="Stored source abstract.",
        categories=["hep-th", "gr-qc"],
        published_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 20, 12, 1, tzinfo=UTC),
        abstract_url="https://arxiv.org/abs/2608.author-header",
        pdf_url=None,
    )


# AppTest copies only this definition, so external annotations must stay quoted.
def _article_header_app(article: "Article") -> None:  # noqa: UP037
    from research_digest.ui.article_header import render_article_header

    render_article_header(article, context="article-header-test")


class ArticleHeaderUiTests(unittest.TestCase):
    def test_source_order_and_one_author_are_preserved(self) -> None:
        one = format_authors(["Juan Maldacena"])
        ordered = format_authors(
            ["Juan Maldacena", "Leonard Susskind", "Edward Witten"]
        )

        self.assertEqual(one.compact, "Juan Maldacena")
        self.assertEqual(one.hidden_count, 0)
        self.assertEqual(
            ordered.compact,
            "Juan Maldacena, Leonard Susskind, Edward Witten",
        )

    def test_five_author_boundary_shows_every_author(self) -> None:
        authors = [f"Author {index}" for index in range(1, MAX_VISIBLE_AUTHORS + 1)]

        presentation = format_authors(authors)

        self.assertEqual(presentation.compact, ", ".join(authors))
        self.assertEqual(presentation.full, presentation.compact)
        self.assertEqual(presentation.hidden_count, 0)

    def test_long_author_list_is_compact_and_full_list_is_accessible(self) -> None:
        authors = [
            "Alice Smith",
            "Bob Jones",
            "Carol Lee",
            "David Chen",
            "Eve Wang",
            *[f"Collaboration Member {index}" for index in range(1, 13)],
        ]
        presentation = format_authors(authors)
        self.assertEqual(
            presentation.compact,
            "Alice Smith, Bob Jones, Carol Lee, David Chen, Eve Wang, +12 more",
        )
        self.assertEqual(presentation.full, ", ".join(authors))

        at = AppTest.from_function(
            _article_header_app,
            default_timeout=5,
            args=(_article(authors),),
        ).run()

        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, presentation.compact)
        self.assertEqual([str(status.label) for status in at.status], ["Show all authors"])
        self.assert_text_present(at, presentation.full)
        self.assertEqual(str(at.main.children[0].value), "Author header paper")
        self.assertEqual(str(at.main.children[1].value), presentation.compact)
        self.assertIn("Published Aug 20, 2026", str(at.main.children[3].value))

    def test_missing_authors_uses_explicit_fallback(self) -> None:
        presentation = format_authors([])
        self.assertEqual(presentation.compact, "Authors unavailable")
        self.assertEqual(presentation.full, "Authors unavailable")

        at = AppTest.from_function(
            _article_header_app,
            default_timeout=5,
            args=(_article([]),),
        ).run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Authors unavailable")

    def test_metadata_line_is_deterministic_and_source_based(self) -> None:
        metadata = format_article_metadata(
            published_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
            categories=["hep-th", "gr-qc"],
            source="arxiv",
            source_article_id="2608.author-header",
        )
        self.assertEqual(
            metadata,
            "Published Aug 20, 2026 · hep-th · gr-qc · arXiv:2608.author-header",
        )

    def test_header_render_and_rerun_have_no_provider_or_source_side_effects(self) -> None:
        article = _article(["Ada Lovelace", "Grace Hopper"])
        forbidden = AssertionError("article header must be source-metadata presentation only")
        with (
            mock.patch("research_digest.ui.common.get_analyzer", side_effect=forbidden) as analyzer,
            mock.patch(
                "research_digest.ui.common.get_library_context_generator",
                side_effect=forbidden,
            ) as library_context,
            mock.patch(
                "research_digest.sources.arxiv.ArxivSource.fetch",
                side_effect=forbidden,
            ) as source_fetch,
        ):
            at = AppTest.from_function(
                _article_header_app,
                default_timeout=5,
                args=(article,),
            ).run()
            first_text = self._plain_text(at)
            at.run()
            second_text = self._plain_text(at)

        self.assert_no_streamlit_exceptions(at)
        self.assertEqual(first_text, second_text)
        analyzer.assert_not_called()
        library_context.assert_not_called()
        source_fetch.assert_not_called()

    def assert_no_streamlit_exceptions(self, at: AppTest) -> None:
        self.assertEqual([str(value) for value in at.exception], [])

    def assert_text_present(self, at: AppTest, expected: str) -> None:
        self.assertIn(expected, self._plain_text(at))

    def _plain_text(self, at: AppTest) -> str:
        return "\n".join(
            [str(element.value) for element in at.subheader]
            + [str(element.value) for element in at.markdown]
            + [str(element.value) for element in at.caption]
        )


if __name__ == "__main__":
    unittest.main()
