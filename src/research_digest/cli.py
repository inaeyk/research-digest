"""Command line interface for Research Digest."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

from research_digest.analysis.base import LLMAnalyzer
from research_digest.analysis.providers import build_configured_analyzer
from research_digest.config import AppConfig, load_config
from research_digest.db import Database
from research_digest.errors import sanitize_error
from research_digest.scheduler import (
    DEFAULT_TASK_NAME,
    ScheduleError,
    SchedulerBackend,
    build_schedule_request,
    select_scheduler_backend,
)
from research_digest.service import (
    HeadlessDigestRun,
    HeadlessProfileRun,
    run_digest_for_enabled_profiles,
)
from research_digest.sources.arxiv import ArxivSource
from research_digest.sources.base import SourceAdapter


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(argv=argv, stdout=sys.stdout, stderr=sys.stderr)


def run_cli(
    *,
    argv: Sequence[str] | None,
    stdout: TextIO,
    stderr: TextIO,
    config: AppConfig | None = None,
    db: Database | None = None,
    source: SourceAdapter | None = None,
    analyzer: LLMAnalyzer | None = None,
    analyzer_message: str | None = None,
    scheduler_backend: SchedulerBackend | None = None,
) -> int:
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    if args.command == "run":
        return _run_digest_command(
            json_output=args.json,
            stdout=stdout,
            stderr=stderr,
            config=config,
            db=db,
            source=source,
            analyzer=analyzer,
            analyzer_message=analyzer_message,
        )
    if args.command == "schedule":
        return _schedule_command(
            args=args,
            stdout=stdout,
            stderr=stderr,
            config=config,
            scheduler_backend=scheduler_backend,
        )

    _build_parser().print_help(stderr)
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-digest",
        description="Run Research Digest without opening Streamlit.",
    )
    subparsers = parser.add_subparsers(dest="command")
    run_parser = subparsers.add_parser("run", help="Run the digest workflow headlessly.")
    run_parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable JSON result.",
    )
    schedule_parser = subparsers.add_parser(
        "schedule",
        help="Manage the OS-backed daily headless run schedule.",
    )
    schedule_subparsers = schedule_parser.add_subparsers(dest="schedule_command", required=True)
    for name in ("status", "remove"):
        command_parser = schedule_subparsers.add_parser(name)
        _add_schedule_common_args(command_parser)
    install_parser = schedule_subparsers.add_parser("install")
    _add_schedule_common_args(install_parser)
    install_parser.add_argument(
        "--time",
        required=True,
        help="Windows local time in HH:MM 24-hour format.",
    )
    install_parser.add_argument(
        "--distro",
        help="WSL distro name. Defaults to WSL_DISTRO_NAME.",
    )
    return parser


def _add_schedule_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--task-name",
        default=DEFAULT_TASK_NAME,
        help=f"Windows Task Scheduler task name. Defaults to {DEFAULT_TASK_NAME!r}.",
    )
    parser.add_argument(
        "--backend",
        default="auto",
        choices=("auto", "windows"),
        help="Scheduler backend. Defaults to auto.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable JSON result.",
    )


def _run_digest_command(
    *,
    json_output: bool,
    stdout: TextIO,
    stderr: TextIO,
    config: AppConfig | None,
    db: Database | None,
    source: SourceAdapter | None,
    analyzer: LLMAnalyzer | None,
    analyzer_message: str | None,
) -> int:
    try:
        active_config = config or load_config()
        active_db = db or Database(active_config.db_path)
        active_source = source or ArxivSource()
        active_analyzer = analyzer
        active_analyzer_message = analyzer_message
        if active_analyzer is None and active_analyzer_message is None:
            analyzer_connection = build_configured_analyzer(active_config)
            active_analyzer = analyzer_connection.analyzer
            active_analyzer_message = analyzer_connection.message
        result = run_digest_for_enabled_profiles(
            db=active_db,
            source=active_source,
            analyzer=active_analyzer,
        )
    except Exception as exc:
        message = sanitize_error(exc)
        _write_failure(stdout, stderr, json_output=json_output, message=message)
        return 1

    command_failed = result.failed_count > 0 or active_analyzer_message is not None
    if json_output:
        json.dump(
            _run_to_json(
                result,
                active_config.db_path,
                active_analyzer_message,
                command_failed=command_failed,
            ),
            stdout,
        )
        stdout.write("\n")
    else:
        _write_human_result(
            stdout,
            result,
            active_config.db_path,
            active_analyzer_message,
            command_failed=command_failed,
        )
    return 1 if command_failed else 0


def _write_failure(
    stdout: TextIO,
    stderr: TextIO,
    *,
    json_output: bool,
    message: str,
) -> None:
    if json_output:
        json.dump({"status": "failed", "error_message": message}, stdout)
        stdout.write("\n")
    else:
        stderr.write(f"Research Digest run failed: {message}\n")


def _schedule_command(
    *,
    args: argparse.Namespace,
    stdout: TextIO,
    stderr: TextIO,
    config: AppConfig | None,
    scheduler_backend: SchedulerBackend | None,
) -> int:
    try:
        backend = scheduler_backend or select_scheduler_backend(backend_name=args.backend)
        if args.schedule_command == "install":
            request = build_schedule_request(
                task_name=args.task_name,
                time_of_day=args.time,
                config=config,
                wsl_distro=args.distro,
            )
            result = backend.install(request)
            payload = result.to_mapping()
        elif args.schedule_command == "remove":
            result = backend.remove(task_name=args.task_name)
            payload = result.to_mapping()
        elif args.schedule_command == "status":
            status = backend.status(task_name=args.task_name)
            payload = status.to_mapping()
        else:
            raise ScheduleError(f"unsupported schedule command: {args.schedule_command}")
    except Exception as exc:
        message = sanitize_error(exc)
        if args.json:
            json.dump({"status": "failed", "error_message": message}, stdout)
            stdout.write("\n")
        else:
            stderr.write(f"Research Digest schedule failed: {message}\n")
        return 1

    if args.json:
        json.dump({"status": "completed", **payload}, stdout)
        stdout.write("\n")
    else:
        _write_schedule_human(stdout, args.schedule_command, payload)
    return 0


def _write_schedule_human(
    stdout: TextIO,
    command: str,
    payload: Mapping[str, object],
) -> None:
    stdout.write(f"Schedule {command} completed\n")
    stdout.write(f"Backend: {payload.get('backend')}\n")
    stdout.write(f"Task: {payload.get('task_name')}\n")
    stdout.write(f"Installed: {payload.get('installed')}\n")
    stdout.write(f"Timezone: {payload.get('timezone')}\n")
    if payload.get("state") is not None:
        stdout.write(f"State: {payload.get('state')}\n")
    if payload.get("last_task_result") is not None:
        stdout.write(f"Last result: {payload.get('last_task_result')}\n")
    if payload.get("last_run_time") is not None:
        stdout.write(f"Last run: {payload.get('last_run_time')}\n")
    if payload.get("next_run_time") is not None:
        stdout.write(f"Next run: {payload.get('next_run_time')}\n")
    if payload.get("execute") is not None:
        stdout.write(f"Execute: {payload.get('execute')}\n")
    if payload.get("arguments") is not None:
        stdout.write(f"Arguments: {payload.get('arguments')}\n")
    if payload.get("message") is not None:
        stdout.write(f"{payload.get('message')}\n")


def _write_human_result(
    stdout: TextIO,
    result: HeadlessDigestRun,
    db_path: Path,
    analyzer_message: str | None,
    *,
    command_failed: bool,
) -> None:
    status = "failed" if command_failed else "completed"
    stdout.write(f"Research Digest run {status}\n")
    stdout.write(f"Data: {db_path}\n")
    if analyzer_message is not None:
        stdout.write(f"Analysis unavailable: {sanitize_error(analyzer_message)}\n")
    stdout.write(
        "Profiles: "
        f"{result.succeeded_count} succeeded, {result.failed_count} failed; "
        f"retrieved {result.retrieved_count}, analyzed {result.analyzed_count}, "
        f"relevant {result.relevant_count}\n"
    )
    for profile_run in result.profiles:
        if profile_run.digest is None:
            stdout.write(
                f"Profile {profile_run.profile_id}: failed: "
                f"{profile_run.error_message or 'unknown error'}\n"
            )
            continue
        digest = profile_run.digest.digest
        calibration = profile_run.digest.calibration
        synthesis = profile_run.digest.synthesis
        analysis_state = "available" if digest.analysis_available else "unavailable"
        stdout.write(
            f"Profile {profile_run.profile_id}: run #{digest.run_id}, "
            f"retrieved {digest.retrieved_count}, stored {digest.stored_count}, "
            f"preselected {digest.preselected_count}, skipped {digest.skipped_analysis_count}, "
            f"analyzed {digest.analyzed_count}, relevant {digest.relevant_count}, "
            f"new {digest.new_analysis_count}, reused {digest.reused_analysis_count}, "
            f"analysis {analysis_state}\n"
        )
        stdout.write(
            f"Profile {profile_run.profile_id}: feedback {calibration.feedback_count}, "
            f"false positives {calibration.false_positive_count}, "
            f"false negatives {calibration.false_negative_count}, "
            f"synthesis relevant {synthesis.relevant_count}, "
            f"recurring topics {len(synthesis.recurring_topics)}, "
            f"high priority {len(synthesis.high_priority_titles)}\n"
        )


def _run_to_json(
    result: HeadlessDigestRun,
    db_path: Path,
    analyzer_message: str | None,
    *,
    command_failed: bool,
) -> dict[str, object]:
    return {
        "status": "failed" if command_failed else "completed",
        "data_path": str(db_path),
        "analyzer_message": sanitize_error(analyzer_message) if analyzer_message else None,
        "profile_count": len(result.profiles),
        "succeeded_count": result.succeeded_count,
        "failed_count": result.failed_count,
        "retrieved_count": result.retrieved_count,
        "analyzed_count": result.analyzed_count,
        "relevant_count": result.relevant_count,
        "analysis_unavailable_count": result.analysis_unavailable_count,
        "profiles": [_profile_run_to_json(profile_run) for profile_run in result.profiles],
    }


def _profile_run_to_json(profile_run: HeadlessProfileRun) -> dict[str, object]:
    if profile_run.digest is None:
        return {
            "profile_id": profile_run.profile_id,
            "status": "failed",
            "error_message": profile_run.error_message,
        }
    digest = profile_run.digest.digest
    calibration = profile_run.digest.calibration
    synthesis = profile_run.digest.synthesis
    return {
        "profile_id": profile_run.profile_id,
        "status": "completed",
        "run_id": digest.run_id,
        "retrieved_count": digest.retrieved_count,
        "stored_count": digest.stored_count,
        "preselected_count": digest.preselected_count,
        "skipped_analysis_count": digest.skipped_analysis_count,
        "analyzed_count": digest.analyzed_count,
        "relevant_count": digest.relevant_count,
        "new_analysis_count": digest.new_analysis_count,
        "reused_analysis_count": digest.reused_analysis_count,
        "analysis_available": digest.analysis_available,
        "feedback_count": calibration.feedback_count,
        "false_positive_count": calibration.false_positive_count,
        "false_negative_count": calibration.false_negative_count,
        "synthesis_relevant_count": synthesis.relevant_count,
        "synthesis_recurring_topic_count": len(synthesis.recurring_topics),
        "synthesis_high_priority_count": len(synthesis.high_priority_titles),
    }


if __name__ == "__main__":
    raise SystemExit(main())
