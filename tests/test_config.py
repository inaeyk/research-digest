from __future__ import annotations

import os
import unittest
from unittest import mock

from research_digest.analysis.base import AnalyzerUnavailable
from research_digest.analysis.openai import OpenAIAnalyzer
from research_digest.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def test_default_analyzer_provider_is_codex(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            config = load_config()

        self.assertEqual(config.analyzer_provider, "codex")
        self.assertIsNone(config.openai_api_key)

    def test_openai_provider_selection_preserves_api_key_config(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
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
        with mock.patch.dict(
            os.environ,
            {"RESEARCH_DIGEST_ANALYZER": "other"},
            clear=True,
        ), self.assertRaises(ConfigError):
            load_config()

    def test_openai_analyzer_still_requires_openai_api_key(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"RESEARCH_DIGEST_ANALYZER": "openai"},
            clear=True,
        ), self.assertRaisesRegex(AnalyzerUnavailable, "OPENAI_API_KEY"):
            OpenAIAnalyzer()


if __name__ == "__main__":
    unittest.main()
