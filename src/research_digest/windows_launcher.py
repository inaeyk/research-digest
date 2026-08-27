"""Thin Windows shortcut adapter for the WSL-hosted Research Digest UI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from research_digest.config import AppConfig, load_config
from research_digest.errors import sanitize_error
from research_digest.scheduler import (
    is_wsl,
    resolve_windows_wsl_executable,
)

WINDOWS_LAUNCHER_ID = "research-digest-wsl-v1"
WINDOWS_LAUNCHER_DESCRIPTION = "Research Digest Windows launcher v1"
WINDOWS_LAUNCHER_FILENAME = "Research Digest.lnk"


class WindowsLauncherError(RuntimeError):
    """Raised when the owned Windows launcher cannot be managed safely."""


class WindowsCommandRunner(Protocol):
    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        """Execute one Windows-boundary command."""


@dataclass(frozen=True)
class WindowsLauncherRequest:
    distro: str
    wsl_executable: str
    command_executable: str
    environment: Mapping[str, str]

    @property
    def wsl_arguments(self) -> list[str]:
        environment = [f"{key}={value}" for key, value in sorted(self.environment.items())]
        return [
            "-d",
            self.distro,
            "--exec",
            "env",
            *environment,
            self.command_executable,
            "launch",
            "--launcher-id",
            WINDOWS_LAUNCHER_ID,
        ]

    @property
    def windows_arguments(self) -> str:
        return subprocess.list2cmdline(self.wsl_arguments)


@dataclass(frozen=True)
class WindowsLauncherResult:
    operation: str
    installed: bool
    path: str | None
    distro: str | None = None
    target: str | None = None
    arguments: str | None = None

    def to_mapping(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "installed": self.installed,
            "path": self.path,
            "distro": self.distro,
            "target": self.target,
            "arguments": self.arguments,
        }


class WindowsLauncherController(Protocol):
    def install(self, request: WindowsLauncherRequest) -> WindowsLauncherResult:
        """Install or update the owned Windows launcher."""

    def uninstall(self) -> WindowsLauncherResult:
        """Remove the owned Windows launcher if present."""


class WindowsLauncherBackend:
    """Create and remove only the exact Research Digest-owned desktop shortcut."""

    def __init__(
        self,
        *,
        powershell_path: str | None = None,
        runner: WindowsCommandRunner | None = None,
    ) -> None:
        self.powershell_path = powershell_path or resolve_windows_powershell()
        self._runner = runner or _run_command

    def install(self, request: WindowsLauncherRequest) -> WindowsLauncherResult:
        payload = self._run_json(_install_launcher_script(request))
        return WindowsLauncherResult(
            operation="installed_or_updated",
            installed=True,
            path=_required_payload_string(payload, "path"),
            distro=request.distro,
            target=request.wsl_executable,
            arguments=request.windows_arguments,
        )

    def uninstall(self) -> WindowsLauncherResult:
        payload = self._run_json(_uninstall_launcher_script())
        removed = bool(payload.get("removed", False))
        path = payload.get("path")
        return WindowsLauncherResult(
            operation="removed" if removed else "not_installed",
            installed=False,
            path=str(path) if isinstance(path, str) else None,
        )

    def _run_json(self, script: str) -> Mapping[str, object]:
        completed = self._run(script)
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise WindowsLauncherError("Windows launcher returned malformed JSON") from exc
        if not isinstance(payload, dict):
            raise WindowsLauncherError("Windows launcher returned non-object JSON")
        return payload

    def _run(self, script: str) -> subprocess.CompletedProcess[str]:
        command = _powershell_command(self.powershell_path, script)
        completed = self._runner(command)
        if completed.returncode != 0:
            details = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
            raise WindowsLauncherError(
                f"Windows launcher command failed: {sanitize_error(details)}"
            )
        return completed


def build_windows_launcher_request(
    *,
    config: AppConfig | None = None,
    distro: str | None = None,
    wsl_executable: str | None = None,
    command_executable: str | None = None,
) -> WindowsLauncherRequest:
    active_config = config or load_config()
    resolved_distro = distro or os.environ.get("WSL_DISTRO_NAME")
    if resolved_distro is None or not resolved_distro.strip():
        raise WindowsLauncherError(
            "WSL_DISTRO_NAME is not set; run from the target WSL distribution or pass --distro"
        )
    environment = {
        "RESEARCH_DIGEST_CONFIG_DIR": str(active_config.config_dir.resolve()),
        "RESEARCH_DIGEST_DATA_DIR": str(active_config.data_dir.resolve()),
        "RESEARCH_DIGEST_DB": str(active_config.db_path.resolve()),
    }
    try:
        resolved_wsl_executable = wsl_executable or resolve_windows_wsl_executable()
    except Exception as exc:
        raise WindowsLauncherError(
            "wsl.exe was not found; the Windows launcher boundary is unavailable"
        ) from exc
    return WindowsLauncherRequest(
        distro=resolved_distro.strip(),
        wsl_executable=resolved_wsl_executable,
        command_executable=command_executable or resolve_research_digest_command(),
        environment=environment,
    )


def select_windows_launcher_backend() -> WindowsLauncherBackend:
    if not is_wsl():
        raise WindowsLauncherError("Windows launcher installation must run from WSL")
    return WindowsLauncherBackend()


def resolve_research_digest_command() -> str:
    candidates: list[Path] = []
    invoked = Path(sys.argv[0]).expanduser()
    if invoked.name == "research-digest" and (
        invoked.is_absolute() or invoked.parent != Path(".")
    ):
        candidates.append(invoked)
    resolved = shutil.which("research-digest")
    if resolved is not None:
        candidates.append(Path(resolved))
    candidates.append(Path(sys.executable).with_name("research-digest"))
    for candidate in candidates:
        try:
            absolute = candidate.resolve(strict=True)
        except OSError:
            continue
        if absolute.is_file() and os.access(absolute, os.X_OK):
            return str(absolute)
    raise WindowsLauncherError(
        "The installed research-digest command could not be found; install the package "
        "before installing the Windows launcher"
    )


def resolve_windows_powershell() -> str:
    resolved = shutil.which("powershell.exe")
    if resolved is None:
        raise WindowsLauncherError(
            "powershell.exe was not found; the Windows browser/launcher boundary is unavailable"
        )
    return resolved


def run_windows_powershell(
    script: str,
    *,
    powershell_path: str | None = None,
    runner: WindowsCommandRunner | None = None,
) -> subprocess.CompletedProcess[str]:
    command = _powershell_command(powershell_path or resolve_windows_powershell(), script)
    completed = (runner or _run_command)(command)
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        raise WindowsLauncherError(
            f"Windows command failed: {sanitize_error(details)}"
        )
    return completed


def _powershell_command(powershell_path: str, script: str) -> list[str]:
    return [
        powershell_path,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
    ]


def _install_launcher_script(request: WindowsLauncherRequest) -> str:
    filename = _ps_quote(WINDOWS_LAUNCHER_FILENAME)
    description = _ps_quote(WINDOWS_LAUNCHER_DESCRIPTION)
    marker = _ps_quote(WINDOWS_LAUNCHER_ID)
    target = _ps_quote(request.wsl_executable)
    arguments = _ps_quote(request.windows_arguments)
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "$desktop = [Environment]::GetFolderPath('Desktop')",
            (
                "if ([string]::IsNullOrWhiteSpace($desktop)) { "
                "throw 'Windows Desktop path is unavailable.' }"
            ),
            f"$path = Join-Path $desktop {filename}",
            "$shell = New-Object -ComObject WScript.Shell",
            "if (Test-Path -LiteralPath $path) {",
            "  $existing = $shell.CreateShortcut($path)",
            (
                f"  if ($existing.Description -ne {description} -or "
                f"$existing.Arguments -notlike ('*' + {marker} + '*') -or "
                "[IO.Path]::GetFileName($existing.TargetPath) -ine 'wsl.exe') {"
            ),
            "    throw 'Refusing to overwrite a launcher not owned by Research Digest.'",
            "  }",
            "}",
            "$shortcut = $shell.CreateShortcut($path)",
            f"$shortcut.TargetPath = {target}",
            f"$shortcut.Arguments = {arguments}",
            f"$shortcut.Description = {description}",
            "$shortcut.WindowStyle = 7",
            "$shortcut.Save()",
            "@{ path = $path; installed = $true } | ConvertTo-Json -Compress",
        ]
    )


def _uninstall_launcher_script() -> str:
    filename = _ps_quote(WINDOWS_LAUNCHER_FILENAME)
    description = _ps_quote(WINDOWS_LAUNCHER_DESCRIPTION)
    marker = _ps_quote(WINDOWS_LAUNCHER_ID)
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "$desktop = [Environment]::GetFolderPath('Desktop')",
            (
                "if ([string]::IsNullOrWhiteSpace($desktop)) { "
                "throw 'Windows Desktop path is unavailable.' }"
            ),
            f"$path = Join-Path $desktop {filename}",
            (
                "if (-not (Test-Path -LiteralPath $path)) { "
                "@{ path = $path; removed = $false } | ConvertTo-Json -Compress; exit 0 }"
            ),
            "$shell = New-Object -ComObject WScript.Shell",
            "$existing = $shell.CreateShortcut($path)",
            (
                f"if ($existing.Description -ne {description} -or "
                f"$existing.Arguments -notlike ('*' + {marker} + '*') -or "
                "[IO.Path]::GetFileName($existing.TargetPath) -ine 'wsl.exe') {"
            ),
            "  throw 'Refusing to remove a launcher not owned by Research Digest.'",
            "}",
            "Remove-Item -LiteralPath $path -Force",
            "@{ path = $path; removed = $true } | ConvertTo-Json -Compress",
        ]
    )


def _required_payload_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise WindowsLauncherError(f"Windows launcher response is missing {key}")
    return value


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        check=False,
    )
