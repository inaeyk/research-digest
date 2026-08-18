from __future__ import annotations

import tempfile
import unittest
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from unittest import mock

from research_digest.analysis.fake import FakeAnalyzer
from research_digest.automation import (
    install_or_update_schedule,
    read_schedule_status,
    remove_schedule,
    run_automatic_digest_now,
)
from research_digest.config import AppConfig
from research_digest.db import Database
from research_digest.library import save_article
from research_digest.library_context import (
    LibraryContextCandidate,
    LibraryContextGeneration,
    LibraryContextSuggestionDraft,
)
from research_digest.models import AnalysisResult, Article, ArxivSourceConfig, DateSelection
from research_digest.preselection import UnavailableFailOpenPreselector
from research_digest.scheduler import (
    WINDOWS_LOCAL_TIME_DESCRIPTION,
    ScheduleOperationResult,
    ScheduleRequest,
    ScheduleStatus,
)
from research_digest.sources.arxiv import ArxivDateRetrievalResult


class DateSource:
    def __init__(self, articles: list[Article], *, latest_date: date) -> None:
        self.articles = articles
        self.latest_date = latest_date
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
        requested = selection.selected_dates()
        dates = set(requested)
        articles = tuple(
            article
            for article in self.articles
            if config.enabled and article.published_at.date() in dates
        )
        article_dates = {article.published_at.date() for article in articles}
        return ArxivDateRetrievalResult(
            selection=selection,
            articles=articles,
            requested_dates=requested,
            covered_dates=requested,
            empty_dates=tuple(value for value in requested if value not in article_dates),
            incomplete_dates=(),
            latest_available_date=self.latest_date,
            retrieved_count=len(articles),
            safety_limit=2000,
            safety_limit_reached=False,
        )


