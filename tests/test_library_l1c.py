from __future__ import annotations

import sqlite3
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest import mock

from research_digest.ai_artifacts import create_artifact, resolve_preferred_library_summary
from research_digest.ai_providers import GeneratedAIText
from research_digest.db import CURRENT_SCHEMA_VERSION, Database
from research_digest.history import (
    SUMMARY_EXPIRED_MESSAGE,
    get_run_snapshot,
    reconstruct_digest_result,
    resolve_snapshot_summaries,
)
from research_digest.library import save_article, unsave_article
from research_digest.library_summaries import (
    LibrarySummaryError,
    build_library_summary_context,
    generate_library_summary,
    library_summary_input_fingerprint,
)
from research_digest.models import (
    AIArtifactProvenance,
    AIArtifactRetentionClass,
    AIArtifactType,
    AnalysisResult,
    Article,
    ArxivSourceConfig,
    DateSelection,
    InterestProfile,
    LibrarySummarySource,
    profile_semantic_fingerprint,
)
from research_digest.service import run_digest_for_profile

FIXED_NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def article(
    source_article_id: str = "2608.l1c",
    *,
    abstract: str = (
        "We derive a compact higher-dimensional gravity result using a controlled analytic method."
    ),
) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title="Canonical summary lifecycle",
        authors=["Ada Lovelace", "Emmy Noether"],
        abstract=abstract,
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
        abstract_url=f"https://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


def analysis(summary: str = "One canonical digest summary body.") -> AnalysisResult:
    return AnalysisResult(
        relevance_score=0.91,
        relevance_reason="Directly relevant to the profile.",
        matched_topics=["compactification"],
        summary=summary,
        why_it_matters="It sharpens the research question.",
        reading_priority="HIGH",
    )


def provenance(fingerprint: str = "digest-input") -> AIArtifactProvenance:
    return AIArtifactProvenance(
        provider="fake-analysis",
        model_id="fake-analysis-model",
        reasoning_effort=None,
        generator_version="fake-digest-v1",
        input_fingerprint=fingerprint,
    )


class CountingSummaryProvider:
    provider = "fake-summary"
    model_id = "fake-summary-model"
    reasoning_effort: str | None = "low"
    generator_version = "fake-library-summary-v1"

    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def generate_summary(self, *, article: Article, context: str) -> GeneratedAIText:
        del article
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider secret path /home/private sk-secret123456")
        return GeneratedAIText(
            content=f"Explicit Library summary version {self.calls}.",
            provider=self.provider,
            model_id=self.model_id,
            reasoning_effort=self.reasoning_effort,
            generator_version=self.generator_version,
            input_fingerprint=library_summary_input_fingerprint(context),
        )


class CountingAnalyzer:
    artifact_provider = "fake-analysis"
    artifact_model_id = "fake-analysis-model"
    artifact_reasoning_effort: str | None = None
    artifact_generator_version = "fake-digest-v1"

    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, *, profile: InterestProfile, article: Article) -> AnalysisResult:
        del profile, article
        raise AssertionError("batch path expected")

    def analyze_many(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> Mapping[str, AnalysisResult]:
        del profile
        self.calls += 1
        return {
            f"{item.source}:{item.source_article_id}": analysis(
                f"Canonical batch summary for {item.source_article_id}."
            )
            for item in articles
        }


class StaticSource:
    def __init__(self, articles: Sequence[Article]) -> None:
        self.articles = tuple(articles)

    def fetch(
        self,
        config: ArxivSourceConfig,
        *,
        now: datetime | None = None,
    ) -> list[Article]:
        del now
        return list(self.articles if config.enabled else ())

    def fetch_date_selection(
        self,
        config: ArxivSourceConfig,
        selection: DateSelection,
    ) -> object:
        from research_digest.sources.arxiv import ArxivDateRetrievalResult

        selected = set(selection.selected_dates())
        articles = tuple(
            item
            for item in self.articles
            if config.enabled and item.published_at.date() in selected
        )
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
            safety_limit=2_000,
            safety_limit_reached=False,
        )


