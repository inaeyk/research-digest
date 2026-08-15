from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from research_digest.analysis.fake import FakeAnalyzer
from research_digest.cli import run_cli
from research_digest.config import AppConfig
from research_digest.db import Database
from research_digest.models import Article, ArxivSourceConfig


class StaticSource:
    def __init__(self, articles: list[Article]) -> None:
        self.articles = articles

    def fetch(self, config: ArxivSourceConfig, *, now: datetime | None = None) -> list[Article]:
        if not config.enabled:
            return []
        return list(self.articles[: config.max_results])


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
            analyzer_provider="codex",
            openai_api_key=None,
            openai_model="unused",
            codex_model=None,
            codex_timeout_seconds=1,
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
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["profile_count"], 1)
        self.assertEqual(payload["retrieved_count"], 1)
        self.assertEqual(payload["analyzed_count"], 1)
        output = stdout.getvalue()
        self.assertNotIn("Private description", output)
        self.assertNotIn("Private title", output)
        self.assertNotIn("Private abstract", output)

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
        self.assertNotIn("/home/" + "inaeyk", output)
        self.assertNotIn("sk-secret", output)
        self.assertIn("[HOME]", output)
        self.assertEqual(stderr.getvalue(), "")

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
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("interest profile", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
