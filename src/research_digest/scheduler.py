"""OS-backed scheduling boundary for headless digest runs."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from research_digest.config import AppConfig, load_config
from research_digest.executable_environment import (
    ExecutableEnvironmentError,
    build_runtime_path,
)
from research_digest.platform_runtime import is_wsl as platform_is_wsl

DEFAULT_TASK_NAME = "Research Digest Daily"
WINDOWS_LOCAL_TIME_DESCRIPTION = (
    "Windows Task Scheduler daily triggers use Windows local time and follow "
    "Windows daylight-saving rules."
)
DEFAULT_WSL_SCHEDULE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
DEFAULT_MACOS_SCHEDULE_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
LAUNCHD_BACKEND_NAME = "launchd"
LAUNCHD_OWNER_ID = "org.research-digest.launch-agent.v1"
LAUNCHD_DEFAULT_LABEL = "org.research-digest.daily"
MACOS_LOCAL_TIME_DESCRIPTION = (
    "macOS launchd daily calendar intervals use macOS local time and follow "
    "macOS daylight-saving rules."
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
    wsl_distro: str | None
    wsl_executable: str | None
    command_executable: str
    working_directory: Path
    db_path: Path
    environment: Mapping[str, str]
    platform: str = "windows_wsl"
    launch_agent_path: Path | None = None
    launchd_label: str | None = None

    @property
    def wsl_arguments(self) -> list[str]:
        if self.wsl_distro is None:
            raise ScheduleError("Windows schedule request is missing its WSL distribution")
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

    @property
    def program_arguments(self) -> list[str]:
        return [self.command_executable, "run"]


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
    environment: Mapping[str, str] | None = None

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
        if request.platform != "windows_wsl" or request.wsl_executable is None:
            raise ScheduleError("Windows Task Scheduler received a non-Windows request")
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
        payload = self._run_json_script(_remove_script(task_name))
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


class LaunchdSchedulerBackend:
    """Owned per-user LaunchAgent backend for native macOS scheduling."""

    backend_name = LAUNCHD_BACKEND_NAME

    def __init__(
        self,
        *,
        home: Path | None = None,
        launchctl_path: str = "/bin/launchctl",
        runner: CommandRunner | None = None,
        uid: int | None = None,
    ) -> None:
        self.home = (home or Path.home()).expanduser().absolute()
        self.launchctl_path = launchctl_path
        self._runner = runner or _run_command
        self.uid = os.getuid() if uid is None else uid

    def install(self, request: ScheduleRequest) -> ScheduleOperationResult:
        if request.platform != LAUNCHD_BACKEND_NAME:
            raise ScheduleError("launchd received a non-macOS schedule request")
        path = request.launch_agent_path or self._agent_path(request.task_name)
        label = request.launchd_label or _launchd_label(request.task_name)
        if path.is_symlink():
            raise ScheduleError(
                f"Refusing to replace {path}; owned LaunchAgents may not be symbolic links."
            )
        if path.exists() and not _launchd_plist_is_owned(path, expected_label=label):
            raise ScheduleError(
                f"Refusing to overwrite {path}; it is not owned by Research Digest."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        request.working_directory.mkdir(parents=True, exist_ok=True)
        plist = _launchd_plist(request, label=label)
        previous = path.read_bytes() if path.exists() else None
        domain = f"gui/{self.uid}"
        was_loaded = previous is not None and self._job_is_loaded(
            domain=domain,
            label=label,
        )
        temporary = path.with_name(f".{path.name}.{uuid4()}.tmp")
        unloaded_previous = False
        replaced = False
        loaded_new = False
        try:
            # Complete the new artifact before changing the live old job.
            with temporary.open("wb") as handle:
                plistlib.dump(plist, handle, fmt=plistlib.FMT_XML, sort_keys=True)
            temporary.chmod(0o600)
            if was_loaded:
                self._bootout_owned_job(domain=domain, label=label, path=path)
                unloaded_previous = True
            temporary.replace(path)
            replaced = True
            self._run_required((self.launchctl_path, "bootstrap", domain, str(path)))
            loaded_new = True
            self._run_required((self.launchctl_path, "enable", f"{domain}/{label}"))
        except BaseException as exc:
            if loaded_new:
                unloaded_new = self._runner(
                    (self.launchctl_path, "bootout", domain, str(path))
                )
                if unloaded_new.returncode != 0 and self._job_is_loaded(
                    domain=domain,
                    label=label,
                ):
                    raise ScheduleError(
                        "launchd loaded the new owned Research Digest job but refused "
                        "to unload it after setup failed. The matching owned plist was "
                        f"retained at {path}; resolve the launchctl error before retrying."
                    ) from exc
            if replaced:
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    _restore_file_atomically(path, previous)
            if previous is not None and was_loaded and unloaded_previous:
                restored = self._runner(
                    (self.launchctl_path, "bootstrap", domain, str(path))
                )
                if restored.returncode == 0:
                    self._run_allowing_failure(
                        (self.launchctl_path, "enable", f"{domain}/{label}")
                    )
            raise
        finally:
            temporary.unlink(missing_ok=True)
        return ScheduleOperationResult(
            backend=self.backend_name,
            task_name=request.task_name,
            operation="installed_or_updated",
            installed=True,
            timezone=MACOS_LOCAL_TIME_DESCRIPTION,
            execute=request.command_executable,
            arguments=subprocess.list2cmdline(request.program_arguments[1:]),
            message=f"Daily schedule set for {request.time_of_day} macOS local time.",
        )

    def remove(self, *, task_name: str) -> ScheduleOperationResult:
        path = self._agent_path(task_name)
        if not path.exists():
            return ScheduleOperationResult(
                backend=self.backend_name,
                task_name=task_name,
                operation="not_installed",
                installed=False,
                timezone=MACOS_LOCAL_TIME_DESCRIPTION,
                message="Schedule was not installed.",
            )
        label = _launchd_label(task_name)
        if path.is_symlink():
            raise ScheduleError(
                f"Refusing to remove {path}; owned LaunchAgents may not be symbolic links."
            )
        if not _launchd_plist_is_owned(path, expected_label=label):
            raise ScheduleError(
                f"Refusing to remove {path}; it is not owned by Research Digest."
            )
        self._bootout_owned_job(
            domain=f"gui/{self.uid}",
            label=label,
            path=path,
        )
        path.unlink()
        return ScheduleOperationResult(
            backend=self.backend_name,
            task_name=task_name,
            operation="removed",
            installed=False,
            timezone=MACOS_LOCAL_TIME_DESCRIPTION,
            message="Schedule removed.",
        )

    def status(self, *, task_name: str) -> ScheduleStatus:
        path = self._agent_path(task_name)
        label = _launchd_label(task_name)
        if not path.exists():
            return ScheduleStatus(
                backend=self.backend_name,
                task_name=task_name,
                installed=False,
                timezone=MACOS_LOCAL_TIME_DESCRIPTION,
                message="Schedule is not installed.",
            )
        if not _launchd_plist_is_owned(path, expected_label=label):
            raise ScheduleError(
                f"LaunchAgent path {path} exists but is not owned by Research Digest."
            )
        plist = _read_launchd_plist(path)
        completed = self._runner(
            (self.launchctl_path, "print", f"gui/{self.uid}/{label}")
        )
        loaded = completed.returncode == 0
        arguments = plist.get("ProgramArguments")
        environment = plist.get("EnvironmentVariables")
        program_args = (
            [str(value) for value in arguments]
            if isinstance(arguments, list)
            else []
        )
        safe_environment = (
            {str(key): str(value) for key, value in environment.items()}
            if isinstance(environment, dict)
            else None
        )
        return ScheduleStatus(
            backend=self.backend_name,
            task_name=task_name,
            installed=True,
            timezone=MACOS_LOCAL_TIME_DESCRIPTION,
            state="enabled" if loaded else "disabled",
            execute=program_args[0] if program_args else None,
            arguments=(
                subprocess.list2cmdline(program_args[1:]) if len(program_args) > 1 else ""
            ),
            environment=safe_environment,
            message=None if loaded else "LaunchAgent is installed but not loaded.",
        )

    def _agent_path(self, task_name: str) -> Path:
        return self.home / "Library" / "LaunchAgents" / f"{_launchd_label(task_name)}.plist"

    def _run_required(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        completed = self._runner(command)
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
            raise ScheduleError(f"launchd command failed: {detail}")
        return completed

    def _run_allowing_failure(self, command: Sequence[str]) -> None:
        self._runner(command)

    def _job_is_loaded(self, *, domain: str, label: str) -> bool:
        return (
            self._runner(
                (self.launchctl_path, "print", f"{domain}/{label}")
            ).returncode
            == 0
        )

    def _bootout_owned_job(self, *, domain: str, label: str, path: Path) -> None:
        completed = self._runner((self.launchctl_path, "bootout", domain, str(path)))
        if completed.returncode == 0:
            return
        inspection = self._runner(
            (self.launchctl_path, "print", f"{domain}/{label}")
        )
        if inspection.returncode == 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
            raise ScheduleError(
                "launchd refused to unload the exact owned Research Digest job; "
                f"the LaunchAgent was left unchanged: {detail}"
            )


def build_schedule_request(
    *,
    task_name: str = DEFAULT_TASK_NAME,
    time_of_day: str,
    config: AppConfig | None = None,
    wsl_distro: str | None = None,
    wsl_executable: str | None = None,
    command_executable: str | None = None,
    working_directory: Path | None = None,
    platform: str | None = None,
    launch_agent_path: Path | None = None,
) -> ScheduleRequest:
    validate_time_of_day(time_of_day)
    active_config = config or load_config()
    selected = platform or (
        "windows_wsl"
        if wsl_distro is not None or wsl_executable is not None
        else LAUNCHD_BACKEND_NAME if sys.platform == "darwin" else "windows_wsl"
    )
    workdir = (
        working_directory
        or (active_config.data_dir if selected == LAUNCHD_BACKEND_NAME else Path.cwd())
    ).resolve()
    db_path = active_config.db_path
    if not db_path.is_absolute():
        db_path = (workdir / db_path).resolve()
    resolved_command = command_executable or resolve_research_digest_command()
    environment = _scheduled_environment(
        active_config,
        db_path,
        command_executable=resolved_command,
        platform=selected,
    )
    if selected == LAUNCHD_BACKEND_NAME:
        label = _launchd_label(task_name)
        return ScheduleRequest(
            task_name=task_name,
            time_of_day=time_of_day,
            wsl_distro=None,
            wsl_executable=None,
            command_executable=resolved_command,
            working_directory=workdir,
            db_path=db_path,
            environment=environment,
            platform=LAUNCHD_BACKEND_NAME,
            launch_agent_path=(
                launch_agent_path
                or Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
            ),
            launchd_label=label,
        )
    if selected != "windows_wsl":
        raise ScheduleError(f"unsupported schedule request platform {selected!r}")
    distro = wsl_distro or os.environ.get("WSL_DISTRO_NAME")
    if distro is None or not distro.strip():
        raise ScheduleError("WSL_DISTRO_NAME is not set; pass --distro explicitly")
    return ScheduleRequest(
        task_name=task_name,
        time_of_day=time_of_day,
        wsl_distro=distro.strip(),
        wsl_executable=wsl_executable or resolve_windows_wsl_executable(),
        command_executable=resolved_command,
        working_directory=workdir,
        db_path=db_path,
        environment=environment,
    )


def select_scheduler_backend(*, backend_name: str = "auto") -> SchedulerBackend:
    if backend_name not in {"auto", "windows", LAUNCHD_BACKEND_NAME}:
        raise ScheduleError("scheduler backend must be 'auto', 'windows', or 'launchd'")
    if backend_name == LAUNCHD_BACKEND_NAME or (
        backend_name == "auto" and sys.platform == "darwin"
    ):
        launchctl = "/bin/launchctl"
        if not Path(launchctl).exists():
            resolved_launchctl = shutil.which("launchctl")
            if resolved_launchctl is None:
                raise ScheduleError("launchctl was not found; macOS scheduling is unavailable")
            launchctl = resolved_launchctl
        return LaunchdSchedulerBackend(launchctl_path=launchctl)
    if backend_name == "auto" and not is_wsl():
        raise ScheduleError("automatic scheduling requires Windows/WSL or macOS")
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


def resolve_codex_executable() -> str:
    resolved = shutil.which("codex")
    if resolved is None:
        raise ScheduleError(
            "Codex analyzer is configured, but the codex executable was not found on PATH. "
            "Install Codex CLI and sign in with ChatGPT before installing the schedule."
        )
    return resolved


def resolve_windows_wsl_executable() -> str:
    resolved = shutil.which("wsl.exe")
    if resolved is None:
        raise ScheduleError("wsl.exe was not found; Windows Task Scheduler is unavailable")
    return _windows_path_from_wsl_path(Path(resolved))


def is_wsl() -> bool:
    return platform_is_wsl()


def validate_time_of_day(value: str) -> None:
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ScheduleError("schedule time must use HH:MM 24-hour format")
    hour = int(parts[0])
    minute = int(parts[1])
    if len(parts[0]) != 2 or len(parts[1]) != 2 or hour > 23 or minute > 59:
        raise ScheduleError("schedule time must use HH:MM 24-hour format")


def _scheduled_environment(
    config: AppConfig,
    db_path: Path,
    *,
    command_executable: str,
    platform: str,
) -> dict[str, str]:
    values = {
        "RESEARCH_DIGEST_DB": str(db_path),
        "RESEARCH_DIGEST_CONFIG_DIR": str(config.config_dir),
        "RESEARCH_DIGEST_DATA_DIR": str(config.data_dir),
        "RESEARCH_DIGEST_ANALYZER": config.analyzer_provider,
        "OPENAI_MODEL": config.openai_model,
        "RESEARCH_DIGEST_CODEX_TIMEOUT_SECONDS": str(config.codex_timeout_seconds),
    }
    if config.codex_model is not None:
        values["RESEARCH_DIGEST_CODEX_MODEL"] = config.codex_model
    try:
        codex_executable = resolve_codex_executable()
    except ScheduleError:
        if config.analyzer_provider == "codex":
            raise
        codex_executable = None
    if codex_executable is not None:
        values["PATH"] = _schedule_path_with_codex(
            codex_executable,
            command_executable=command_executable,
            platform=platform,
        )
    return values


def scheduler_codex_path_warning(config: AppConfig, status: ScheduleStatus) -> str | None:
    if not status.installed:
        return None
    current_codex = shutil.which("codex")
    if current_codex is None:
        if config.analyzer_provider != "codex":
            return None
        return (
            "Schedule is installed, but the current interactive environment cannot resolve "
            "`codex`; reinstall after Codex CLI is available on PATH."
        )
    current_dir = Path(current_codex).parent.as_posix()
    if status.environment is not None:
        scheduled_path = status.environment.get("PATH")
    elif status.arguments is not None:
        scheduled_path = _scheduled_env_value(status.arguments, "PATH")
    else:
        return (
            "Schedule is installed, but its action arguments are unavailable; reinstall the "
            "schedule if scheduled Codex runs cannot find `codex`."
        )
    if scheduled_path is None:
        return (
            "Schedule is installed, but its action does not set PATH for Codex; reinstall "
            "the schedule to capture the current Codex executable directory."
        )
    if current_dir not in scheduled_path.split(os.pathsep):
        return (
            "Schedule is installed, but its Codex PATH does not include the current Codex "
            f"directory {current_dir}; reinstall the schedule to refresh the runtime path."
        )
    return None


def _schedule_path_with_codex(
    codex_executable: str,
    *,
    command_executable: str = "research-digest",
    platform: str = "windows_wsl",
) -> str:
    defaults = (
        DEFAULT_MACOS_SCHEDULE_PATH
        if platform == LAUNCHD_BACKEND_NAME
        else DEFAULT_WSL_SCHEDULE_PATH
    )
    try:
        return build_runtime_path(
            executables=(codex_executable, command_executable),
            default_path=defaults,
        )
    except ExecutableEnvironmentError as exc:
        raise ScheduleError(
            f"The non-interactive scheduler environment is incomplete: {exc} "
            "Install the required executable runtime, then reinstall the schedule."
        ) from exc


def _launchd_label(task_name: str) -> str:
    if task_name == DEFAULT_TASK_NAME:
        return LAUNCHD_DEFAULT_LABEL
    digest = hashlib.sha256(task_name.encode("utf-8")).hexdigest()[:12]
    return f"org.research-digest.daily.{digest}"


def _restore_file_atomically(path: Path, content: bytes) -> None:
    restore = path.with_name(f".{path.name}.{uuid4()}.restore")
    try:
        restore.write_bytes(content)
        restore.chmod(0o600)
        restore.replace(path)
    finally:
        restore.unlink(missing_ok=True)


def _launchd_plist(request: ScheduleRequest, *, label: str) -> dict[str, object]:
    hour_text, minute_text = request.time_of_day.split(":", 1)
    log_path = request.working_directory / "scheduler.log"
    return {
        "EnvironmentVariables": dict(sorted(request.environment.items())),
        "Label": label,
        "ProcessType": "Background",
        "ProgramArguments": request.program_arguments,
        "ResearchDigestOwner": LAUNCHD_OWNER_ID,
        "ResearchDigestTaskName": request.task_name,
        "RunAtLoad": False,
        "StandardErrorPath": str(log_path),
        "StandardOutPath": str(log_path),
        "StartCalendarInterval": {
            "Hour": int(hour_text),
            "Minute": int(minute_text),
        },
        "WorkingDirectory": str(request.working_directory),
    }


def _read_launchd_plist(path: Path) -> Mapping[str, object]:
    try:
        with path.open("rb") as handle:
            payload = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise ScheduleError(f"LaunchAgent plist is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise ScheduleError(f"LaunchAgent plist is not a dictionary: {path}")
    return payload


def _launchd_plist_is_owned(path: Path, *, expected_label: str) -> bool:
    try:
        payload = _read_launchd_plist(path)
    except ScheduleError:
        return False
    return bool(
        payload.get("ResearchDigestOwner") == LAUNCHD_OWNER_ID
        and payload.get("Label") == expected_label
    )


def _scheduled_env_value(arguments: str, key: str) -> str | None:
    prefix = f"{key}="
    start = arguments.find(prefix)
    if start < 0:
        return None
    value_start = start + len(prefix)
    if start > 0 and arguments[start - 1] == '"':
        value_end = arguments.find('"', value_start)
        if value_end < 0:
            return arguments[value_start:]
        return arguments[value_start:value_end]
    value_end = arguments.find(" ", value_start)
    if value_end < 0:
        return arguments[value_start:]
    return arguments[value_start:value_end]


def _install_script(request: ScheduleRequest) -> str:
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            (
                "$action = New-ScheduledTaskAction "
                f"-Execute {_ps_quote(request.wsl_executable or '')} "
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
            "  last_task_result = [int64]$info.LastTaskResult",
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