class L1CTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = Path(self.tmpdir.name) / "l1c.sqlite3"
        self.db = Database(self.path)
        self.addCleanup(self.db.close)
        self.profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
        )
        self.persisted_article, _ = self.db.upsert_article(article())
        assert self.profile.id is not None and self.persisted_article.id is not None
        self.profile_id = self.profile.id
        self.article_id = self.persisted_article.id
        self.profile_fingerprint = profile_semantic_fingerprint(self.profile)


class CanonicalDigestSummaryTests(L1CTestCase):
    def test_new_digest_summary_is_stored_once_and_cache_resolves_pointer(self) -> None:
        artifact = self.db.persist_generated_digest_analysis(
            article_id=self.article_id,
            profile_id=self.profile_id,
            profile_fingerprint=self.profile_fingerprint,
            analysis=analysis(),
            provenance=provenance(),
            created_at=FIXED_NOW,
        )

        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT summary, summary_artifact_id FROM relevance_analyses"
            ).fetchone()
            durable_occurrences = conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM ai_artifacts WHERE content = ?) +
                    (SELECT COUNT(*) FROM relevance_analyses WHERE summary = ?)
                """,
                (analysis().summary, analysis().summary),
            ).fetchone()
        self.assertEqual(row, ("", artifact.id))
        self.assertEqual(durable_occurrences, (1,))
        self.assertEqual(
            self.db.get_analysis(
                article_id=self.article_id,
                profile_id=self.profile_id,
                profile_fingerprint=self.profile_fingerprint,
            ),
            analysis(),
        )
        self.assertEqual(artifact.retention_class, AIArtifactRetentionClass.TEMPORARY)
        self.assertEqual(artifact.expires_at, FIXED_NOW + timedelta(days=90))

    def test_saved_paper_retains_only_current_default_digest(self) -> None:
        save_article(self.db, self.article_id)
        first = self.db.persist_generated_digest_analysis(
            article_id=self.article_id,
            profile_id=self.profile_id,
            profile_fingerprint=self.profile_fingerprint,
            analysis=analysis("First digest summary."),
            provenance=provenance("first"),
            created_at=FIXED_NOW,
        )
        second = self.db.persist_generated_digest_analysis(
            article_id=self.article_id,
            profile_id=self.profile_id,
            profile_fingerprint=self.profile_fingerprint,
            analysis=analysis("Second digest summary."),
            provenance=provenance("second"),
            created_at=FIXED_NOW + timedelta(days=1),
        )

        first_after = self.db.get_ai_artifact(first.id or 0)
        second_after = self.db.get_ai_artifact(second.id or 0)
        assert first_after is not None and second_after is not None
        self.assertEqual(first_after.retention_class, AIArtifactRetentionClass.TEMPORARY)
        self.assertEqual(second_after.retention_class, AIArtifactRetentionClass.LIBRARY)
        self.assertEqual(
            resolve_preferred_library_summary(self.db, article_id=self.article_id).artifact_id,  # type: ignore[union-attr]
            second.id,
        )

    def test_expired_artifact_gc_clears_pointer_but_preserves_analysis_facts(self) -> None:
        artifact = self.db.persist_generated_digest_analysis(
            article_id=self.article_id,
            profile_id=self.profile_id,
            profile_fingerprint=self.profile_fingerprint,
            analysis=analysis(),
            provenance=provenance(),
            created_at=FIXED_NOW,
        )
        self.assertEqual(
            self.db.collect_expired_ai_artifacts(now=FIXED_NOW + timedelta(days=91)),
            1,
        )
        self.assertIsNone(self.db.get_ai_artifact(artifact.id or 0))
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT summary, summary_artifact_id, relevance_score FROM relevance_analyses"
            ).fetchone()
        self.assertEqual(row, ("", None, 0.91))
        self.assertIsNone(
            self.db.get_analysis(
                article_id=self.article_id,
                profile_id=self.profile_id,
                profile_fingerprint=self.profile_fingerprint,
            )
        )

    def test_cache_reuse_uses_same_artifact_and_zero_second_analysis_calls(self) -> None:
        source = StaticSource([article()])
        analyzer = CountingAnalyzer()
        first = run_digest_for_profile(
            db=self.db,
            source=source,
            analyzer=analyzer,
            profile_id=self.profile_id,
            date_selection=DateSelection.single_date(date(2026, 8, 14)),
        )
        second = run_digest_for_profile(
            db=self.db,
            source=source,
            analyzer=analyzer,
            profile_id=self.profile_id,
            date_selection=DateSelection.single_date(date(2026, 8, 14)),
        )

        self.assertEqual(analyzer.calls, 1)
        self.assertEqual(first.digest.new_analysis_count, 1)
        self.assertEqual(second.digest.reused_analysis_count, 1)
        self.assertEqual(len(self.db.list_ai_artifacts(self.article_id)), 1)


class SaveUnsaveSummaryTests(L1CTestCase):
    def test_save_promotes_same_preferred_artifact_and_unsave_demotes_with_grace(self) -> None:
        artifact = self.db.persist_generated_digest_analysis(
            article_id=self.article_id,
            profile_id=self.profile_id,
            profile_fingerprint=self.profile_fingerprint,
            analysis=analysis(),
            provenance=provenance(),
            created_at=FIXED_NOW,
        )
        save_article(self.db, self.article_id)
        promoted = self.db.get_ai_artifact(artifact.id or 0)
        assert promoted is not None
        self.assertEqual(promoted.retention_class, AIArtifactRetentionClass.LIBRARY)
        self.assertEqual(len(self.db.list_ai_artifacts(self.article_id)), 1)

        unsave_article(self.db, self.article_id)
        demoted = self.db.get_ai_artifact(artifact.id or 0)
        assert demoted is not None and demoted.expires_at is not None
        self.assertEqual(demoted.retention_class, AIArtifactRetentionClass.TEMPORARY)
        self.assertGreater(demoted.expires_at, FIXED_NOW)

    def test_saving_legacy_inline_summary_creates_no_artifact(self) -> None:
        self.db.upsert_analysis(
            article_id=self.article_id,
            profile_id=self.profile_id,
            profile_fingerprint=self.profile_fingerprint,
            analysis=analysis("Grandfathered inline summary."),
        )
        save_article(self.db, self.article_id)

        self.assertEqual(self.db.list_ai_artifacts(self.article_id), [])
        resolved = resolve_preferred_library_summary(self.db, article_id=self.article_id)
        assert resolved is not None
        self.assertEqual(resolved.source, LibrarySummarySource.LEGACY_DIGEST_ANALYSIS)


class ExplicitLibrarySummaryTests(L1CTestCase):
    def setUp(self) -> None:
        super().setUp()
        save_article(self.db, self.article_id)

    def test_generate_calls_provider_once_then_compatible_generate_reuses(self) -> None:
        provider = CountingSummaryProvider()
        first = generate_library_summary(
            self.db,
            article_id=self.article_id,
            provider=provider,
            now=FIXED_NOW,
        )
        second = generate_library_summary(
            self.db,
            article_id=self.article_id,
            provider=provider,
            now=FIXED_NOW + timedelta(days=1),
        )

        self.assertEqual(provider.calls, 1)
        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertFalse(second.provider_called)
        self.assertEqual(first.artifact.id, second.artifact.id)
        self.assertEqual(len(self.db.list_ai_artifacts(self.article_id)), 1)

    def test_regenerate_creates_new_preferred_then_demotes_old(self) -> None:
        provider = CountingSummaryProvider()
        first = generate_library_summary(
            self.db,
            article_id=self.article_id,
            provider=provider,
            now=FIXED_NOW,
        )
        second = generate_library_summary(
            self.db,
            article_id=self.article_id,
            provider=provider,
            regenerate=True,
            now=FIXED_NOW + timedelta(days=1),
        )

        self.assertEqual(provider.calls, 2)
        self.assertNotEqual(first.artifact.id, second.artifact.id)
        old = self.db.get_ai_artifact(first.artifact.id or 0)
        new = self.db.get_ai_artifact(second.artifact.id or 0)
        assert old is not None and new is not None
        self.assertEqual(old.retention_class, AIArtifactRetentionClass.TEMPORARY)
        self.assertEqual(old.expires_at, FIXED_NOW + timedelta(days=91))
        self.assertEqual(new.retention_class, AIArtifactRetentionClass.LIBRARY)
        self.assertEqual(
            resolve_preferred_library_summary(self.db, article_id=self.article_id).artifact_id,  # type: ignore[union-attr]
            new.id,
        )

    def test_provider_and_persistence_failure_leave_previous_summary_untouched(self) -> None:
        provider = CountingSummaryProvider()
        original = generate_library_summary(
            self.db,
            article_id=self.article_id,
            provider=provider,
            now=FIXED_NOW,
        ).artifact
        failing = CountingSummaryProvider(fail=True)
        with self.assertRaises(RuntimeError):
            generate_library_summary(
                self.db,
                article_id=self.article_id,
                provider=failing,
                regenerate=True,
                now=FIXED_NOW + timedelta(days=1),
            )
        self.assertEqual(len(self.db.list_ai_artifacts(self.article_id)), 1)
        self.assertEqual(
            self.db.get_ai_artifact(original.id or 0).retention_class,  # type: ignore[union-attr]
            AIArtifactRetentionClass.LIBRARY,
        )

        with (
            mock.patch.object(
                self.db,
                "persist_library_summary",
                side_effect=sqlite3.OperationalError("disk full"),
            ),
            self.assertRaises(sqlite3.OperationalError),
        ):
            generate_library_summary(
                self.db,
                article_id=self.article_id,
                provider=provider,
                regenerate=True,
                now=FIXED_NOW + timedelta(days=2),
            )
        self.assertEqual(len(self.db.list_ai_artifacts(self.article_id)), 1)

    def test_input_is_bounded_by_utf8_bytes(self) -> None:
        oversized = article("2608.large", abstract="é" * 40_000)
        with self.assertRaisesRegex(LibrarySummaryError, "too large"):
            build_library_summary_context(oversized)


class HistoryAndGCTests(L1CTestCase):
    def test_history_summary_resolution_batches_artifact_and_legacy_reads(self) -> None:
        artifact = self.db.persist_generated_digest_analysis(
            article_id=self.article_id,
            profile_id=self.profile_id,
            profile_fingerprint=self.profile_fingerprint,
            analysis=analysis("Canonical History body."),
            provenance=provenance(),
            created_at=FIXED_NOW,
        )
        legacy_article, _ = self.db.upsert_article(article("2608.history-legacy"))
        assert legacy_article.id is not None
        self.db.upsert_analysis(
            article_id=legacy_article.id,
            profile_id=self.profile_id,
            profile_fingerprint=self.profile_fingerprint,
            analysis=analysis("Legacy History body."),
        )
        references = self.db.list_analysis_summary_references(
            article_ids=(self.article_id, legacy_article.id),
            profile_id=self.profile_id,
            profile_fingerprint=self.profile_fingerprint,
        )
        legacy_reference = references[legacy_article.id]
        payload = [
            {
                "summary_reference": (
                    {"kind": "artifact", "artifact_id": artifact.id}
                    if index % 2 == 0
                    else {
                        "kind": "legacy_analysis",
                        "analysis_id": legacy_reference.analysis_id,
                    }
                )
            }
            for index in range(1_000)
        ]
        with (
            mock.patch.object(
                self.db,
                "get_ai_artifacts_by_ids",
                wraps=self.db.get_ai_artifacts_by_ids,
            ) as artifact_read,
            mock.patch.object(
                self.db,
                "get_legacy_analysis_summaries",
                wraps=self.db.get_legacy_analysis_summaries,
            ) as legacy_read,
        ):
            displays = resolve_snapshot_summaries(self.db, payload, now=FIXED_NOW)

        self.assertEqual(len(displays), 1_000)
        artifact_read.assert_called_once()
        legacy_read.assert_called_once()

    def test_gc_uses_retention_and_rolling_summary_indexes(self) -> None:
        with sqlite3.connect(self.path) as conn:
            plan = conn.execute(
                """
                EXPLAIN QUERY PLAN
                SELECT artifacts.id
                FROM ai_artifacts AS artifacts
                WHERE artifacts.retention_class = ?
                  AND artifacts.expires_at < ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM ai_conversations
                      WHERE ai_conversations.rolling_summary_artifact_id = artifacts.id
                  )
                ORDER BY artifacts.id
                """,
                (AIArtifactRetentionClass.TEMPORARY.value, "2026-08-29T00:00:00Z"),
            ).fetchall()
        details = "\n".join(str(row[3]) for row in plan)
        self.assertIn("idx_ai_artifacts_gc", details)
        self.assertIn("idx_ai_conversations_rolling_summary", details)

    def test_completed_digest_runs_gc_once_without_ai_work(self) -> None:
        expirable = create_artifact(
            self.db,
            article_id=self.article_id,
            artifact_type=AIArtifactType.CONVERSATION_SUMMARY,
            content="Expired replaceable prose.",
            provider="fixture",
            model_id="fixture-model",
            reasoning_effort=None,
            generator_version="fixture-v1",
            input_fingerprint="expired-fixture",
            retention_class=AIArtifactRetentionClass.TEMPORARY,
            created_at=datetime(1999, 1, 1, tzinfo=UTC),
        )
        analyzer = CountingAnalyzer()
        with mock.patch.object(
            self.db,
            "collect_expired_ai_artifacts",
            wraps=self.db.collect_expired_ai_artifacts,
        ) as cleanup:
            run_digest_for_profile(
                db=self.db,
                source=StaticSource([article()]),
                analyzer=analyzer,
                profile_id=self.profile_id,
                date_selection=DateSelection.single_date(date(2026, 8, 14)),
            )

        cleanup.assert_called_once_with()
        self.assertEqual(analyzer.calls, 1)
        self.assertIsNone(self.db.get_ai_artifact(expirable.id or 0))

    def test_new_snapshot_references_without_prose_and_reports_expiration(self) -> None:
        analyzer = CountingAnalyzer()
        run = run_digest_for_profile(
            db=self.db,
            source=StaticSource([article()]),
            analyzer=analyzer,
            profile_id=self.profile_id,
            date_selection=DateSelection.single_date(date(2026, 8, 14)),
        )
        snapshot = get_run_snapshot(self.db, run_id=run.digest.run_id)
        assert snapshot is not None
        items = snapshot["items"]
        assert isinstance(items, list) and isinstance(items[0], dict)
        self.assertNotIn("summary", items[0])
        reference = items[0]["summary_reference"]
        assert isinstance(reference, dict)
        self.assertEqual(reference["kind"], "artifact")
        artifact_id = reference["artifact_id"]
        assert isinstance(artifact_id, int)

        artifact = self.db.get_ai_artifact(artifact_id)
        assert artifact is not None and artifact.expires_at is not None
        self.db.collect_expired_ai_artifacts(now=artifact.expires_at + timedelta(seconds=1))
        display = resolve_snapshot_summaries(
            self.db,
            items,
            now=artifact.expires_at + timedelta(seconds=1),
        )[0]
        self.assertTrue(display.unavailable)
        self.assertEqual(display.content, SUMMARY_EXPIRED_MESSAGE)
        self.db.persist_generated_digest_analysis(
            article_id=self.article_id,
            profile_id=self.profile_id,
            profile_fingerprint=self.profile_fingerprint,
            analysis=analysis("A newer cache summary must not rewrite old History."),
            provenance=provenance("newer-history-cache"),
            created_at=artifact.expires_at + timedelta(days=1),
        )
        reconstructed = reconstruct_digest_result(self.db, run_id=run.digest.run_id)
        assert reconstructed is not None
        self.assertEqual(len(reconstructed.items), 1)
        self.assertEqual(reconstructed.items[0].analysis.summary, SUMMARY_EXPIRED_MESSAGE)
        self.assertNotIn("newer cache summary", reconstructed.items[0].analysis.summary)
        self.assertEqual(reconstructed.items[0].analysis.relevance_score, 0.91)

    def test_legacy_snapshot_inline_summary_still_resolves_without_ai(self) -> None:
        payload = [{"summary": "Grandfathered History summary."}]
        with mock.patch(
            "research_digest.summary_providers.build_configured_library_summary_provider",
            side_effect=AssertionError("History invoked AI"),
        ) as provider_factory:
            display = resolve_snapshot_summaries(self.db, payload)[0]
        provider_factory.assert_not_called()
        self.assertEqual(display.content, "Grandfathered History summary.")


class Schema20MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = Path(self.tmpdir.name) / "schema19.sqlite3"
        _create_schema19_database(self.path)

    def test_schema20_is_additive_backup_safe_replay_safe_and_ai_free(self) -> None:
        with mock.patch(
            "research_digest.summary_providers.build_configured_library_summary_provider",
            side_effect=AssertionError("migration invoked AI"),
        ) as provider_factory:
            migrated = Database(self.path)
        provider_factory.assert_not_called()
        self.assertEqual(CURRENT_SCHEMA_VERSION, 20)
        self.assertEqual(migrated.get_schema_version(), 20)
        backup = migrated.last_migration_backup_path
        assert backup is not None
        self.assertIn("backup-v19-to-v20", backup.name)
        with sqlite3.connect(backup) as conn:
            self.assertEqual(
                conn.execute("SELECT summary FROM relevance_analyses").fetchone(),
                ("Exact grandfathered summary.",),
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM ai_artifacts").fetchone(), (0,))
        with sqlite3.connect(self.path) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(relevance_analyses)")}
            row = conn.execute(
                "SELECT summary, summary_artifact_id FROM relevance_analyses"
            ).fetchone()
            artifact_count = conn.execute("SELECT COUNT(*) FROM ai_artifacts").fetchone()
        self.assertIn("summary_artifact_id", columns)
        self.assertEqual(row, ("Exact grandfathered summary.", None))
        self.assertEqual(artifact_count, (0,))

        reopened = Database(self.path)
        self.assertEqual(reopened.get_schema_version(), 20)
        self.assertIsNone(reopened.last_migration_backup_path)


def _create_schema19_database(path: Path) -> None:
    timestamp = "2026-08-29T12:00:00Z"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE source_configs (
                source_name TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL,
                categories_json TEXT NOT NULL,
                lookback_hours INTEGER NOT NULL,
                max_results INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE interest_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                relevance_threshold REAL NOT NULL,
                enabled INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_article_id TEXT NOT NULL,
                title TEXT NOT NULL,
                authors_json TEXT NOT NULL,
                abstract TEXT NOT NULL,
                categories_json TEXT NOT NULL,
                published_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                abstract_url TEXT NOT NULL,
                pdf_url TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(source, source_article_id)
            );
            CREATE TABLE ai_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                artifact_type TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                provider TEXT NOT NULL,
                model_id TEXT NOT NULL,
                reasoning_effort TEXT,
                generator_version TEXT NOT NULL,
                input_fingerprint TEXT NOT NULL,
                retention_class TEXT NOT NULL,
                expires_at TEXT,
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
            );
            CREATE TABLE relevance_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                profile_id INTEGER NOT NULL,
                profile_fingerprint TEXT NOT NULL,
                relevance_score REAL NOT NULL,
                relevance_reason TEXT NOT NULL,
                matched_topics_json TEXT NOT NULL,
                summary TEXT NOT NULL,
                why_it_matters TEXT NOT NULL,
                reading_priority TEXT NOT NULL,
                analyzed_at TEXT NOT NULL,
                UNIQUE(article_id, profile_id, profile_fingerprint),
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
                FOREIGN KEY(profile_id) REFERENCES interest_profiles(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            "INSERT INTO schema_metadata VALUES ('schema_version', '19', ?)",
            (timestamp,),
        )
        conn.execute(
            """
            INSERT INTO interest_profiles VALUES (
                1, 'Gravity', 'Higher-dimensional gravity.', 0.6, 1, ?, ?
            )
            """,
            (timestamp, timestamp),
        )
        conn.execute(
            """
            INSERT INTO articles VALUES (
                1, 'arxiv', '2608.legacy', 'Legacy paper', '["Ada Lovelace"]',
                'Legacy abstract.', '["hep-th"]', ?, ?,
                'https://arxiv.org/abs/2608.legacy', NULL, ?
            )
            """,
            (timestamp, timestamp, timestamp),
        )
        conn.execute(
            """
            INSERT INTO relevance_analyses VALUES (
                1, 1, 1, 'legacy-profile', 0.8, 'Legacy reason.', '["gravity"]',
                'Exact grandfathered summary.', 'Legacy why.', 'HIGH', ?
            )
            """,
            (timestamp,),
        )
