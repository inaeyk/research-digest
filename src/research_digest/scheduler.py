"""OS-backed scheduling boundary for headless digest runs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from research_digest.config import AppConfig, load_config

DEFAULT_TASK_NAME = "Research Digest Daily"
WINDOWS_LOCAL_TIME_DESCRIPTION = (
    "Windows Task Scheduler daily triggers use Windows local time and follow "
    "Windows daylight-saving rules."
)


class ScheduleError(RuntimeError):
    """Raised when schedule configuration or OS scheduler operations fail."""


class SchedulerBackend(Protocol):
    def install(self, request: ScheduleRequest) -> ScheduleOperationResult:
        """Install or update the configured schedule."""

    def remove(self, *, task_name: str) -> ScheduleOperationResult:
        """Remove the configured schedule if present."""

    def status(self, *, task_name: str) -> ScheduleStatus:
        """Return scheduler status for the configured task."""


class CommandRunner(Protocol):
    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        """Run an OS command."""


@dataclass(frozen=True)
class ScheduleRequest:
    task_name: str
    time_of_day: str
    wsl_distro: str
    wsl_executable: str
    command_executable: str
    working_directory: Path
    db_path: Path
    environment: Mapping[str, str]

    @property
    def wsl_arguments(self) -> list[str]:
        env_args = [f"{key}={value}" for key, value in sorted(self.environment.items())]
        return [
            "-d",
            self.wsl_distro,
            "--cd",
            str(self.working_directory),
            "--exec",
            "env",
            *env_args,
            self.command_executable,
            "run",
        ]

    @property
    def windows_action_arguments(self) -> str:
        return subprocess.list2cmdline(self.wsl_arguments)


@dataclass(frozen=True)
class ScheduleStatus:
    backend: str
    task_name: str
    installed: bool
    timezone: str
    state: str | None = None
    last_task_result: int | None = None
    last_run_time: str | None = None
    next_run_time: str | None = None
    execute: str | None = None
    arguments: str | None = None
    message: str | None = None

    def to_mapping(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "task_name": self.task_name,
            "installed": self.installed,
            "timezone": self.timezone,
            "state": self.state,
            "last_task_result": self.last_task_result,
            "last_run_time": self.last_run_time,
            "next_run_time": self.next_run_time,
            "execute": self.execute,
            "arguments": self.arguments,
            "message": self.message,
        }


@dataclass(frozen=True)
class ScheduleOperationResult:
    backend: str
    task_name: str
    operation: str
    installed: bool
    timezone: str
    execute: str | None = None
    arguments: str | None = None
    message: str | None = None

    def to_mapping(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "task_name": self.task_name,
            "operation": self.operation,
            "installed": self.installed,
            "timezone": self.timezone,
            "execute": self.execute,
            "arguments": self.arguments,
            "message": self.message,
        }


class WindowsTaskSchedulerBackend:
    """Windows Task Scheduler backend invoked from WSL."""

    backend_name = "windows_task_scheduler"

    def __init__(
        self,
        *,
        powershell_path: str = "powershell.exe",
        runner: CommandRunner | None = None,
    ) -> None:
        self.powershell_path = powershell_path
        self._runner = runner or _run_command

    def install(self, request: ScheduleRequest) -> ScheduleOperationResult:
        script = _install_script(request)
        self._run_powershell(script)
        return ScheduleOperationResult(
            backend=self.backend_name,
            task_name=request.task_name,
            operation="installed_or_updated",
            installed=True,
            timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
            execute=request.wsl_executable,
            arguments=request.windows_action_arguments,
            message=f"Daily schedule set for {request.time_of_day} Windows local time.",
        )

    def remove(self, *, task_name: str) -> ScheduleOperationResult:
        script = _remove_script(task_name)
        payload = self._run_json_script(script)
        removed = bool(payload.get("removed", False))
        return ScheduleOperationResult(
            backend=self.backend_name,
            task_name=task_name,
            operation="removed" if removed else "not_installed",
            installed=False,
            timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
            message="Schedule removed." if removed else "Schedule was not installed.",
        )

    def status(self, *, task_name: str) -> ScheduleStatus:
        payload = self._run_json_script(_status_script(task_name))
        return ScheduleStatus(
            backend=self.backend_name,
            task_name=task_name,
            installed=bool(payload.get("installed", False)),
            timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
            state=_optional_str(payload.get("state")),
            last_task_result=_optional_int(payload.get("last_task_result")),
            last_run_time=_optional_str(payload.get("last_run_time")),
            next_run_time=_optional_str(payload.get("next_run_time")),
            execute=_optional_str(payload.get("execute")),
            arguments=_optional_str(payload.get("arguments")),
            message=_optional_str(payload.get("message")),
        )

    def _run_json_script(self, script: str) -> Mapping[str, object]:
        completed = self._run_powershell(script)
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ScheduleError("scheduler returned malformed status JSON") from exc
        if not isinstance(payload, dict):
            raise ScheduleError("scheduler returned non-object status JSON")
        return payload

    def _run_powershell(self, script: str) -> subprocess.CompletedProcess[str]:
        command = [
            self.powershell_path,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ]
        completed = self._runner(command)
        if completed.returncode != 0:
            details = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
            raise ScheduleError(f"Windows Task Scheduler command failed: {details}")
        return completed


def build_schedule_request(
    *,
    task_name: str = DEFAULT_TASK_NAME,
    time_of_day: str,
    config: AppConfig | None = None,
    wsl_distro: str | None = None,
    wsl_executable: str | None = None,
    command_executable: str | None = None,
    working_directory: Path | None = None,
) -> ScheduleRequest:
    validate_time_of_day(time_of_day)
    active_config = config or load_config()
    distro = wsl_distro or os.environ.get("WSL_DISTRO_NAME")
    if distro is None or not distro.strip():
        raise ScheduleError("WSL_DISTRO_NAME is not set; pass --distro explicitly")
    workdir = (working_directory or Path.cwd()).resolve()
    db_path = active_config.db_path
    if not db_path.is_absolute():
        db_path = (workdir / db_path).resolve()
    environment = _scheduled_environment(active_config, db_path)
    return ScheduleRequest(
        task_name=task_name,
        time_of_day=time_of_day,
        wsl_distro=distro.strip(),
        wsl_executable=wsl_executable or resolve_windows_wsl_executable(),
        command_executable=command_executable or resolve_research_digest_command(),
        working_directory=workdir,
        db_path=db_path,
        environment=environment,
    )


def select_scheduler_backend(*, backend_name: str = "auto") -> SchedulerBackend:
    if backend_name not in {"auto", "windows"}:
        raise ScheduleError("scheduler backend must be 'auto' or 'windows'")
    if backend_name == "auto" and not is_wsl():
        raise ScheduleError("automatic scheduling currently requires WSL on Windows")
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        raise ScheduleError("powershell.exe was not found; Windows Task Scheduler is unavailable")
    return WindowsTaskSchedulerBackend(powershell_path=powershell)


def resolve_research_digest_command() -> str:
    resolved = shutil.which("research-digest")
    if resolved is None:
        raise ScheduleError(
            "research-digest command was not found on PATH; install the package before "
            "installing a schedule"
        )
    return resolved


def resolve_windows_wsl_executable() -> str:
    resolved = shutil.which("wsl.exe")
    if resolved is None:
        raise ScheduleError("wsl.exe was not found; Windows Task Scheduler is unavailable")
    return _windows_path_from_wsl_path(Path(resolved))


def is_wsl() -> bool:
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return "microsoft" in release or "wsl" in release


def validate_time_of_day(value: str) -> None:
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ScheduleError("schedule time must use HH:MM 24-hour format")
    hour = int(parts[0])
    minute = int(parts[1])
    if len(parts[0]) != 2 or len(parts[1]) != 2 or hour > 23 or minute > 59:
        raise ScheduleError("schedule time must use HH:MM 24-hour format")


def _scheduled_environment(config: AppConfig, db_path: Path) -> dict[str, str]:
    values = {
        "RESEARCH_DIGEST_DB": str(db_path),
        "RESEARCH_DIGEST_ANALYZER": config.analyzer_provider,
        "OPENAI_MODEL": config.openai_model,
        "RESEARCH_DIGEST_CODEX_TIMEOUT_SECONDS": str(config.codex_timeout_seconds),
    }
    if config.codex_model is not None:
        values["RESEARCH_DIGEST_CODEX_MODEL"] = config.codex_model
    return values


def _install_script(request: ScheduleRequest) -> str:
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            (
                "$action = New-ScheduledTaskAction "
                f"-Execute {_ps_quote(request.wsl_executable)} "
                f"-Argument {_ps_quote(request.windows_action_arguments)}"
            ),
            (
                "$trigger = New-ScheduledTaskTrigger "
                f"-Daily -At {_ps_quote(request.time_of_day)}"
            ),
            "$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable",
            (
                "Register-ScheduledTask "
                f"-TaskName {_ps_quote(request.task_name)} "
                "-Action $action -Trigger $trigger -Settings $settings "
                f"-Description {_ps_quote('Run Research Digest once per day from WSL.')} "
                "-Force | Out-Null"
            ),
        ]
    )


def _remove_script(task_name: str) -> str:
    get_task = (
        f"$task = Get-ScheduledTask -TaskName {_ps_quote(task_name)} "
        "-ErrorAction SilentlyContinue"
    )
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            get_task,
            "if ($null -eq $task) { @{ removed = $false } | ConvertTo-Json -Compress; exit 0 }",
            f"Unregister-ScheduledTask -TaskName {_ps_quote(task_name)} -Confirm:$false",
            "@{ removed = $true } | ConvertTo-Json -Compress",
        ]
    )


def _status_script(task_name: str) -> str:
    get_task = (
        f"$task = Get-ScheduledTask -TaskName {_ps_quote(task_name)} "
        "-ErrorAction SilentlyContinue"
    )
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            get_task,
            (
                "if ($null -eq $task) { "
                "@{ installed = $false; message = 'Schedule is not installed.' } "
                "| ConvertTo-Json -Compress; exit 0 }"
            ),
            f"$info = Get-ScheduledTaskInfo -TaskName {_ps_quote(task_name)}",
            "$action = @($task.Actions)[0]",
            "@{",
            "  installed = $true",
            "  state = [string]$task.State",
            "  last_task_result = [int]$info.LastTaskResult",
            "  last_run_time = $info.LastRunTime.ToString('o')",
            "  next_run_time = $info.NextRunTime.ToString('o')",
            "  execute = [string]$action.Execute",
            "  arguments = [string]$action.Arguments",
            "} | ConvertTo-Json -Compress",
        ]
    )


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _windows_path_from_wsl_path(path: Path) -> str:
    text = path.as_posix()
    parts = text.split("/")
    if len(parts) >= 4 and parts[1] == "mnt" and len(parts[2]) == 1:
        drive = parts[2].upper()
        return drive + ":\\" + "\\".join(parts[3:])
    return text


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        check=False,
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except ValueError:
        return None
