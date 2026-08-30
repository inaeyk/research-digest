from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import research_digest.db as db_module
from research_digest.cli import run_cli
from research_digest.config import AppConfig
from research_digest.db import APP_RUN_COMPLETED, APP_RUN_FAILED, Database
from research_digest.doctor import DoctorSeverity, ReadOnlyDoctorDatabase, run_doctor
from research_digest.scheduler import ScheduleError, ScheduleOperationResult, ScheduleStatus


class InstalledSchedulerBackend:
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
        )


class FailingSchedulerBackend:
    def install(self, request: object) -> ScheduleOperationResult:
        raise AssertionError("not used")

    def remove(self, *, task_name: str) -> ScheduleOperationResult:
        raise AssertionError("not used")

    def status(self, *, task_name: str) -> ScheduleStatus:
        raise ScheduleError(
            "scheduler failed at /home/"
            + "inaeyk/private with OPENAI_API_KEY=sk-secret"
        )


class LeakySchedulerStatusBackend:
    def install(self, request: object) -> ScheduleOperationResult:
        raise AssertionError("not used")

    def remove(self, *, task_name: str) -> ScheduleOperationResult:
        raise AssertionError("not used")

    def status(self, *, task_name: str) -> ScheduleStatus:
        return ScheduleStatus(
            backend="test",
            task_name=task_name,
            installed=False,
            timezone="test local time",
            message="OPENAI_API_KEY=sk-secret123456789 at /home/inaeyk/private",
        )


class StaleCodexPathSchedulerBackend:
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
            arguments=(
                "-d Ubuntu --exec env "
                "PATH=/old/node/bin:/usr/local/bin:/usr/bin "
                "/tmp/venv/bin/research-digest run"
            ),
        )


