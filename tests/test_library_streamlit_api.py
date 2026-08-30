from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path
from types import ModuleType

import streamlit as st

from research_digest.ui import article_header
from research_digest.ui.pages import library, today


class LibraryStreamlitApiCompatibilityTests(unittest.TestCase):
    def test_library_and_today_keywords_match_installed_streamlit_signatures(self) -> None:
        unsupported: list[str] = []
        for module in (library, today, article_header):
            unsupported.extend(_unsupported_streamlit_keywords(module))

        self.assertEqual(unsupported, [])

    def test_today_segmented_controls_do_not_use_post_floor_required_keyword(self) -> None:
        module_path = Path(inspect.getfile(today))
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        unsupported_lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "st"
            and node.func.attr == "segmented_control"
            and any(keyword.arg == "required" for keyword in node.keywords)
        ]

        self.assertEqual(unsupported_lines, [])


def _unsupported_streamlit_keywords(module: ModuleType) -> list[str]:
    module_path = Path(inspect.getfile(module))
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    unsupported: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != "st":
            continue
        command = node.func.attr
        callable_object = getattr(st, command, None)
        if callable_object is None:
            unsupported.append(f"{module_path.name}:{node.lineno}: st.{command} is unavailable")
            continue
        keyword_names = [keyword.arg for keyword in node.keywords if keyword.arg is not None]
        try:
            inspect.signature(callable_object).bind_partial(
                **dict.fromkeys(keyword_names),
            )
        except TypeError as exc:
            unsupported.append(
                f"{module_path.name}:{node.lineno}: st.{command}: {exc}"
            )
    return unsupported
