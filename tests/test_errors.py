from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from research_digest.db import Database
from research_digest.errors import sanitize_error_text


class ErrorSanitizationTests(unittest.TestCase):
    def test_sanitize_error_text_redacts_secrets_paths_and_long_payloads(self) -> None:
        home_path = "/home/" + "inaeyk/.codex/auth" + ".json"
        api_key = "sk-" + "testsecret123456789"
        bearer = "abc" + ".def.ghi"
        raw = (
            f"Request failed for {home_path} "
            f"OPENAI_API_KEY={api_key} "
            f"Authorization: Bearer {bearer} "
            + ("payload " * 120)
        )

        sanitized = sanitize_error_text(raw, max_length=180)

        self.assertNotIn("sk-" + "testsecret", sanitized)
        self.assertNotIn(bearer, sanitized)
        self.assertNotIn("/home/" + "inaeyk", sanitized)
        self.assertIn("[REDACTED_API_KEY]", sanitized)
        self.assertIn("Bearer [REDACTED]", sanitized)
        self.assertIn("[HOME]", sanitized)
        self.assertIn("[truncated]", sanitized)

    def test_existing_app_run_errors_are_sanitized_on_database_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite3"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE source_configs (
                    source_name TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    categories_json TEXT NOT NULL,
                    lookback_hours INTEGER NOT NULL,
                    max_results INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
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
                    analyzed_count INTEGER NOT NULL DEFAULT 0,
                    relevant_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT
                );
                INSERT INTO app_runs (
                    source_name, started_at, status, error_message
                )
                VALUES (
                    'arxiv',
                    '2026-08-14T00:00:00Z',
                    'failed',
                    'failed at /home/' || 'inaeyk/private with Bearer ' || 'token.secret.value'
                );
                """
            )
            conn.commit()
            conn.close()

            Database(db_path)
            conn = sqlite3.connect(db_path)
            error_message = conn.execute(
                "SELECT error_message FROM app_runs WHERE id = 1"
            ).fetchone()[0]
            conn.close()

        self.assertNotIn("/home/" + "inaeyk", error_message)
        self.assertNotIn("token.secret.value", error_message)
        self.assertIn("[HOME]", error_message)
        self.assertIn("Bearer [REDACTED]", error_message)


if __name__ == "__main__":
    unittest.main()
