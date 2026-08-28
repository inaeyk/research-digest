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
from research_digest.collections import (
    add_article_to_collection,
    create_collection,
    save_note,
)
from research_digest.db import APP_RUN_COMPLETED, Database
from research_digest.library_context import build_collection_intelligence_snapshot
from research_digest.models import (
    Article,
    ArxivSourceConfig,
    RunOrigin,
    profile_semantic_fingerprint,
)
from research_digest.preselection import AbstractPreselectionDecision
from research_digest.suggested_interests import refresh_suggested_interests
from research_digest.tags import add_user_tag, assign_ai_tags, remove_ai_tag


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

        self.assertEqual(result.db_path, self.db_path.resolve())
        self.assertEqual(result.backup_path.parent, output_dir.resolve())
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
        related, _ = self.db.upsert_article(
            Article(
                id=None,
                source="arxiv",
                source_article_id="2608.70002",
                title="Related backup export title",
                authors=["Ada Lovelace"],
                abstract="Related abstract.",
                categories=["hep-th"],
                published_at=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
                updated_at=datetime(2026, 8, 14, 12, 30, tzinfo=UTC),
                abstract_url="http://arxiv.org/abs/2608.70002",
                pdf_url=None,
            )
        )
        assert related.id is not None
        self.db.save_library_article(article.id)
        self.db.save_library_article(related.id)
        add_user_tag(self.db, article_id=article.id, tag="Black branes")
        assign_ai_tags(
            self.db,
            article_id=article.id,
            tags=["KK spectra"],
            provenance={"prompt_version": "library_ai_tags_v1", "provider": "fake"},
        )
        remove_ai_tag(self.db, article_id=article.id, tag="KK spectra")
        save_note(self.db, article_id=article.id, note_text="Private local note.")
        collection = create_collection(
            self.db,
            name="GL project",
            description="Collection description.",
        )
        assert collection.id is not None
        add_article_to_collection(
            self.db,
            collection_id=collection.id,
            article_id=article.id,
        )
        self.db.upsert_article_feedback(
            article_id=article.id,
            profile_id=profile.id,
            profile_fingerprint=profile_semantic_fingerprint(profile),
            profile_match="NO",
            personal_interest="YES",
        )
        suggestion = refresh_suggested_interests(self.db, profile=profile, min_evidence=1)[0]
        assert suggestion.id is not None
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
        self.db.save_preselection_decisions(
            run_id=run_id,
            profile_id=profile.id,
            profile_fingerprint=profile_semantic_fingerprint(profile),
            source_name="arxiv",
            source_fingerprint="source-a",
            article_by_key={f"{article.source}:{article.source_article_id}": article},
            decisions=(
                AbstractPreselectionDecision(
                    article_id=f"{article.source}:{article.source_article_id}",
                    selected=True,
                    stage="model_abstract",
                    matched_terms=(),
                    reason="fake model score",
                    preselection_score=0.51,
                    preselection_threshold=0.49,
                    preselector_version="fake_model_abstract_v1",
                ),
            ),
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
        self.db.upsert_library_connection(
            article_id_a=article.id,
            article_id_b=related.id,
            relation_label="shared system",
            rationale="Both are backup export fixtures.",
            provenance={"prompt_version": "library_connections_v1", "provider": "fake"},
            confidence=0.5,
        )
        self.db.upsert_library_context_suggestion(
            run_id=run_id,
            article_id=article.id,
            related_article_id=related.id,
            collection_id=collection.id,
            relation_label="project context",
            rationale="Related through the GL project.",
            provenance={"prompt_version": "library_context_v1", "provider": "fake"},
            confidence=0.6,
        )
        build_collection_intelligence_snapshot(self.db, collection_id=collection.id)

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
        self.assertEqual(payload["feedback"][0]["feedback_label"], "NOT_RELEVANT")
        self.assertEqual(payload["feedback"][0]["profile_match"], "NO")
        self.assertEqual(payload["feedback"][0]["personal_interest"], "YES")
        self.assertEqual(payload["runs"][0]["status"], APP_RUN_COMPLETED)
        self.assertEqual(payload["runs"][0]["progress_stage"], APP_RUN_COMPLETED.lower())
        self.assertIsNone(payload["runs"][0]["progress_message"])
        self.assertEqual(payload["run_snapshots"][0]["snapshot"]["profile_name"], "Gravity")
        self.assertEqual(payload["source_date_coverage"][0]["source_date"], "2026-08-14")
        self.assertEqual(
            payload["preselection_decisions"][0]["preselector_version"],
            "fake_model_abstract_v1",
        )
        self.assertEqual(payload["preselection_decisions"][0]["preselection_score"], 0.51)
        self.assertEqual(
            payload["suggested_interest_profiles"][0]["suggested_name"],
            suggestion.suggested_name,
        )
        self.assertEqual(payload["library_articles"][0]["article"]["title"], "Backup export title")
        self.assertTrue(payload["library_articles"][0]["saved"])
        self.assertEqual(payload["library_tags"][0]["display_name"], "Black branes")
        self.assertEqual(payload["library_tag_assignments"][0]["origin"], "USER")
        self.assertEqual(
            payload["library_ai_tag_suppressions"][0]["tag"]["display_name"],
            "KK spectra",
        )
        self.assertEqual(payload["library_article_notes"][0]["note_text"], "Private local note.")
        self.assertEqual(payload["library_collections"][0]["name"], "GL project")
        self.assertEqual(
            payload["library_collection_memberships"][0]["collection"]["name"],
            "GL project",
        )
        self.assertEqual(
            payload["library_article_connections"][0]["relation_label"],
            "shared system",
        )
        self.assertEqual(
            payload["library_context_suggestions"][0]["relation_label"],
            "project context",
        )
        self.assertEqual(
            payload["collection_intelligence_snapshots"][0]["collection"]["name"],
            "GL project",
        )
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
