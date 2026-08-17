from __future__ import annotations

import tempfile
import unittest
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from research_digest.analysis.base import article_analysis_key
from research_digest.analysis.fake import FakeAnalyzer
from research_digest.db import APP_RUN_FAILED, Database
from research_digest.models import (
    AnalysisOrigin,
    AnalysisResult,
    Article,
    ArxivSourceConfig,
    DateSelection,
    InterestProfile,
    ModelValidationError,
    RunOrigin,
    above_threshold_digest_items,
    below_threshold_digest_items,
    profile_semantic_fingerprint,
)
from research_digest.pipeline import run_digest
from research_digest.preselection import TermOverlapPreselector


class StaticSource:
    def __init__(self, articles: list[Article]) -> None:
        self.articles = articles

    def fetch(self, config: ArxivSourceConfig, *, now: datetime | None = None) -> list[Article]:
        if not config.enabled:
            return []
        return list(self.articles[: config.max_results])


class DateStaticSource(StaticSource):
    def __init__(
        self,
        articles: list[Article],
        *,
        incomplete_dates: tuple[date, ...] = (),
        safety_limit: int = 2000,
    ) -> None:
        super().__init__(articles)
        self.incomplete_dates = incomplete_dates
        self.safety_limit = safety_limit

    def fetch_date_selection(
        self,
        config: ArxivSourceConfig,
        selection: DateSelection,
    ) -> object:
        from research_digest.sources.arxiv import ArxivDateRetrievalResult

        if not config.enabled:
            articles: tuple[Article, ...] = ()
        else:
            selected = set(selection.selected_dates())
            articles = tuple(
                article
                for article in self.articles
                if article.published_at.date() in selected
            )
        requested_dates = selection.selected_dates()
        covered_dates = tuple(
            value for value in requested_dates if value not in self.incomplete_dates
        )
        article_dates = {item.published_at.date() for item in articles}
        empty_dates = tuple(value for value in covered_dates if value not in article_dates)
        return ArxivDateRetrievalResult(
            selection=selection,
            articles=articles,
            requested_dates=requested_dates,
            covered_dates=covered_dates,
            empty_dates=empty_dates,
            incomplete_dates=self.incomplete_dates,
            latest_available_date=None,
            retrieved_count=len(articles),
            safety_limit=self.safety_limit,
            safety_limit_reached=bool(self.incomplete_dates),
        )


