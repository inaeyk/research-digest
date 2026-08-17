from __future__ import annotations

import tempfile
import unittest
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from research_digest.analysis.fake import FakeAnalyzer
from research_digest.db import APP_RUN_ANALYSIS_UNAVAILABLE, Database
from research_digest.history import get_run_snapshot, list_run_history
from research_digest.models import (
    AnalysisResult,
    Article,
    ArxivSourceConfig,
    DateSelection,
    InterestProfile,
    RunOrigin,
)
from research_digest.service import run_digest_for_profile
from research_digest.ui.pages.history import (
    _run_label,
    history_period_label,
    history_status_label,
    origin_label,
)


class StaticSource:
    def __init__(self, articles: list[Article]) -> None:
        self.articles = articles

    def fetch(self, config: ArxivSourceConfig, *, now: datetime | None = None) -> list[Article]:
        if not config.enabled:
            return []
        return list(self.articles[: config.max_results])


class DateStaticSource(StaticSource):
    def fetch_date_selection(
        self,
        config: ArxivSourceConfig,
        selection: DateSelection,
    ) -> object:
        from research_digest.sources.arxiv import ArxivDateRetrievalResult

        articles = tuple(self.articles if config.enabled else [])
        requested_dates = selection.selected_dates()
        article_dates = {item.published_at.date() for item in articles}
        return ArxivDateRetrievalResult(
            selection=selection,
            articles=articles,
            requested_dates=requested_dates,
            covered_dates=requested_dates,
            empty_dates=tuple(value for value in requested_dates if value not in article_dates),
            incomplete_dates=(),
            latest_available_date=None,
            retrieved_count=len(articles),
            safety_limit=2000,
            safety_limit_reached=False,
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
        raise RuntimeError(
            "provider failed at /home/"
            + "inaeyk/private with OPENAI_API_KEY=sk-"
            + "secret123456789"
        )


def article(source_article_id: str, title: str) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title=title,
        authors=["Ada Lovelace"],
        abstract=f"{title} abstract about higher-dimensional gravity.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


class HistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.sqlite3")
        self.profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
        )

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_completed_digest_run_writes_history_snapshot(self) -> None:
        result = run_digest_for_profile(
            db=self.db,
            source=StaticSource([article("2608.history01", "History paper")]),
            analyzer=FakeAnalyzer(),
            profile_id=self.profile.id or 0,
        )

        entries = list_run_history(self.db)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].run_id, result.digest.run_id)
        self.assertTrue(entries[0].has_snapshot)
        snapshot = get_run_snapshot(self.db, run_id=result.digest.run_id)
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot["run_id"], result.digest.run_id)
        self.assertEqual(snapshot["profile_name"], "Gravity")
        self.assertEqual(snapshot["items"][0]["title"], "History paper")
        self.assertEqual(snapshot["items"][0]["source"], "arxiv")
        self.assertEqual(snapshot["items"][0]["source_article_id"], "2608.history01")
        self.assertEqual(
            snapshot["items"][0]["abstract"],
            "History paper abstract about higher-dimensional gravity.",
        )

    def test_analysis_unavailable_run_has_sanitized_history_snapshot(self) -> None:
        result = run_digest_for_profile(
            db=self.db,
            source=StaticSource([article("2608.history02", "Failure paper")]),
            analyzer=FailingAnalyzer(),
            profile_id=self.profile.id or 0,
        )

        entries = list_run_history(self.db)
        self.assertEqual(result.digest.run_status, APP_RUN_ANALYSIS_UNAVAILABLE)
        self.assertEqual(entries[0].status, APP_RUN_ANALYSIS_UNAVAILABLE)
        self.assertTrue(entries[0].has_snapshot)
        self.assertIsNotNone(entries[0].error_message)
        assert entries[0].error_message is not None
        self.assertNotIn("/home/" + "inaeyk", entries[0].error_message)
        self.assertIn("Analysis unavailable", entries[0].error_message)
        snapshot = get_run_snapshot(self.db, run_id=entries[0].run_id)
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot["unresolved_articles"][0]["source_article_id"], "2608.history02")

    def test_current_profile_changes_do_not_mutate_history_snapshot(self) -> None:
        result = run_digest_for_profile(
            db=self.db,
            source=StaticSource([article("2608.history03", "Immutable paper")]),
            analyzer=FakeAnalyzer(),
            profile_id=self.profile.id or 0,
        )
        before = get_run_snapshot(self.db, run_id=result.digest.run_id)
        self.db.update_interest_profile(
            InterestProfile(
                id=self.profile.id,
                name="Changed profile",
                description="Changed description.",
            )
        )
        after = get_run_snapshot(self.db, run_id=result.digest.run_id)

        self.assertEqual(before, after)
        assert after is not None
        self.assertEqual(after["profile_name"], "Gravity")

    def test_history_limit_is_bounded(self) -> None:
        for index in range(3):
            run_digest_for_profile(
                db=self.db,
                source=StaticSource([article(f"2608.history1{index}", f"Paper {index}")]),
                analyzer=FakeAnalyzer(),
                profile_id=self.profile.id or 0,
            )

        entries = list_run_history(self.db, limit=2)

        self.assertEqual(len(entries), 2)
        self.assertGreater(entries[0].run_id, entries[1].run_id)

    def test_history_limit_must_be_positive(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            list_run_history(self.db, limit=0)

    def test_history_preserves_original_date_selection_metadata(self) -> None:
        selection = DateSelection.single_date(date(2026, 8, 14))
        result = run_digest_for_profile(
            db=self.db,
            source=DateStaticSource([article("2608.history04", "Date history paper")]),
            analyzer=FakeAnalyzer(),
            profile_id=self.profile.id or 0,
            date_selection=selection,
            run_origin=RunOrigin.MANUAL,
        )
        before = get_run_snapshot(self.db, run_id=result.digest.run_id)
        self.db.save_arxiv_config(ArxivSourceConfig(categories=["gr-qc"]))
        after = get_run_snapshot(self.db, run_id=result.digest.run_id)
        entries = list_run_history(self.db)

        self.assertEqual(before, after)
        assert after is not None
        self.assertEqual(after["date_selection"], selection.to_mapping())
        self.assertEqual(after["run_origin"], RunOrigin.MANUAL)
        self.assertEqual(after["requested_source_dates"], ["2026-08-14"])
        self.assertEqual(entries[0].date_selection, selection.to_mapping())
        self.assertEqual(entries[0].requested_source_dates, ("2026-08-14",))

    def test_history_labels_are_date_oriented(self) -> None:
        manual = run_digest_for_profile(
            db=self.db,
            source=DateStaticSource([article("2608.history05", "Manual paper")]),
            analyzer=FakeAnalyzer(),
            profile_id=self.profile.id or 0,
            date_selection=DateSelection.date_range(date(2026, 8, 14), date(2026, 8, 16)),
            run_origin=RunOrigin.MANUAL,
        )
        scheduled = run_digest_for_profile(
            db=self.db,
            source=DateStaticSource([article("2608.history06", "Scheduled paper")]),
            analyzer=FakeAnalyzer(),
            profile_id=self.profile.id or 0,
            date_selection=DateSelection.explicit_dates(
                (date(2026, 8, 12), date(2026, 8, 17))
            ),
            run_origin=RunOrigin.SCHEDULED,
        )
        entries = {entry.run_id: entry for entry in list_run_history(self.db)}

        self.assertEqual(
            history_period_label(entries[manual.digest.run_id]),
            "Aug 14, 2026 to Aug 16, 2026",
        )
        self.assertEqual(origin_label(entries[manual.digest.run_id]), "Manual")
        self.assertEqual(
            history_period_label(entries[scheduled.digest.run_id]),
            "Aug 12, 2026, Aug 17, 2026",
        )
        self.assertEqual(origin_label(entries[scheduled.digest.run_id]), "Scheduled")
        self.assertIn("preselected", _run_label(entries[scheduled.digest.run_id]))

    def test_history_labels_no_submission_and_legacy_runs(self) -> None:
        empty = run_digest_for_profile(
            db=self.db,
            source=DateStaticSource([]),
            analyzer=None,
            profile_id=self.profile.id or 0,
            date_selection=DateSelection.single_date(date(2026, 8, 18)),
            run_origin=RunOrigin.SCHEDULED,
        )
        legacy = run_digest_for_profile(
            db=self.db,
            source=StaticSource([article("2608.history07", "Legacy paper")]),
            analyzer=FakeAnalyzer(),
            profile_id=self.profile.id or 0,
        )
        entries = {entry.run_id: entry for entry in list_run_history(self.db)}

        self.assertEqual(history_status_label(entries[empty.digest.run_id]), "No submissions")
        self.assertEqual(history_period_label(entries[empty.digest.run_id]), "Aug 18, 2026")
        self.assertEqual(history_period_label(entries[legacy.digest.run_id]), "Legacy digest")
        self.assertEqual(origin_label(entries[legacy.digest.run_id]), "Legacy")


if __name__ == "__main__":
    unittest.main()
