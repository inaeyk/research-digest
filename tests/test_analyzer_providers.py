from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from research_digest.analysis.codex_cli import CodexCLIAnalyzer
from research_digest.analysis.providers import build_configured_analyzer
from research_digest.config import AppConfig


class AnalyzerProviderTests(unittest.TestCase):
    def test_codex_provider_does_not_require_openai_api_key(self) -> None:
        config = AppConfig(
            db_path=Path("test.sqlite3"),
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
            analyzer_provider="openai",
            openai_api_key=None,
            openai_model="gpt-test",
            codex_model=None,
            codex_timeout_seconds=12,
        )

        connection = build_configured_analyzer(config)

        self.assertIsNone(connection.analyzer)
        self.assertEqual(connection.message, "OPENAI_API_KEY is not set.")


if __name__ == "__main__":
    unittest.main()
