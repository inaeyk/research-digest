from __future__ import annotations

import tempfile
import unittest
from typing import Any

from streamlit.testing.v1 import AppTest


def _settings_app(root: str) -> None:
    import os
    from pathlib import Path

    root_path = Path(root)
    os.environ["RESEARCH_DIGEST_CONFIG_DIR"] = str(root_path / "config")
    os.environ["RESEARCH_DIGEST_DATA_DIR"] = str(root_path / "data")
    os.environ["RESEARCH_DIGEST_LEGACY_DB"] = str(root_path / "missing.sqlite3")

    import streamlit as st

    st.cache_resource.clear()
    from research_digest.ui.pages.settings import render

    render()


def _automation_app(root: str, status_kind: str) -> None:
    import os
    from importlib import import_module
    from pathlib import Path

    root_path = Path(root)
    os.environ["RESEARCH_DIGEST_CONFIG_DIR"] = str(root_path / "config")
    os.environ["RESEARCH_DIGEST_DATA_DIR"] = str(root_path / "data")
    os.environ["RESEARCH_DIGEST_LEGACY_DB"] = str(root_path / "missing.sqlite3")
    (root_path / "data").mkdir(parents=True, exist_ok=True)

    import streamlit as st

    st.cache_resource.clear()

    from research_digest.automation import AutomationStatus
    from research_digest.config import load_config
    from research_digest.db import Database
    from research_digest.scheduler import WINDOWS_LOCAL_TIME_DESCRIPTION, ScheduleStatus
    settings = import_module("research_digest.ui.pages.settings")
    settings_module = vars(settings)

    db = Database(root_path / "data" / "research_digest.sqlite3")
    config = load_config()
    if status_kind == "ready_zero":
        status = AutomationStatus(
            ok=True,
            schedule=ScheduleStatus(
                backend="windows_task_scheduler",
                task_name="Research Digest Daily",
                installed=True,
                timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
                state="Ready",
                last_task_result=0,
                next_run_time="2026-08-19T06:00:00",
            ),
        )
    elif status_kind == "ready_nonzero":
        status = AutomationStatus(
            ok=True,
            schedule=ScheduleStatus(
                backend="windows_task_scheduler",
                task_name="Research Digest Daily",
                installed=True,
                timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
                state="Ready",
                last_task_result=3221225786,
                next_run_time="2026-08-19T06:00:00",
            ),
        )
    elif status_kind == "disabled":
        status = AutomationStatus(
            ok=True,
            schedule=ScheduleStatus(
                backend="windows_task_scheduler",
                task_name="Research Digest Daily",
                installed=True,
                timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
                state="Disabled",
            ),
        )
    else:
        status = AutomationStatus(
            ok=False,
            schedule=None,
            error_message="LastTaskResult conversion failed",
        )

    original = settings_module["read_schedule_status"]
    settings_module["read_schedule_status"] = lambda: status
    try:
        settings_module["_render_automation"](config, db)
    finally:
        settings_module["read_schedule_status"] = original
        db.close()


class SettingsUiSmokeTests(unittest.TestCase):
    def test_analysis_controls_and_scoring_guide_are_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            at = AppTest.from_function(
                _settings_app,
                default_timeout=5,
                args=(tmp,),
            ).run()

        self.assertEqual([str(value) for value in at.exception], [])
        texts = self._plain_texts(at)
        model_effort = next(
            element for element in at.slider if str(element.label) == "Model effort"
        )
        self.assertEqual(model_effort.value, 40)
        self.assertTrue(
            any(str(element.label) == "Automatic Library connections" for element in at.toggle)
        )
        self.assertTrue(
            any("new paper's relevance" in str(element.label) for element in at.number_input)
        )
        self.assertTrue(
            any("Papers below it can still be checked manually" in text for text in texts)
        )
        self.assertTrue(any("Stage-1 cutoff" in text for text in texts))
        self.assertTrue(any("false-negative risk" in text for text in texts))
        self.assertTrue(any("Example with the values shown here" in text for text in texts))
        self.assertTrue(
            any(
                "A cache-miss paper with a preselection score at or above" in text
                for text in texts
            )
        )
        self.assertTrue(any("screened out early" in text for text in texts))
        self.assertTrue(any("Scoring Guide" in text for text in texts))

    def test_scheduler_ready_with_zero_result_renders_automatic_toggle_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            at = AppTest.from_function(
                _automation_app,
                default_timeout=5,
                args=(tmp, "ready_zero"),
            ).run()

        self.assertEqual([str(value) for value in at.exception], [])
        toggle = self._toggle(at, "Automatic daily digest")
        self.assertTrue(toggle.value)
        self.assert_text_present(at, "2026-08-19T06:00:00")

    def test_scheduler_ready_with_nonzero_previous_result_still_renders_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            at = AppTest.from_function(
                _automation_app,
                default_timeout=5,
                args=(tmp, "ready_nonzero"),
            ).run()

        self.assertEqual([str(value) for value in at.exception], [])
        toggle = self._toggle(at, "Automatic daily digest")
        self.assertTrue(toggle.value)
        self.assert_text_present(at, "Schedule is installed, but the last run reported a warning.")
        self.assert_text_present(at, "2026-08-19T06:00:00")

    def test_scheduler_disabled_renders_automatic_toggle_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            at = AppTest.from_function(
                _automation_app,
                default_timeout=5,
                args=(tmp, "disabled"),
            ).run()

        self.assertEqual([str(value) for value in at.exception], [])
        toggle = self._toggle(at, "Automatic daily digest")
        self.assertFalse(toggle.value)

    def test_scheduler_status_unknown_does_not_render_off_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            at = AppTest.from_function(
                _automation_app,
                default_timeout=5,
                args=(tmp, "unknown"),
            ).run()

        self.assertEqual([str(value) for value in at.exception], [])
        self.assertFalse(
            any(str(element.label) == "Automatic daily digest" for element in at.toggle)
        )
        self.assert_text_present(at, "Schedule state unavailable")

    def _plain_texts(self, at: AppTest) -> list[str]:
        texts = (
            [str(element.value) for element in at.markdown]
            + [str(element.value) for element in at.text]
            + [str(element.value) for element in at.caption]
        )
        for collection_name in ("info", "warning", "success", "error"):
            collection = getattr(at, collection_name, ())
            texts.extend(str(element.value) for element in collection)
        for element in at.metric:
            texts.append(str(element.label))
            texts.append(str(element.value))
        return texts

    def _toggle(self, at: AppTest, label: str) -> Any:
        for element in at.toggle:
            if str(element.label) == label:
                return element
        self.fail(f"toggle {label!r} not found")

    def assert_text_present(self, at: AppTest, expected: str) -> None:
        haystack = "\n".join(self._plain_texts(at))
        self.assertIn(expected, haystack)


if __name__ == "__main__":
    unittest.main()
