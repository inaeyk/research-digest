from __future__ import annotations

import json
import subprocess
import unittest
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from research_digest.analysis.base import article_analysis_key
from research_digest.analysis.codex_cli import (
    CODEX_ABSTRACT_PRESELECTOR_VERSION,
    CodexAbstractPreselector,
)
from research_digest.models import Article, InterestProfile
from research_digest.preselection import PRESELECTION_ORIGIN_UNAVAILABLE_FAIL_OPEN


class ScriptedCodexRunner:
    def __init__(self, scripts: Sequence[object]) -> None:
        self.scripts = list(scripts)
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self,
        command: Sequence[str],
        *,
        input_text: str,
        cwd: Path,
        env: Mapping[str, str],
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, timeout_seconds
        requested_ids = _requested_ids(input_text)
        self.calls.append(tuple(requested_ids))
        script = self.scripts.pop(0) if self.scripts else {}
        if script == "nonzero":
            return subprocess.CompletedProcess(list(command), 1, "", "failed")
        if script == "malformed":
            payload = "{not json"
        elif isinstance(script, dict):
            payload = json.dumps(
                {
                    "results": [
                        {"article_id": article_id, "preselection_score": score}
                        for article_id, score in script.items()
                    ]
                }
            )
        elif isinstance(script, list):
            payload = json.dumps({"results": script})
        else:
            raise AssertionError(f"unknown script: {script!r}")
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(payload, encoding="utf-8")
        return subprocess.CompletedProcess(list(command), 0, "", "")


class CodexAbstractPreselectorTests(unittest.TestCase):
    def test_valid_batch_scores_with_inclusive_threshold(self) -> None:
        articles = [_article("2608.10001"), _article("2608.10002"), _article("2608.10003")]
        scores = {
            article_analysis_key(articles[0]): 0.48,
            article_analysis_key(articles[1]): 0.49,
            article_analysis_key(articles[2]): 0.80,
        }
        runner = ScriptedCodexRunner([scores])
        preselector = CodexAbstractPreselector(
            codex_path="codex",
            runner=runner,
            preselection_fraction=0.70,
            chunk_size=10,
        )

        result = preselector.preselect(profile=_profile(), articles=articles)

        self.assertEqual(result.selected_count, 2)
        self.assertEqual(result.skipped_count, 1)
        self.assertFalse(result.decisions[0].selected)
        self.assertTrue(result.decisions[1].selected)
        self.assertAlmostEqual(result.decisions[1].preselection_threshold or 0.0, 0.49)
        self.assertEqual(
            result.decisions[2].preselector_version,
            CODEX_ABSTRACT_PRESELECTOR_VERSION,
        )

    def test_bounded_chunking_uses_final_short_chunk(self) -> None:
        articles = [_article(f"2608.1100{i}") for i in range(5)]
        scripts = [
            {article_analysis_key(article): 0.6 for article in articles[:2]},
            {article_analysis_key(article): 0.6 for article in articles[2:4]},
            {article_analysis_key(articles[4]): 0.6},
        ]
        runner = ScriptedCodexRunner(scripts)
        preselector = CodexAbstractPreselector(
            codex_path="codex",
            runner=runner,
            preselection_fraction=0.70,
            chunk_size=2,
        )

        result = preselector.preselect(profile=_profile(), articles=articles)

        self.assertEqual(result.selected_count, 5)
        self.assertEqual([len(call) for call in runner.calls], [2, 2, 1])

    def test_missing_result_is_retried_without_rescoring_success(self) -> None:
        articles = [_article("2608.12001"), _article("2608.12002")]
        runner = ScriptedCodexRunner(
            [
                {article_analysis_key(articles[0]): 0.7},
                {article_analysis_key(articles[1]): 0.8},
            ]
        )
        preselector = CodexAbstractPreselector(
            codex_path="codex",
            runner=runner,
            preselection_fraction=0.70,
            chunk_size=2,
        )

        result = preselector.preselect(profile=_profile(), articles=articles)

        self.assertEqual(result.selected_count, 2)
        self.assertEqual(
            runner.calls[0],
            tuple(article_analysis_key(article) for article in articles),
        )
        self.assertEqual(runner.calls[1], (article_analysis_key(articles[1]),))

    def test_duplicate_unknown_and_malformed_results_are_retried(self) -> None:
        article = _article("2608.13001")
        key = article_analysis_key(article)
        runner = ScriptedCodexRunner(
            [
                [
                    {"article_id": key, "preselection_score": 0.8},
                    {"article_id": key, "preselection_score": 0.7},
                    {"article_id": "arxiv:unknown", "preselection_score": 1.0},
                    {"article_id": "", "preselection_score": 1.0},
                ],
                {key: 0.5},
            ]
        )
        preselector = CodexAbstractPreselector(
            codex_path="codex",
            runner=runner,
            preselection_fraction=0.70,
            chunk_size=2,
        )

        result = preselector.preselect(profile=_profile(), articles=[article])

        self.assertEqual(result.selected_count, 1)
        self.assertEqual(result.decisions[0].preselection_score, 0.5)
        self.assertEqual(len(runner.calls), 2)

    def test_malformed_or_failed_preselection_fails_open(self) -> None:
        article = _article("2608.14001")
        runner = ScriptedCodexRunner(["malformed", "nonzero"])
        preselector = CodexAbstractPreselector(
            codex_path="codex",
            runner=runner,
            preselection_fraction=0.70,
            chunk_size=2,
        )

        result = preselector.preselect(profile=_profile(), articles=[article])

        self.assertEqual(result.selected_count, 1)
        self.assertIsNone(result.decisions[0].preselection_score)
        self.assertEqual(
            result.decisions[0].decision_origin,
            PRESELECTION_ORIGIN_UNAVAILABLE_FAIL_OPEN,
        )


def _profile() -> InterestProfile:
    return InterestProfile(
        id=1,
        name="Warped gravity / black holes",
        description="Higher-dimensional gravity, black strings, black branes, and spin-2 states.",
        relevance_threshold=0.70,
    )


def _article(source_article_id: str) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title=f"Paper {source_article_id}",
        authors=["Ada Lovelace"],
        abstract="We study a scientific system with possible relevance.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


def _requested_ids(input_text: str) -> list[str]:
    marker_start = "BEGIN_INTEREST_PROFILE_AND_ARTICLES_JSON"
    marker_end = "END_INTEREST_PROFILE_AND_ARTICLES_JSON"
    start = input_text.index(marker_start) + len(marker_start)
    end = input_text.index(marker_end)
    payload = json.loads(input_text[start:end].strip())
    return [str(article["article_id"]) for article in payload["articles"]]


if __name__ == "__main__":
    unittest.main()
