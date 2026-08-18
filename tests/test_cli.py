from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from unittest import mock

from research_digest.analysis.fake import FakeAnalyzer
from research_digest.cli import run_cli
from research_digest.config import AppConfig
from research_digest.db import APP_RUN_COMPLETED, APP_RUN_RUNNING, Database
from research_digest.models import Article, ArxivSourceConfig, DateSelection
from research_digest.preselection import UnavailableFailOpenPreselector
from research_digest.scheduler import ScheduleError, ScheduleOperationResult, ScheduleStatus
from research_digest.sources.arxiv import ArxivDateRetrievalResult


class StaticSource:
    def __init__(self, articles: list[Article], *, latest_date: date | None = None) -> None:
        self.articles = articles
        self.latest_date = latest_date

    def fetch(self, config: ArxivSourceConfig, *, now: datetime | None = None) -> list[Article]:
        if not config.enabled:
            return []
        return list(self.articles[: config.max_results])

    def resolve_latest_available_date(self, config: ArxivSourceConfig) -> date | None:
        if not config.enabled:
            return None
        if self.latest_date is not None:
            return self.latest_date
        if not self.articles:
            return None
        return max(article.published_at.date() for article in self.articles)

    def fetch_date_selection(
        self,
        config: ArxivSourceConfig,
        selection: DateSelection,
    ) -> ArxivDateRetrievalResult:
        requested_dates = selection.selected_dates()
        selected = set(requested_dates)
        articles = tuple(
            article
            for article in self.articles
            if config.enabled and article.published_at.date() in selected
        )
        article_dates = {article.published_at.date() for article in articles}
        return ArxivDateRetrievalResult(
            selection=selection,
            articles=articles,
            requested_dates=requested_dates,
            covered_dates=requested_dates,
            empty_dates=tuple(value for value in requested_dates if value not in article_dates),
            incomplete_dates=(),
            latest_available_date=self.resolve_latest_available_date(config),
            retrieved_count=len(articles),
            safety_limit=2000,
            safety_limit_reached=False,
        )


class StaticSchedulerBackend:
    def install(self, request: object) -> ScheduleOperationResult:
        raise AssertionError("not used")

    def remove(self, *, task_name: str) -> ScheduleOperationResult:
        raise AssertionError("not used")

    def status(self, *, task_name: str) -> ScheduleStatus:
        return ScheduleStatus(
            backend="test",
            task_name=task_name,
            installed=True,
            timezone="test local time",
            state="Ready",
            last_task_result=0,
        )


class FailingSchedulerBackend:
    def install(self, request: object) -> ScheduleOperationResult:
        raise AssertionError("not used")

    def remove(self, *, task_name: str) -> ScheduleOperationResult:
        raise AssertionError("not used")

    def status(self, *, task_name: str) -> ScheduleStatus:
        raise ScheduleError("LastTaskResult conversion failed")


def article() -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id="2608.20001",
        title="Private title should not be printed in CLI summaries",
        authors=["Ada Lovelace"],
        abstract="Private abstract should not be printed in CLI summaries.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
        abstract_url="http://arxiv.org/abs/2608.20001",
        pdf_url=None,
    )


class CLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self.db = Database(self.db_path)
        self.config = AppConfig(
            db_path=self.db_path,
            data_dir=self.db_path.parent,
            config_dir=self.db_path.parent / "config",
            analyzer_provider="codex",
            openai_api_key=None,
            openai_model="unused",
            codex_model=None,
            codex_timeout_seconds=1,
            automatic_coverage_start_date=date(2026, 8, 14),
        )
        self.preselector = UnavailableFailOpenPreselector(
            preselection_fraction=self.config.preselection_fraction,
            reason="deterministic CLI test preselector",
        )

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_run_json_outputs_counts_without_private_content(self) -> None:
        self.db.create_interest_profile(
            name="Private profile",
            description="Private description should not be printed.",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            argv=["run", "--json"],
            stdout=stdout,
            stderr=stderr,
            config=self.config,
            db=self.db,
            source=StaticSource([article()]),
            analyzer=FakeAnalyzer(),
            preselector=self.preselector,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["profile_count"], 1)
        self.assertEqual(payload["retrieved_count"], 1)
        self.assertEqual(payload["analyzed_count"], 1)
        self.assertEqual(payload["pending_source_dates"], ["2026-08-14"])
        self.assertEqual(payload["date_selection"]["kind"], "SINGLE_DATE")
        output = stdout.getvalue()
        self.assertNotIn("Private description", output)
        self.assertNotIn("Private title", output)
        self.assertNotIn("Private abstract", output)

    def test_injected_analyzer_without_preselector_does_not_build_live_preselector(
        self,
    ) -> None:
        self.db.create_interest_profile(
            name="Private profile",
            description="Private description should not be printed.",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with mock.patch(
            "research_digest.automation.build_configured_preselector",
            side_effect=AssertionError("should not build live preselector"),
        ):
            exit_code = run_cli(
                argv=["run", "--json"],
                stdout=stdout,
                stderr=stderr,
                config=self.config,
                db=self.db,
                source=StaticSource([article()]),
                analyzer=FakeAnalyzer(),
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["analyzed_count"], 1)

    def test_run_human_output_fails_for_sanitized_analyzer_unavailable(self) -> None:
        self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            argv=["run"],
            stdout=stdout,
            stderr=stderr,
            config=self.config,
            db=self.db,
            source=StaticSource([article()]),
            analyzer=None,
            analyzer_message=(
                "provider failed at /home/"
                + "inaeyk/private with OPENAI_API_KEY=sk-"
                + "secret123456789"
            ),
        )

        self.assertEqual(exit_code, 1)
        output = stdout.getvalue()
        self.assertIn("Research Digest run failed", output)
        self.assertIn("Analysis unavailable:", output)
        self.assertIn("Source dates: 2026-08-14", output)
        self.assertNotIn("/home/" + "inaeyk", output)
        self.assertNotIn("sk-secret", output)
        self.assertIn("[HOME]", output)
        self.assertEqual(stderr.getvalue(), "")

    def test_run_succeeds_for_no_submission_date_without_analyzer(self) -> None:
        self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            argv=["run", "--json"],
            stdout=stdout,
            stderr=stderr,
            config=self.config,
            db=self.db,
            source=StaticSource([], latest_date=date(2026, 8, 14)),
            analyzer=None,
            analyzer_message="codex unavailable",
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["retrieved_count"], 0)
        self.assertEqual(payload["pending_source_dates"], ["2026-08-14"])

    def test_run_without_profiles_returns_failure(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            argv=["run"],
            stdout=stdout,
            stderr=stderr,
            config=self.config,
            db=self.db,
            source=StaticSource([article()]),
            analyzer=FakeAnalyzer(),
            preselector=self.preselector,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("interest profile", stderr.getvalue())

    def test_version_outputs_package_version(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(argv=["--version"], stdout=stdout, stderr=stderr)

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertRegex(stdout.getvalue(), r"research-digest \d+\.\d+\.\d+")

    def test_serve_launches_streamlit_and_prints_selected_url(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        launched: list[Sequence[str]] = []
        preferred_port = 18501

        with mock.patch("research_digest.cli._is_port_available", side_effect=[False, True]):
            exit_code = run_cli(
                argv=["serve", "--port", str(preferred_port)],
                stdout=stdout,
                stderr=stderr,
                process_launcher=lambda command: launched.append(tuple(command)),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(len(launched), 1)
        command = list(launched[0])
        self.assertIn("-m", command)
        self.assertIn("streamlit", command)
        self.assertIn("run", command)
        self.assertIn(f"--server.port={preferred_port + 1}", command)
        self.assertIn(f"http://localhost:{preferred_port + 1}", stdout.getvalue())

    def test_status_json_reports_versions_last_run_and_schedule(self) -> None:
        run_id = self.db.create_app_run(profile_id=None, source_name="arxiv")
        self.db.finish_app_run(
            run_id,
            status=APP_RUN_COMPLETED,
            retrieved_count=3,
            stored_count=2,
            preselected_count=2,
            skipped_analysis_count=1,
            analyzed_count=2,
            relevant_count=1,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            argv=["status", "--json"],
            stdout=stdout,
            stderr=stderr,
            config=self.config,
            db=self.db,
            scheduler_backend=StaticSchedulerBackend(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["data_path"], str(self.db_path))
        self.assertEqual(payload["analyzer_provider"], "codex")
        self.assertEqual(payload["schema_version"], self.db.get_schema_version())
        self.assertEqual(payload["config_version"], self.config.config_version)
        self.assertEqual(payload["last_run"]["status"], APP_RUN_COMPLETED)
        self.assertEqual(payload["last_run"]["relevant_count"], 1)
        self.assertTrue(payload["schedule"]["installed"])
        self.assertTrue(payload["schedule"]["status_available"])
        self.assertTrue(payload["automation"]["catch_up_missed_dates"])
        self.assertEqual(payload["automation"]["coverage_start_date"], "2026-08-14")
        self.assertEqual(payload["automation"]["covered_source_date_count"], 0)
        output = stdout.getvalue()
        self.assertNotIn("OPENAI_API_KEY", output)
        self.assertNotIn("sk-", output)

    def test_status_json_reports_scheduler_unknown_without_false_off_state(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            argv=["status", "--json"],
            stdout=stdout,
            stderr=stderr,
            config=self.config,
            db=self.db,
            scheduler_backend=FailingSchedulerBackend(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["schedule"]["status_available"])
        self.assertIsNone(payload["schedule"]["installed"])
        self.assertIn("LastTaskResult conversion failed", payload["schedule"]["message"])

    def test_status_json_reports_run_lock_state(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO run_locks (name, owner, acquired_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "digest",
                    "pid:legacy-uuid",
                    "2026-08-18T11:00:02.059131Z",
                    "2026-08-18T11:00:02.059131Z",
                ),
            )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            argv=["status", "--json"],
            stdout=stdout,
            stderr=stderr,
            config=self.config,
            db=self.db,
            scheduler_backend=FailingSchedulerBackend(),
        )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["run_lock"]["owner_state"], "unknown")
        self.assertEqual(payload["run_lock"]["acquired_at"], "2026-08-18T11:00:02.059131+00:00")

    def test_status_human_reports_scheduler_unknown_without_installed_false(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            argv=["status"],
            stdout=stdout,
            stderr=stderr,
            config=self.config,
            db=self.db,
            scheduler_backend=FailingSchedulerBackend(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        output = stdout.getvalue()
        self.assertIn("Schedule: status unavailable", output)
        self.assertIn("LastTaskResult conversion failed", output)
        self.assertNotIn("installed=False", output)

    def test_recover_abandoned_run_requires_force_for_legacy_owner(self) -> None:
        run_id = self.db.create_app_run(profile_id=None, source_name="arxiv")
        self.db.mark_app_run_running(run_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO run_locks (name, owner, acquired_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "digest",
                    "pid:legacy-uuid",
                    "2026-08-18T11:00:02.059131Z",
                    "2026-08-18T11:00:02.059131Z",
                ),
            )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            argv=["recover-abandoned-run", "--run-id", str(run_id), "--json"],
            stdout=stdout,
            stderr=stderr,
            config=self.config,
            db=self.db,
            scheduler_backend=StaticSchedulerBackend(),
        )

        self.assertEqual(exit_code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "failed")
        self.assertIn("cannot be verified", payload["error_message"])

    def test_recover_abandoned_run_force_preserves_counts_and_releases_lock(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO app_runs (
                    profile_id, source_name, started_at, status, retrieved_count,
                    stored_count, preselected_count, skipped_analysis_count, analyzed_count,
                    relevant_count
                )
                VALUES (?, ?, ?, ?, 198, 58, 177, 21, 70, 0)
                """,
                (None, "arxiv", "2026-08-18T11:00:02.527674Z", APP_RUN_RUNNING),
            )
            run_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute(
                """
                INSERT INTO run_locks (name, owner, acquired_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "digest",
                    "pid:legacy-uuid",
                    "2026-08-18T11:00:02.059131Z",
                    "2026-08-18T11:00:02.059131Z",
                ),
            )
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            argv=[
                "recover-abandoned-run",
                "--run-id",
                str(run_id),
                "--force-uninspectable-owner",
                "--json",
            ],
            stdout=stdout,
            stderr=stderr,
            config=self.config,
            db=self.db,
            scheduler_backend=StaticSchedulerBackend(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["recovered"])
        self.assertEqual(payload["status_before"], APP_RUN_RUNNING)
        self.assertEqual(payload["status_after"], "FAILED")
        self.assertEqual(payload["retrieved_count"], 198)
        self.assertEqual(payload["preselected_count"], 177)
        self.assertEqual(payload["analyzed_count"], 70)
        self.assertIsNone(self.db.get_run_lock())

    def test_backup_json_creates_snapshot(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        output_dir = Path(self.tmpdir.name) / "cli-backups"

        with mock.patch.dict("os.environ", {"RESEARCH_DIGEST_DB": str(self.db_path)}):
            exit_code = run_cli(
                argv=["backup", "--json", "--output", str(output_dir)],
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["data_path"], str(self.db_path))
        self.assertTrue(Path(str(payload["backup_path"])).exists())

if __name__ == "__main__":
    unittest.main()