def article(source_article_id: str, source_date: date) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title=f"Paper {source_article_id}",
        authors=["Ada Lovelace"],
        abstract="A paper about higher-dimensional gravity.",
        categories=["hep-th"],
        published_at=datetime(source_date.year, source_date.month, source_date.day, 10, tzinfo=UTC),
        updated_at=datetime(source_date.year, source_date.month, source_date.day, 11, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


class FakeSchedulerBackend:
    def __init__(self) -> None:
        self.requests: list[ScheduleRequest] = []
        self.removed: list[str] = []
        self.status_calls: list[str] = []

    def install(self, request: ScheduleRequest) -> ScheduleOperationResult:
        self.requests.append(request)
        return ScheduleOperationResult(
            backend="windows_task_scheduler",
            task_name=request.task_name,
            operation="installed_or_updated",
            installed=True,
            timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
            arguments=request.windows_action_arguments,
        )

    def remove(self, *, task_name: str) -> ScheduleOperationResult:
        self.removed.append(task_name)
        return ScheduleOperationResult(
            backend="windows_task_scheduler",
            task_name=task_name,
            operation="removed",
            installed=False,
            timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
        )

    def status(self, *, task_name: str) -> ScheduleStatus:
        self.status_calls.append(task_name)
        return ScheduleStatus(
            backend="windows_task_scheduler",
            task_name=task_name,
            installed=True,
            timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
            state="Ready",
        )


class FakeContextGenerator:
    def __init__(self) -> None:
        self.calls = 0

    def suggest_context(
        self,
        *,
        article: Article,
        analysis: AnalysisResult,
        candidates: Sequence[LibraryContextCandidate],
        max_suggestions: int = 5,
    ) -> LibraryContextGeneration:
        self.calls += 1
        return LibraryContextGeneration(
            suggestions=(
                LibraryContextSuggestionDraft(
                    related_candidate_id="arxiv:2608.related",
                    collection_id=None,
                    relation_label="shared system",
                    rationale="Both discuss higher-dimensional gravity.",
                ),
            ),
            provenance={"provider": "fake"},
        )


def config(db_path: Path) -> AppConfig:
    return AppConfig(
        db_path=db_path,
        data_dir=db_path.parent,
        config_dir=db_path.parent / "config",
        analyzer_provider="codex",
        openai_api_key=None,
        openai_model="gpt-test",
        codex_model=None,
        codex_timeout_seconds=12,
    )


def deterministic_preselector(app_config: AppConfig) -> UnavailableFailOpenPreselector:
    return UnavailableFailOpenPreselector(
        preselection_fraction=app_config.preselection_fraction,
        reason="deterministic automation test preselector",
    )


class AutomationTests(unittest.TestCase):
    def test_read_schedule_status_sanitizes_unsupported_backend(self) -> None:
        class FailingBackend:
            def install(self, request: ScheduleRequest) -> ScheduleOperationResult:
                raise AssertionError("not used")

            def remove(self, *, task_name: str) -> ScheduleOperationResult:
                raise AssertionError("not used")

            def status(self, *, task_name: str) -> ScheduleStatus:
                raise RuntimeError("failed with OPENAI_API_KEY=sk-secret123456789")

        status = read_schedule_status(scheduler_backend=FailingBackend())

        self.assertFalse(status.ok)
        self.assertIsNone(status.schedule)
        self.assertIsNotNone(status.error_message)
        assert status.error_message is not None
        self.assertIn("[REDACTED_API_KEY]", status.error_message)
        self.assertNotIn("sk-secret", status.error_message)

    def test_install_and_remove_delegate_to_backend_without_secret_exposure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "research_digest.scheduler.shutil.which",
            side_effect=lambda name: {
                "codex": "/home/me/.nvm/versions/node/v22/bin/codex",
                "research-digest": "/tmp/bin/research-digest",
                "wsl.exe": "/mnt/c/windows/system32/wsl.exe",
            }.get(name),
        ):
            backend = FakeSchedulerBackend()
            result = install_or_update_schedule(
                time_of_day="07:30",
                config=config(Path(tmp) / "digest.sqlite3"),
                scheduler_backend=backend,
                task_name="Research Digest Test",
                wsl_distro="Ubuntu",
            )
            removed = remove_schedule(
                scheduler_backend=backend,
                task_name="Research Digest Test",
            )

        self.assertTrue(result.installed)
        self.assertEqual(backend.requests[0].time_of_day, "07:30")
        self.assertIn("research-digest run", result.arguments or "")
        self.assertNotIn("OPENAI_API_KEY", result.arguments or "")
        self.assertEqual(removed.operation, "removed")
        self.assertEqual(backend.removed, ["Research Digest Test"])

    def test_run_now_with_zero_pending_dates_does_not_create_history_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "test.sqlite3")
            db.create_interest_profile(name="Gravity", description="Higher-dimensional gravity.")
            source = DateSource([], latest_date=date(2026, 8, 13))
            app_config = replace(
                config(Path(tmp) / "test.sqlite3"),
                automatic_coverage_start_date=date(2026, 8, 14),
            )

            result = run_automatic_digest_now(
                config=app_config,
                db=db,
                source=source,
                analyzer=None,
            )

            self.assertEqual(result.profiles, ())
            self.assertEqual(result.pending_source_dates, ())
            self.assertEqual(source.selections, [])
            self.assertEqual(db.get_app_runs(), [])
            db.close()

    def test_run_now_with_pending_dates_uses_shared_digest_service(self) -> None:
        source_date = date(2026, 8, 14)
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "test.sqlite3")
            db.create_interest_profile(name="Gravity", description="Higher-dimensional gravity.")
            source = DateSource([article("2608.14001", source_date)], latest_date=source_date)
            app_config = replace(
                config(Path(tmp) / "test.sqlite3"),
                automatic_coverage_start_date=source_date,
            )

            result = run_automatic_digest_now(
                config=app_config,
                db=db,
                source=source,
                analyzer=FakeAnalyzer(),
                preselector=deterministic_preselector(app_config),
            )

            self.assertEqual(result.succeeded_count, 1)
            self.assertEqual(result.pending_source_dates, (source_date,))
            self.assertEqual(source.selections, [DateSelection.single_date(source_date)])
            self.assertEqual(len(db.get_app_runs()), 1)
            self.assertEqual(len(db.list_source_date_coverage()), 1)
            db.close()

    def test_injected_analyzer_without_preselector_does_not_build_live_preselector(
        self,
    ) -> None:
        source_date = date(2026, 8, 14)
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "test.sqlite3")
            db.create_interest_profile(name="Gravity", description="Higher-dimensional gravity.")
            source = DateSource([article("2608.14001", source_date)], latest_date=source_date)
            app_config = replace(
                config(Path(tmp) / "test.sqlite3"),
                automatic_coverage_start_date=source_date,
            )

            with mock.patch(
                "research_digest.automation.build_configured_preselector",
                side_effect=AssertionError("should not build live preselector"),
            ):
                result = run_automatic_digest_now(
                    config=app_config,
                    db=db,
                    source=source,
                    analyzer=FakeAnalyzer(),
                )

            self.assertEqual(result.succeeded_count, 1)
            db.close()

    def test_run_now_passes_configured_library_context_threshold(self) -> None:
        source_date = date(2026, 8, 14)
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "test.sqlite3")
            db.create_interest_profile(name="Gravity", description="Higher-dimensional gravity.")
            related, _ = db.upsert_article(article("2608.related", source_date))
            assert related.id is not None
            save_article(db, related.id)
            source = DateSource([article("2608.new", source_date)], latest_date=source_date)
            app_config = replace(
                config(Path(tmp) / "test.sqlite3"),
                automatic_coverage_start_date=source_date,
                automatic_library_context_threshold=0.90,
            )
            generator = FakeContextGenerator()

            run_automatic_digest_now(
                config=app_config,
                db=db,
                source=source,
                analyzer=FakeAnalyzer(
                    {
                        "2608.new": {
                            "relevance_score": 0.89,
                            "relevance_reason": "Below automatic context threshold.",
                            "matched_topics": ["gravity"],
                            "summary": "Summary.",
                            "why_it_matters": "Reason.",
                            "reading_priority": "HIGH",
                        }
                    }
                ),
                preselector=deterministic_preselector(app_config),
                library_context_generator=generator,
            )
            self.assertEqual(generator.calls, 0)

            high_date = date(2026, 8, 15)
            high_source = DateSource([article("2608.high", high_date)], latest_date=high_date)
            run_automatic_digest_now(
                config=replace(app_config, automatic_coverage_start_date=high_date),
                db=db,
                source=high_source,
                analyzer=FakeAnalyzer(
                    {
                        "2608.high": {
                            "relevance_score": 0.90,
                            "relevance_reason": "At automatic context threshold.",
                            "matched_topics": ["gravity"],
                            "summary": "Summary.",
                            "why_it_matters": "Reason.",
                            "reading_priority": "HIGH",
                        }
                    }
                ),
                preselector=deterministic_preselector(app_config),
                library_context_generator=generator,
            )

            self.assertEqual(generator.calls, 1)
            db.close()

    def test_run_now_library_context_toggle_blocks_automatic_generation(self) -> None:
        source_date = date(2026, 8, 14)
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "test.sqlite3")
            db.create_interest_profile(name="Gravity", description="Higher-dimensional gravity.")
            related, _ = db.upsert_article(article("2608.related.toggle", source_date))
            assert related.id is not None
            save_article(db, related.id)
            source = DateSource([article("2608.new.toggle", source_date)], latest_date=source_date)
            app_config = replace(
                config(Path(tmp) / "test.sqlite3"),
                automatic_coverage_start_date=source_date,
                automatic_library_connections_enabled=False,
                automatic_library_context_threshold=0.0,
            )
            generator = FakeContextGenerator()

            run_automatic_digest_now(
                config=app_config,
                db=db,
                source=source,
                analyzer=FakeAnalyzer(
                    {
                        "2608.new.toggle": {
                            "relevance_score": 1.0,
                            "relevance_reason": "High relevance.",
                            "matched_topics": ["gravity"],
                            "summary": "Summary.",
                            "why_it_matters": "Reason.",
                            "reading_priority": "HIGH",
                        }
                    }
                ),
                preselector=deterministic_preselector(app_config),
                library_context_generator=generator,
            )

            self.assertEqual(generator.calls, 0)
            db.close()


if __name__ == "__main__":
    unittest.main()
