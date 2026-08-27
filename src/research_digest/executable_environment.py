"""Deterministic non-interactive PATH support for installed executable shims."""

from __future__ import annotations

import os
import shlex
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path


class ExecutableEnvironmentError(RuntimeError):
    """Raised when an executable's declared interpreter cannot be resolved."""


ExecutableFinder = Callable[[str], str | None]


def executable_runtime_directories(
    executable: str,
    *,
    finder: ExecutableFinder | None = None,
) -> list[str]:
    """Return the executable directory plus any required shebang interpreter directory."""

    active_finder = finder or shutil.which
    candidate = Path(executable).expanduser()
    if candidate.is_absolute() or candidate.parent != Path("."):
        path = candidate.absolute()
    else:
        resolved_executable = active_finder(executable)
        if resolved_executable is None:
            return []
        path = Path(resolved_executable).expanduser().absolute()
    directories = [str(path.parent)]
    shebang = _read_shebang(path)
    if shebang is None:
        return directories
    try:
        parts = shlex.split(shebang)
    except ValueError as exc:
        raise ExecutableEnvironmentError(
            f"Executable has an invalid shebang: {path}"
        ) from exc
    if not parts:
        return directories
    interpreter = Path(parts[0])
    if interpreter.name != "env":
        if interpreter.is_absolute():
            directories.append(str(interpreter.parent))
        return _deduplicate(directories)
    command = _env_shebang_command(parts[1:])
    if command is None:
        raise ExecutableEnvironmentError(
            f"Executable uses /usr/bin/env without an interpreter command: {path}"
        )
    resolved = active_finder(command)
    if resolved is None:
        raise ExecutableEnvironmentError(
            f"Executable {path} requires {command!r}, but it was not found on PATH."
        )
    resolved_path = Path(resolved).expanduser().absolute()
    if not resolved_path.is_file() or not os.access(resolved_path, os.X_OK):
        raise ExecutableEnvironmentError(
            f"Executable {path} requires {command!r}, but its resolved path is not executable."
        )
    directories.append(str(resolved_path.parent))
    return _deduplicate(directories)


def build_runtime_path(
    *,
    executables: Iterable[str],
    default_path: str,
    finder: ExecutableFinder | None = None,
) -> str:
    directories: list[str] = []
    for executable in executables:
        directories.extend(
            executable_runtime_directories(executable, finder=finder)
        )
    directories.extend(default_path.split(os.pathsep))
    return os.pathsep.join(_deduplicate(directories))


def _read_shebang(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            first_line = handle.readline(4096)
    except OSError:
        return None
    if not first_line.startswith(b"#!"):
        return None
    try:
        return first_line[2:].decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise ExecutableEnvironmentError(
            f"Executable has a non-UTF-8 shebang: {path}"
        ) from exc


def _env_shebang_command(arguments: list[str]) -> str | None:
    index = 0
    while index < len(arguments):
        value = arguments[index]
        if value == "-S":
            index += 1
            if index >= len(arguments):
                return None
            split = shlex.split(arguments[index])
            return split[0] if split else None
        if value.startswith("-") or "=" in value:
            index += 1
            continue
        return value
    return None


def _deduplicate(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
