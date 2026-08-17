from __future__ import annotations

import tempfile
import unittest
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

from research_digest.analysis.fake import FakeAnalyzer
from research_digest.coverage import (
    build_automatic_coverage_plan,
    build_coverage_scope,
    date_selection_from_dates,
)
from research_digest.db import Database
from research_digest.models import (
    AnalysisResult,
    Article,
    ArxivSourceConfig,
    DateSelection,
    InterestProfile,
    RunOrigin,
)
from research_digest.service import run_automatic_digest_for_enabled_profiles
from research_digest.sources.arxiv import ArxivDateRetrievalResult


class DateSource:
    def __init__(
        self,
        articles: list[Article],
        *,
        latest_date: date,
        incomplete_dates: tuple[date, ...] = (),
    ) -> None:
        self.articles = articles
        self.latest_date = latest_date
        self.incomplete_dates = incomplete_dates
        self.selections: list[DateSelection] = []

    def fetch(self, config: ArxivSourceConfig, *, now: datetime | None = None) -> list[Article]:
        if not config.enabled:
            return []
        return list(self.articles)

    def resolve_latest_available_date(self, config: ArxivSourceConfig) -> date | None:
        return self.latest_date if config.enabled else None

    def fetch_date_selection(
        self,
        config: ArxivSourceConfig,
        selection: DateSelection,
    ) -> ArxivDateRetrievalResult:
        self.selections.append(selection)
        requested_dates = selection.selected_dates()
        selected = set(requested_dates)
        articles = tuple(
            article
            for article in self.articles
            if config.enabled and article.published_at.date() in selected
        )
        incomplete = tuple(value for value in self.incomplete_dates if value in selected)
        covered = tuple(value for value in requested_dates if value not in incomplete)
        article_dates = {article.published_at.date() for article in articles}
        return ArxivDateRetrievalResult(
            selection=selection,
            articles=articles,
            requested_dates=requested_dates,
            covered_dates=covered,
            empty_dates=tuple(value for value in covered if value not in article_dates),
            incomplete_dates=incomplete,
            latest_available_date=self.latest_date,
            retrieved_count=len(articles),
            safety_limit=2000,
            safety_limit_reached=bool(incomplete),
        )


