"""Command line interface for Research Digest."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO, cast

from research_digest import __version__
from research_digest.analysis.base import LLMAnalyzer
from research_digest.analysis.providers import build_configured_analyzer
from research_digest.automation import (
    install_or_update_schedule,
    read_schedule_status,
    remove_schedule,
    run_automatic_digest_now,
)
from research_digest.backup import run_backup
from research_digest.cancellation import (
    RunCancelled,
    request_run_cancellation,
    stop_abandoned_provider_processes,
)
from research_digest.config import AppConfig, load_config, resolve_data_dir
from research_digest.db import Database, RunAlreadyActiveError, RunLockError
from research_digest.doctor import DoctorReport, run_doctor, run_doctor_from_environment
from research_digest.errors import sanitize_error
from research_digest.launcher import (
    LauncherResult,
    MacLauncherController,
    install_launcher,
    uninstall_launcher,
)
from research_digest.macos_launcher import MACOS_LAUNCHER_ID, MacLauncherResult
from research_digest.preselection import AbstractPreselector, UnavailableFailOpenPreselector
from research_digest.run_locks import process_run_owner_state
from research_digest.scheduler import (
    DEFAULT_TASK_NAME,
    ScheduleError,
    SchedulerBackend,
    select_scheduler_backend,
)
from research_digest.service import (
    DEFAULT_RUN_LOCK_STALE_SECONDS,
    HeadlessDigestRun,
    HeadlessProfileRun,
)
from research_digest.sources.base import SourceAdapter
from research_digest.sources.registry import ARXIV_SOURCE_DEFINITION
from research_digest.ui_server import (
    DEFAULT_UI_PORT,
    DEFAULT_UI_STARTUP_TIMEOUT_SECONDS,
    UILaunchResult,
    UIServerController,
    UIServerManager,
    UIServerStatus,
    UIStopResult,
)
from research_digest.windows_launcher import (
    WINDOWS_LAUNCHER_ID,
    WindowsLauncherController,
)

DEFAULT_SERVE_PORT = 8501
SERVE_PORT_SCAN_LIMIT = 50
STREAMLIT_APP_PATH = Path(__file__).resolve().parent / "ui" / "app.py"
ProcessLauncher = Callable[[Sequence[str]], object]


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
    preselector: AbstractPreselector | None = None,
    scheduler_backend: SchedulerBackend | None = None,
    process_launcher: ProcessLauncher | None = None,
    ui_server_manager: UIServerController | None = None,
    windows_launcher_backend: WindowsLauncherController | None = None,
    macos_launcher_backend: MacLauncherController | None = None,
) -> int:
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    if args.version:
        stdout.write(f"research-digest {__version__}\n")
        return 0
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
            preselector=preselector,
        )
    if args.command == "schedule":
        return _schedule_command(
            args=args,
            stdout=stdout,
            stderr=stderr,
            config=config,
            scheduler_backend=scheduler_backend,
        )
    if args.command == "serve":
        return _serve_command(
            args=args,
            stdout=stdout,
            stderr=stderr,
            config=config,
            process_launcher=process_launcher,
        )
    if args.command == "launch":
        return _launch_ui_command(
            args=args,
            stdout=stdout,
            stderr=stderr,
            config=config,
            manager=ui_server_manager,
        )
    if args.command == "ui-status":
        return _ui_status_command(
            args=args,
            stdout=stdout,
            stderr=stderr,
            config=config,
            manager=ui_server_manager,
        )
    if args.command == "ui-stop":
        return _ui_stop_command(
            args=args,
            stdout=stdout,
            stderr=stderr,
            config=config,
            manager=ui_server_manager,
        )
    if args.command == "install-launcher":
        return _install_launcher_command(
            args=args,
            stdout=stdout,
            stderr=stderr,
            config=config,
            windows_backend=windows_launcher_backend,
            macos_backend=macos_launcher_backend,
        )
    if args.command == "uninstall-launcher":
        return _uninstall_launcher_command(
            args=args,
            stdout=stdout,
            stderr=stderr,
            windows_backend=windows_launcher_backend,
            macos_backend=macos_launcher_backend,
        )
    if args.command == "status":
        return _status_command(
            args=args,
            stdout=stdout,
            stderr=stderr,
            config=config,
            db=db,
            scheduler_backend=scheduler_backend,
        )
    if args.command == "cancel":
        return _cancel_command(
            args=args,
            stdout=stdout,
            stderr=stderr,
            config=config,
            db=db,
        )
    if args.command == "doctor":
        return _doctor_command(
            args=args,
            stdout=stdout,
            stderr=stderr,
            config=config,
            db=db,
            scheduler_backend=scheduler_backend,
        )
    if args.command == "recover-abandoned-run":
        return _recover_abandoned_run_command(
            args=args,
            stdout=stdout,
            stderr=stderr,
            config=config,
            db=db,
        )
    if args.command == "backup":
        return _backup_command(args=args, stdout=stdout, stderr=stderr)

    _build_parser().print_help(stderr)
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-digest",
        description="Run Research Digest and manage its local UI.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the installed Research Digest version.",
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
        help="Computer local time in HH:MM 24-hour format.",
    )
    install_parser.add_argument(
        "--distro",
        help="WSL distro name. Defaults to WSL_DISTRO_NAME.",
    )
    serve_parser = subparsers.add_parser("serve", help="Launch the Streamlit UI.")
    serve_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_SERVE_PORT,
        help=f"Preferred local port. Defaults to {DEFAULT_SERVE_PORT}.",
    )
    serve_parser.add_argument(
        "--host",
        default="localhost",
        help="Host name to print in the usable URL. Defaults to localhost.",
    )
    launch_parser = subparsers.add_parser(
        "launch",
        help="Open or start the detached Research Digest UI and open its browser URL.",
    )
    launch_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_UI_PORT,
        help=f"Preferred local UI port. Defaults to {DEFAULT_UI_PORT}.",
    )
    launch_parser.add_argument(
        "--startup-timeout",
        type=_ui_timeout,
        default=DEFAULT_UI_STARTUP_TIMEOUT_SECONDS,
        help="Bounded UI startup wait in seconds. Defaults to 30.",
    )
    launch_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start or reuse the UI without opening the default browser.",
    )
    launch_parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable JSON result.",
    )
    launch_parser.add_argument(
        "--launcher-id",
        choices=(WINDOWS_LAUNCHER_ID, MACOS_LAUNCHER_ID),
        help=argparse.SUPPRESS,
    )
    for name, help_text in (
        ("ui-status", "Show detached Research Digest UI-server status."),
        ("ui-stop", "Stop only the exact owned Research Digest UI server."),
    ):
        command_parser = subparsers.add_parser(name, help=help_text)
        command_parser.add_argument(
            "--json",
            action="store_true",
            help="Print a machine-readable JSON result.",
        )
    install_launcher_parser = subparsers.add_parser(
        "install-launcher",
        help="Create or update the owned Windows/macOS application launcher.",
    )
    install_launcher_parser.add_argument(
        "--distro",
        help="Windows/WSL only: distribution name. Defaults to WSL_DISTRO_NAME.",
    )
    install_launcher_parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable JSON result.",
    )
    uninstall_launcher_parser = subparsers.add_parser(
        "uninstall-launcher",
        help="Remove only the Research Digest-owned application launcher.",
    )
    uninstall_launcher_parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable JSON result.",
    )
    status_parser = subparsers.add_parser("status", help="Show local application status.")
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable JSON result.",
    )
    cancel_parser = subparsers.add_parser(
        "cancel",
        help="Cancel one active digest and preserve completed work.",
    )
    cancel_parser.add_argument(
        "--run-id",
        type=int,
        required=True,
        help="Active app run id to cancel.",
    )
    cancel_parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable JSON result.",
    )
    doctor_parser = subparsers.add_parser("doctor", help="Run safe local diagnostics.")
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable JSON result.",
    )
    doctor_parser.add_argument(
        "--network",
        action="store_true",
        help="Include bounded arXiv network reachability checks.",
    )
    doctor_parser.add_argument(
        "--network-timeout",
        type=_doctor_network_timeout,
        default=5.0,
        help="Network check timeout in seconds. Defaults to 5.",
    )
    recover_parser = subparsers.add_parser(
        "recover-abandoned-run",
        help="Mark an abandoned RUNNING digest terminal and release stale ownership.",
    )
    recover_parser.add_argument(
        "--run-id",
        type=int,
        required=True,
        help="RUNNING app run id to recover.",
    )
    recover_parser.add_argument(
        "--force-uninspectable-owner",
        action="store_true",
        help=(
            "Recover even when an old lock owner cannot be inspected. Use only after "
            "confirming no digest process is still running."
        ),
    )
    recover_parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable JSON result.",
    )
    backup_parser = subparsers.add_parser("backup", help="Back up local user data.")
    backup_parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable JSON result.",
    )
    backup_parser.add_argument(
        "--output",
        type=Path,
        help="Backup file or directory. Defaults to the active data directory's backups folder.",
    )
    backup_parser.add_argument(
        "--export-json",
        action="store_true",
        help="Write a portable JSON export next to the SQLite backup.",
    )
    return parser


def _add_schedule_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--task-name",
        default=DEFAULT_TASK_NAME,
        help=f"OS scheduler task name. Defaults to {DEFAULT_TASK_NAME!r}.",
    )
    parser.add_argument(
        "--backend",
        default="auto",
        choices=("auto", "windows", "launchd"),
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
    preselector: AbstractPreselector | None,
) -> int:
    try:
        active_config = config or load_config()
        active_db = db or Database(active_config.db_path)
        active_source = source or ARXIV_SOURCE_DEFINITION.build_adapter()
        active_analyzer = analyzer
        active_analyzer_message = analyzer_message
        if active_analyzer is None and active_analyzer_message is None:
            analyzer_connection = build_configured_analyzer(active_config)
            active_analyzer = analyzer_connection.analyzer
            active_analyzer_message = analyzer_connection.message
        active_preselector = preselector
        if active_preselector is None and analyzer is not None:
            active_preselector = UnavailableFailOpenPreselector(
                preselection_fraction=active_config.preselection_fraction,
                reason="Injected analyzer supplied without model preselector.",
            )
        result = run_automatic_digest_now(
            config=active_config,
            db=active_db,
            source=active_source,
            analyzer=active_analyzer,
            preselector=active_preselector,
            use_configured_preselector=True,
        )
    except RunCancelled as exc:
        message = sanitize_error(exc)
        _write_failure(stdout, stderr, json_output=json_output, message=message)
        return 2
    except Exception as exc:
        message = sanitize_error(exc)
        _write_failure(stdout, stderr, json_output=json_output, message=message)
        return 1

    command_failed = result.failed_count > 0 or (
        active_analyzer_message is not None and _analysis_was_needed(result)
    ) or result.analysis_incomplete_count > 0
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


def _cancel_command(
    *,
    args: argparse.Namespace,
    stdout: TextIO,
    stderr: TextIO,
    config: AppConfig | None,
    db: Database | None,
) -> int:
    try:
        active_config = config or load_config()
        active_db = db or Database(active_config.db_path)
        result = request_run_cancellation(active_db, run_id=int(args.run_id))
    except Exception as exc:
        message = sanitize_error(exc)
        if bool(args.json):
            json.dump({"status": "failed", "error_message": message}, stdout)
            stdout.write("\n")
        else:
            stderr.write(f"Research Digest cancellation failed: {message}\n")
        return 1

    payload = {
        "run_id": result.run_id,
        "accepted": result.accepted,
        "status": result.status,
        "owner_stopped": result.owner_stopped,
    }
    if bool(args.json):
        json.dump(payload, stdout)
        stdout.write("\n")
    elif result.accepted:
        stdout.write(
            f"Cancellation requested for digest run #{result.run_id}: {result.status}.\n"
        )
    else:
        stdout.write(
            f"Digest run #{result.run_id} is already terminal: {result.status}.\n"
        )
    return 0


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


def _serve_command(
    *,
    args: argparse.Namespace,
    stdout: TextIO,
    stderr: TextIO,
    config: AppConfig | None,
    process_launcher: ProcessLauncher | None,
) -> int:
    try:
        if process_launcher is None:
            manager = _build_ui_server_manager(
                config=config,
                preferred_port=int(args.port),
                public_host=str(args.host),
            )
            server = manager.start_foreground()
            stdout.write(f"Research Digest UI: {server.registration.url}\n")
            stdout.write(
                "Existing UI server reused.\n"
                if server.reused
                else "Foreground UI server started; press Ctrl+C to stop the UI only.\n"
            )
            stdout.flush()
            return server.wait()

        port = _select_available_port(int(args.port))
        command = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(STREAMLIT_APP_PATH),
            f"--server.port={port}",
            "--server.headless=true",
        ]
        url = f"http://{args.host}:{port}"
        stdout.write(f"Research Digest UI: {url}\n")
        stdout.write("Command: " + subprocess.list2cmdline(command) + "\n")
        stdout.flush()
        process_launcher(command)
        return 0
    except Exception as exc:
        stderr.write(f"Research Digest serve failed: {sanitize_error(exc)}\n")
        return 1


def _launch_ui_command(
    *,
    args: argparse.Namespace,
    stdout: TextIO,
    stderr: TextIO,
    config: AppConfig | None,
    manager: UIServerController | None,
) -> int:
    try:
        active_manager = manager or _build_ui_server_manager(
            config=config,
            preferred_port=int(args.port),
            startup_timeout_seconds=float(args.startup_timeout),
        )
        result = active_manager.launch(open_browser=not bool(args.no_browser))
    except Exception as exc:
        return _write_launcher_failure(
            args=args,
            stdout=stdout,
            stderr=stderr,
            operation="launch",
            error=exc,
        )
    _write_ui_launch_result(stdout, result, json_output=bool(args.json))
    return 0


def _ui_status_command(
    *,
    args: argparse.Namespace,
    stdout: TextIO,
    stderr: TextIO,
    config: AppConfig | None,
    manager: UIServerController | None,
) -> int:
    try:
        active_manager = manager or _build_ui_server_manager(config=config)
        status = active_manager.status()
    except Exception as exc:
        return _write_launcher_failure(
            args=args,
            stdout=stdout,
            stderr=stderr,
            operation="UI status",
            error=exc,
        )
    _write_ui_status(stdout, status, json_output=bool(args.json))
    return 0


def _ui_stop_command(
    *,
    args: argparse.Namespace,
    stdout: TextIO,
    stderr: TextIO,
    config: AppConfig | None,
    manager: UIServerController | None,
) -> int:
    try:
        active_manager = manager or _build_ui_server_manager(config=config)
        result = active_manager.stop()
    except Exception as exc:
        return _write_launcher_failure(
            args=args,
            stdout=stdout,
            stderr=stderr,
            operation="UI stop",
            error=exc,
        )
    _write_ui_stop_result(stdout, result, json_output=bool(args.json))
    return 0


def _install_launcher_command(
    *,
    args: argparse.Namespace,
    stdout: TextIO,
    stderr: TextIO,
    config: AppConfig | None,
    windows_backend: WindowsLauncherController | None,
    macos_backend: MacLauncherController | None,
) -> int:
    try:
        result = install_launcher(
            config=config,
            distro=args.distro,
            windows_backend=windows_backend,
            macos_backend=macos_backend,
        )
    except Exception as exc:
        return _write_launcher_failure(
            args=args,
            stdout=stdout,
            stderr=stderr,
            operation="launcher installation",
            error=exc,
        )
    _write_launcher_result(stdout, result, json_output=bool(args.json))
    return 0


def _uninstall_launcher_command(
    *,
    args: argparse.Namespace,
    stdout: TextIO,
    stderr: TextIO,
    windows_backend: WindowsLauncherController | None,
    macos_backend: MacLauncherController | None,
) -> int:
    try:
        result = uninstall_launcher(
            windows_backend=windows_backend,
            macos_backend=macos_backend,
        )
    except Exception as exc:
        return _write_launcher_failure(
            args=args,
            stdout=stdout,
            stderr=stderr,
            operation="launcher removal",
            error=exc,
        )
    _write_launcher_result(stdout, result, json_output=bool(args.json))
    return 0


def _build_ui_server_manager(
    *,
    config: AppConfig | None,
    preferred_port: int = DEFAULT_UI_PORT,
    startup_timeout_seconds: float = DEFAULT_UI_STARTUP_TIMEOUT_SECONDS,
    public_host: str = "localhost",
) -> UIServerManager:
    data_dir = config.data_dir if config is not None else resolve_data_dir()
    return UIServerManager(
        data_dir=data_dir,
        preferred_port=preferred_port,
        startup_timeout_seconds=startup_timeout_seconds,
        public_host=public_host,
    )


def _write_ui_launch_result(
    stdout: TextIO,
    result: UILaunchResult,
    *,
    json_output: bool,
) -> None:
    if json_output:
        json.dump({"status": "completed", **result.to_mapping()}, stdout)
        stdout.write("\n")
        return
    action = "reused" if result.reused else "started"
    stdout.write(f"Research Digest UI {action}: {result.status.url}\n")
    stdout.write(f"PID: {result.status.pid}; log: {result.status.log_path}\n")
    stdout.write("Default browser opened.\n" if result.browser_opened else "Browser not opened.\n")


def _write_ui_status(
    stdout: TextIO,
    status: UIServerStatus,
    *,
    json_output: bool,
) -> None:
    if json_output:
        json.dump({"status": "completed", **status.to_mapping()}, stdout)
        stdout.write("\n")
        return
    stdout.write(f"Research Digest UI: {status.state}\n")
    if status.pid is not None:
        stdout.write(f"PID: {status.pid}; URL: {status.url}; log: {status.log_path}\n")


def _write_ui_stop_result(
    stdout: TextIO,
    result: UIStopResult,
    *,
    json_output: bool,
) -> None:
    if json_output:
        json.dump({"status": "completed", **result.to_mapping()}, stdout)
        stdout.write("\n")
        return
    if result.stopped:
        stdout.write("Research Digest UI server stopped. Digest workers and schedule unchanged.\n")
    elif result.stale_registration_removed:
        stdout.write("Stale Research Digest UI registration removed; no process was stopped.\n")
    else:
        stdout.write("Research Digest UI server is not running.\n")


def _write_launcher_result(
    stdout: TextIO,
    result: LauncherResult,
    *,
    json_output: bool,
) -> None:
    if json_output:
        json.dump({"status": "completed", **result.to_mapping()}, stdout)
        stdout.write("\n")
        return
    platform_label = "macOS" if isinstance(result, MacLauncherResult) else "Windows"
    if result.operation == "installed_or_updated":
        stdout.write(f"Research Digest {platform_label} launcher installed: {result.path}\n")
    elif result.operation == "removed":
        stdout.write(f"Research Digest {platform_label} launcher removed: {result.path}\n")
    else:
        stdout.write(f"Research Digest {platform_label} launcher is not installed.\n")


def _write_launcher_failure(
    *,
    args: argparse.Namespace,
    stdout: TextIO,
    stderr: TextIO,
    operation: str,
    error: Exception,
) -> int:
    message = sanitize_error(error)
    if bool(args.json):
        json.dump({"status": "failed", "error_message": message}, stdout)
        stdout.write("\n")
    else:
        stderr.write(f"Research Digest {operation} failed: {message}\n")
    return 1


def _status_command(
    *,
    args: argparse.Namespace,
    stdout: TextIO,
    stderr: TextIO,
    config: AppConfig | None,
    db: Database | None,
    scheduler_backend: SchedulerBackend | None,
) -> int:
    try:
        active_config = config or load_config()
        active_db = db or Database(active_config.db_path)
        payload = _status_payload(active_config, active_db, scheduler_backend=scheduler_backend)
    except Exception as exc:
        message = sanitize_error(exc)
        if args.json:
            json.dump({"status": "failed", "error_message": message}, stdout)
            stdout.write("\n")
        else:
            stderr.write(f"Research Digest status failed: {message}\n")
        return 1

    if args.json:
        json.dump({"status": "completed", **payload}, stdout)
        stdout.write("\n")
    else:
        _write_status_human(stdout, payload)
    return 0


def _doctor_command(
    *,
    args: argparse.Namespace,
    stdout: TextIO,
    stderr: TextIO,
    config: AppConfig | None,
    db: Database | None,
    scheduler_backend: SchedulerBackend | None,
) -> int:
    try:
        if config is None and db is None:
            report = run_doctor_from_environment(
                scheduler_backend=scheduler_backend,
                include_network=bool(args.network),
                network_timeout_seconds=float(args.network_timeout),
            )
        else:
            active_config = config or load_config()
            active_db = db or Database(active_config.db_path)
            report = run_doctor(
                config=active_config,
                db=active_db,
                scheduler_backend=scheduler_backend,
                include_network=bool(args.network),
                network_timeout_seconds=float(args.network_timeout),
            )
    except Exception as exc:
        message = sanitize_error(exc)
        if args.json:
            json.dump({"status": "failed", "error_message": message}, stdout)
            stdout.write("\n")
        else:
            stderr.write(f"Research Digest doctor failed: {message}\n")
        return 1

    if args.json:
        json.dump(report.to_mapping(), stdout)
        stdout.write("\n")
    else:
        _write_doctor_human(stdout, report)
    return report.exit_code


def _write_doctor_human(stdout: TextIO, report: DoctorReport) -> None:
    stdout.write("Research Digest doctor\n")
    stdout.write(f"Failures: {report.failure_count}; warnings: {report.warning_count}\n")
    for check in report.checks:
        stdout.write(f"{check.severity}: {check.name}: {check.message}\n")


def _recover_abandoned_run_command(
    *,
    args: argparse.Namespace,
    stdout: TextIO,
    stderr: TextIO,
    config: AppConfig | None,
    db: Database | None,
) -> int:
    try:
        active_config = config or load_config()
        active_db = db or Database(active_config.db_path)
        stop_abandoned_provider_processes(
            active_db,
            stale_after_seconds=DEFAULT_RUN_LOCK_STALE_SECONDS,
            run_id=int(args.run_id),
            force_uninspectable_owner=bool(args.force_uninspectable_owner),
        )
        result = active_db.recover_abandoned_run(
            run_id=int(args.run_id),
            force_uninspectable_owner=bool(args.force_uninspectable_owner),
        )
    except (RunAlreadyActiveError, RunLockError, ValueError) as exc:
        message = sanitize_error(exc)
        if args.json:
            json.dump({"status": "failed", "error_message": message}, stdout)
            stdout.write("\n")
        else:
            stderr.write(f"Research Digest recovery failed: {message}\n")
        return 1
    except Exception as exc:
        message = sanitize_error(exc)
        if args.json:
            json.dump({"status": "failed", "error_message": message}, stdout)
            stdout.write("\n")
        else:
            stderr.write(f"Research Digest recovery failed: {message}\n")
        return 1

    payload = {
        "run_id": result.run_id,
        "recovered": result.recovered,
        "status_before": result.status_before,
        "status_after": result.status_after,
        "retrieved_count": result.retrieved_count,
        "stored_count": result.stored_count,
        "preselected_count": result.preselected_count,
        "skipped_analysis_count": result.skipped_analysis_count,
        "analyzed_count": result.analyzed_count,
        "relevant_count": result.relevant_count,
        "message": result.message,
    }
    if args.json:
        json.dump({"status": "completed", **payload}, stdout)
        stdout.write("\n")
    else:
        stdout.write("Research Digest recovery completed\n")
        stdout.write(f"Run: #{result.run_id}\n")
        stdout.write(f"Recovered: {result.recovered}\n")
        stdout.write(f"Status: {result.status_before} -> {result.status_after}\n")
        stdout.write(
            "Counts: "
            f"retrieved {result.retrieved_count}, "
            f"preselected {result.preselected_count}, "
            f"analyzed {result.analyzed_count}, "
            f"relevant {result.relevant_count}\n"
        )
        stdout.write(f"{result.message}\n")
    return 0


def _backup_command(*, args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    try:
        result = run_backup(
            output_path=cast(Path | None, args.output),
            export_json=bool(args.export_json),
        )
    except Exception as exc:
        message = sanitize_error(exc)
        if args.json:
            json.dump({"status": "failed", "error_message": message}, stdout)
            stdout.write("\n")
        else:
            stderr.write(f"Research Digest backup failed: {message}\n")
        return 1

    if args.json:
        json.dump(result.to_mapping(), stdout)
        stdout.write("\n")
    else:
        stdout.write(f"Research Digest backup: {result.backup_path}\n")
        if result.export_path is not None:
            stdout.write(f"Research Digest export: {result.export_path}\n")
    return 0


def _doctor_network_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive finite number") from exc
    if timeout <= 0 or timeout != timeout or timeout == float("inf") or timeout > 60:
        raise argparse.ArgumentTypeError("must be a positive finite number no greater than 60")
    return timeout


def _ui_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive finite number") from exc
    if timeout <= 0 or timeout != timeout or timeout == float("inf") or timeout > 120:
        raise argparse.ArgumentTypeError("must be a positive finite number no greater than 120")
    return timeout


def _status_payload(
    config: AppConfig,
    db: Database,
    *,
    scheduler_backend: SchedulerBackend | None,
) -> dict[str, object]:
    app_runs = db.get_app_runs()
    last_run = _last_run_to_mapping(app_runs[0]) if app_runs else None
    schedule = _schedule_status_payload(scheduler_backend)
    run_lock = db.get_run_lock()
    return {
        "data_path": str(config.db_path),
        "config_path": str(config.config_path) if config.config_path else None,
        "analyzer_provider": config.analyzer_provider,
        "schema_version": db.get_schema_version(),
        "config_version": config.config_version,
        "last_run": last_run,
        "run_lock": _run_lock_to_mapping(run_lock),
        "schedule": schedule,
        "automation": {
            "catch_up_missed_dates": config.automatic_catch_up_enabled,
            "coverage_start_date": config.automatic_coverage_start_date.isoformat(),
            "covered_source_date_count": len(db.list_source_date_coverage()),
        },
    }


def _run_lock_to_mapping(lock: object | None) -> dict[str, object] | None:
    if lock is None:
        return None
    values = cast(Any, lock)
    return {
        "name": values.name,
        "owner": values.owner,
        "owner_state": process_run_owner_state(values.owner).value,
        "acquired_at": values.acquired_at.isoformat(),
    }


def _last_run_to_mapping(row: object) -> dict[str, object]:
    values = cast(Mapping[str, Any], row)
    return {
        "id": values["id"],
        "profile_id": values["profile_id"],
        "source_name": values["source_name"],
        "started_at": values["started_at"],
        "completed_at": values["completed_at"],
        "status": values["status"],
        "retrieved_count": values["retrieved_count"],
        "stored_count": values["stored_count"],
        "preselected_count": values["preselected_count"],
        "skipped_analysis_count": values["skipped_analysis_count"],
        "analyzed_count": values["analyzed_count"],
        "relevant_count": values["relevant_count"],
        "error_message": sanitize_error(str(values["error_message"]))
        if values["error_message"] is not None
        else None,
        "run_origin": values["run_origin"],
        "date_selection": json.loads(str(values["date_selection_json"]))
        if values["date_selection_json"] is not None
        else None,
        "requested_source_dates": json.loads(str(values["requested_source_dates_json"])),
        "covered_source_dates": json.loads(str(values["covered_source_dates_json"])),
        "empty_source_dates": json.loads(str(values["empty_source_dates_json"])),
        "incomplete_source_dates": json.loads(str(values["incomplete_source_dates_json"])),
        "retrieval_complete": bool(values["retrieval_complete"]),
        "retrieval_safety_limit": values["retrieval_safety_limit"],
        "cancel_requested_at": values["cancel_requested_at"],
        "cancel_reason": (
            sanitize_error(str(values["cancel_reason"]))
            if values["cancel_reason"] is not None
            else None
        ),
    }


def _schedule_status_payload(scheduler_backend: SchedulerBackend | None) -> dict[str, object]:
    status = read_schedule_status(scheduler_backend=scheduler_backend)
    if status.schedule is not None:
        return {"status_available": True, **status.schedule.to_mapping()}
    error_message = status.error_message or "Schedule status is unavailable."
    return {
        "status_available": False,
        "backend": None,
        "task_name": DEFAULT_TASK_NAME,
        "installed": None,
        "message": error_message,
    }


def _write_status_human(stdout: TextIO, payload: Mapping[str, object]) -> None:
    stdout.write("Research Digest status\n")
    stdout.write(f"Data: {payload['data_path']}\n")
    stdout.write(f"Config: {payload['config_path']}\n")
    stdout.write(f"Analyzer: {payload['analyzer_provider']}\n")
    stdout.write(f"Schema version: {payload['schema_version']}\n")
    stdout.write(f"Config version: {payload['config_version']}\n")
    last_run = payload.get("last_run")
    if isinstance(last_run, Mapping):
        stdout.write(
            "Last run: "
            f"#{last_run['id']} {last_run['status']} "
            f"retrieved {last_run['retrieved_count']}, "
            f"analyzed {last_run['analyzed_count']}, "
            f"relevant {last_run['relevant_count']}\n"
        )
    else:
        stdout.write("Last run: none\n")
    schedule = payload.get("schedule")
    if isinstance(schedule, Mapping):
        if schedule.get("status_available") is False:
            stdout.write(
                "Schedule: status unavailable "
                f"message={schedule.get('message')}\n"
            )
        else:
            stdout.write(
                "Schedule: "
                f"installed={schedule.get('installed')} "
                f"backend={schedule.get('backend')} "
                f"message={schedule.get('message')}\n"
            )
    run_lock = payload.get("run_lock")
    if isinstance(run_lock, Mapping):
        stdout.write(
            "Run lock: "
            f"owner_state={run_lock.get('owner_state')} "
            f"acquired_at={run_lock.get('acquired_at')}\n"
        )
    else:
        stdout.write("Run lock: none\n")
    automation = payload.get("automation")
    if isinstance(automation, Mapping):
        stdout.write(
            "Automation: "
            f"catch_up={automation.get('catch_up_missed_dates')} "
            f"coverage_start={automation.get('coverage_start_date')} "
            f"covered_dates={automation.get('covered_source_date_count')}\n"
        )


def _deferred_command(
    *,
    stdout: TextIO,
    json_output: bool,
    command: str,
    milestone: str,
) -> int:
    message = (
        f"`research-digest {command}` is reserved; "
        f"release behavior is implemented in {milestone}."
    )
    if json_output:
        json.dump({"status": "deferred", "command": command, "message": message}, stdout)
        stdout.write("\n")
    else:
        stdout.write(message + "\n")
    return 1


def _select_available_port(preferred_port: int) -> int:
    if preferred_port <= 0:
        raise ValueError("port must be positive")
    for port in range(preferred_port, preferred_port + SERVE_PORT_SCAN_LIMIT):
        if _is_port_available(port):
            return port
    raise RuntimeError(
        f"no available local port from {preferred_port} to "
        f"{preferred_port + SERVE_PORT_SCAN_LIMIT - 1}"
    )


def _is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _launch_process(command: Sequence[str]) -> object:
    return subprocess.run(list(command), check=False)


def _schedule_command(
    *,
    args: argparse.Namespace,
    stdout: TextIO,
    stderr: TextIO,
    config: AppConfig | None,
    scheduler_backend: SchedulerBackend | None,
) -> int:
    try:
        if args.schedule_command == "install":
            backend = scheduler_backend or select_scheduler_backend(backend_name=args.backend)
            result = install_or_update_schedule(
                time_of_day=args.time,
                config=config,
                scheduler_backend=backend,
                task_name=args.task_name,
                wsl_distro=args.distro,
            )
            payload = result.to_mapping()
        elif args.schedule_command == "remove":
            backend = scheduler_backend or select_scheduler_backend(backend_name=args.backend)
            result = remove_schedule(scheduler_backend=backend, task_name=args.task_name)
            payload = result.to_mapping()
        elif args.schedule_command == "status":
            status = read_schedule_status(
                scheduler_backend=scheduler_backend
                or select_scheduler_backend(backend_name=args.backend),
                task_name=args.task_name,
            )
            if status.schedule is None:
                raise ScheduleError(status.error_message or "Schedule status is unavailable.")
            payload = status.schedule.to_mapping()
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
    if result.pending_source_dates:
        stdout.write(
            "Source dates: "
            + ", ".join(value.isoformat() for value in result.pending_source_dates)
            + "\n"
        )
    elif result.latest_available_source_date is not None:
        stdout.write("Source dates: no uncovered dates\n")
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
            f"screened this run {digest.preselected_count + digest.skipped_analysis_count}, "
            f"passed preselection {digest.preselected_count}, "
            f"preselected out {digest.skipped_analysis_count}, "
            f"new full analyses {digest.new_analysis_count}, "
            f"reused full analyses {digest.reused_analysis_count}, "
            f"total analyzed {digest.analyzed_count}, relevant {digest.relevant_count}, "
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


def _analysis_was_needed(result: HeadlessDigestRun) -> bool:
    return any(
        profile_run.digest is not None and profile_run.digest.digest.retrieved_count > 0
        for profile_run in result.profiles
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
        "analysis_incomplete_count": result.analysis_incomplete_count,
        "date_selection": (
            result.date_selection.to_mapping() if result.date_selection is not None else None
        ),
        "pending_source_dates": [value.isoformat() for value in result.pending_source_dates],
        "latest_available_source_date": (
            result.latest_available_source_date.isoformat()
            if result.latest_available_source_date is not None
            else None
        ),
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
        "status": digest.run_status.lower(),
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
        "analysis_complete": digest.analysis_complete,
        "unresolved_article_count": len(digest.unresolved_articles),
        "unresolved_articles": [
            {
                "source": article.source,
                "source_article_id": article.source_article_id,
                "title": article.title,
            }
            for article in digest.unresolved_articles
        ],
        "run_origin": digest.run_origin.value,
        "date_selection": (
            digest.date_selection.to_mapping() if digest.date_selection is not None else None
        ),
        "requested_source_dates": [
            value.isoformat() for value in digest.requested_source_dates
        ],
        "covered_source_dates": [value.isoformat() for value in digest.covered_source_dates],
        "empty_source_dates": [value.isoformat() for value in digest.empty_source_dates],
        "incomplete_source_dates": [
            value.isoformat() for value in digest.incomplete_source_dates
        ],
        "retrieval_complete": digest.retrieval_complete,
        "retrieval_safety_limit": digest.retrieval_safety_limit,
        "feedback_count": calibration.feedback_count,
        "false_positive_count": calibration.false_positive_count,
        "false_negative_count": calibration.false_negative_count,
        "synthesis_relevant_count": synthesis.relevant_count,
        "synthesis_recurring_topic_count": len(synthesis.recurring_topics),
        "synthesis_high_priority_count": len(synthesis.high_priority_titles),
    }


if __name__ == "__main__":
    raise SystemExit(main())
