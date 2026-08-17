from __future__ import annotations

import hashlib
import json
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
    build_date_coverage_statuses,
    date_selection_from_dates,
    source_config_semantic_fingerprint,
)
from research_digest.db import (
    APP_RUN_ANALYSIS_UNAVAILABLE,
    APP_RUN_COMPLETED,
    APP_RUN_PARTIAL,
    SOURCE_ARXIV,
    Database,
)
from research_digest.models import (
    AnalysisResult,
    Article,
    ArxivSourceConfig,
    DateSelection,
    InterestProfile,
    RunOrigin,
    profile_semantic_fingerprint,
    source_date_from_datetime,
)
from research_digest.service import (
    run_automatic_digest_for_enabled_profiles,
    run_digest_for_profile,
)
from research_digest.sources.arxiv import ArxivDateRetrievalResult
from research_digest.sources.registry import SourceRunRequest


def legacy_source_fingerprint(categories: tuple[str, ...], *, enabled: bool = True) -> str:
    payload = {
        "source": "arxiv",
        "enabled": enabled,
        "categories": list(categories),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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

    def test_source_fingerprint_uses_category_set_semantics(self) -> None:
        first = ArxivSourceConfig(categories=["hep-th", "gr-qc"])
        reordered = ArxivSourceConfig(categories=[" gr-qc ", "hep-th", "hep-th"])
        changed = ArxivSourceConfig(categories=["hep-th", "astro-ph.CO"])

        self.assertEqual(
            source_config_semantic_fingerprint(first),
            source_config_semantic_fingerprint(reordered),
        )
        self.assertNotEqual(
            source_config_semantic_fingerprint(first),
            source_config_semantic_fingerprint(changed),
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

    def test_catch_up_latest_date_uses_chicago_source_date_helper(self) -> None:
        latest_source_date = source_date_from_datetime(
            datetime(2026, 8, 17, 4, 30, tzinfo=UTC)
        )
        source = DateSource([], latest_date=latest_source_date)

        plan = build_automatic_coverage_plan(
            db=self.db,
            profiles=(self.profile,),
            source_name="arxiv",
            source_config=self.config,
            latest_resolver=source,
            coverage_start_date=date(2026, 8, 16),
            catch_up_missed_dates=True,
        )

        self.assertEqual(latest_source_date, date(2026, 8, 16))
        self.assertEqual(plan.pending_dates, (date(2026, 8, 16),))
        self.assertEqual(plan.date_selection, DateSelection.single_date(date(2026, 8, 16)))

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
        statuses = {
            item.source_date: item
            for item in build_date_coverage_statuses(
                db=self.db,
                profile=self.profile,
                source_name=SOURCE_ARXIV,
                source_config=self.config,
                start_date=date(2026, 8, 14),
                end_date=date(2026, 8, 16),
            )
        }
        self.assertEqual(statuses[date(2026, 8, 14)].status, "completed")
        self.assertEqual(statuses[date(2026, 8, 15)].status, "empty")
        self.assertEqual(statuses[date(2026, 8, 15)].label, "Checked: no submissions")
        self.assertEqual(statuses[date(2026, 8, 16)].status, "empty")

    def test_manual_completed_date_marks_coverage_and_is_not_scheduled_again(self) -> None:
        source_date = date(2026, 8, 14)
        source = DateSource(
            [article("2608.14001", source_date)],
            latest_date=source_date,
        )

        manual = run_digest_for_profile(
            db=self.db,
            source=source,
            analyzer=FakeAnalyzer(),
            profile_id=cast(int, self.profile.id),
            date_selection=DateSelection.single_date(source_date),
            run_origin=RunOrigin.MANUAL,
        )
        plan = build_automatic_coverage_plan(
            db=self.db,
            profiles=(self.profile,),
            source_name=SOURCE_ARXIV,
            source_config=self.config,
            latest_resolver=source,
            coverage_start_date=source_date,
            catch_up_missed_dates=True,
        )
        scheduled = run_automatic_digest_for_enabled_profiles(
            db=self.db,
            source=source,
            analyzer=FakeAnalyzer(),
            coverage_start_date=source_date,
            catch_up_missed_dates=True,
        )
        statuses = build_date_coverage_statuses(
            db=self.db,
            profile=self.profile,
            source_name=SOURCE_ARXIV,
            source_config=self.config,
            start_date=source_date,
            end_date=source_date,
            selected_dates=(source_date,),
            pending_dates=plan.pending_dates,
        )

        self.assertEqual(manual.digest.run_origin, RunOrigin.MANUAL)
        self.assertEqual(plan.pending_dates, ())
        self.assertEqual(scheduled.profiles, ())
        self.assertEqual(scheduled.pending_source_dates, ())
        self.assertEqual(len(self.db.list_source_date_coverage()), 1)
        self.assertEqual(statuses[0].status, "completed")
        self.assertTrue(statuses[0].selected)

    def test_reordered_categories_keep_completed_dates_and_pending_plan(self) -> None:
        source_date = date(2026, 8, 14)
        original_config = ArxivSourceConfig(categories=["hep-th", "gr-qc"])
        reordered_config = ArxivSourceConfig(categories=["gr-qc", "hep-th"])
        source = DateSource([article("2608.14001", source_date)], latest_date=source_date)
        run = run_digest_for_profile(
            db=self.db,
            source=source,
            analyzer=FakeAnalyzer(),
            profile_id=cast(int, self.profile.id),
            source_request=SourceRunRequest(
                source_name=SOURCE_ARXIV,
                adapter=source,
                config=original_config,
            ),
            date_selection=DateSelection.single_date(source_date),
            run_origin=RunOrigin.MANUAL,
        )

        plan = build_automatic_coverage_plan(
            db=self.db,
            profiles=(self.profile,),
            source_name=SOURCE_ARXIV,
            source_config=reordered_config,
            latest_resolver=source,
            coverage_start_date=source_date,
            catch_up_missed_dates=True,
        )
        today_status = build_date_coverage_statuses(
            db=self.db,
            profile=self.profile,
            source_name=SOURCE_ARXIV,
            source_config=reordered_config,
            start_date=source_date,
            end_date=source_date,
            selected_dates=(source_date,),
            pending_dates=plan.pending_dates,
        )[0]
        automatic_status = build_date_coverage_statuses(
            db=self.db,
            profile=self.profile,
            source_name=SOURCE_ARXIV,
            source_config=reordered_config,
            start_date=source_date,
            end_date=source_date,
            pending_dates=plan.pending_dates,
        )[0]
        scheduled = run_automatic_digest_for_enabled_profiles(
            db=self.db,
            source=source,
            analyzer=FakeAnalyzer(),
            source_request=SourceRunRequest(
                source_name=SOURCE_ARXIV,
                adapter=source,
                config=reordered_config,
            ),
            coverage_start_date=source_date,
            catch_up_missed_dates=True,
        )

        self.assertEqual(plan.pending_dates, ())
        self.assertEqual(today_status.status, "completed")
        self.assertTrue(today_status.selected)
        self.assertEqual(automatic_status.status, "completed")
        self.assertEqual(scheduled.profiles, ())
        self.assertEqual(len(self.db.get_app_runs()), 1)
        self.assertEqual(run.digest.run_id, self.db.get_app_runs()[0]["id"])

    def test_legacy_order_sensitive_coverage_is_recognized_after_reorder(self) -> None:
        source_date = date(2026, 8, 14)
        source = DateSource([], latest_date=source_date)
        legacy_fingerprint = legacy_source_fingerprint(("hep-th", "gr-qc"))
        run_id = self.db.create_app_run(
            profile_id=self.profile.id,
            profile_fingerprint=profile_semantic_fingerprint(self.profile),
            source_name=SOURCE_ARXIV,
            source_fingerprint=legacy_fingerprint,
            date_selection=DateSelection.single_date(source_date),
        )
        self.db.finish_app_run(
            run_id,
            status=APP_RUN_COMPLETED,
            retrieved_count=19,
            stored_count=19,
            preselected_count=17,
            skipped_analysis_count=2,
            analyzed_count=17,
            relevant_count=2,
            requested_source_dates=(source_date.isoformat(),),
            covered_source_dates=(source_date.isoformat(),),
        )
        self.db.mark_source_date_covered(
            profile_id=cast(int, self.profile.id),
            profile_fingerprint=profile_semantic_fingerprint(self.profile),
            source_name=SOURCE_ARXIV,
            source_fingerprint=legacy_fingerprint,
            source_date=source_date,
            run_id=run_id,
            run_origin=RunOrigin.MANUAL,
        )
        reordered_config = ArxivSourceConfig(categories=["gr-qc", "hep-th"])

        plan = build_automatic_coverage_plan(
            db=self.db,
            profiles=(self.profile,),
            source_name=SOURCE_ARXIV,
            source_config=reordered_config,
            latest_resolver=source,
            coverage_start_date=source_date,
            catch_up_missed_dates=True,
        )
        status = build_date_coverage_statuses(
            db=self.db,
            profile=self.profile,
            source_name=SOURCE_ARXIV,
            source_config=reordered_config,
            start_date=source_date,
            end_date=source_date,
            pending_dates=plan.pending_dates,
        )[0]

        self.assertEqual(plan.pending_dates, ())
        self.assertEqual(status.status, "completed")
        self.assertEqual(status.run_id, run_id)
        self.assertEqual(status.retrieved_count, 19)

    def test_legacy_duplicate_category_coverage_is_recognized_after_reorder(self) -> None:
        source_date = date(2026, 8, 14)
        source = DateSource([], latest_date=source_date)
        legacy_fingerprint = legacy_source_fingerprint(("hep-th", "gr-qc", "hep-th"))
        run_id = self.db.create_app_run(
            profile_id=self.profile.id,
            profile_fingerprint=profile_semantic_fingerprint(self.profile),
            source_name=SOURCE_ARXIV,
            source_fingerprint=legacy_fingerprint,
            date_selection=DateSelection.single_date(source_date),
        )
        self.db.finish_app_run(
            run_id,
            status=APP_RUN_COMPLETED,
            retrieved_count=19,
            stored_count=19,
            preselected_count=17,
            skipped_analysis_count=2,
            analyzed_count=17,
            relevant_count=2,
            requested_source_dates=(source_date.isoformat(),),
            covered_source_dates=(source_date.isoformat(),),
        )
        self.db.mark_source_date_covered(
            profile_id=cast(int, self.profile.id),
            profile_fingerprint=profile_semantic_fingerprint(self.profile),
            source_name=SOURCE_ARXIV,
            source_fingerprint=legacy_fingerprint,
            source_date=source_date,
            run_id=run_id,
            run_origin=RunOrigin.MANUAL,
        )
        reordered_config = ArxivSourceConfig(categories=["gr-qc", "hep-th"])

        plan = build_automatic_coverage_plan(
            db=self.db,
            profiles=(self.profile,),
            source_name=SOURCE_ARXIV,
            source_config=reordered_config,
            latest_resolver=source,
            coverage_start_date=source_date,
            catch_up_missed_dates=True,
        )
        status = build_date_coverage_statuses(
            db=self.db,
            profile=self.profile,
            source_name=SOURCE_ARXIV,
            source_config=reordered_config,
            start_date=source_date,
            end_date=source_date,
            pending_dates=plan.pending_dates,
        )[0]
        scheduled = run_automatic_digest_for_enabled_profiles(
            db=self.db,
            source=source,
            analyzer=FakeAnalyzer(),
            source_request=SourceRunRequest(
                source_name=SOURCE_ARXIV,
                adapter=source,
                config=reordered_config,
            ),
            coverage_start_date=source_date,
            catch_up_missed_dates=True,
        )

        self.assertEqual(plan.pending_dates, ())
        self.assertEqual(status.status, "completed")
        self.assertEqual(status.run_id, run_id)
        self.assertEqual(scheduled.profiles, ())
        self.assertEqual(len(self.db.get_app_runs()), 1)

    def test_completed_app_run_fallback_is_recognized_after_reorder(self) -> None:
        source_date = date(2026, 8, 14)
        source = DateSource([], latest_date=source_date)
        legacy_fingerprint = legacy_source_fingerprint(("hep-th", "gr-qc"))
        run_id = self.db.create_app_run(
            profile_id=self.profile.id,
            profile_fingerprint=profile_semantic_fingerprint(self.profile),
            source_name=SOURCE_ARXIV,
            source_fingerprint=legacy_fingerprint,
            date_selection=DateSelection.single_date(source_date),
        )
        self.db.finish_app_run(
            run_id,
            status=APP_RUN_COMPLETED,
            retrieved_count=19,
            stored_count=19,
            preselected_count=17,
            skipped_analysis_count=2,
            analyzed_count=17,
            relevant_count=2,
            requested_source_dates=(source_date.isoformat(),),
            covered_source_dates=(source_date.isoformat(),),
        )
        reordered_config = ArxivSourceConfig(categories=["gr-qc", "hep-th"])

        plan = build_automatic_coverage_plan(
            db=self.db,
            profiles=(self.profile,),
            source_name=SOURCE_ARXIV,
            source_config=reordered_config,
            latest_resolver=source,
            coverage_start_date=source_date,
            catch_up_missed_dates=True,
        )
        status = build_date_coverage_statuses(
            db=self.db,
            profile=self.profile,
            source_name=SOURCE_ARXIV,
            source_config=reordered_config,
            start_date=source_date,
            end_date=source_date,
            pending_dates=plan.pending_dates,
        )[0]
        scheduled = run_automatic_digest_for_enabled_profiles(
            db=self.db,
            source=source,
            analyzer=FakeAnalyzer(),
            source_request=SourceRunRequest(
                source_name=SOURCE_ARXIV,
                adapter=source,
                config=reordered_config,
            ),
            coverage_start_date=source_date,
            catch_up_missed_dates=True,
        )

        self.assertEqual(plan.pending_dates, ())
        self.assertEqual(status.status, "completed")
        self.assertEqual(status.run_id, run_id)
        self.assertEqual(status.retrieved_count, 19)
        self.assertEqual(scheduled.profiles, ())
        self.assertEqual(self.db.list_source_date_coverage(), [])
        self.assertEqual(len(self.db.get_app_runs()), 1)

    def test_actual_category_set_change_creates_distinct_pending_scope(self) -> None:
        source_date = date(2026, 8, 14)
        source = DateSource([article("2608.14001", source_date)], latest_date=source_date)
        run_digest_for_profile(
            db=self.db,
            source=source,
            analyzer=FakeAnalyzer(),
            profile_id=cast(int, self.profile.id),
            source_request=SourceRunRequest(
                source_name=SOURCE_ARXIV,
                adapter=source,
                config=ArxivSourceConfig(categories=["hep-th", "gr-qc"]),
            ),
            date_selection=DateSelection.single_date(source_date),
            run_origin=RunOrigin.MANUAL,
        )

        plan = build_automatic_coverage_plan(
            db=self.db,
            profiles=(self.profile,),
            source_name=SOURCE_ARXIV,
            source_config=ArxivSourceConfig(categories=["hep-th", "astro-ph.CO"]),
            latest_resolver=source,
            coverage_start_date=source_date,
            catch_up_missed_dates=True,
        )

        self.assertEqual(plan.pending_dates, (source_date,))

    def test_reordered_categories_do_not_invalidate_analysis_cache(self) -> None:
        source_date = date(2026, 8, 14)
        source = DateSource([article("2608.14001", source_date)], latest_date=source_date)
        first = run_digest_for_profile(
            db=self.db,
            source=source,
            analyzer=FakeAnalyzer(),
            profile_id=cast(int, self.profile.id),
            source_request=SourceRunRequest(
                source_name=SOURCE_ARXIV,
                adapter=source,
                config=ArxivSourceConfig(categories=["hep-th", "gr-qc"]),
            ),
            date_selection=DateSelection.single_date(source_date),
            run_origin=RunOrigin.MANUAL,
        )
        second = run_digest_for_profile(
            db=self.db,
            source=source,
            analyzer=FailingAnalyzer(),
            profile_id=cast(int, self.profile.id),
            source_request=SourceRunRequest(
                source_name=SOURCE_ARXIV,
                adapter=source,
                config=ArxivSourceConfig(categories=["gr-qc", "hep-th"]),
            ),
            date_selection=DateSelection.single_date(source_date),
            run_origin=RunOrigin.MANUAL,
        )

        self.assertEqual(first.digest.new_analysis_count, 1)
        self.assertEqual(second.digest.new_analysis_count, 0)
        self.assertEqual(second.digest.reused_analysis_count, 1)
        self.assertEqual(second.digest.run_status, APP_RUN_COMPLETED)

    def test_automatic_catch_up_runs_only_profiles_with_uncovered_dates(self) -> None:
        source_date = date(2026, 8, 14)
        source = DateSource(
            [article("2608.14001", source_date)],
            latest_date=source_date,
        )
        other_profile = self.db.create_interest_profile(
            name="Cosmology",
            description="Quantum cosmology.",
        )

        run_digest_for_profile(
            db=self.db,
            source=source,
            analyzer=FakeAnalyzer(),
            profile_id=cast(int, self.profile.id),
            date_selection=DateSelection.single_date(source_date),
            run_origin=RunOrigin.MANUAL,
        )
        automatic = run_automatic_digest_for_enabled_profiles(
            db=self.db,
            source=source,
            analyzer=FakeAnalyzer(),
            coverage_start_date=source_date,
            catch_up_missed_dates=True,
        )

        self.assertEqual(automatic.pending_source_dates, (source_date,))
        self.assertEqual([run.profile_id for run in automatic.profiles], [other_profile.id])
        self.assertEqual(len(source.selections), 2)
        scheduled_runs = [
            row for row in self.db.get_app_runs() if row["run_origin"] == RunOrigin.SCHEDULED.value
        ]
        self.assertEqual(len(scheduled_runs), 1)
        self.assertEqual(scheduled_runs[0]["profile_id"], other_profile.id)

    def test_analysis_unavailable_run_with_cached_analysis_does_not_mark_coverage(self) -> None:
        source_date = date(2026, 8, 14)
        source_article = article("2608.14001", source_date)
        saved_articles, _ = self.db.upsert_articles([source_article])
        saved_article = saved_articles[0]
        assert saved_article.id is not None
        assert self.profile.id is not None
        self.db.upsert_analysis(
            article_id=saved_article.id,
            profile_id=self.profile.id,
            profile_fingerprint=profile_semantic_fingerprint(self.profile),
            analysis=AnalysisResult(
                relevance_score=0.95,
                relevance_reason="Relevant cached analysis.",
                matched_topics=["gravity"],
                summary="Cached summary.",
                why_it_matters="Cached reason.",
                reading_priority="HIGH",
            ),
        )
        source = DateSource([source_article], latest_date=source_date)

        result = run_digest_for_profile(
            db=self.db,
            source=source,
            analyzer=None,
            profile_id=self.profile.id,
            date_selection=DateSelection.single_date(source_date),
            run_origin=RunOrigin.MANUAL,
        )
        plan = build_automatic_coverage_plan(
            db=self.db,
            profiles=(self.profile,),
            source_name=SOURCE_ARXIV,
            source_config=self.config,
            latest_resolver=source,
            coverage_start_date=source_date,
            catch_up_missed_dates=True,
        )

        self.assertEqual(result.digest.run_status, APP_RUN_ANALYSIS_UNAVAILABLE)
        self.assertEqual(self.db.list_source_date_coverage(), [])
        self.assertEqual(plan.pending_dates, (source_date,))

    def test_automatic_analysis_unavailable_cached_run_is_not_reported_successful(self) -> None:
        source_date = date(2026, 8, 14)
        source_article = article("2608.14001", source_date)
        saved_articles, _ = self.db.upsert_articles([source_article])
        saved_article = saved_articles[0]
        assert saved_article.id is not None
        assert self.profile.id is not None
        self.db.upsert_analysis(
            article_id=saved_article.id,
            profile_id=self.profile.id,
            profile_fingerprint=profile_semantic_fingerprint(self.profile),
            analysis=AnalysisResult(
                relevance_score=0.95,
                relevance_reason="Relevant cached analysis.",
                matched_topics=["gravity"],
                summary="Cached summary.",
                why_it_matters="Cached reason.",
                reading_priority="HIGH",
            ),
        )
        source = DateSource([source_article], latest_date=source_date)

        result = run_automatic_digest_for_enabled_profiles(
            db=self.db,
            source=source,
            analyzer=None,
            coverage_start_date=source_date,
            catch_up_missed_dates=True,
        )

        self.assertEqual(result.succeeded_count, 0)
        self.assertEqual(result.failed_count, 1)
        digest_run = result.profiles[0].digest
        self.assertIsNotNone(digest_run)
        assert digest_run is not None
        self.assertEqual(digest_run.digest.run_status, APP_RUN_ANALYSIS_UNAVAILABLE)
        self.assertEqual(self.db.list_source_date_coverage(), [])

    def test_manual_failed_date_remains_pending_until_successful_retry(self) -> None:
        source_date = date(2026, 8, 14)
        source = DateSource(
            [article("2608.14001", source_date)],
            latest_date=source_date,
        )

        failed = run_digest_for_profile(
            db=self.db,
            source=source,
            analyzer=FailingAnalyzer(),
            profile_id=cast(int, self.profile.id),
            date_selection=DateSelection.single_date(source_date),
            run_origin=RunOrigin.MANUAL,
        )
        failed_plan = build_automatic_coverage_plan(
            db=self.db,
            profiles=(self.profile,),
            source_name=SOURCE_ARXIV,
            source_config=self.config,
            latest_resolver=source,
            coverage_start_date=source_date,
            catch_up_missed_dates=True,
        )
        failed_status = build_date_coverage_statuses(
            db=self.db,
            profile=self.profile,
            source_name=SOURCE_ARXIV,
            source_config=self.config,
            start_date=source_date,
            end_date=source_date,
            pending_dates=failed_plan.pending_dates,
        )[0]

        self.assertEqual(failed.digest.run_status, APP_RUN_ANALYSIS_UNAVAILABLE)
        self.assertEqual(failed_plan.pending_dates, (source_date,))
        self.assertEqual(failed_status.status, "partial")
        self.assertEqual(self.db.list_source_date_coverage(), [])

        retry = run_digest_for_profile(
            db=self.db,
            source=source,
            analyzer=FakeAnalyzer(),
            profile_id=cast(int, self.profile.id),
            date_selection=DateSelection.single_date(source_date),
            run_origin=RunOrigin.MANUAL,
        )
        retry_plan = build_automatic_coverage_plan(
            db=self.db,
            profiles=(self.profile,),
            source_name=SOURCE_ARXIV,
            source_config=self.config,
            latest_resolver=source,
            coverage_start_date=source_date,
            catch_up_missed_dates=True,
        )
        retry_status = build_date_coverage_statuses(
            db=self.db,
            profile=self.profile,
            source_name=SOURCE_ARXIV,
            source_config=self.config,
            start_date=source_date,
            end_date=source_date,
            pending_dates=retry_plan.pending_dates,
        )[0]
        run_statuses = [row["status"] for row in self.db.get_app_runs()]

        self.assertEqual(retry.digest.run_status, APP_RUN_COMPLETED)
        self.assertEqual(retry_plan.pending_dates, ())
        self.assertEqual(retry_status.status, "completed")
        self.assertIn(APP_RUN_ANALYSIS_UNAVAILABLE, run_statuses)
        self.assertIn(APP_RUN_COMPLETED, run_statuses)

    def test_scheduled_no_submission_date_is_empty_without_analyzer(self) -> None:
        source = DateSource([], latest_date=date(2026, 8, 14))

        result = run_automatic_digest_for_enabled_profiles(
            db=self.db,
            source=source,
            analyzer=None,
            coverage_start_date=date(2026, 8, 14),
            catch_up_missed_dates=True,
        )

        self.assertEqual(result.succeeded_count, 1)
        self.assertEqual(result.analysis_unavailable_count, 0)
        self.assertEqual(result.analysis_incomplete_count, 0)
        run = self.db.get_app_runs()[0]
        self.assertEqual(run["status"], APP_RUN_COMPLETED)
        statuses = build_date_coverage_statuses(
            db=self.db,
            profile=self.profile,
            source_name=SOURCE_ARXIV,
            source_config=self.config,
            start_date=date(2026, 8, 14),
            end_date=date(2026, 8, 14),
        )
        self.assertEqual(statuses[0].status, "empty")
        self.assertEqual(statuses[0].label, "Checked: no submissions")

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
        self.assertEqual(first.analysis_incomplete_count, 1)
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

        self.assertEqual(result.succeeded_count, 0)
        self.assertEqual(result.failed_count, 1)
        self.assertEqual(
            result.profiles[0].error_message,
            "Retrieval incomplete for source date(s): 2026-08-14",
        )
        self.assertEqual(self.db.list_source_date_coverage(), [])

    def test_date_coverage_statuses_are_scoped_to_profile_and_source_semantics(self) -> None:
        config = ArxivSourceConfig(categories=["hep-th"])
        other_config = ArxivSourceConfig(categories=["astro-ph.CO"])
        assert self.profile.id is not None
        source_fingerprint = source_config_semantic_fingerprint(config)
        profile_fingerprint = profile_semantic_fingerprint(self.profile)
        partial_run = self.db.create_app_run(
            profile_id=self.profile.id,
            profile_fingerprint=profile_fingerprint,
            source_name=SOURCE_ARXIV,
            source_fingerprint=source_fingerprint,
            date_selection=DateSelection.single_date(date(2026, 8, 14)),
        )
        self.db.finish_app_run(
            partial_run,
            status=APP_RUN_PARTIAL,
            retrieved_count=2,
            stored_count=2,
            preselected_count=2,
            skipped_analysis_count=0,
            analyzed_count=1,
            relevant_count=1,
            requested_source_dates=("2026-08-14",),
        )
        empty_run = self.db.create_app_run(
            profile_id=self.profile.id,
            profile_fingerprint=profile_fingerprint,
            source_name=SOURCE_ARXIV,
            source_fingerprint=source_fingerprint,
            date_selection=DateSelection.single_date(date(2026, 8, 15)),
        )
        self.db.finish_app_run(
            empty_run,
            status=APP_RUN_COMPLETED,
            retrieved_count=0,
            stored_count=0,
            preselected_count=0,
            skipped_analysis_count=0,
            analyzed_count=0,
            relevant_count=0,
            requested_source_dates=("2026-08-15",),
            empty_source_dates=("2026-08-15",),
        )
        scope = build_coverage_scope(
            profile=self.profile,
            source_name=SOURCE_ARXIV,
            source_config=config,
        )
        self.db.mark_source_date_covered(
            profile_id=scope.profile_id,
            profile_fingerprint=scope.profile_fingerprint,
            source_name=scope.source_name,
            source_fingerprint=scope.source_fingerprint,
            source_date=date(2026, 8, 16),
            run_id=empty_run,
            run_origin=RunOrigin.SCHEDULED,
        )

        statuses = {
            item.source_date: item
            for item in build_date_coverage_statuses(
                db=self.db,
                profile=self.profile,
                source_name=SOURCE_ARXIV,
                source_config=config,
                start_date=date(2026, 8, 14),
                end_date=date(2026, 8, 17),
                selected_dates=(date(2026, 8, 17),),
                pending_dates=(date(2026, 8, 17),),
            )
        }
        other_statuses = {
            item.source_date: item.status
            for item in build_date_coverage_statuses(
                db=self.db,
                profile=self.profile,
                source_name=SOURCE_ARXIV,
                source_config=other_config,
                start_date=date(2026, 8, 14),
                end_date=date(2026, 8, 17),
            )
        }

        self.assertEqual(statuses[date(2026, 8, 14)].status, "partial")
        self.assertEqual(statuses[date(2026, 8, 15)].status, "empty")
        self.assertEqual(statuses[date(2026, 8, 16)].status, "completed")
        self.assertEqual(statuses[date(2026, 8, 17)].status, "pending")
        self.assertTrue(statuses[date(2026, 8, 17)].selected)
        self.assertEqual(set(other_statuses.values()), {"out_of_scope"})

    def test_statuses_do_not_default_out_of_interval_dates_to_pending(self) -> None:
        statuses = build_date_coverage_statuses(
            db=self.db,
            profile=self.profile,
            source_name=SOURCE_ARXIV,
            source_config=self.config,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            pending_dates=(),
        )

        self.assertEqual({item.status for item in statuses}, {"out_of_scope"})

    def test_old_profile_run_status_does_not_leak_into_current_calendar_scope(self) -> None:
        config = ArxivSourceConfig(categories=["hep-th"])
        assert self.profile.id is not None
        source_date = date(2026, 8, 14)
        source_fingerprint = source_config_semantic_fingerprint(config)
        old_fingerprint = profile_semantic_fingerprint(self.profile)
        failed_run = self.db.create_app_run(
            profile_id=self.profile.id,
            profile_fingerprint=old_fingerprint,
            source_name=SOURCE_ARXIV,
            source_fingerprint=source_fingerprint,
            date_selection=DateSelection.single_date(source_date),
        )
        self.db.finish_app_run(
            failed_run,
            status=APP_RUN_ANALYSIS_UNAVAILABLE,
            retrieved_count=1,
            stored_count=1,
            preselected_count=1,
            skipped_analysis_count=0,
            analyzed_count=0,
            relevant_count=0,
            requested_source_dates=(source_date.isoformat(),),
        )
        changed = self.db.update_interest_profile(
            InterestProfile(
                id=self.profile.id,
                name=self.profile.name,
                description="Changed semantic meaning.",
                relevance_threshold=self.profile.relevance_threshold,
            )
        )

        statuses = build_date_coverage_statuses(
            db=self.db,
            profile=changed,
            source_name=SOURCE_ARXIV,
            source_config=config,
            start_date=source_date,
            end_date=source_date,
            pending_dates=(source_date,),
        )

        self.assertEqual(statuses[0].status, "pending")

    def test_completed_digest_status_overrides_older_partial_retry_state(self) -> None:
        config = ArxivSourceConfig(categories=["hep-th"])
        assert self.profile.id is not None
        source_fingerprint = source_config_semantic_fingerprint(config)
        profile_fingerprint = profile_semantic_fingerprint(self.profile)
        source_date = date(2026, 8, 14)
        partial_run = self.db.create_app_run(
            profile_id=self.profile.id,
            profile_fingerprint=profile_fingerprint,
            source_name=SOURCE_ARXIV,
            source_fingerprint=source_fingerprint,
            date_selection=DateSelection.single_date(source_date),
        )
        self.db.finish_app_run(
            partial_run,
            status=APP_RUN_PARTIAL,
            retrieved_count=2,
            stored_count=2,
            preselected_count=2,
            skipped_analysis_count=0,
            analyzed_count=1,
            relevant_count=1,
            requested_source_dates=(source_date.isoformat(),),
        )
        completed_run = self.db.create_app_run(
            profile_id=self.profile.id,
            profile_fingerprint=profile_fingerprint,
            source_name=SOURCE_ARXIV,
            source_fingerprint=source_fingerprint,
            date_selection=DateSelection.single_date(source_date),
        )
        self.db.finish_app_run(
            completed_run,
            status=APP_RUN_COMPLETED,
            retrieved_count=2,
            stored_count=2,
            preselected_count=2,
            skipped_analysis_count=0,
            analyzed_count=2,
            relevant_count=1,
            requested_source_dates=(source_date.isoformat(),),
            covered_source_dates=(source_date.isoformat(),),
        )
        scope = build_coverage_scope(
            profile=self.profile,
            source_name=SOURCE_ARXIV,
            source_config=config,
        )
        self.db.mark_source_date_covered(
            profile_id=scope.profile_id,
            profile_fingerprint=scope.profile_fingerprint,
            source_name=scope.source_name,
            source_fingerprint=scope.source_fingerprint,
            source_date=source_date,
            run_id=completed_run,
            run_origin=RunOrigin.MANUAL,
        )

        statuses = build_date_coverage_statuses(
            db=self.db,
            profile=self.profile,
            source_name=SOURCE_ARXIV,
            source_config=config,
            start_date=source_date,
            end_date=source_date,
        )

        self.assertEqual(statuses[0].status, "completed")
        self.assertEqual(statuses[0].label, "Completed digest")

    def test_completed_detail_uses_current_profile_fingerprint_scope(self) -> None:
        config = ArxivSourceConfig(categories=["hep-th"])
        assert self.profile.id is not None
        source_date = date(2026, 8, 14)
        source_fingerprint = source_config_semantic_fingerprint(config)
        original_fingerprint = profile_semantic_fingerprint(self.profile)
        original_run = self.db.create_app_run(
            profile_id=self.profile.id,
            profile_fingerprint=original_fingerprint,
            source_name=SOURCE_ARXIV,
            source_fingerprint=source_fingerprint,
            date_selection=DateSelection.single_date(source_date),
        )
        self.db.finish_app_run(
            original_run,
            status=APP_RUN_COMPLETED,
            retrieved_count=19,
            stored_count=19,
            preselected_count=17,
            skipped_analysis_count=2,
            analyzed_count=17,
            relevant_count=2,
            requested_source_dates=(source_date.isoformat(),),
            covered_source_dates=(source_date.isoformat(),),
        )
        self.db.mark_source_date_covered(
            profile_id=self.profile.id,
            profile_fingerprint=original_fingerprint,
            source_name=SOURCE_ARXIV,
            source_fingerprint=source_fingerprint,
            source_date=source_date,
            run_id=original_run,
            run_origin=RunOrigin.MANUAL,
        )
        changed = self.db.update_interest_profile(
            InterestProfile(
                id=self.profile.id,
                name=self.profile.name,
                description="Changed semantic meaning.",
                relevance_threshold=self.profile.relevance_threshold,
            )
        )
        changed_fingerprint = profile_semantic_fingerprint(changed)
        changed_run = self.db.create_app_run(
            profile_id=self.profile.id,
            profile_fingerprint=changed_fingerprint,
            source_name=SOURCE_ARXIV,
            source_fingerprint=source_fingerprint,
            date_selection=DateSelection.single_date(source_date),
        )
        self.db.finish_app_run(
            changed_run,
            status=APP_RUN_COMPLETED,
            retrieved_count=5,
            stored_count=5,
            preselected_count=5,
            skipped_analysis_count=0,
            analyzed_count=5,
            relevant_count=1,
            requested_source_dates=(source_date.isoformat(),),
            covered_source_dates=(source_date.isoformat(),),
        )
        self.db.mark_source_date_covered(
            profile_id=self.profile.id,
            profile_fingerprint=changed_fingerprint,
            source_name=SOURCE_ARXIV,
            source_fingerprint=source_fingerprint,
            source_date=source_date,
            run_id=changed_run,
            run_origin=RunOrigin.MANUAL,
        )

        statuses = build_date_coverage_statuses(
            db=self.db,
            profile=self.profile,
            source_name=SOURCE_ARXIV,
            source_config=config,
            start_date=source_date,
            end_date=source_date,
        )

        self.assertEqual(statuses[0].status, "completed")
        self.assertEqual(statuses[0].run_id, original_run)
        self.assertEqual(statuses[0].retrieved_count, 19)
        self.assertEqual(statuses[0].analyzed_count, 17)
        self.assertEqual(statuses[0].relevant_count, 2)

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
