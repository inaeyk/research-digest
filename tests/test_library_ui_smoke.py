from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from research_digest.db import Database
from research_digest.library import save_article
from research_digest.models import Article


def _article() -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id="2608.library-smoke",
        title="Library smoke paper",
        authors=["Ada Lovelace", "Grace Hopper"],
        abstract="Stored source abstract for the Library smoke paper.",
        categories=["hep-th", "gr-qc"],
        published_at=datetime(2026, 8, 14, 16, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 16, 10, tzinfo=UTC),
        abstract_url="https://arxiv.org/abs/2608.library-smoke",
        pdf_url="https://arxiv.org/pdf/2608.library-smoke",
    )


def _library_app(config_dir: str, data_dir: str) -> None:
    import os

    os.environ["RESEARCH_DIGEST_CONFIG_DIR"] = config_dir
    os.environ["RESEARCH_DIGEST_DATA_DIR"] = data_dir

    import streamlit as st

    st.cache_resource.clear()
    from research_digest.ui.pages.library import render

    render()


class LibraryUiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.config_dir = self.root / "config"
        self.data_dir = self.root / "data"
        self.data_dir.mkdir(parents=True)
        self.db = Database(self.data_dir / "research_digest.sqlite3")
        article, _ = self.db.upsert_article(_article())
        self.assertIsNotNone(article.id)
        save_article(self.db, article.id or 0)

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_library_page_renders_saved_article_and_abstract_toggle(self) -> None:
        at = AppTest.from_function(
            _library_app,
            default_timeout=5,
            args=(str(self.config_dir), str(self.data_dir)),
        ).run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Library smoke paper")
        self.assert_text_present(at, "Ada Lovelace, Grace Hopper")
        self.assert_text_present(at, "1 saved paper(s)")
        self.assert_text_absent(at, "Stored source abstract for the Library smoke paper.")

        self.click_button(at, "Show abstract").run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Stored source abstract for the Library smoke paper.")

    def assert_no_streamlit_exceptions(self, at: AppTest) -> None:
        self.assertEqual([str(value) for value in at.exception], [])

    def assert_text_present(self, at: AppTest, expected: str) -> None:
        self.assertTrue(any(expected in text for text in self._plain_texts(at)))

    def assert_text_absent(self, at: AppTest, expected: str) -> None:
        self.assertFalse(any(expected in text for text in self._plain_texts(at)))

    def click_button(self, at: AppTest, label: str) -> AppTest:
        matches = [button for button in at.button if str(button.label) == label]
        self.assertGreater(len(matches), 0)
        return matches[0].click()

    def _plain_texts(self, at: AppTest) -> list[str]:
        return (
            [str(element.value) for element in at.title]
            + [str(element.value) for element in at.header]
            + [str(element.value) for element in at.subheader]
            + [str(element.value) for element in at.markdown]
            + [str(element.value) for element in at.text]
            + [str(element.value) for element in at.caption]
        )


if __name__ == "__main__":
    unittest.main()
