from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from research_digest.analysis.base import AnalyzerUnavailable
from research_digest.analysis.openai import OpenAIAnalyzer
from research_digest.config import (
    CONFIG_VERSION,
    DEFAULT_CONFIG_FILENAME,
    DEFAULT_DB_FILENAME,
    ConfigError,
    load_config,
)


class ConfigTests(unittest.TestCase):
    def test_default_analyzer_provider_is_codex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {
                "RESEARCH_DIGEST_DATA_DIR": str(Path(tmp) / "data"),
                "RESEARCH_DIGEST_CONFIG_DIR": str(Path(tmp) / "config"),
                "RESEARCH_DIGEST_LEGACY_DB": str(Path(tmp) / "missing.sqlite3"),
            },
            clear=True,
        ):
            config = load_config()
            config_file_exists = (Path(tmp) / "config" / DEFAULT_CONFIG_FILENAME).exists()

        self.assertEqual(config.analyzer_provider, "codex")
        self.assertIsNone(config.openai_api_key)
        self.assertEqual(config.db_path.name, DEFAULT_DB_FILENAME)
        self.assertEqual(config.data_dir.name, "data")
        self.assertEqual(config.config_dir.name, "config")
        self.assertEqual(config.config_version, CONFIG_VERSION)
        self.assertEqual(config.config_path, Path(tmp) / "config" / DEFAULT_CONFIG_FILENAME)
        self.assertTrue(config_file_exists)

    def test_openai_provider_selection_preserves_api_key_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            _isolated_env(tmp)
            | {
                "RESEARCH_DIGEST_ANALYZER": "openai",
                "OPENAI_API_KEY": "test-key",
                "OPENAI_MODEL": "test-model",
            },
            clear=True,
        ):
            config = load_config()

        self.assertEqual(config.analyzer_provider, "openai")
        self.assertEqual(config.openai_api_key, "test-key")
        self.assertEqual(config.openai_model, "test-model")

    def test_current_versioned_config_loads_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config" / DEFAULT_CONFIG_FILENAME
            _write_config_json(
                config_path,
                {
                    "config_version": CONFIG_VERSION,
                    "analyzer_provider": "openai",
                    "openai_model": "stored-openai-model",
                    "codex_model": "stored-codex-model",
                    "codex_timeout_seconds": 33,
                },
            )
            with mock.patch.dict(os.environ, _isolated_env(tmp), clear=True):
                config = load_config()

        self.assertEqual(config.analyzer_provider, "openai")
        self.assertEqual(config.openai_model, "stored-openai-model")
        self.assertEqual(config.codex_model, "stored-codex-model")
        self.assertEqual(config.codex_timeout_seconds, 33)
        self.assertIsNone(config.last_config_backup_path)

    def test_old_supported_config_upgrades_with_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config" / DEFAULT_CONFIG_FILENAME
            _write_config_json(
                config_path,
                {
                    "analyzer_provider": "openai",
                    "openai_model": "legacy-model",
                    "codex_timeout_seconds": 44,
                },
            )
            with mock.patch.dict(os.environ, _isolated_env(tmp), clear=True):
                config = load_config()

            self.assertEqual(config.config_version, CONFIG_VERSION)
            self.assertIsNotNone(config.last_config_backup_path)
            assert config.last_config_backup_path is not None
            self.assertTrue(config.last_config_backup_path.exists())
            self.assertEqual(
                _read_json(config.last_config_backup_path)["openai_model"],
                "legacy-model",
            )
            upgraded = _read_json(config_path)

        self.assertEqual(upgraded["config_version"], CONFIG_VERSION)
        self.assertEqual(upgraded["analyzer_provider"], "openai")
        self.assertEqual(upgraded["openai_model"], "legacy-model")
        self.assertNotIn("OPENAI_API_KEY", json.dumps(upgraded))

    def test_unknown_future_config_version_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config" / DEFAULT_CONFIG_FILENAME
            _write_config_json(config_path, {"config_version": CONFIG_VERSION + 1})
            with (
                mock.patch.dict(os.environ, _isolated_env(tmp), clear=True),
                self.assertRaisesRegex(ConfigError, "newer than supported"),
            ):
                load_config()

    def test_invalid_semantic_config_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config" / DEFAULT_CONFIG_FILENAME
            _write_config_json(
                config_path,
                {
                    "config_version": CONFIG_VERSION,
                    "analyzer_provider": "other",
                    "openai_model": "stored-openai-model",
                    "codex_model": None,
                    "codex_timeout_seconds": 33,
                },
            )
            with (
                mock.patch.dict(os.environ, _isolated_env(tmp), clear=True),
                self.assertRaisesRegex(ConfigError, "analyzer_provider"),
            ):
                load_config()

    def test_persisted_config_rejects_secret_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config" / DEFAULT_CONFIG_FILENAME
            _write_config_json(
                config_path,
                {
                    "config_version": CONFIG_VERSION,
                    "analyzer_provider": "codex",
                    "openai_model": "stored-openai-model",
                    "codex_model": None,
                    "codex_timeout_seconds": 33,
                    "OPENAI_API_KEY": "sk-not-allowed",
                },
            )
            with (
                mock.patch.dict(os.environ, _isolated_env(tmp), clear=True),
                self.assertRaisesRegex(ConfigError, "must not contain secrets"),
            ):
                load_config()

    def test_environment_overrides_do_not_mutate_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config" / DEFAULT_CONFIG_FILENAME
            _write_config_json(
                config_path,
                {
                    "config_version": CONFIG_VERSION,
                    "analyzer_provider": "codex",
                    "openai_model": "stored-openai-model",
                    "codex_model": "stored-codex-model",
                    "codex_timeout_seconds": 33,
                },
            )
            with mock.patch.dict(
                os.environ,
                _isolated_env(tmp)
                | {
                    "RESEARCH_DIGEST_ANALYZER": "openai",
                    "OPENAI_MODEL": "env-openai-model",
                    "RESEARCH_DIGEST_CODEX_MODEL": "env-codex-model",
                    "RESEARCH_DIGEST_CODEX_TIMEOUT_SECONDS": "66",
                    "OPENAI_API_KEY": "sk-not-persisted",
                },
                clear=True,
            ):
                config = load_config()

            stored = _read_json(config_path)

        self.assertEqual(config.analyzer_provider, "openai")
        self.assertEqual(config.openai_model, "env-openai-model")
        self.assertEqual(config.codex_model, "env-codex-model")
        self.assertEqual(config.codex_timeout_seconds, 66)
        self.assertEqual(stored["analyzer_provider"], "codex")
        self.assertEqual(stored["openai_model"], "stored-openai-model")
        self.assertEqual(stored["codex_model"], "stored-codex-model")
        self.assertEqual(stored["codex_timeout_seconds"], 33)
        self.assertNotIn("sk-not-persisted", json.dumps(stored))

    def test_empty_openai_model_override_fails_clearly(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(
                os.environ,
                _isolated_env(tmp) | {"OPENAI_MODEL": ""},
                clear=True,
            ),
            self.assertRaisesRegex(ConfigError, "OPENAI_MODEL"),
        ):
            load_config()

    def test_blank_codex_model_override_fails_clearly(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(
                os.environ,
                _isolated_env(tmp) | {"RESEARCH_DIGEST_CODEX_MODEL": "   "},
                clear=True,
            ),
            self.assertRaisesRegex(ConfigError, "RESEARCH_DIGEST_CODEX_MODEL"),
        ):
            load_config()

    def test_invalid_analyzer_provider_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            _isolated_env(tmp) | {"RESEARCH_DIGEST_ANALYZER": "other"},
            clear=True,
        ), self.assertRaises(ConfigError):
            load_config()

    def test_openai_analyzer_still_requires_openai_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            _isolated_env(tmp) | {"RESEARCH_DIGEST_ANALYZER": "openai"},
            clear=True,
        ), self.assertRaisesRegex(AnalyzerUnavailable, "OPENAI_API_KEY"):
            OpenAIAnalyzer()

    def test_explicit_db_path_is_respected_and_disables_adoption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "legacy.sqlite3"
            explicit = Path(tmp) / "explicit.sqlite3"
            _create_sqlite_db(legacy)
            with mock.patch.dict(
                os.environ,
                _isolated_env(tmp)
                | {
                    "RESEARCH_DIGEST_DB": str(explicit),
                    "RESEARCH_DIGEST_LEGACY_DB": str(legacy),
                },
                clear=True,
            ):
                config = load_config()

        self.assertEqual(config.db_path, explicit.resolve())
        self.assertFalse(explicit.exists())

    def test_legacy_db_is_adopted_when_user_data_db_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "legacy.sqlite3"
            _create_sqlite_db(legacy)
            data_dir = Path(tmp) / "data"
            with mock.patch.dict(
                os.environ,
                _isolated_env(tmp)
                | {
                    "RESEARCH_DIGEST_DATA_DIR": str(data_dir),
                    "RESEARCH_DIGEST_LEGACY_DB": str(legacy),
                },
                clear=True,
            ):
                config = load_config()

            adopted = data_dir / DEFAULT_DB_FILENAME
            self.assertEqual(config.db_path, adopted.resolve())
            self.assertTrue(adopted.exists())
            self.assertTrue(legacy.exists())
            self.assertEqual(_sqlite_user_version(adopted), 7)

    def test_existing_user_data_db_is_not_overwritten_by_legacy_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "legacy.sqlite3"
            data_dir = Path(tmp) / "data"
            existing = data_dir / DEFAULT_DB_FILENAME
            _create_sqlite_db(legacy, user_version=7)
            _create_sqlite_db(existing, user_version=3)
            with mock.patch.dict(
                os.environ,
                _isolated_env(tmp)
                | {
                    "RESEARCH_DIGEST_DATA_DIR": str(data_dir),
                    "RESEARCH_DIGEST_LEGACY_DB": str(legacy),
                },
                clear=True,
            ):
                config = load_config()

            self.assertEqual(config.db_path, existing.resolve())
            self.assertEqual(_sqlite_user_version(existing), 3)

    def test_partial_adoption_target_is_repaired_from_valid_legacy_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "legacy.sqlite3"
            data_dir = Path(tmp) / "data"
            target = data_dir / DEFAULT_DB_FILENAME
            _create_sqlite_db(legacy, user_version=7)
            target.parent.mkdir(parents=True)
            target.write_bytes(b"partial")
            with mock.patch.dict(
                os.environ,
                _isolated_env(tmp)
                | {
                    "RESEARCH_DIGEST_DATA_DIR": str(data_dir),
                    "RESEARCH_DIGEST_LEGACY_DB": str(legacy),
                },
                clear=True,
            ):
                config = load_config()

            self.assertEqual(config.db_path, target.resolve())
            self.assertEqual(_sqlite_user_version(target), 7)

    def test_invalid_active_db_fails_closed_when_no_valid_legacy_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            target = data_dir / DEFAULT_DB_FILENAME
            target.parent.mkdir(parents=True)
            target.write_bytes(b"partial")
            with mock.patch.dict(
                os.environ,
                _isolated_env(tmp)
                | {
                    "RESEARCH_DIGEST_DATA_DIR": str(data_dir),
                    "RESEARCH_DIGEST_LEGACY_DB": str(Path(tmp) / "missing.sqlite3"),
                },
                clear=True,
            ), self.assertRaisesRegex(ConfigError, "valid SQLite"):
                load_config()


def _isolated_env(tmp: str) -> dict[str, str]:
    root = Path(tmp)
    return {
        "RESEARCH_DIGEST_DATA_DIR": str(root / "data"),
        "RESEARCH_DIGEST_CONFIG_DIR": str(root / "config"),
        "RESEARCH_DIGEST_LEGACY_DB": str(root / "missing.sqlite3"),
    }


def _create_sqlite_db(path: Path, *, user_version: int = 7) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(f"PRAGMA user_version = {user_version}")
        conn.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY)")


def _sqlite_user_version(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def _write_config_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


if __name__ == "__main__":
    unittest.main()
