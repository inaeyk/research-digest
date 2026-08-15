from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from research_digest.analysis.base import AnalyzerUnavailable
from research_digest.analysis.openai import OpenAIAnalyzer
from research_digest.config import DEFAULT_DB_FILENAME, ConfigError, load_config


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

        self.assertEqual(config.analyzer_provider, "codex")
        self.assertIsNone(config.openai_api_key)
        self.assertEqual(config.db_path.name, DEFAULT_DB_FILENAME)
        self.assertEqual(config.data_dir.name, "data")
        self.assertEqual(config.config_dir.name, "config")

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


if __name__ == "__main__":
    unittest.main()
