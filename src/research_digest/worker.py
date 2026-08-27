"""Detached local digest worker launched by Streamlit."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from research_digest.analysis.codex_context import CodexLibraryContextGenerator
from research_digest.analysis.providers import (
    build_configured_analyzer,
    build_configured_preselector,
)
from research_digest.automation import run_automatic_digest_now
from research_digest.cancellation import RunCancelled
from research_digest.config import AppConfig, load_config
from research_digest.db import Database, RunAlreadyActiveError
from research_digest.models import DateSelection, ModelValidationError, RunOrigin
from research_digest.service import run_digest_for_profile
from research_digest.sources.arxiv import ArxivSource


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = load_config()
    db = Database(config.db_path)
    analyzer = build_configured_analyzer(config).analyzer
    try:
        if args.mode == "automatic":
            run_automatic_digest_now(
                config=config,
                db=db,
                source=ArxivSource(),
                analyzer=analyzer,
                use_configured_preselector=True,
            )
            return 0
        date_selection = _date_selection(str(args.date_selection_json))
        run_digest_for_profile(
            db=db,
            source=ArxivSource(),
            analyzer=analyzer,
            profile_id=int(args.profile_id),
            date_selection=date_selection,
            run_origin=RunOrigin.MANUAL,
            preselector=build_configured_preselector(config).preselector,
            library_context_generator=_library_context_generator(config),
            automatic_library_context_threshold=(
                config.automatic_library_context_threshold
            ),
            relevance_calibration_prompt_probability=(
                config.relevance_calibration_prompt_probability
            ),
        )
    except RunCancelled:
        return 2
    except RunAlreadyActiveError:
        return 3
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-digest-worker")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    manual = subparsers.add_parser("manual")
    manual.add_argument("--profile-id", required=True, type=int)
    manual.add_argument("--date-selection-json", required=True)
    subparsers.add_parser("automatic")
    return parser


def _date_selection(raw: str) -> DateSelection:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ModelValidationError("date selection must be an object")
    return DateSelection.from_mapping(payload)


def _library_context_generator(
    config: AppConfig,
) -> CodexLibraryContextGenerator | None:
    if not config.automatic_library_connections_enabled:
        return None
    try:
        return CodexLibraryContextGenerator(
            model=config.codex_model,
            timeout_seconds=config.codex_timeout_seconds,
        )
    except Exception:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
