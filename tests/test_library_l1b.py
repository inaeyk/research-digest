from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from unittest import mock

from research_digest.collections import (
    add_article_to_collection,
    create_collection,
    save_note,
)
from research_digest.conversations import (
    append_message,
    create_conversation,
    list_conversation_overviews,
)
from research_digest.db import CURRENT_SCHEMA_VERSION, Database
from research_digest.library import (
    list_library_items,
    save_article,
    set_interest_rating,
    set_reading_state,
)
from research_digest.models import AIConversationRole, Article, ReadingState
from research_digest.tags import add_user_tag
from research_digest.ui.library_view import (
    MAX_DENSE_COLLECTIONS,
    MAX_DENSE_TAGS,
    MAX_NOTE_PREVIEW_CHARS,
    build_dense_library_row,
    build_note_preview,
)

FIXED_NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def _article(
    source_id: str,
    title: str,
    *,
    published_at: datetime,
    authors: list[str] | None = None,
) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_id,
        title=title,
        authors=authors or ["Ada Researcher", "Ben Scientist"],
        abstract=f"Stored abstract for {title}.",
        categories=["hep-th"],
        published_at=published_at,
        updated_at=published_at + timedelta(minutes=1),
        abstract_url=f"https://arxiv.org/abs/{source_id}",
        pdf_url=f"https://arxiv.org/pdf/{source_id}",
    )


class DenseLibraryPresentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db = Database(Path(self.tempdir.name) / "dense.sqlite3")
        article, _ = self.db.upsert_article(
            _article(
                "2608.dense",
                "Dense Library paper",
                published_at=datetime(1993, 6, 1, tzinfo=UTC),
                authors=[f"Author {index}" for index in range(1, 10)],
            )
        )
        assert article.id is not None
        self.article_id = article.id
        save_article(self.db, self.article_id)

    def test_dense_row_contains_primary_state_and_bounded_relationships(self) -> None:
        set_interest_rating(self.db, article_id=self.article_id, interest_rating=4)
        set_reading_state(
            self.db,
            article_id=self.article_id,
            reading_state=ReadingState.READ,
        )
        note_text = "A deterministic note preview " + "connection " * 30
        save_note(self.db, article_id=self.article_id, note_text=note_text)
        for index in range(1, 5):
            collection = create_collection(self.db, name=f"Collection {index}")
            assert collection.id is not None
            add_article_to_collection(
                self.db,
                collection_id=collection.id,
                article_id=self.article_id,
            )
        for index in range(1, 6):
            add_user_tag(self.db, article_id=self.article_id, tag=f"Tag {index}")

        item = list_library_items(self.db)[0]
        row = build_dense_library_row(item)

        self.assertEqual(row.title, "Dense Library paper")
        self.assertIn("Author 1", row.authors_and_year)
        self.assertIn("+4 more", row.authors_and_year)
        self.assertTrue(row.authors_and_year.endswith("· 1993"))
        self.assertEqual(row.interest, "★★★★☆ (4/5)")
        self.assertEqual(row.reading, "Read")
        self.assertEqual(row.collections.count("Collection"), MAX_DENSE_COLLECTIONS)
        self.assertIn("+2 more", row.collections)
        self.assertEqual(row.tags.count("Tag"), MAX_DENSE_TAGS)
        self.assertIn("+2 more", row.tags)
        assert row.note_preview is not None
        self.assertLessEqual(len(row.note_preview), MAX_NOTE_PREVIEW_CHARS)
        self.assertTrue(row.note_preview.endswith("…"))

    def test_null_states_are_explicit_and_empty_note_preview_is_omitted(self) -> None:
        row = build_dense_library_row(list_library_items(self.db)[0])

        self.assertEqual(row.interest, "Unrated")
        self.assertEqual(row.reading, "Not set")
        self.assertIsNone(row.note_preview)
        self.assertIsNone(build_note_preview(" \n\t "))

    def test_l1b_adds_no_persisted_preview_field_after_l1c_migration(self) -> None:
        self.assertEqual(CURRENT_SCHEMA_VERSION, 20)
        self.assertEqual(self.db.get_schema_version(), 20)
        with sqlite3.connect(self.db.path) as conn:
            library_columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(library_articles)")
            }
            note_columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(library_article_notes)")
            }
        self.assertNotIn("note_preview", library_columns)
        self.assertNotIn("note_preview", note_columns)


class LibraryFilterSortTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db = Database(Path(self.tempdir.name) / "filters.sqlite3")
        specs = (
            ("paper-a", "Alpha gravity", datetime(2020, 1, 1, tzinfo=UTC)),
            ("paper-b", "Beta brane", datetime(2024, 1, 1, tzinfo=UTC)),
            ("paper-c", "Gamma strings", datetime(1993, 1, 1, tzinfo=UTC)),
            ("paper-d", "Delta horizons", datetime(2026, 1, 1, tzinfo=UTC)),
        )
        self.article_ids: dict[str, int] = {}
        for index, (source_id, title, published_at) in enumerate(specs):
            article, _ = self.db.upsert_article(
                _article(source_id, title, published_at=published_at)
            )
            assert article.id is not None
            self.article_ids[source_id] = article.id
            with mock.patch(
                "research_digest.db.utc_now",
                return_value=FIXED_NOW + timedelta(minutes=index),
            ):
                save_article(self.db, article.id)
        set_interest_rating(
            self.db,
            article_id=self.article_ids["paper-a"],
            interest_rating=1,
        )
        set_interest_rating(
            self.db,
            article_id=self.article_ids["paper-b"],
            interest_rating=5,
        )
        set_interest_rating(
            self.db,
            article_id=self.article_ids["paper-c"],
            interest_rating=4,
        )
        set_reading_state(
            self.db,
            article_id=self.article_ids["paper-b"],
            reading_state=ReadingState.UNREAD,
        )
        collection = create_collection(self.db, name="Core project")
        assert collection.id is not None
        self.collection_id = collection.id
        add_article_to_collection(
            self.db,
            collection_id=collection.id,
            article_id=self.article_ids["paper-c"],
        )
        add_user_tag(
            self.db,
            article_id=self.article_ids["paper-c"],
            tag="instability",
        )
        save_note(
            self.db,
            article_id=self.article_ids["paper-d"],
            note_text="Unique note needle.",
        )

    def test_interest_reading_collection_and_tag_filters(self) -> None:
        self.assertEqual(
            [item.article.source_article_id for item in list_library_items(
                self.db,
                interest_filter="at_least_4",
                sort_by="interest_desc",
            )],
            ["paper-b", "paper-c"],
        )
        self.assertEqual(
            [item.article.source_article_id for item in list_library_items(
                self.db,
                reading_filter="unread",
            )],
            ["paper-b"],
        )
        self.assertEqual(
            [item.article.source_article_id for item in list_library_items(
                self.db,
                collection_id=self.collection_id,
            )],
            ["paper-c"],
        )
        self.assertEqual(
            [item.article.source_article_id for item in list_library_items(
                self.db,
                normalized_tag_name="instability",
            )],
            ["paper-c"],
        )

    def test_search_reads_normalized_article_note_tag_and_collection_content(self) -> None:
        cases = {
            "Alpha gravity": "paper-a",
            "Ada Researcher": "paper-a",
            "Unique note needle": "paper-d",
            "instability": "paper-c",
            "Core project": "paper-c",
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                matches = list_library_items(self.db, query=query)
                self.assertIn(expected, [item.article.source_article_id for item in matches])

    def test_recent_interest_publication_and_title_sorts_are_stable(self) -> None:
        self.assertEqual(
            [item.article.source_article_id for item in list_library_items(
                self.db,
                sort_by="saved_newest",
            )],
            ["paper-d", "paper-c", "paper-b", "paper-a"],
        )
        self.assertEqual(
            [item.article.source_article_id for item in list_library_items(
                self.db,
                sort_by="interest_desc",
            )],
            ["paper-b", "paper-c", "paper-a", "paper-d"],
        )
        self.assertEqual(
            [item.article.source_article_id for item in list_library_items(
                self.db,
                sort_by="published_newest",
            )],
            ["paper-d", "paper-b", "paper-a", "paper-c"],
        )
        self.assertEqual(
            [item.article.source_article_id for item in list_library_items(
                self.db,
                sort_by="published_oldest",
            )],
            ["paper-c", "paper-a", "paper-b", "paper-d"],
        )
        self.assertEqual(
            [item.article.title for item in list_library_items(self.db, sort_by="title")],
            ["Alpha gravity", "Beta brane", "Delta horizons", "Gamma strings"],
        )


class LibraryQueryScalingTests(unittest.TestCase):
    def test_100_and_1000_paper_navigation_query_counts_are_constant(self) -> None:
        measurements: dict[int, tuple[int, int]] = {}
        for count in (100, 1000):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as tempdir:
                db = Database(Path(tempdir) / f"library-{count}.sqlite3")
                _bulk_insert_library_fixture(db, count=count)
                list_queries = _count_read_queries(
                    db,
                    partial(list_library_items, db),
                )
                search_queries = _count_read_queries(
                    db,
                    partial(list_library_items, db, query=f"Paper {count}"),
                )
                measurements[count] = (list_queries, search_queries)
        self.assertEqual(measurements[100], measurements[1000])
        self.assertEqual(measurements[100], (5, 6))

    def test_conversation_overviews_count_messages_in_one_result(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "conversations.sqlite3")
            article, _ = db.upsert_article(
                _article(
                    "conversation",
                    "Conversation paper",
                    published_at=FIXED_NOW,
                )
            )
            assert article.id is not None
            save_article(db, article.id)
            first = create_conversation(
                db,
                article_id=article.id,
                title="First discussion",
                provider="fixture",
                model_id="fixture",
            )
            second = create_conversation(
                db,
                article_id=article.id,
                title="Second discussion",
                provider="fixture",
                model_id="fixture",
            )
            assert first.id is not None and second.id is not None
            for content in ("one", "two", "three"):
                append_message(
                    db,
                    conversation_id=first.id,
                    role=AIConversationRole.USER,
                    content=content,
                )

            by_title = {
                overview.conversation.title: overview.message_count
                for overview in list_conversation_overviews(db, article_id=article.id)
            }
            self.assertEqual(by_title, {"First discussion": 3, "Second discussion": 0})


def _bulk_insert_library_fixture(db: Database, *, count: int) -> None:
    articles: list[tuple[object, ...]] = []
    entries: list[tuple[object, ...]] = []
    notes: list[tuple[object, ...]] = []
    assignments: list[tuple[object, ...]] = []
    memberships: list[tuple[object, ...]] = []
    for article_id in range(1, count + 1):
        timestamp = (FIXED_NOW + timedelta(minutes=article_id)).isoformat()
        articles.append(
            (
                article_id,
                "arxiv",
                f"fixture.{article_id}",
                f"Paper {article_id}",
                json.dumps([f"Author {article_id}"]),
                f"Abstract {article_id}",
                json.dumps(["hep-th"]),
                timestamp,
                timestamp,
                f"https://arxiv.org/abs/fixture.{article_id}",
                None,
                timestamp,
            )
        )
        entries.append((article_id, 1, timestamp, timestamp, None, None))
        notes.append((article_id, f"Note {article_id}", timestamp, timestamp))
        assignments.append((article_id, 1, "USER", None, timestamp, timestamp))
        memberships.append((1, article_id, timestamp))
    with sqlite3.connect(db.path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            INSERT INTO library_tags (
                id, normalized_name, display_name, created_at, updated_at
            ) VALUES (1, 'fixture-tag', 'Fixture tag', ?, ?)
            """,
            (FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
        )
        conn.execute(
            """
            INSERT INTO library_collections (
                id, name, normalized_name, description, created_at, updated_at
            ) VALUES (1, 'Fixture collection', 'fixture collection', '', ?, ?)
            """,
            (FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
        )
        conn.executemany(
            """
            INSERT INTO articles (
                id, source, source_article_id, title, authors_json, abstract,
                categories_json, published_at, updated_at, abstract_url, pdf_url, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            articles,
        )
        conn.executemany(
            """
            INSERT INTO library_articles (
                article_id, saved, saved_at, updated_at, reading_state, interest_rating
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            entries,
        )
        conn.executemany(
            """
            INSERT INTO library_article_notes (
                article_id, note_text, created_at, updated_at
            ) VALUES (?, ?, ?, ?)
            """,
            notes,
        )
        conn.executemany(
            """
            INSERT INTO library_tag_assignments (
                article_id, tag_id, origin, ai_provenance_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            assignments,
        )
        conn.executemany(
            """
            INSERT INTO library_collection_memberships (
                collection_id, article_id, added_at
            ) VALUES (?, ?, ?)
            """,
            memberships,
        )


def _count_read_queries(db: Database, operation: Callable[[], object]) -> int:
    statements: list[str] = []
    original_connection = db._connection

    @contextmanager
    def traced_connection() -> Iterator[sqlite3.Connection]:
        with original_connection() as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    with mock.patch.object(db, "_connection", new=traced_connection):
        operation()
    return sum(
        statement.lstrip().upper().startswith(("SELECT", "WITH"))
        for statement in statements
    )


if __name__ == "__main__":
    unittest.main()
