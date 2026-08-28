"""Owned private-runtime activation for end-user wheel installations."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from research_digest import __version__
from research_digest.automation import install_or_update_schedule
from research_digest.config import AppConfig
from research_digest.launcher import (
    LauncherResult,
    MacLauncherController,
    install_launcher,
)
from research_digest.scheduler import (
    DEFAULT_TASK_NAME,
    LAUNCHD_BACKEND_NAME,
    SchedulerBackend,
    ScheduleStatus,
    TransactionalSchedulerBackend,
    select_scheduler_backend,
)
from research_digest.windows_launcher import WindowsLauncherController

RUNTIME_OWNER_ID = "org.research-digest.private-runtime.v1"
RUNTIME_STATE_SCHEMA = 1
RUNTIME_ROOT_MARKER = ".research-digest-runtime-root.json"
RUNTIME_VERSION_MARKER = ".research-digest-runtime.json"
CURRENT_RUNTIME_STATE = "current.json"
PREVIOUS_RUNTIME_STATE = "previous.json"
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DistributionError(RuntimeError):
    """Raised when a private runtime cannot be activated safely."""


@dataclass(frozen=True)
class RuntimeRecord:
    version: str
    command: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": RUNTIME_STATE_SCHEMA,
            "owner": RUNTIME_OWNER_ID,
            "version": self.version,
            "command": self.command,
        }


@dataclass(frozen=True)
class DistributionActivationResult:
    runtime_root: str
    version: str
    command: str
    launcher: LauncherResult
    schedule_migrated: bool
    schedule_enabled: bool | None
    schedule_time: str | None
    previous: RuntimeRecord | None

    def to_mapping(self) -> dict[str, object]:
        return {
            "runtime_root": self.runtime_root,
            "version": self.version,
            "command": self.command,
            "launcher": self.launcher.to_mapping(),
            "schedule_migrated": self.schedule_migrated,
            "schedule_enabled": self.schedule_enabled,
            "schedule_time": self.schedule_time,
            "previous": self.previous.to_mapping() if self.previous is not None else None,
        }


def activate_distribution(
    *,
    config: AppConfig,
    runtime_root: Path,
    version: str,
    command_executable: Path,
    distro: str | None = None,
    scheduler_backend: SchedulerBackend | None = None,
    windows_launcher_backend: WindowsLauncherController | None = None,
    macos_launcher_backend: MacLauncherController | None = None,
    platform: str | None = None,
) -> DistributionActivationResult:
    """Repoint owned launch surfaces and declare one verified private runtime current."""

    selected_platform = platform or sys.platform
    root = _validate_runtime_root(config=config, runtime_root=runtime_root)
    command = _validate_runtime_command(
        runtime_root=root,
        version=version,
        command_executable=command_executable,
    )
    selected_backend = scheduler_backend or select_scheduler_backend()
    if not isinstance(selected_backend, TransactionalSchedulerBackend):
        raise DistributionError(
            "Selected scheduler backend cannot snapshot and restore exact state."
        )
    backend = selected_backend
    schedule = backend.status(task_name=DEFAULT_TASK_NAME)
    _validate_schedule_for_migration(schedule)
    schedule_snapshot = (
        backend.snapshot(task_name=DEFAULT_TASK_NAME) if schedule.installed else None
    )
    schedule_enabled = _schedule_is_enabled(schedule) if schedule.installed else None
    previous = read_runtime_record(root / CURRENT_RUNTIME_STATE)
    state_snapshot = {
        name: _snapshot_state_file(root / name)
        for name in (CURRENT_RUNTIME_STATE, PREVIOUS_RUNTIME_STATE)
    }
    schedule_migrated = False
    try:
        if schedule.installed:
            assert schedule.time_of_day is not None
            assert schedule_snapshot is not None
            _replace_schedule(
                schedule=schedule,
                config=config,
                backend=backend,
                command_executable=str(command),
                enabled=bool(schedule_enabled),
                loaded=schedule_snapshot.loaded,
                distro=distro,
                selected_platform=selected_platform,
            )
            schedule_migrated = True

        current = RuntimeRecord(version=version, command=str(command))
        if previous is not None and previous != current:
            _atomic_json(root / PREVIOUS_RUNTIME_STATE, previous.to_mapping())
        _atomic_json(root / CURRENT_RUNTIME_STATE, current.to_mapping())

        # Install the launcher last. Both platform backends replace their exact
        # owned artifact atomically, so no failure-prone activation work follows
        # a successful launcher replacement.
        launcher = install_launcher(
            config=config,
            distro=distro,
            windows_backend=windows_launcher_backend,
            macos_backend=macos_launcher_backend,
            platform=selected_platform,
            command_executable=str(command),
        )
    except BaseException as exc:
        rollback_errors: list[str] = []
        if schedule_migrated:
            assert schedule_snapshot is not None
            try:
                backend.restore(schedule_snapshot)
            except BaseException as rollback_exc:
                rollback_errors.append(f"schedule: {type(rollback_exc).__name__}")
        for name, snapshot in state_snapshot.items():
            try:
                _restore_state_file(root / name, snapshot)
            except BaseException as rollback_exc:
                rollback_errors.append(f"{name}: {type(rollback_exc).__name__}")
        if rollback_errors:
            raise DistributionError(
                "Private runtime activation failed and rollback was incomplete ("
                + ", ".join(rollback_errors)
                + "). The verified new runtime was retained; inspect launcher, schedule, "
                "and runtime state before retrying."
            ) from exc
        raise
    return DistributionActivationResult(
        runtime_root=str(root),
        version=version,
        command=str(command),
        launcher=launcher,
        schedule_migrated=schedule_migrated,
        schedule_enabled=schedule_enabled,
        schedule_time=schedule.time_of_day,
        previous=previous,
    )


def read_runtime_record(path: Path) -> RuntimeRecord | None:
    if not path.exists():
        return None
    payload = _read_owned_mapping(path)
    version = payload.get("version")
    command = payload.get("command")
    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
        raise DistributionError(f"Runtime state has an invalid version: {path}")
    if not isinstance(command, str) or not Path(command).is_absolute():
        raise DistributionError(f"Runtime state has an invalid command: {path}")
    return RuntimeRecord(version=version, command=command)


def _validate_runtime_root(*, config: AppConfig, runtime_root: Path) -> Path:
    if runtime_root.is_symlink():
        raise DistributionError("Private runtime root may not be a symbolic link.")
    expected = (config.data_dir / "runtime").resolve()
    requested = runtime_root.expanduser().resolve()
    if requested != expected:
        raise DistributionError(
            f"Private runtime root must be the application-owned path {expected}."
        )
    _validate_private_directory(requested)
    marker = requested / RUNTIME_ROOT_MARKER
    _read_owned_mapping(marker)
    return requested


def _validate_runtime_command(
    *,
    runtime_root: Path,
    version: str,
    command_executable: Path,
) -> Path:
    if version != __version__ or _VERSION.fullmatch(version) is None:
        raise DistributionError(
            f"Activation version {version!r} does not match installed version {__version__}."
        )
    version_root = runtime_root / version
    if version_root.is_symlink():
        raise DistributionError("Versioned runtime directory may not be a symbolic link.")
    _validate_private_directory(version_root)
    environment = version_root / "venv"
    if environment.is_symlink():
        raise DistributionError("Private virtual environment may not be a symbolic link.")
    bin_directory = environment / "bin"
    if bin_directory.is_symlink():
        raise DistributionError("Private runtime bin directory may not be a symbolic link.")
    version_payload = _read_owned_mapping(version_root / RUNTIME_VERSION_MARKER)
    wheel_sha256 = version_payload.get("wheel_sha256")
    if (
        version_payload.get("version") != version
        or not isinstance(wheel_sha256, str)
        or _SHA256.fullmatch(wheel_sha256) is None
    ):
        raise DistributionError("Versioned runtime ownership marker does not match.")
    if not command_executable.is_absolute():
        raise DistributionError("Private runtime command must be an absolute path.")
    try:
        command = command_executable.resolve(strict=True)
        expected_path = bin_directory / "research-digest"
        if command_executable.is_symlink() or expected_path.is_symlink():
            raise DistributionError("Private runtime command may not be a symbolic link.")
        expected = expected_path.resolve(strict=True)
    except OSError as exc:
        raise DistributionError("Private runtime command does not exist.") from exc
    if (
        command != expected
        or not command.is_relative_to(version_root.resolve(strict=True))
        or not command.is_file()
        or not os.access(command, os.X_OK)
    ):
        raise DistributionError(
            "Private runtime command must be the executable owned by the versioned runtime."
        )
    metadata = command.stat()
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o022:
        raise DistributionError(
            "Private runtime command must belong to the current user and not be "
            "group/other writable."
        )
    return command


def _validate_schedule_for_migration(schedule: ScheduleStatus) -> None:
    if not schedule.installed:
        return
    if schedule.owned is not True:
        raise DistributionError(
            "Refusing to migrate a scheduler artifact without verified Research Digest "
            "ownership."
        )
    if schedule.time_of_day is None:
        raise DistributionError(
            "Installed schedule has no recoverable daily time; it was left unchanged."
        )
    if (
        schedule.command_executable is None
        or not Path(schedule.command_executable).is_absolute()
    ):
        raise DistributionError(
            "Installed schedule has no recoverable runtime command; it was left unchanged."
        )


def _schedule_is_enabled(schedule: ScheduleStatus) -> bool:
    state = (schedule.state or "").strip().lower()
    return state not in {"disabled", "unloaded"}


def _replace_schedule(
    *,
    schedule: ScheduleStatus,
    config: AppConfig,
    backend: SchedulerBackend,
    command_executable: str,
    enabled: bool,
    loaded: bool | None,
    distro: str | None,
    selected_platform: str,
) -> None:
    assert schedule.time_of_day is not None
    install_or_update_schedule(
        time_of_day=schedule.time_of_day,
        config=config,
        scheduler_backend=backend,
        task_name=DEFAULT_TASK_NAME,
        wsl_distro=distro,
        command_executable=command_executable,
        enabled=enabled,
        loaded=loaded,
        platform=(
            LAUNCHD_BACKEND_NAME if selected_platform == "darwin" else "windows_wsl"
        ),
    )


def _snapshot_state_file(path: Path) -> tuple[bytes, int] | None:
    if path.is_symlink():
        raise DistributionError(f"Runtime state may not be a symbolic link: {path}")
    if not path.exists():
        return None
    try:
        _validate_private_file(path)
        return path.read_bytes(), path.stat().st_mode & 0o777
    except OSError as exc:
        raise DistributionError(f"Runtime state could not be snapshotted: {path}") from exc


def _restore_state_file(path: Path, snapshot: tuple[bytes, int] | None) -> None:
    if path.is_symlink():
        raise DistributionError(f"Runtime state may not be a symbolic link: {path}")
    if snapshot is None:
        path.unlink(missing_ok=True)
        return
    content, mode = snapshot
    temporary = path.with_name(f".{path.name}.{uuid4()}.rollback")
    try:
        temporary.write_bytes(content)
        temporary.chmod(mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_owned_mapping(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise DistributionError(f"Owned runtime state may not be a symbolic link: {path}")
    _validate_private_file(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DistributionError(f"Owned runtime state is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise DistributionError(f"Owned runtime state is not an object: {path}")
    if (
        payload.get("schema_version") != RUNTIME_STATE_SCHEMA
        or payload.get("owner") != RUNTIME_OWNER_ID
    ):
        raise DistributionError(f"Runtime state is not owned by Research Digest: {path}")
    return payload


def _validate_private_directory(path: Path) -> None:
    try:
        metadata = path.stat()
    except OSError as exc:
        raise DistributionError(f"Owned runtime directory is unavailable: {path}") from exc
    if not path.is_dir() or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise DistributionError(
            f"Owned runtime directory must belong to the current user with mode 0700: {path}"
        )


def _validate_private_file(path: Path) -> None:
    try:
        metadata = path.stat()
    except OSError as exc:
        raise DistributionError(f"Owned runtime state is unavailable: {path}") from exc
    if not path.is_file() or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise DistributionError(
            f"Owned runtime state must belong to the current user with mode 0600: {path}"
        )


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    if path.is_symlink():
        raise DistributionError(f"Refusing to replace symbolic-link runtime state: {path}")
    temporary = path.with_name(f".{path.name}.{uuid4()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
