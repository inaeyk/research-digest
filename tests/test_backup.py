from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from unittest import mock

from research_digest.backup import BackupError, run_backup
from research_digest.cli import run_cli
from research_digest.db import APP_RUN_COMPLETED, Database
from research_digest.models import (
    Article,
    ArxivSourceConfig,
    RunOrigin,
    profile_semantic_fingerprint,
)


def sample_article() -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id="2608.70001",
        title="Backup export title",
        authors=["Ada Lovelace"],
        abstract="Abstract remains inside the SQLite backup.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
        abstract_url="http://arxiv.org/abs/2608.70001",
        pdf_url=None,
    )


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.db_path = self.root / "research_digest.sqlite3"
        self.db = Database(self.db_path)
        self.env_patch = mock.patch.dict(
            "os.environ",
            {"RESEARCH_DIGEST_DB": str(self.db_path)},
        )
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.db.close()
        self.tmpdir.cleanup()

    def test_backup_creates_valid_sqlite_snapshot(self) -> None:
        profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
        )
        self.assertIsNotNone(profile.id)
        output_dir = self.root / "backups"

        result = run_backup(
            output_path=output_dir,
            timestamp=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
        )

        self.assertEqual(result.db_path, self.db_path)
        self.assertEqual(result.backup_path.parent, output_dir)
        self.assertTrue(result.backup_path.exists())
        with sqlite3.connect(result.backup_path) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            count = conn.execute("SELECT COUNT(*) FROM interest_profiles").fetchone()
        self.assertIsNotNone(integrity)
        self.assertEqual(integrity[0], "ok")
        self.assertIsNotNone(count)
        self.assertEqual(count[0], 1)

    def test_backup_refuses_missing_database_without_creating_state(self) -> None:
        missing_path = self.root / "missing.sqlite3"
        output_dir = self.root / "missing-backups"

        with (
            mock.patch.dict("os.environ", {"RESEARCH_DIGEST_DB": str(missing_path)}),
            self.assertRaisesRegex(BackupError, "database does not exist"),
        ):
            run_backup(output_path=output_dir)

        self.assertFalse(missing_path.exists())
        self.assertFalse(output_dir.exists())

    def test_backup_refuses_invalid_database(self) -> None:
        invalid_path = self.root / "invalid.sqlite3"
        invalid_path.write_text("not sqlite", encoding="utf-8")

        with (
            mock.patch.dict("os.environ", {"RESEARCH_DIGEST_DB": str(invalid_path)}),
            self.assertRaises(BackupError),
        ):
            run_backup(output_path=self.root / "invalid-backups")

    def test_backup_handles_read_only_path_with_uri_reserved_characters(self) -> None:
        reserved_path = self.root / "db?with#reserved.sqlite3"
        reserved_db = Database(reserved_path)
        try:
            reserved_db.create_interest_profile(
                name="Reserved",
                description="Filename contains URI-reserved characters.",
            )
        finally:
            reserved_db.close()

        with mock.patch.dict("os.environ", {"RESEARCH_DIGEST_DB": str(reserved_path)}):
            result = run_backup(
                output_path=self.root / "reserved-backups",
                timestamp=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
            )

        self.assertTrue(result.backup_path.exists())
        with sqlite3.connect(result.backup_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM interest_profiles").fetchone()
        self.assertIsNotNone(count)
        self.assertEqual(count[0], 1)

    def test_existing_export_sidecar_fails_before_backup_is_written(self) -> None:
        backup_path = self.root / "manual.sqlite3"
        export_path = self.root / "manual.export.json"
        export_path.write_text("{}\n", encoding="utf-8")

        with self.assertRaisesRegex(BackupError, "export path already exists"):
            run_backup(output_path=backup_path, export_json=True)

        self.assertFalse(backup_path.exists())

    def test_backup_json_export_contains_user_semantic_data_without_secrets(self) -> None:
        profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
        )
        assert profile.id is not None
        self.db.save_arxiv_config(
            ArxivSourceConfig(
                enabled=True,
                categories=["hep-th"],
                lookback_hours=24,
                max_results=10,
            )
        )
        article, _ = self.db.upsert_article(sample_article())
        assert article.id is not None
        self.db.upsert_article_feedback(
            article_id=article.id,
            profile_id=profile.id,
            profile_fingerprint=profile_semantic_fingerprint(profile),
            feedback_label="RELEVANT",
        )
        run_id = self.db.create_app_run(profile_id=profile.id, source_name="arxiv")
        self.db.finish_app_run(
            run_id,
            status=APP_RUN_COMPLETED,
            retrieved_count=1,
            stored_count=1,
            preselected_count=1,
            skipped_analysis_count=0,
            analyzed_count=1,
            relevant_count=1,
        )
        self.db.mark_source_date_covered(
            profile_id=profile.id,
            profile_fingerprint=profile_semantic_fingerprint(profile),
            source_name="arxiv",
            source_fingerprint="source-a",
            source_date=date(2026, 8, 14),
            run_id=run_id,
            run_origin=RunOrigin.SCHEDULED,
        )
        self.db.save_run_snapshot(
            run_id=run_id,
            snapshot_json=json.dumps(
                {
                    "run_id": run_id,
                    "profile_name": "Gravity",
                    "synthesis": {"relevant_count": 1},
                }
            ),
        )

        with mock.patch.dict(
            "os.environ",
            {
                "RESEARCH_DIGEST_DB": str(self.db_path),
                "OPENAI_API_KEY": "sk-secret123456789",
            },
        ):
            result = run_backup(
                output_path=self.root / "export-backups",
                export_json=True,
                timestamp=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
            )

        self.assertIsNotNone(result.export_path)
        assert result.export_path is not None
        payload = json.loads(result.export_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["export_version"], 1)
        self.assertEqual(payload["profiles"][0]["name"], "Gravity")
        self.assertEqual(payload["source_settings"][0]["categories"], ["hep-th"])
        self.assertEqual(payload["feedback"][0]["feedback_label"], "RELEVANT")
        self.assertEqual(payload["runs"][0]["status"], APP_RUN_COMPLETED)
        self.assertEqual(payload["run_snapshots"][0]["snapshot"]["profile_name"], "Gravity")
        self.assertEqual(payload["source_date_coverage"][0]["source_date"], "2026-08-14")
        output = result.export_path.read_text(encoding="utf-8")
        self.assertNotIn("OPENAI_API_KEY", output)
        self.assertNotIn("sk-secret", output)
        self.assertNotIn(".env", output)

    def test_cli_backup_json_success_and_failure(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        output_dir = self.root / "cli-backups"

        with mock.patch.dict("os.environ", {"RESEARCH_DIGEST_DB": str(self.db_path)}):
            exit_code = run_cli(
                argv=["backup", "--json", "--output", str(output_dir), "--export-json"],
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "completed")
        self.assertTrue(Path(str(payload["backup_path"])).exists())
        self.assertTrue(Path(str(payload["export_path"])).exists())

        missing_stdout = io.StringIO()
        missing_stderr = io.StringIO()
        with mock.patch.dict(
            "os.environ",
            {"RESEARCH_DIGEST_DB": str(self.root / "does-not-exist.sqlite3")},
        ):
            missing_exit = run_cli(
                argv=["backup", "--json", "--output", str(self.root / "missing-out")],
                stdout=missing_stdout,
                stderr=missing_stderr,
            )

        self.assertEqual(missing_exit, 1)
        self.assertEqual(missing_stderr.getvalue(), "")
        self.assertEqual(json.loads(missing_stdout.getvalue())["status"], "failed")


if __name__ == "__main__":
    unittest.main()