class FailingAnalyzer:
    def analyze(self, *, profile: InterestProfile, article: Article) -> AnalysisResult:
        raise AssertionError("pipeline should call analyze_many")

    def analyze_many(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> Mapping[str, AnalysisResult]:
        api_key = "sk-" + "secret123456789"
        raise RuntimeError(
            "provider failed at /home/"
            + "inaeyk/private with OPENAI_API_KEY="
            + api_key
            + " Bearer "
            + "token.secret.value"
        )


class FailingDateSource(DateStaticSource):
    def fetch_date_selection(
        self,
        config: ArxivSourceConfig,
        selection: DateSelection,
    ) -> object:
        raise RuntimeError("source failed before metadata")


class ProfileEchoAnalyzer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, float]] = []

    def analyze(self, *, profile: InterestProfile, article: Article) -> AnalysisResult:
        self.calls.append(
            (
                article.source_article_id,
                profile.name,
                profile.description,
                profile.relevance_threshold,
            )
        )
        return AnalysisResult(
            relevance_score=0.8,
            relevance_reason=f"Analyzed for {profile.name}.",
            matched_topics=["profile"],
            summary=f"Summary for {profile.description}",
            why_it_matters=f"Threshold {profile.relevance_threshold}.",
            reading_priority="HIGH",
        )

    def analyze_many(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> Mapping[str, AnalysisResult]:
        return {
            article_analysis_key(article): self.analyze(profile=profile, article=article)
            for article in articles
        }


def article(source_article_id: str, title: str, published_hour: int) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title=title,
        authors=["Ada Lovelace"],
        abstract=f"{title} abstract about gravity.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, published_hour, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, published_hour, 10, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.sqlite3")
        self.profile = self.db.create_interest_profile(
            name="Gravity",
            description=(
                "Higher-dimensional gravity, black strings, black branes, "
                "and spin-2 states."
            ),
            relevance_threshold=0.6,
        )
        self.articles = [
            article("2608.00001", "Warped spin-2 compactifications", 10),
            article("2608.00002", "Black strings", 9),
            article("2608.00003", "Unrelated detector calibration", 8),
        ]
        self.analysis_payloads = {
            "2608.00001": {
                "relevance_score": 0.95,
                "relevance_reason": "Direct spin-2 compactification match.",
                "matched_topics": ["spin-2", "compactifications"],
                "summary": "Summary one.",
                "why_it_matters": "It targets the requested spectrum.",
                "reading_priority": "HIGH",
            },
            "2608.00002": {
                "relevance_score": 0.7,
                "relevance_reason": "Black-string match.",
                "matched_topics": ["black strings"],
                "summary": "Summary two.",
                "why_it_matters": "It concerns Gregory-Laflamme-adjacent systems.",
                "reading_priority": "MEDIUM",
            },
            "2608.00003": {
                "relevance_score": 0.2,
                "relevance_reason": "No real scientific connection.",
                "matched_topics": [],
                "summary": "Summary three.",
                "why_it_matters": "It does not matter for the profile.",
                "reading_priority": "LOW",
            },
        }

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_fake_analyzer_and_pipeline_ranking_filtering(self) -> None:
        analyzer = FakeAnalyzer(self.analysis_payloads)

        result = run_digest(
            db=self.db,
            source=StaticSource(self.articles),
            analyzer=analyzer,
            profile_id=self.profile.id,
            now=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
        )

        self.assertEqual(result.retrieved_count, 3)
        self.assertEqual(result.stored_count, 3)
        self.assertEqual(result.preselected_count, 3)
        self.assertEqual(result.skipped_analysis_count, 0)
        self.assertEqual(result.analyzed_count, 3)
        self.assertEqual(result.new_analysis_count, 3)
        self.assertEqual(result.reused_analysis_count, 0)
        self.assertEqual(result.new_analysis_count + result.reused_analysis_count, 3)
        self.assertEqual(result.above_threshold_count, 2)
        self.assertEqual(result.relevant_count, 2)
        self.assertEqual(
            [item.article.source_article_id for item in result.items],
            ["2608.00001", "2608.00002", "2608.00003"],
        )
        self.assertEqual(
            [item.article.source_article_id for item in above_threshold_digest_items(result)],
            ["2608.00001", "2608.00002"],
        )
        self.assertEqual(
            [item.article.source_article_id for item in below_threshold_digest_items(result)],
            ["2608.00003"],
        )
        self.assertEqual(
            {item.article.source_article_id: item.analysis_origin for item in result.items},
            {
                "2608.00001": AnalysisOrigin.NEW_THIS_RUN,
                "2608.00002": AnalysisOrigin.NEW_THIS_RUN,
                "2608.00003": AnalysisOrigin.NEW_THIS_RUN,
            },
        )
        self.assertEqual(analyzer.calls, ["2608.00001", "2608.00002", "2608.00003"])

        second = run_digest(
            db=self.db,
            source=StaticSource(self.articles),
            analyzer=analyzer,
            profile_id=self.profile.id,
            now=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
        )
        self.assertEqual(second.stored_count, 0)
        self.assertEqual(second.preselected_count, 0)
        self.assertEqual(second.skipped_analysis_count, 0)
        self.assertEqual(second.analyzed_count, 3)
        self.assertEqual(second.new_analysis_count, 0)
        self.assertEqual(second.reused_analysis_count, 3)
        self.assertEqual(second.new_analysis_count + second.reused_analysis_count, 3)
        self.assertEqual(second.above_threshold_count, 2)
        self.assertEqual(self.db.count_articles(), 3)
        self.assertEqual(analyzer.calls, ["2608.00001", "2608.00002", "2608.00003"])
        self.assertEqual(
            {item.article.source_article_id: item.analysis_origin for item in second.items},
            {
                "2608.00001": AnalysisOrigin.REUSED,
                "2608.00002": AnalysisOrigin.REUSED,
                "2608.00003": AnalysisOrigin.REUSED,
            },
        )

    def test_pipeline_counts_mixed_new_and_reused_analyses(self) -> None:
        analyzer = FakeAnalyzer(self.analysis_payloads)
        run_digest(
            db=self.db,
            source=StaticSource(self.articles[:1]),
            analyzer=analyzer,
            profile_id=self.profile.id,
        )
        analyzer.calls.clear()

        result = run_digest(
            db=self.db,
            source=StaticSource(self.articles),
            analyzer=analyzer,
            profile_id=self.profile.id,
        )

        self.assertEqual(result.retrieved_count, 3)
        self.assertEqual(result.preselected_count, 2)
        self.assertEqual(result.skipped_analysis_count, 0)
        self.assertEqual(result.analyzed_count, 3)
        self.assertEqual(result.new_analysis_count, 2)
        self.assertEqual(result.reused_analysis_count, 1)
        self.assertEqual(result.new_analysis_count + result.reused_analysis_count, 3)
        self.assertEqual(analyzer.calls, ["2608.00002", "2608.00003"])
        self.assertEqual(
            {item.article.source_article_id: item.analysis_origin for item in result.items},
            {
                "2608.00001": AnalysisOrigin.REUSED,
                "2608.00002": AnalysisOrigin.NEW_THIS_RUN,
                "2608.00003": AnalysisOrigin.NEW_THIS_RUN,
            },
        )

    def test_pipeline_without_analyzer_remains_usable(self) -> None:
        result = run_digest(
            db=self.db,
            source=StaticSource(self.articles[:1]),
            analyzer=None,
            profile_id=self.profile.id,
        )

        self.assertFalse(result.analysis_available)
        self.assertEqual(result.retrieved_count, 1)
        self.assertEqual(result.preselected_count, 0)
        self.assertEqual(result.skipped_analysis_count, 0)
        self.assertEqual(result.analyzed_count, 0)
        self.assertEqual(result.new_analysis_count, 0)
        self.assertEqual(result.reused_analysis_count, 0)
        self.assertEqual(result.above_threshold_count, 0)
        self.assertEqual(result.relevant_count, 0)
        self.assertEqual(self.db.count_articles(), 1)

    def test_pipeline_without_analyzer_reuses_existing_analyses(self) -> None:
        analyzer = FakeAnalyzer(self.analysis_payloads)
        run_digest(
            db=self.db,
            source=StaticSource(self.articles[:1]),
            analyzer=analyzer,
            profile_id=self.profile.id,
        )
        analyzer.calls.clear()

        result = run_digest(
            db=self.db,
            source=StaticSource(self.articles[:1]),
            analyzer=None,
            profile_id=self.profile.id,
        )

        self.assertFalse(result.analysis_available)
        self.assertEqual(result.analyzed_count, 1)
        self.assertEqual(result.preselected_count, 0)
        self.assertEqual(result.skipped_analysis_count, 0)
        self.assertEqual(result.new_analysis_count, 0)
        self.assertEqual(result.reused_analysis_count, 1)
        self.assertEqual(result.new_analysis_count + result.reused_analysis_count, 1)
        self.assertEqual(result.items[0].analysis_origin, AnalysisOrigin.REUSED)
        self.assertEqual(analyzer.calls, [])

    def test_identical_profile_semantics_reuse_cached_analysis_after_profile_update(
        self,
    ) -> None:
        analyzer = ProfileEchoAnalyzer()
        result = run_digest(
            db=self.db,
            source=StaticSource(self.articles[:1]),
            analyzer=analyzer,
            profile_id=self.profile.id,
        )
        self.assertEqual(result.new_analysis_count, 1)
        self.assertEqual(result.reused_analysis_count, 0)

        self.db.update_interest_profile(
            InterestProfile(
                id=self.profile.id,
                name=self.profile.name,
                description=self.profile.description,
                relevance_threshold=self.profile.relevance_threshold,
                enabled=self.profile.enabled,
            )
        )
        second = run_digest(
            db=self.db,
            source=StaticSource(self.articles[:1]),
            analyzer=analyzer,
            profile_id=self.profile.id,
        )

        self.assertEqual(second.new_analysis_count, 0)
        self.assertEqual(second.reused_analysis_count, 1)
        self.assertEqual(second.items[0].analysis_origin, AnalysisOrigin.REUSED)
        self.assertEqual(len(analyzer.calls), 1)

    def test_same_profile_id_semantic_edits_do_not_reuse_cached_analysis(self) -> None:
        scenarios = [
            ("Quantum gravity", self.profile.description, self.profile.relevance_threshold),
            (self.profile.name, "Condensed matter dualities.", self.profile.relevance_threshold),
            (self.profile.name, self.profile.description, 0.7),
        ]
        for index, (name, description, relevance_threshold) in enumerate(scenarios, start=1):
            with self.subTest(
                name=name,
                description=description,
                relevance_threshold=relevance_threshold,
            ):
                tmpdir = tempfile.TemporaryDirectory()
                db: Database | None = None
                try:
                    db = Database(Path(tmpdir.name) / "test.sqlite3")
                    profile = db.create_interest_profile(
                        name=self.profile.name,
                        description=self.profile.description,
                        relevance_threshold=self.profile.relevance_threshold,
                    )
                    analyzer = ProfileEchoAnalyzer()
                    source_article = article(
                        f"2608.0100{index}",
                        f"Profile semantic cache test {index}",
                        7,
                    )

                    first = run_digest(
                        db=db,
                        source=StaticSource([source_article]),
                        analyzer=analyzer,
                        profile_id=profile.id,
                    )
                    self.assertEqual(first.new_analysis_count, 1)
                    self.assertEqual(first.skipped_analysis_count, 0)
                    self.assertEqual(first.reused_analysis_count, 0)

                    changed = db.update_interest_profile(
                        InterestProfile(
                            id=profile.id,
                            name=name,
                            description=description,
                            relevance_threshold=relevance_threshold,
                            enabled=profile.enabled,
                        )
                    )
                    second = run_digest(
                        db=db,
                        source=StaticSource([source_article]),
                        analyzer=analyzer,
                        profile_id=changed.id,
                    )

                    self.assertEqual(second.new_analysis_count, 1)
                    self.assertEqual(second.skipped_analysis_count, 0)
                    self.assertEqual(second.reused_analysis_count, 0)
                    self.assertEqual(second.items[0].analysis_origin, AnalysisOrigin.NEW_THIS_RUN)
                    self.assertEqual(len(analyzer.calls), 2)
                finally:
                    if db is not None:
                        db.close()
                    tmpdir.cleanup()

    def test_threshold_boundary_is_relevant(self) -> None:
        boundary = article("2608.00004", "Boundary score paper", 7)
        analyzer = FakeAnalyzer(
            {
                "2608.00004": {
                    "relevance_score": 0.6,
                    "relevance_reason": "Exactly at the configured threshold.",
                    "matched_topics": ["gravity"],
                    "summary": "Boundary summary.",
                    "why_it_matters": "It verifies threshold inclusivity.",
                    "reading_priority": "MEDIUM",
                }
            }
        )

        result = run_digest(
            db=self.db,
            source=StaticSource([boundary]),
            analyzer=analyzer,
            profile_id=self.profile.id,
        )

        self.assertEqual(result.above_threshold_count, 1)
        self.assertEqual(
            [item.article.source_article_id for item in above_threshold_digest_items(result)],
            ["2608.00004"],
        )
        self.assertEqual(below_threshold_digest_items(result), [])

    def test_preselection_skips_cache_misses_without_profile_term_overlap(self) -> None:
        analyzer = FakeAnalyzer(self.analysis_payloads)
        relevant = article("2608.00001", "Warped spin-2 compactifications", 10)
        irrelevant = Article(
            id=None,
            source="arxiv",
            source_article_id="2608.00999",
            title="Detector calibration constants",
            authors=["Grace Hopper"],
            abstract="A procedure for measuring pixel gains in an accelerator detector.",
            categories=["physics.ins-det"],
            published_at=datetime(2026, 8, 14, 7, 0, tzinfo=UTC),
            updated_at=datetime(2026, 8, 14, 7, 10, tzinfo=UTC),
            abstract_url="http://arxiv.org/abs/2608.00999",
            pdf_url=None,
        )

        result = run_digest(
            db=self.db,
            source=StaticSource([relevant, irrelevant]),
            analyzer=analyzer,
            profile_id=self.profile.id,
            preselector=TermOverlapPreselector(),
        )

        self.assertEqual(result.retrieved_count, 2)
        self.assertEqual(result.preselected_count, 1)
        self.assertEqual(result.skipped_analysis_count, 1)
        self.assertEqual(result.analyzed_count, 1)
        self.assertEqual(result.new_analysis_count, 1)
        self.assertEqual(analyzer.calls, ["2608.00001"])
        self.assertEqual(
            [item.article.source_article_id for item in result.items],
            ["2608.00001"],
        )

    def test_preselection_preserves_reused_analysis_for_later_obvious_non_candidate(
        self,
    ) -> None:
        analyzer = FakeAnalyzer(
            {
                "2608.00998": {
                    "relevance_score": 0.1,
                    "relevance_reason": "Previously analyzed.",
                    "matched_topics": [],
                    "summary": "Old summary.",
                    "why_it_matters": "It was analyzed before preselection.",
                    "reading_priority": "LOW",
                }
            }
        )
        old_article = Article(
            id=None,
            source="arxiv",
            source_article_id="2608.00998",
            title="Detector calibration constants",
            authors=["Grace Hopper"],
            abstract="A procedure for measuring pixel gains in an accelerator detector.",
            categories=["physics.ins-det"],
            published_at=datetime(2026, 8, 14, 7, 0, tzinfo=UTC),
            updated_at=datetime(2026, 8, 14, 7, 10, tzinfo=UTC),
            abstract_url="http://arxiv.org/abs/2608.00998",
            pdf_url=None,
        )
        first = run_digest(
            db=self.db,
            source=StaticSource([old_article]),
            analyzer=analyzer,
            profile_id=self.profile.id,
            preselector=None,
        )
        self.assertEqual(first.skipped_analysis_count, 1)
        self.assertEqual(first.analyzed_count, 0)

        saved, _ = self.db.upsert_article(old_article)
        assert saved.id is not None
        assert self.profile.id is not None
        self.db.upsert_analysis(
            article_id=saved.id,
            profile_id=self.profile.id,
            profile_fingerprint=profile_semantic_fingerprint(self.profile),
            analysis=analyzer.analyze(profile=self.profile, article=saved),
        )
        analyzer.calls.clear()

        second = run_digest(
            db=self.db,
            source=StaticSource([old_article]),
            analyzer=analyzer,
            profile_id=self.profile.id,
            preselector=TermOverlapPreselector(),
        )

        self.assertEqual(second.preselected_count, 0)
        self.assertEqual(second.skipped_analysis_count, 0)
        self.assertEqual(second.analyzed_count, 1)
        self.assertEqual(second.reused_analysis_count, 1)
        self.assertEqual(second.items[0].analysis_origin, AnalysisOrigin.REUSED)
        self.assertEqual(analyzer.calls, [])

    def test_malformed_analysis_rejected_and_run_marked_failed(self) -> None:
        analyzer = FakeAnalyzer(
            {
                "2608.00001": {
                    "relevance_score": 1.5,
                    "relevance_reason": "Invalid score.",
                    "matched_topics": [],
                    "summary": "Summary.",
                    "why_it_matters": "Reason.",
                    "reading_priority": "HIGH",
                }
            }
        )

        with self.assertRaises(ModelValidationError):
            run_digest(
                db=self.db,
                source=StaticSource(self.articles[:1]),
                analyzer=analyzer,
                profile_id=self.profile.id,
            )

        runs = self.db.get_app_runs()
        self.assertEqual(runs[0]["status"], APP_RUN_FAILED)
        self.assertIn("relevance_score", runs[0]["error_message"])

    def test_pipeline_persists_sanitized_error_message(self) -> None:
        with self.assertRaises(RuntimeError):
            run_digest(
                db=self.db,
                source=StaticSource(self.articles[:1]),
                analyzer=FailingAnalyzer(),
                profile_id=self.profile.id,
            )

        runs = self.db.get_app_runs()
        error_message = runs[0]["error_message"]
        self.assertNotIn("/home/" + "inaeyk", error_message)
        self.assertNotIn("sk-secret", error_message)
        self.assertNotIn("token.secret.value", error_message)
        self.assertIn("[HOME]", error_message)
        self.assertIn("[REDACTED_API_KEY]", error_message)
        self.assertIn("Bearer [REDACTED]", error_message)

    def test_date_selection_run_persists_metadata_and_reuses_identical_rerun_cache(self) -> None:
        selection = DateSelection.single_date(date(2026, 8, 14))
        analyzer = FakeAnalyzer(self.analysis_payloads)

        first = run_digest(
            db=self.db,
            source=DateStaticSource(self.articles),
            analyzer=analyzer,
            profile_id=self.profile.id,
            date_selection=selection,
            run_origin=RunOrigin.MANUAL,
        )
        analyzer.calls.clear()
        second = run_digest(
            db=self.db,
            source=DateStaticSource(self.articles),
            analyzer=analyzer,
            profile_id=self.profile.id,
            date_selection=selection,
            run_origin=RunOrigin.MANUAL,
        )

        self.assertEqual(first.date_selection, selection)
        self.assertEqual(first.run_origin, RunOrigin.MANUAL)
        self.assertEqual(first.requested_source_dates, (date(2026, 8, 14),))
        self.assertEqual(first.covered_source_dates, (date(2026, 8, 14),))
        self.assertTrue(first.retrieval_complete)
        self.assertEqual(second.new_analysis_count, 0)
        self.assertEqual(second.reused_analysis_count, 3)
        self.assertEqual(analyzer.calls, [])
        runs = self.db.get_app_runs()
        self.assertEqual(runs[0]["run_origin"], RunOrigin.MANUAL)
        self.assertEqual(runs[0]["requested_source_dates_json"], '["2026-08-14"]')
        self.assertEqual(runs[0]["covered_source_dates_json"], '["2026-08-14"]')

    def test_different_date_selections_produce_distinct_run_metadata(self) -> None:
        analyzer = FakeAnalyzer(self.analysis_payloads)

        run_digest(
            db=self.db,
            source=DateStaticSource(self.articles),
            analyzer=analyzer,
            profile_id=self.profile.id,
            date_selection=DateSelection.single_date(date(2026, 8, 14)),
            run_origin=RunOrigin.MANUAL,
        )
        run_digest(
            db=self.db,
            source=DateStaticSource(self.articles),
            analyzer=analyzer,
            profile_id=self.profile.id,
            date_selection=DateSelection.date_range(date(2026, 8, 14), date(2026, 8, 15)),
            run_origin=RunOrigin.MANUAL,
        )

        runs = self.db.get_app_runs()
        self.assertNotEqual(runs[0]["date_selection_json"], runs[1]["date_selection_json"])
        self.assertIn("DATE_RANGE", runs[0]["date_selection_json"])
        self.assertIn("SINGLE_DATE", runs[1]["date_selection_json"])
        self.assertEqual(
            runs[0]["requested_source_dates_json"],
            '["2026-08-14", "2026-08-15"]',
        )
        self.assertEqual(
            runs[0]["covered_source_dates_json"],
            '["2026-08-14", "2026-08-15"]',
        )

    def test_empty_source_date_is_completed_with_empty_coverage(self) -> None:
        result = run_digest(
            db=self.db,
            source=DateStaticSource([]),
            analyzer=FakeAnalyzer(),
            profile_id=self.profile.id,
            date_selection=DateSelection.single_date(date(2026, 8, 15)),
            run_origin=RunOrigin.MANUAL,
        )

        self.assertEqual(result.retrieved_count, 0)
        self.assertEqual(result.analyzed_count, 0)
        self.assertEqual(result.covered_source_dates, (date(2026, 8, 15),))
        self.assertEqual(result.empty_source_dates, (date(2026, 8, 15),))
        self.assertTrue(result.retrieval_complete)

    def test_partial_retrieval_cannot_mark_date_covered(self) -> None:
        result = run_digest(
            db=self.db,
            source=DateStaticSource(
                self.articles[:1],
                incomplete_dates=(date(2026, 8, 14),),
                safety_limit=1,
            ),
            analyzer=FakeAnalyzer(self.analysis_payloads),
            profile_id=self.profile.id,
            date_selection=DateSelection.single_date(date(2026, 8, 14)),
            run_origin=RunOrigin.MANUAL,
        )

        self.assertFalse(result.retrieval_complete)
        self.assertEqual(result.covered_source_dates, ())
        self.assertEqual(result.incomplete_source_dates, (date(2026, 8, 14),))
        self.assertEqual(result.retrieval_safety_limit, 1)
        run = self.db.get_app_runs()[0]
        self.assertEqual(run["retrieval_complete"], 0)
        self.assertEqual(run["covered_source_dates_json"], "[]")
        self.assertEqual(run["incomplete_source_dates_json"], '["2026-08-14"]')

    def test_date_selection_failure_records_retrieval_metadata_and_retry_succeeds(self) -> None:
        selection = DateSelection.single_date(date(2026, 8, 14))
        with self.assertRaises(RuntimeError):
            run_digest(
                db=self.db,
                source=DateStaticSource(self.articles[:1]),
                analyzer=FailingAnalyzer(),
                profile_id=self.profile.id,
                date_selection=selection,
                run_origin=RunOrigin.MANUAL,
            )
        failed = self.db.get_app_runs()[0]

        retry = run_digest(
            db=self.db,
            source=DateStaticSource(self.articles[:1]),
            analyzer=FakeAnalyzer(self.analysis_payloads),
            profile_id=self.profile.id,
            date_selection=selection,
            run_origin=RunOrigin.MANUAL,
        )

        self.assertEqual(failed["status"], APP_RUN_FAILED)
        self.assertEqual(failed["requested_source_dates_json"], '["2026-08-14"]')
        self.assertEqual(failed["covered_source_dates_json"], '["2026-08-14"]')
        self.assertEqual(failed["retrieval_complete"], 1)
        self.assertEqual(retry.new_analysis_count, 1)
        self.assertTrue(retry.retrieval_complete)

    def test_date_selection_source_failure_before_metadata_marks_requested_incomplete(
        self,
    ) -> None:
        with self.assertRaises(RuntimeError):
            run_digest(
                db=self.db,
                source=FailingDateSource([]),
                analyzer=FakeAnalyzer(),
                profile_id=self.profile.id,
                date_selection=DateSelection.single_date(date(2026, 8, 14)),
                run_origin=RunOrigin.MANUAL,
            )

        failed = self.db.get_app_runs()[0]
        self.assertEqual(failed["status"], APP_RUN_FAILED)
        self.assertEqual(failed["requested_source_dates_json"], '["2026-08-14"]')
        self.assertEqual(failed["covered_source_dates_json"], "[]")
        self.assertEqual(failed["incomplete_source_dates_json"], '["2026-08-14"]')
        self.assertEqual(failed["retrieval_complete"], 0)

    def test_latest_available_source_failure_remains_unresolved_but_incomplete(self) -> None:
        with self.assertRaises(RuntimeError):
            run_digest(
                db=self.db,
                source=FailingDateSource([]),
                analyzer=FakeAnalyzer(),
                profile_id=self.profile.id,
                date_selection=DateSelection.latest_available(),
                run_origin=RunOrigin.MANUAL,
            )

        failed = self.db.get_app_runs()[0]
        self.assertEqual(failed["requested_source_dates_json"], "[]")
        self.assertEqual(failed["covered_source_dates_json"], "[]")
        self.assertEqual(failed["incomplete_source_dates_json"], "[]")
        self.assertEqual(failed["retrieval_complete"], 0)


if __name__ == "__main__":
    unittest.main()
