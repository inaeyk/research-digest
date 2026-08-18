from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from research_digest.analysis.codex_cli import CodexAbstractPreselector, CodexCLIAnalyzer
from research_digest.analysis.providers import (
    build_configured_analyzer,
    build_configured_preselector,
)
from research_digest.config import AppConfig
from research_digest.preselection import UnavailableFailOpenPreselector


class AnalyzerProviderTests(unittest.TestCase):
    def test_codex_provider_does_not_require_openai_api_key(self) -> None:
        config = AppConfig(
            db_path=Path("test.sqlite3"),
            data_dir=Path("."),
            config_dir=Path("."),
            analyzer_provider="codex",
            openai_api_key=None,
            openai_model="unused",
            codex_model="gpt-test",
            codex_timeout_seconds=12,
        )

        with mock.patch("shutil.which", return_value="/usr/bin/codex"):
            connection = build_configured_analyzer(config)

        self.assertIsNone(connection.message)
        self.assertIsInstance(connection.analyzer, CodexCLIAnalyzer)

    def test_openai_provider_without_api_key_is_unavailable_data(self) -> None:
        config = AppConfig(
            db_path=Path("test.sqlite3"),
            data_dir=Path("."),
            config_dir=Path("."),
            analyzer_provider="openai",
            openai_api_key=None,
            openai_model="gpt-test",
            codex_model=None,
            codex_timeout_seconds=12,
        )

        connection = build_configured_analyzer(config)

        self.assertIsNone(connection.analyzer)
        self.assertEqual(connection.message, "OPENAI_API_KEY is not set.")

    def test_codex_provider_builds_model_based_preselector(self) -> None:
        config = AppConfig(
            db_path=Path("test.sqlite3"),
            data_dir=Path("."),
            config_dir=Path("."),
            analyzer_provider="codex",
            openai_api_key=None,
            openai_model="unused",
            codex_model="gpt-test",
            codex_timeout_seconds=12,
            preselection_fraction=0.70,
        )

        with mock.patch("shutil.which", return_value="/usr/bin/codex"):
            connection = build_configured_preselector(config)

        self.assertIsNone(connection.message)
        self.assertIsInstance(connection.preselector, CodexAbstractPreselector)
        self.assertEqual(connection.preselector.preselection_fraction, 0.70)

    def test_unavailable_preselector_fails_open_explicitly(self) -> None:
        config = AppConfig(
            db_path=Path("test.sqlite3"),
            data_dir=Path("."),
            config_dir=Path("."),
            analyzer_provider="openai",
            openai_api_key=None,
            openai_model="gpt-test",
            codex_model=None,
            codex_timeout_seconds=12,
            preselection_fraction=0.70,
        )

        connection = build_configured_preselector(config)

        self.assertEqual(connection.message, "OPENAI_API_KEY is not set.")
        self.assertIsInstance(connection.preselector, UnavailableFailOpenPreselector)


if __name__ == "__main__":
    unittest.main()