class DoctorTests(unittest.TestCase):
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
        )

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_doctor_json_success_warning_and_failure(self) -> None:
        self.db.create_app_run(profile_id=None, source_name="arxiv")
        run_id = self.db.create_app_run(profile_id=None, source_name="arxiv")
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
        stdout = io.StringIO()
        stderr = io.StringIO()

        with mock.patch("shutil.which", return_value="/usr/bin/codex"):
            exit_code = run_cli(
                argv=["doctor", "--json"],
                stdout=stdout,
                stderr=stderr,
                config=self.config,
                db=self.db,
                scheduler_backend=InstalledSchedulerBackend(),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "completed")
        severities = {check["name"]: check["severity"] for check in payload["checks"]}
        self.assertEqual(severities["python"], DoctorSeverity.PASS)
        self.assertEqual(severities["provider"], DoctorSeverity.PASS)
        self.assertEqual(severities["network"], DoctorSeverity.WARNING)

    def test_missing_codex_executable_is_failure(self) -> None:
        with mock.patch("shutil.which", return_value=None):
            report = run_doctor(
                config=self.config,
                db=self.db,
                scheduler_backend=InstalledSchedulerBackend(),
            )

        provider = _check(report.to_mapping(), "provider")
        self.assertEqual(provider["severity"], DoctorSeverity.FAILURE)
        self.assertEqual(report.exit_code, 1)

    def test_openai_without_api_key_is_failure_without_secret_output(self) -> None:
        config = AppConfig(
            db_path=self.db_path,
            data_dir=self.db_path.parent,
            config_dir=self.db_path.parent / "config",
            analyzer_provider="openai",
            openai_api_key=None,
            openai_model="gpt-test",
            codex_model=None,
            codex_timeout_seconds=1,
        )

        report = run_doctor(
            config=config,
            db=self.db,
            scheduler_backend=InstalledSchedulerBackend(),
        )

        payload_text = json.dumps(report.to_mapping())
        self.assertIn("OPENAI_API_KEY is not set", payload_text)
        self.assertNotIn("sk-", payload_text)
        self.assertEqual(report.exit_code, 1)

    def test_failed_last_run_is_failure(self) -> None:
        run_id = self.db.create_app_run(profile_id=None, source_name="arxiv")
        self.db.finish_app_run(
            run_id,
            status=APP_RUN_FAILED,
            retrieved_count=0,
            stored_count=0,
            preselected_count=0,
            skipped_analysis_count=0,
            analyzed_count=0,
            relevant_count=0,
            error_message="failed",
        )

        with mock.patch("shutil.which", return_value="/usr/bin/codex"):
            report = run_doctor(
                config=self.config,
                db=self.db,
                scheduler_backend=InstalledSchedulerBackend(),
            )

        self.assertEqual(
            _check(report.to_mapping(), "last_run")["severity"],
            DoctorSeverity.FAILURE,
        )

    def test_scheduler_error_is_sanitized_warning(self) -> None:
        with mock.patch("shutil.which", return_value="/usr/bin/codex"):
            report = run_doctor(
                config=self.config,
                db=self.db,
                scheduler_backend=FailingSchedulerBackend(),
            )

        scheduler = _check(report.to_mapping(), "scheduler")
        message = str(scheduler["message"])
        self.assertEqual(scheduler["severity"], DoctorSeverity.WARNING)
        self.assertNotIn("/home/" + "inaeyk", message)
        self.assertNotIn("sk-secret", message)

    def test_scheduler_status_message_is_sanitized_warning(self) -> None:
        with mock.patch("shutil.which", return_value="/usr/bin/codex"):
            report = run_doctor(
                config=self.config,
                db=self.db,
                scheduler_backend=LeakySchedulerStatusBackend(),
            )

        scheduler = _check(report.to_mapping(), "scheduler")
        message = str(scheduler["message"])
        self.assertEqual(scheduler["severity"], DoctorSeverity.WARNING)
        self.assertNotIn("/home/" + "inaeyk", message)
        self.assertNotIn("sk-secret", message)
        self.assertIn("[REDACTED_API_KEY]", message)

    def test_scheduler_warns_when_installed_codex_path_is_stale(self) -> None:
        with mock.patch(
            "shutil.which",
            return_value="/home/me/.nvm/versions/node/v22.22.2/bin/codex",
        ):
            report = run_doctor(
                config=self.config,
                db=self.db,
                scheduler_backend=StaleCodexPathSchedulerBackend(),
            )

        scheduler = _check(report.to_mapping(), "scheduler")
        message = str(scheduler["message"])
        self.assertEqual(scheduler["severity"], DoctorSeverity.WARNING)
        self.assertIn("does not include the current Codex directory", message)
        self.assertIn("/home/me/.nvm/versions/node/v22.22.2/bin", message)

    def test_network_check_runs_only_when_requested(self) -> None:
        calls: list[tuple[str, float]] = []

        def checker(url: str, timeout: float) -> None:
            calls.append((url, timeout))

        report = run_doctor(
            config=self.config,
            db=self.db,
            scheduler_backend=InstalledSchedulerBackend(),
            include_network=False,
            network_checker=checker,
        )
        self.assertEqual(calls, [])
        self.assertEqual(_check(report.to_mapping(), "network")["severity"], DoctorSeverity.WARNING)

        with mock.patch("shutil.which", return_value="/usr/bin/codex"):
            report = run_doctor(
                config=self.config,
                db=self.db,
                scheduler_backend=InstalledSchedulerBackend(),
                include_network=True,
                network_timeout_seconds=2.5,
                network_checker=checker,
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 2.5)
        self.assertEqual(_check(report.to_mapping(), "network")["severity"], DoctorSeverity.PASS)

    def test_invalid_network_timeout_is_failure_without_network_probe(self) -> None:
        calls: list[tuple[str, float]] = []

        def checker(url: str, timeout: float) -> None:
            calls.append((url, timeout))

        with mock.patch("shutil.which", return_value="/usr/bin/codex"):
            report = run_doctor(
                config=self.config,
                db=self.db,
                scheduler_backend=InstalledSchedulerBackend(),
                include_network=True,
                network_timeout_seconds=float("inf"),
                network_checker=checker,
            )

        self.assertEqual(calls, [])
        self.assertEqual(
            _check(report.to_mapping(), "network_timeout")["severity"],
            DoctorSeverity.FAILURE,
        )
        self.assertEqual(report.exit_code, 1)

    def test_supported_schema_18_is_read_only_warning_for_upgrade_preflight(self) -> None:
        schema_18_path = Path(self.tmpdir.name) / "schema-18.sqlite3"
        _create_database_at_schema(schema_18_path, version=18)
        config = replace(self.config, db_path=schema_18_path)
        before = schema_18_path.read_bytes()

        with mock.patch("shutil.which", return_value="/usr/bin/codex"):
            report = run_doctor(
                config=config,
                db=ReadOnlyDoctorDatabase(schema_18_path),
                scheduler_backend=InstalledSchedulerBackend(),
            )

        schema = _check(report.to_mapping(), "schema_version")
        self.assertEqual(schema["severity"], DoctorSeverity.WARNING)
        self.assertEqual(
            schema["message"],
            "database schema 18 is supported and will migrate to schema 20 on normal "
            "application startup.",
        )
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(schema_18_path.read_bytes(), before)
        with sqlite3.connect(schema_18_path) as conn:
            version = conn.execute(
                "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
            ).fetchone()
        self.assertEqual(version, ("18",))
        self.assertEqual(list(schema_18_path.parent.glob("*.backup-v18-to-v20-*.sqlite3")), [])

    def test_supported_pre_metadata_legacy_schema_is_read_only_warning(self) -> None:
        legacy_path = Path(self.tmpdir.name) / "pre-metadata.sqlite3"
        with sqlite3.connect(legacy_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            db_module.MIGRATIONS[0].apply(conn)
        before = legacy_path.read_bytes()

        report = run_doctor(
            config=replace(self.config, db_path=legacy_path),
            db=ReadOnlyDoctorDatabase(legacy_path),
            scheduler_backend=InstalledSchedulerBackend(),
        )

        schema = _check(report.to_mapping(), "schema_version")
        self.assertEqual(schema["severity"], DoctorSeverity.WARNING)
        self.assertEqual(
            schema["message"],
            "database schema 0 is supported and will migrate to schema 20 on normal "
            "application startup.",
        )
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(legacy_path.read_bytes(), before)
        self.assertEqual(list(legacy_path.parent.glob("*.backup-v0-to-v20-*.sqlite3")), [])

    def test_existing_metadata_table_without_schema_version_is_failure(self) -> None:
        invalid_path = Path(self.tmpdir.name) / "missing-schema-version.sqlite3"
        _create_database_at_schema(invalid_path, version=18)
        with sqlite3.connect(invalid_path) as conn:
            conn.execute("DELETE FROM schema_metadata WHERE key = 'schema_version'")
        before = invalid_path.read_bytes()

        report = run_doctor(
            config=replace(self.config, db_path=invalid_path),
            db=ReadOnlyDoctorDatabase(invalid_path),
            scheduler_backend=InstalledSchedulerBackend(),
        )

        schema = _check(report.to_mapping(), "schema_version")
        self.assertEqual(schema["severity"], DoctorSeverity.FAILURE)
        self.assertIn("metadata is missing a supported schema version", str(schema["message"]))
        self.assertEqual(report.exit_code, 1)
        self.assertEqual(invalid_path.read_bytes(), before)

    def test_explicit_schema_zero_metadata_is_failure(self) -> None:
        invalid_path = Path(self.tmpdir.name) / "explicit-schema-zero.sqlite3"
        _create_database_at_schema(invalid_path, version=18)
        with sqlite3.connect(invalid_path) as conn:
            conn.execute(
                "UPDATE schema_metadata SET value = '0' WHERE key = 'schema_version'"
            )

        report = run_doctor(
            config=replace(self.config, db_path=invalid_path),
            db=ReadOnlyDoctorDatabase(invalid_path),
            scheduler_backend=InstalledSchedulerBackend(),
        )

        schema = _check(report.to_mapping(), "schema_version")
        self.assertEqual(schema["severity"], DoctorSeverity.FAILURE)
        self.assertIn("metadata is missing a supported schema version", str(schema["message"]))
        self.assertEqual(report.exit_code, 1)

    def test_pre_metadata_partial_unique_is_rejected_after_rehearsal(self) -> None:
        invalid_path = Path(self.tmpdir.name) / "partial-unique-pre-metadata.sqlite3"
        _create_database_at_schema(invalid_path, version=18)
        with sqlite3.connect(invalid_path) as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("PRAGMA legacy_alter_table = ON")
            conn.execute("DROP TABLE schema_metadata")
            conn.execute("ALTER TABLE articles RENAME TO articles_with_unique")
            conn.execute(
                """
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
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("DROP TABLE articles_with_unique")
            conn.execute(
                "CREATE UNIQUE INDEX misleading_article_unique "
                "ON articles(source, source_article_id) WHERE id < 0"
            )

        report = run_doctor(
            config=replace(self.config, db_path=invalid_path),
            db=ReadOnlyDoctorDatabase(invalid_path),
            scheduler_backend=InstalledSchedulerBackend(),
        )

        schema = _check(report.to_mapping(), "schema_version")
        self.assertEqual(schema["severity"], DoctorSeverity.FAILURE)
        self.assertIn("does not match its required definition", str(schema["message"]))
        self.assertEqual(report.exit_code, 1)

    def test_pre_metadata_added_check_constraint_is_rejected_after_rehearsal(self) -> None:
        invalid_path = Path(self.tmpdir.name) / "extra-check-pre-metadata.sqlite3"
        _create_database_at_schema(invalid_path, version=18)
        with sqlite3.connect(invalid_path) as conn:
            conn.execute("DROP TABLE schema_metadata")
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'articles'"
            ).fetchone()
            assert row is not None and isinstance(row[0], str)
            definition, separator, suffix = row[0].rpartition(")")
            self.assertEqual(separator, ")")
            changed = definition + ", CHECK(length(title) > 0))" + suffix
            conn.execute("PRAGMA writable_schema = ON")
            conn.execute(
                "UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = 'articles'",
                (changed,),
            )
            conn.execute("PRAGMA writable_schema = OFF")

        report = run_doctor(
            config=replace(self.config, db_path=invalid_path),
            db=ReadOnlyDoctorDatabase(invalid_path),
            scheduler_backend=InstalledSchedulerBackend(),
        )

        schema = _check(report.to_mapping(), "schema_version")
        self.assertEqual(schema["severity"], DoctorSeverity.FAILURE)
        self.assertIn("does not match its required definition", str(schema["message"]))
        self.assertEqual(report.exit_code, 1)

    def test_structurally_invalid_schema_18_is_failure(self) -> None:
        invalid_path = Path(self.tmpdir.name) / "invalid-schema-18.sqlite3"
        with sqlite3.connect(invalid_path) as conn:
            conn.executescript(
                """
                CREATE TABLE schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO schema_metadata (key, value, updated_at)
                VALUES ('schema_version', '18', '2026-08-30T00:00:00Z');
                """
            )

        report = run_doctor(
            config=replace(self.config, db_path=invalid_path),
            db=ReadOnlyDoctorDatabase(invalid_path),
            scheduler_backend=InstalledSchedulerBackend(),
        )

        schema = _check(report.to_mapping(), "schema_version")
        self.assertEqual(schema["severity"], DoctorSeverity.FAILURE)
        self.assertIn("missing required tables", str(schema["message"]))
        self.assertEqual(report.exit_code, 1)

    def test_schema_18_missing_required_unique_constraint_is_failure(self) -> None:
        invalid_path = Path(self.tmpdir.name) / "schema-18-without-article-unique.sqlite3"
        _create_database_at_schema(invalid_path, version=18)
        with sqlite3.connect(invalid_path) as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("PRAGMA legacy_alter_table = ON")
            conn.execute("ALTER TABLE articles RENAME TO articles_with_unique")
            conn.execute(
                """
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
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("DROP TABLE articles_with_unique")
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertFalse(
                any(bool(row["unique"]) for row in _index_rows(conn, "articles"))
            )

        report = run_doctor(
            config=replace(self.config, db_path=invalid_path),
            db=ReadOnlyDoctorDatabase(invalid_path),
            scheduler_backend=InstalledSchedulerBackend(),
        )

        schema = _check(report.to_mapping(), "schema_version")
        self.assertEqual(schema["severity"], DoctorSeverity.FAILURE)
        self.assertIn("does not match its required definition", str(schema["message"]))
        self.assertEqual(report.exit_code, 1)

    def test_schema_18_changed_check_constraint_is_failure(self) -> None:
        invalid_path = Path(self.tmpdir.name) / "schema-18-with-changed-check.sqlite3"
        _create_database_at_schema(invalid_path, version=18)
        with sqlite3.connect(invalid_path) as conn:
            row = conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'quantitative_relevance_calibrations'"
            ).fetchone()
            assert row is not None and isinstance(row[0], str)
            changed = row[0].replace("'PENDING'", "'pending'", 1)
            self.assertNotEqual(changed, row[0])
            conn.execute("PRAGMA writable_schema = ON")
            conn.execute(
                "UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = ?",
                (changed, "quantitative_relevance_calibrations"),
            )
            conn.execute("PRAGMA writable_schema = OFF")

        report = run_doctor(
            config=replace(self.config, db_path=invalid_path),
            db=ReadOnlyDoctorDatabase(invalid_path),
            scheduler_backend=InstalledSchedulerBackend(),
        )

        schema = _check(report.to_mapping(), "schema_version")
        self.assertEqual(schema["severity"], DoctorSeverity.FAILURE)
        self.assertIn("does not match its required definition", str(schema["message"]))
        self.assertEqual(report.exit_code, 1)

    def test_schema_18_missing_required_explicit_index_is_failure(self) -> None:
        invalid_path = Path(self.tmpdir.name) / "schema-18-without-index.sqlite3"
        _create_database_at_schema(invalid_path, version=18)
        with sqlite3.connect(invalid_path) as conn:
            conn.execute("DROP INDEX idx_library_articles_saved_saved_at")

        report = run_doctor(
            config=replace(self.config, db_path=invalid_path),
            db=ReadOnlyDoctorDatabase(invalid_path),
            scheduler_backend=InstalledSchedulerBackend(),
        )

        schema = _check(report.to_mapping(), "schema_version")
        self.assertEqual(schema["severity"], DoctorSeverity.FAILURE)
        self.assertIn("missing required index", str(schema["message"]))
        self.assertEqual(report.exit_code, 1)

    def test_future_schema_is_failure_not_migration_warning(self) -> None:
        future_path = Path(self.tmpdir.name) / "future.sqlite3"
        with sqlite3.connect(future_path) as conn:
            conn.executescript(
                """
                CREATE TABLE schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO schema_metadata (key, value, updated_at)
                VALUES ('schema_version', '999', '2026-08-30T00:00:00Z');
                """
            )

        report = run_doctor(
            config=replace(self.config, db_path=future_path),
            db=ReadOnlyDoctorDatabase(future_path),
            scheduler_backend=InstalledSchedulerBackend(),
        )

        schema = _check(report.to_mapping(), "schema_version")
        self.assertEqual(schema["severity"], DoctorSeverity.FAILURE)
        self.assertIn("newer than supported", str(schema["message"]))
        self.assertNotIn("will migrate", str(schema["message"]))
        self.assertEqual(report.exit_code, 1)

    def test_corrupt_database_is_failure_not_migration_warning(self) -> None:
        corrupt_path = Path(self.tmpdir.name) / "corrupt.sqlite3"
        corrupt_path.write_bytes(b"not a SQLite database")

        report = run_doctor(
            config=replace(self.config, db_path=corrupt_path),
            db=ReadOnlyDoctorDatabase(corrupt_path),
            scheduler_backend=InstalledSchedulerBackend(),
        )

        payload = report.to_mapping()
        self.assertEqual(_check(payload, "sqlite")["severity"], DoctorSeverity.FAILURE)
        schema = _check(payload, "schema_version")
        self.assertEqual(schema["severity"], DoctorSeverity.FAILURE)
        self.assertNotIn("will migrate", str(schema["message"]))
        self.assertEqual(report.exit_code, 1)

    def test_cli_doctor_does_not_create_missing_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            config_dir = root / "config"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                mock.patch.dict(
                    "os.environ",
                    {
                        "RESEARCH_DIGEST_DATA_DIR": str(data_dir),
                        "RESEARCH_DIGEST_CONFIG_DIR": str(config_dir),
                    },
                    clear=False,
                ),
                mock.patch("shutil.which", return_value="/usr/bin/codex"),
            ):
                exit_code = run_cli(
                    argv=["doctor", "--json"],
                    stdout=stdout,
                    stderr=stderr,
                    scheduler_backend=InstalledSchedulerBackend(),
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertFalse(data_dir.exists())
            self.assertFalse(config_dir.exists())
            self.assertFalse((data_dir / "research_digest.sqlite3").exists())
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(_check(payload, "config_file")["severity"], DoctorSeverity.WARNING)

    def test_cli_doctor_rejects_config_that_requires_upgrade_without_mutating_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            config_dir = root / "config"
            config_dir.mkdir()
            config_path = config_dir / "config.json"
            config_path.write_text('{"config_version": 4}\n', encoding="utf-8")
            before = config_path.read_bytes()
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                mock.patch.dict(
                    "os.environ",
                    {
                        "RESEARCH_DIGEST_DATA_DIR": str(data_dir),
                        "RESEARCH_DIGEST_CONFIG_DIR": str(config_dir),
                    },
                    clear=False,
                ),
                mock.patch("shutil.which", return_value="/usr/bin/codex"),
            ):
                exit_code = run_cli(
                    argv=["doctor", "--json"],
                    stdout=stdout,
                    stderr=stderr,
                    scheduler_backend=InstalledSchedulerBackend(),
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(
                _check(payload, "config_file")["severity"],
                DoctorSeverity.FAILURE,
            )
            self.assertEqual(config_path.read_bytes(), before)

    def test_cli_rejects_invalid_network_timeout(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            argv=["doctor", "--network", "--network-timeout", "inf"],
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")


def _check(payload: dict[str, object], name: str) -> dict[str, object]:
    checks = payload["checks"]
    assert isinstance(checks, list)
    for check in checks:
        assert isinstance(check, dict)
        if check["name"] == name:
            return check
    raise AssertionError(f"missing check: {name}")


def _create_database_at_schema(path: Path, *, version: int) -> None:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        for migration in db_module.MIGRATIONS:
            if migration.version > version:
                break
            migration.apply(conn)
        conn.execute(
            """
            INSERT INTO schema_metadata (key, value, updated_at)
            VALUES ('schema_version', ?, '2026-08-30T00:00:00Z')
            """,
            (str(version),),
        )


def _index_rows(conn: sqlite3.Connection, table_name: str) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return list(conn.execute(f"PRAGMA index_list({table_name})"))


if __name__ == "__main__":
    unittest.main()