class FailingAnalyzer:
    def analyze(self, *, profile: InterestProfile, article: Article) -> AnalysisResult:
        raise AssertionError("service should call analyze_many")

    def analyze_many(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> Mapping[str, AnalysisResult]:
        raise RuntimeError("analysis failed")


def article(source_article_id: str, source_date: date) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title=f"Paper {source_article_id}",
        authors=["Ada Lovelace"],
        abstract="A paper about higher-dimensional gravity.",
        categories=["hep-th"],
        published_at=datetime(
            source_date.year,
            source_date.month,
            source_date.day,
            10,
            0,
            tzinfo=UTC,
        ),
        updated_at=datetime(
            source_date.year,
            source_date.month,
            source_date.day,
            11,
            0,
            tzinfo=UTC,
        ),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


class CoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.sqlite3")
        self.profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
        )
        self.config = cast(ArxivSourceConfig, self.db.get_arxiv_config())

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_date_selection_from_dates_prefers_compact_representations(self) -> None:
        self.assertEqual(
            date_selection_from_dates((date(2026, 8, 14),)),
            DateSelection.single_date(date(2026, 8, 14)),
        )
        self.assertEqual(
            date_selection_from_dates((date(2026, 8, 14), date(2026, 8, 15))),
            DateSelection.date_range(date(2026, 8, 14), date(2026, 8, 15)),
        )
        self.assertEqual(
            date_selection_from_dates((date(2026, 8, 14), date(2026, 8, 17))),
            DateSelection.explicit_dates((date(2026, 8, 14), date(2026, 8, 17))),
        )

    def test_catch_up_plans_uncovered_dates_from_anchor_to_latest(self) -> None:
        source = DateSource(
            [article("2608.14001", date(2026, 8, 14))],
            latest_date=date(2026, 8, 17),
        )
        scope = build_coverage_scope(
            profile=self.profile,
            source_name="arxiv",
            source_config=self.config,
        )
        self.db.mark_source_date_covered(
            profile_id=scope.profile_id,
            profile_fingerprint=scope.profile_fingerprint,
            source_name=scope.source_name,
            source_fingerprint=scope.source_fingerprint,
            source_date=date(2026, 8, 14),
            run_id=self.db.create_app_run(profile_id=self.profile.id, source_name="arxiv"),
            run_origin=RunOrigin.SCHEDULED,
        )

        plan = build_automatic_coverage_plan(
            db=self.db,
            profiles=(self.profile,),
            source_name="arxiv",
            source_config=self.config,
            latest_resolver=source,
            coverage_start_date=date(2026, 8, 14),
            catch_up_missed_dates=True,
        )

        self.assertEqual(
            plan.pending_dates,
            (date(2026, 8, 15), date(2026, 8, 16), date(2026, 8, 17)),
        )
        self.assertEqual(
            plan.date_selection,
            DateSelection.date_range(date(2026, 8, 15), date(2026, 8, 17)),
        )

    def test_catch_up_off_only_plans_latest_available_date(self) -> None:
        source = DateSource([], latest_date=date(2026, 8, 17))

        plan = build_automatic_coverage_plan(
            db=self.db,
            profiles=(self.profile,),
            source_name="arxiv",
            source_config=self.config,
            latest_resolver=source,
            coverage_start_date=date(2026, 8, 14),
            catch_up_missed_dates=False,
        )

        self.assertEqual(plan.pending_dates, (date(2026, 8, 17),))
        self.assertEqual(plan.date_selection, DateSelection.single_date(date(2026, 8, 17)))

    def test_scheduled_run_marks_retrieved_and_empty_dates_covered(self) -> None:
        source = DateSource(
            [article("2608.14001", date(2026, 8, 14))],
            latest_date=date(2026, 8, 16),
        )

        result = run_automatic_digest_for_enabled_profiles(
            db=self.db,
            source=source,
            analyzer=FakeAnalyzer(),
            coverage_start_date=date(2026, 8, 14),
            catch_up_missed_dates=True,
        )

        self.assertEqual(result.succeeded_count, 1)
        self.assertEqual(
            result.pending_source_dates,
            (date(2026, 8, 14), date(2026, 8, 15), date(2026, 8, 16)),
        )
        rows = self.db.list_source_date_coverage()
        self.assertEqual(
            [str(row["source_date"]) for row in rows],
            ["2026-08-16", "2026-08-15", "2026-08-14"],
        )

    def test_failed_date_remains_pending_for_retry(self) -> None:
        source = DateSource(
            [article("2608.14001", date(2026, 8, 14))],
            latest_date=date(2026, 8, 14),
        )

        first = run_automatic_digest_for_enabled_profiles(
            db=self.db,
            source=source,
            analyzer=FailingAnalyzer(),
            coverage_start_date=date(2026, 8, 14),
            catch_up_missed_dates=True,
        )
        second = run_automatic_digest_for_enabled_profiles(
            db=self.db,
            source=source,
            analyzer=FakeAnalyzer(),
            coverage_start_date=date(2026, 8, 14),
            catch_up_missed_dates=True,
        )

        self.assertEqual(first.failed_count, 1)
        self.assertEqual(first.pending_source_dates, (date(2026, 8, 14),))
        self.assertEqual(second.succeeded_count, 1)
        self.assertEqual(second.pending_source_dates, (date(2026, 8, 14),))
        self.assertEqual(len(self.db.list_source_date_coverage()), 1)

    def test_partial_retrieval_is_not_marked_covered(self) -> None:
        source = DateSource(
            [article("2608.14001", date(2026, 8, 14))],
            latest_date=date(2026, 8, 14),
            incomplete_dates=(date(2026, 8, 14),),
        )

        result = run_automatic_digest_for_enabled_profiles(
            db=self.db,
            source=source,
            analyzer=FakeAnalyzer(),
            coverage_start_date=date(2026, 8, 14),
            catch_up_missed_dates=True,
        )

        self.assertEqual(result.succeeded_count, 1)
        self.assertEqual(self.db.list_source_date_coverage(), [])

    def test_profile_semantic_change_reopens_date_for_new_scope(self) -> None:
        source = DateSource(
            [article("2608.14001", date(2026, 8, 14))],
            latest_date=date(2026, 8, 14),
        )
        run_automatic_digest_for_enabled_profiles(
            db=self.db,
            source=source,
            analyzer=FakeAnalyzer(),
            coverage_start_date=date(2026, 8, 14),
            catch_up_missed_dates=True,
        )
        changed = self.db.update_interest_profile(
            InterestProfile(
                id=self.profile.id,
                name=self.profile.name,
                description="Changed semantic meaning.",
                relevance_threshold=self.profile.relevance_threshold,
            )
        )

        plan = build_automatic_coverage_plan(
            db=self.db,
            profiles=(changed,),
            source_name="arxiv",
            source_config=self.config,
            latest_resolver=source,
            coverage_start_date=date(2026, 8, 14),
            catch_up_missed_dates=True,
        )

        self.assertEqual(plan.pending_dates, (date(2026, 8, 14),))

    def test_no_pending_dates_returns_noop_success(self) -> None:
        source = DateSource([], latest_date=date(2026, 8, 13))

        result = run_automatic_digest_for_enabled_profiles(
            db=self.db,
            source=source,
            analyzer=None,
            coverage_start_date=date(2026, 8, 14),
            catch_up_missed_dates=True,
        )

        self.assertEqual(result.succeeded_count, 0)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(result.pending_source_dates, ())


if __name__ == "__main__":
    unittest.main()
