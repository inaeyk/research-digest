from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from research_digest.backup import run_backup
from research_digest.cli import run_cli
from research_digest.config import CONFIG_VERSION, DEFAULT_CONFIG_FILENAME, load_config
from research_digest.db import CURRENT_SCHEMA_VERSION, Database
from research_digest.doctor import DoctorSeverity, run_doctor


class ReleaseQualificationMatrixTests(unittest.TestCase):
    def test_fresh_install_like_environment_initializes_config_db_and_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = _isolated_env(tmp)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=True):
                exit_code = run_cli(argv=["status", "--json"], stdout=stdout, stderr=stderr)

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["schema_version"], CURRENT_SCHEMA_VERSION)
            self.assertEqual(payload["config_version"], CONFIG_VERSION)
            self.assertTrue((Path(tmp) / "config" / DEFAULT_CONFIG_FILENAME).exists())
            self.assertTrue((Path(tmp) / "data" / "research_digest.sqlite3").exists())

    def test_m2_style_upgrade_repeated_startup_and_backup_preserve_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.sqlite3"
            _create_representative_m2_qualified_db(legacy)
            env = _isolated_env(tmp) | {"RESEARCH_DIGEST_LEGACY_DB": str(legacy)}

            with mock.patch.dict(os.environ, env, clear=True):
                config = load_config()
                db = Database(config.db_path)
                try:
                    first_counts = _semantic_counts(config.db_path)
                    first_version = db.get_schema_version()
                    migration_backup = db.get_last_migration_backup_path()
                finally:
                    db.close()

                reopened = Database(config.db_path)
                try:
                    second_counts = _semantic_counts(config.db_path)
                    second_version = reopened.get_schema_version()
                    migrated_fingerprint = _single_value(
                        config.db_path,
                        "SELECT profile_fingerprint FROM relevance_analyses WHERE id = 1",
                    )
                    backup = run_backup(
                        output_path=root / "backup?with#reserved.sqlite3",
                        export_json=True,
                        timestamp=datetime(2026, 8, 17, 12, 0, tzinfo=UTC),
                    )
                finally:
                    reopened.close()

            self.assertEqual(first_version, CURRENT_SCHEMA_VERSION)
            self.assertEqual(second_version, CURRENT_SCHEMA_VERSION)
            self.assertEqual(first_counts, second_counts)
            self.assertEqual(first_counts["interest_profiles"], 1)
            self.assertEqual(first_counts["articles"], 1)
            self.assertEqual(first_counts["relevance_analyses"], 1)
            self.assertEqual(first_counts["article_feedback"], 1)
            self.assertEqual(first_counts["app_runs"], 1)
            self.assertEqual(first_counts["run_snapshots"], 0)
            self.assertEqual(migrated_fingerprint, "m2:fingerprint")
            self.assertIsNotNone(migration_backup)
            assert migration_backup is not None
            self.assertTrue(migration_backup.exists())
            self.assertTrue(backup.backup_path.exists())
            self.assertIsNotNone(backup.export_path)
            assert backup.export_path is not None
            self.assertTrue(backup.export_path.exists())
            with sqlite3.connect(backup.backup_path) as conn:
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_v010_upgrade_preserves_history_config_and_legacy_source_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = _isolated_env(tmp)
            config_path = root / "config" / DEFAULT_CONFIG_FILENAME
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "config_version": 1,
                        "analyzer_provider": "codex",
                        "openai_model": "gpt-5-mini",
                        "codex_model": None,
                        "codex_timeout_seconds": 180.0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            legacy_db = root / "data" / "research_digest.sqlite3"
            legacy_db.parent.mkdir(parents=True)
            _create_representative_v010_db(legacy_db)

            with mock.patch.dict(os.environ, env, clear=True):
                config = load_config()
                db = Database(config.db_path)
                try:
                    source = db.get_arxiv_config()
                    runs = db.get_app_runs()
                    snapshot = db.get_run_snapshot(run_id=1)
                    backup = run_backup(
                        output_path=root / "v010-upgrade-backup.sqlite3",
                        export_json=True,
                    )
                    first_counts = _semantic_counts(config.db_path)
                    first_version = db.get_schema_version()
                    migration_backup = db.get_last_migration_backup_path()
                finally:
                    db.close()

                reopened = Database(config.db_path)
                try:
                    second_counts = _semantic_counts(config.db_path)
                    second_version = reopened.get_schema_version()
                finally:
                    reopened.close()

            self.assertEqual(config.config_version, CONFIG_VERSION)
            self.assertIsNotNone(config.last_config_backup_path)
            self.assertEqual(first_version, CURRENT_SCHEMA_VERSION)
            self.assertEqual(second_version, CURRENT_SCHEMA_VERSION)
            self.assertIsNotNone(migration_backup)
            self.assertEqual(first_counts, second_counts)
            self.assertEqual(first_counts["interest_profiles"], 1)
            self.assertEqual(first_counts["articles"], 1)
            self.assertEqual(first_counts["relevance_analyses"], 1)
            self.assertEqual(first_counts["article_feedback"], 1)
            self.assertEqual(first_counts["app_runs"], 1)
            self.assertEqual(first_counts["run_snapshots"], 1)
            self.assertEqual(first_counts["source_date_coverage"], 0)
            self.assertIsNotNone(source)
            assert source is not None
            self.assertEqual(source.lookback_hours, 72)
            self.assertEqual(source.max_results, 25)
            self.assertEqual(runs[0]["run_origin"], "LEGACY")
            self.assertEqual(runs[0]["requested_source_dates_json"], "[]")
            self.assertEqual(runs[0]["retrieval_complete"], 1)
            self.assertIsNotNone(snapshot)
            self.assertTrue(backup.backup_path.exists())
            self.assertIsNotNone(backup.export_path)
            assert backup.export_path is not None
            self.assertTrue(backup.export_path.exists())

    def test_codex_unavailable_and_network_failure_are_bounded_and_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = _isolated_env(tmp)
            with mock.patch.dict(os.environ, env, clear=True):
                config = load_config()
                db = Database(config.db_path)
                self.addCleanup(db.close)
                with mock.patch("research_digest.doctor.shutil.which", return_value=None):
                    report = run_doctor(config=config, db=db, include_network=False)

                self.assertIn(
                    "provider",
                    [
                        check.name
                        for check in report.checks
                        if check.severity == DoctorSeverity.FAILURE
                    ],
                )
                output = json.dumps(report.to_mapping())
                self.assertNotIn("OPENAI_API_KEY", output)
                self.assertNotIn("sk-", output)

                network_report = run_doctor(
                    config=config,
                    db=db,
                    include_network=True,
                    network_checker=lambda url, timeout: (_raise_secret_network_error()),
                )

            network_output = json.dumps(network_report.to_mapping())
            self.assertIn("[REDACTED_API_KEY]", network_output)
            self.assertNotIn("sk-secret", network_output)

    def test_serve_port_conflict_uses_next_available_port(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        launched: list[tuple[str, ...]] = []
        preferred_port = 18601

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
        self.assertIn(f"--server.port={preferred_port + 1}", launched[0])
        self.assertIn(f"http://localhost:{preferred_port + 1}", stdout.getvalue())

    def test_package_wheel_exposes_installed_cli_entry_point(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            wheelhouse = Path(tmp) / "wheelhouse"
            wheelhouse.mkdir()
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    ".",
                    "--no-deps",
                    "-w",
                    str(wheelhouse),
                ],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            wheels = sorted(wheelhouse.glob("research_digest-*.whl"))
            self.assertEqual(len(wheels), 1)
            with zipfile.ZipFile(wheels[0]) as wheel:
                names = set(wheel.namelist())
                entry_points = wheel.read(
                    "research_digest-0.5.0.dist-info/entry_points.txt"
                ).decode("utf-8")
                metadata = wheel.read("research_digest-0.5.0.dist-info/METADATA").decode(
                    "utf-8"
                )

        self.assertIn("research_digest/cli.py", names)
        self.assertNotIn("research_digest/analysis/fake.py", names)
        self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in names))
        self.assertIn("research-digest = research_digest.cli:main", entry_points)
        self.assertIn("Provides-Extra: dev", metadata)
        self.assertIn('Requires-Dist: pytest>=8.0; extra == "dev"', metadata)
        self.assertIn('Requires-Dist: mypy>=1.10; extra == "dev"', metadata)
        self.assertIn('Requires-Dist: ruff>=0.5; extra == "dev"', metadata)

    def test_documented_editable_dev_install_exposes_cli_entry_point(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "venv"
            subprocess.run(
                [sys.executable, "-m", "venv", str(venv)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    str(venv / "bin" / "python"),
                    "-m",
                    "pip",
                    "install",
                    "-e",
                    ".[dev]",
                    "--no-deps",
                ],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            result = subprocess.run(
                [str(venv / "bin" / "research-digest"), "--version"],
                cwd=Path(tmp),
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.stdout.strip(), "research-digest 0.5.0")


def _isolated_env(tmp: str) -> dict[str, str]:
    root = Path(tmp)
    return {
        "RESEARCH_DIGEST_DATA_DIR": str(root / "data"),
        "RESEARCH_DIGEST_CONFIG_DIR": str(root / "config"),
        "RESEARCH_DIGEST_LEGACY_DB": str(root / "missing.sqlite3"),
    }


def _create_representative_m2_qualified_db(path: Path) -> None:
    now = "2026-08-14T12:00:00Z"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE interest_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                relevance_threshold REAL NOT NULL,
                enabled INTEGER NOT NULL,
                created_at TEXT NOT NULL,
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
            CREATE TABLE article_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                profile_id INTEGER NOT NULL,
                profile_fingerprint TEXT NOT NULL,
                feedback_label TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(article_id, profile_id, profile_fingerprint),
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
                FOREIGN KEY(profile_id) REFERENCES interest_profiles(id) ON DELETE CASCADE
            );
            CREATE TABLE app_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER,
                source_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                retrieved_count INTEGER NOT NULL DEFAULT 0,
                stored_count INTEGER NOT NULL DEFAULT 0,
                preselected_count INTEGER NOT NULL DEFAULT 0,
                skipped_analysis_count INTEGER NOT NULL DEFAULT 0,
                analyzed_count INTEGER NOT NULL DEFAULT 0,
                relevant_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                FOREIGN KEY(profile_id) REFERENCES interest_profiles(id) ON DELETE SET NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO interest_profiles (
                id, name, description, relevance_threshold, enabled, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "Gravity", "Higher-dimensional gravity.", 0.6, 1, now, now),
        )
        conn.execute(
            """
            INSERT INTO source_configs (
                source_name, enabled, categories_json, lookback_hours, max_results, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("arxiv", 1, json.dumps(["hep-th"]), 24, 5, now),
        )
        conn.execute(
            """
            INSERT INTO articles (
                id, source, source_article_id, title, authors_json, abstract,
                categories_json, published_at, updated_at, abstract_url, pdf_url, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "arxiv",
                "2608.release01",
                "Release qualification paper",
                json.dumps(["Ada Lovelace"]),
                "A paper about higher-dimensional gravity.",
                json.dumps(["hep-th"]),
                "2026-08-14T10:00:00Z",
                "2026-08-14T11:00:00Z",
                "http://arxiv.org/abs/2608.release01",
                None,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO relevance_analyses (
                id, article_id, profile_id, profile_fingerprint, relevance_score,
                relevance_reason, matched_topics_json, summary, why_it_matters,
                reading_priority, analyzed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                1,
                1,
                "m2:fingerprint",
                0.9,
                "Direct match.",
                json.dumps(["gravity"]),
                "Summary.",
                "It matches.",
                "HIGH",
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO article_feedback (
                id, article_id, profile_id, profile_fingerprint, feedback_label,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 1, 1, "m2:fingerprint", "RELEVANT", now, now),
        )
        conn.execute(
            """
            INSERT INTO app_runs (
                id, profile_id, source_name, started_at, completed_at, status,
                retrieved_count, stored_count, preselected_count,
                skipped_analysis_count, analyzed_count, relevant_count, error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 1, "arxiv", now, now, "COMPLETED", 1, 1, 1, 0, 1, 1, None),
        )


def _create_representative_v010_db(path: Path) -> None:
    now = "2026-08-14T12:00:00Z"
    _create_representative_m2_qualified_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            UPDATE source_configs
            SET lookback_hours = ?, max_results = ?
            WHERE source_name = ?
            """,
            (72, 25, "arxiv"),
        )
        conn.executescript(
            """
            CREATE TABLE schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE run_locks (
                name TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE run_snapshots (
                run_id INTEGER PRIMARY KEY,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES app_runs(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            """
            INSERT INTO schema_metadata (key, value, updated_at)
            VALUES (?, ?, ?)
            """,
            ("schema_version", "4", now),
        )
        conn.execute(
            """
            INSERT INTO run_snapshots (run_id, snapshot_json, created_at)
            VALUES (?, ?, ?)
            """,
            (
                1,
                json.dumps(
                    {
                        "run_id": 1,
                        "profile_id": 1,
                        "profile_name": "Gravity",
                        "items": [],
                        "synthesis": {"relevant_count": 1},
                    }
                ),
                now,
            ),
        )


def _semantic_counts(path: Path) -> dict[str, int]:
    tables = (
        "interest_profiles",
        "source_configs",
        "articles",
        "relevance_analyses",
        "article_feedback",
        "app_runs",
        "run_snapshots",
        "source_date_coverage",
        "library_articles",
        "library_tags",
        "library_tag_assignments",
        "library_ai_tag_suppressions",
        "library_article_notes",
        "library_collections",
        "library_collection_memberships",
        "library_search_documents",
        "library_article_connections",
        "library_context_suggestions",
        "collection_intelligence_snapshots",
        "suggested_interest_profiles",
    )
    with sqlite3.connect(path) as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }


def _single_value(path: Path, sql: str) -> str:
    with sqlite3.connect(path) as conn:
        value = conn.execute(sql).fetchone()[0]
    return str(value)


def _raise_secret_network_error() -> None:
    raise RuntimeError("network failed with OPENAI_API_KEY=sk-secret123456789")


if __name__ == "__main__":
    unittest.main()
