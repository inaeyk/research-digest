"""Thin Windows shortcut adapter for the WSL-hosted Research Digest UI."""

from __future__ import annotations

import json
import ntpath
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from research_digest.config import AppConfig, load_config
from research_digest.errors import sanitize_error
from research_digest.executable_environment import (
    ExecutableEnvironmentError,
    build_runtime_path,
)
from research_digest.scheduler import (
    is_wsl,
    resolve_windows_wsl_executable,
)

WINDOWS_LAUNCHER_ID = "research-digest-wsl-v1"
WINDOWS_LAUNCHER_DESCRIPTION = "Research Digest Windows launcher v1"
WINDOWS_LAUNCHER_FILENAME = "Research Digest.lnk"
WINDOWS_LAUNCHER_ARGUMENT_MAX = 900
WINDOWS_LEGACY_TRUNCATED_ARGUMENT_LENGTH = 1023
WINDOWS_LAUNCHER_DEFAULT_PATH = (
    "/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin"
)

WindowsLauncherOwnership = Literal["absent", "current", "legacy_truncated", "unowned"]


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
class WindowsShortcutState:
    path: str
    exists: bool
    description: str | None = None
    target: str | None = None
    arguments: str | None = None


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
        arguments = request.windows_arguments
        if len(arguments) > WINDOWS_LAUNCHER_ARGUMENT_MAX:
            raise WindowsLauncherError(
                "Windows launcher arguments are too long to store safely "
                f"({len(arguments)} characters; maximum "
                f"{WINDOWS_LAUNCHER_ARGUMENT_MAX})."
            )
        state = _shortcut_state_from_payload(self._run_json(_inspect_launcher_script()))
        ownership = classify_windows_shortcut(state, request)
        if ownership == "unowned":
            raise WindowsLauncherError(
                "Refusing to overwrite a launcher not owned by Research Digest."
            )
        payload = self._run_json(_install_launcher_script(request, previous=state))
        path = _required_payload_string(payload, "path")
        target = _required_payload_string(payload, "target")
        stored_arguments = _required_payload_string(payload, "arguments")
        description = _required_payload_string(payload, "description")
        if (
            payload.get("installed") is not True
            or path != state.path
            or target != request.wsl_executable
            or stored_arguments != arguments
            or description != WINDOWS_LAUNCHER_DESCRIPTION
        ):
            raise WindowsLauncherError(
                "Windows launcher round-trip verification returned unexpected values."
            )
        return WindowsLauncherResult(
            operation=(
                "migrated_legacy_launcher"
                if ownership == "legacy_truncated"
                else "installed_or_updated"
            ),
            installed=True,
            path=path,
            distro=request.distro,
            target=target,
            arguments=stored_arguments,
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
    codex_executable: str | None = None,
) -> WindowsLauncherRequest:
    active_config = config or load_config()
    resolved_distro = distro or os.environ.get("WSL_DISTRO_NAME")
    if resolved_distro is None or not resolved_distro.strip():
        raise WindowsLauncherError(
            "WSL_DISTRO_NAME is not set; run from the target WSL distribution or pass --distro"
        )
    resolved_command = command_executable or resolve_research_digest_command()
    resolved_codex = codex_executable
    if resolved_codex is None:
        candidate = shutil.which("codex")
        if candidate is not None:
            resolved_codex = _validated_codex_executable(candidate)
        elif active_config.analyzer_provider == "codex":
            raise WindowsLauncherError(
                "Codex is configured, but the codex executable was not found on PATH. "
                "Install and authenticate Codex CLI inside WSL, then run "
                "research-digest install-launcher again."
            )
    else:
        resolved_codex = _validated_codex_executable(resolved_codex)
    executables = [resolved_command]
    if resolved_codex is not None:
        executables.append(resolved_codex)
    try:
        runtime_path = build_runtime_path(
            executables=executables,
            default_path=WINDOWS_LAUNCHER_DEFAULT_PATH,
        )
    except ExecutableEnvironmentError as exc:
        raise WindowsLauncherError(
            f"The non-interactive Windows launcher environment is incomplete: {exc} "
            "Install the required executable runtime, then reinstall the launcher."
        ) from exc
    environment = {
        "RESEARCH_DIGEST_CONFIG_DIR": str(active_config.config_dir.resolve()),
        "RESEARCH_DIGEST_DATA_DIR": str(active_config.data_dir.resolve()),
        "RESEARCH_DIGEST_DB": str(active_config.db_path.resolve()),
        "PATH": runtime_path,
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
        command_executable=resolved_command,
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


def _validated_codex_executable(resolved: str) -> str:
    path = Path(resolved).expanduser().absolute()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise WindowsLauncherError(
            "The resolved codex executable is not an executable file inside WSL."
        )
    return str(path)


def classify_windows_shortcut(
    state: WindowsShortcutState,
    request: WindowsLauncherRequest,
) -> WindowsLauncherOwnership:
    """Recognize current or narrowly qualified truncated historical launchers."""

    if not state.exists:
        return "absent"
    if (
        state.description != WINDOWS_LAUNCHER_DESCRIPTION
        or state.target is None
        or not _same_windows_path(state.target, request.wsl_executable)
        or state.arguments is None
    ):
        return "unowned"
    arguments = state.arguments
    command_prefix = subprocess.list2cmdline(
        ["-d", request.distro, "--exec", "env"]
    )
    current_tail = subprocess.list2cmdline(
        ["launch", "--launcher-id", WINDOWS_LAUNCHER_ID]
    )
    if arguments.startswith(command_prefix + " ") and arguments.endswith(current_tail):
        return "current"
    legacy_prefix = command_prefix + ' "PATH='
    if (
        len(arguments) == WINDOWS_LEGACY_TRUNCATED_ARGUMENT_LENGTH
        and arguments.startswith(legacy_prefix)
        and WINDOWS_LAUNCHER_ID not in arguments
    ):
        return "legacy_truncated"
    return "unowned"


def _same_windows_path(first: str, second: str) -> bool:
    return ntpath.normcase(ntpath.normpath(first)) == ntpath.normcase(
        ntpath.normpath(second)
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


def _inspect_launcher_script() -> str:
    filename = _ps_quote(WINDOWS_LAUNCHER_FILENAME)
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "$desktop = [Environment]::GetFolderPath('Desktop')",
            (
                "if ([string]::IsNullOrWhiteSpace($desktop)) { "
                "throw 'Windows Desktop path is unavailable.' }"
            ),
            f"$path = Join-Path $desktop {filename}",
            "if (-not (Test-Path -LiteralPath $path)) {",
            "  @{ path = $path; exists = $false } | ConvertTo-Json -Compress",
            "  exit 0",
            "}",
            "$shell = New-Object -ComObject WScript.Shell",
            "$shortcut = $shell.CreateShortcut($path)",
            (
                "@{ path = $path; exists = $true; description = $shortcut.Description; "
                "target = $shortcut.TargetPath; arguments = $shortcut.Arguments } | "
                "ConvertTo-Json -Compress"
            ),
        ]
    )


def _install_launcher_script(
    request: WindowsLauncherRequest,
    *,
    previous: WindowsShortcutState,
) -> str:
    filename = _ps_quote(WINDOWS_LAUNCHER_FILENAME)
    description = _ps_quote(WINDOWS_LAUNCHER_DESCRIPTION)
    target = _ps_quote(request.wsl_executable)
    arguments = _ps_quote(request.windows_arguments)
    previous_description = _ps_quote(previous.description or "")
    previous_target = _ps_quote(previous.target or "")
    previous_arguments = _ps_quote(previous.arguments or "")
    prior_check = (
        [
            "if (Test-Path -LiteralPath $path) {",
            "  throw 'Windows launcher changed during installation; retry safely.'",
            "}",
        ]
        if not previous.exists
        else [
            "if (-not (Test-Path -LiteralPath $path)) {",
            "  throw 'Windows launcher changed during installation; retry safely.'",
            "}",
            "$prior = $shell.CreateShortcut($path)",
            (
                f"if ($prior.Description -cne {previous_description} -or "
                f"$prior.TargetPath -cne {previous_target} -or "
                f"$prior.Arguments -cne {previous_arguments}) {{"
            ),
            "  throw 'Windows launcher changed during installation; retry safely.'",
            "}",
        ]
    )
    return "\n".join(
        [
            *_launcher_file_transaction_function(),
            *_launcher_roundtrip_function(),
            "$ErrorActionPreference = 'Stop'",
            f"$maximumArguments = {WINDOWS_LAUNCHER_ARGUMENT_MAX}",
            f"$expectedTarget = {target}",
            f"$expectedArguments = {arguments}",
            f"$expectedDescription = {description}",
            "if ($expectedArguments.Length -gt $maximumArguments) {",
            (
                "  throw ('Windows launcher arguments exceed the safe limit of ' + "
                "$maximumArguments + ' characters.')"
            ),
            "}",
            "$desktop = [Environment]::GetFolderPath('Desktop')",
            (
                "if ([string]::IsNullOrWhiteSpace($desktop)) { "
                "throw 'Windows Desktop path is unavailable.' }"
            ),
            f"$path = Join-Path $desktop {filename}",
            "$shell = New-Object -ComObject WScript.Shell",
            *prior_check,
            (
                "$temporary = Join-Path $desktop ('.Research Digest.' + "
                "[guid]::NewGuid().ToString('N') + '.tmp.lnk')"
            ),
            (
                "$backup = Join-Path $desktop ('.Research Digest.' + "
                "[guid]::NewGuid().ToString('N') + '.backup.lnk')"
            ),
            "try {",
            "  $shortcut = $shell.CreateShortcut($temporary)",
            "  $shortcut.TargetPath = $expectedTarget",
            "  $shortcut.Arguments = $expectedArguments",
            "  $shortcut.Description = $expectedDescription",
            "  $shortcut.WindowStyle = 7",
            "  $shortcut.Save()",
            "  if (-not (Test-Path -LiteralPath $temporary)) {",
            "    throw 'The new launcher was not written.'",
            "  }",
            (
                "  Assert-ResearchDigestLauncherRoundTrip -Shell $shell "
                "-Path $temporary -Target $expectedTarget "
                "-Arguments $expectedArguments -Description $expectedDescription"
            ),
            "}",
            "catch {",
            "  if (Test-Path -LiteralPath $temporary) {",
            (
                "    Remove-Item -LiteralPath $temporary -Force "
                "-ErrorAction SilentlyContinue"
            ),
            "  }",
            "  throw",
            "}",
            "$verify = {",
            "  param([string]$installedPath)",
            (
                "  Assert-ResearchDigestLauncherRoundTrip -Shell $shell "
                "-Path $installedPath -Target $expectedTarget "
                "-Arguments $expectedArguments -Description $expectedDescription"
            ),
            "}",
            (
                "Install-ResearchDigestLauncherFile -Candidate $temporary "
                "-Destination $path -Backup $backup -Verify $verify"
            ),
            "$installed = $shell.CreateShortcut($path)",
            (
                "@{ path = $path; installed = $true; target = $installed.TargetPath; "
                "arguments = $installed.Arguments; description = $installed.Description } | "
                "ConvertTo-Json -Compress"
            ),
        ]
    )


def _launcher_roundtrip_function() -> list[str]:
    return [
        "function Assert-ResearchDigestLauncherRoundTrip {",
        (
            "  param($Shell, [string]$Path, [string]$Target, "
            "[string]$Arguments, [string]$Description)"
        ),
        "  if (-not (Test-Path -LiteralPath $Path)) {",
        "    throw 'Windows launcher round-trip verification found no shortcut.'",
        "  }",
        "  $stored = $Shell.CreateShortcut($Path)",
        (
            "  if ($stored.TargetPath -cne $Target -or "
            "$stored.Arguments -cne $Arguments -or "
            "$stored.Description -cne $Description) {"
        ),
        "    throw 'Windows launcher round-trip verification failed.'",
        "  }",
        "}",
    ]


def _launcher_file_transaction_function() -> list[str]:
    return [
        "# BEGIN RESEARCH DIGEST LAUNCHER FILE TRANSACTION",
        "function Install-ResearchDigestLauncherFile {",
        (
            "  param([string]$Candidate, [string]$Destination, [string]$Backup, "
            "[scriptblock]$Verify)"
        ),
        "  $hadPrior = Test-Path -LiteralPath $Destination",
        "  $movedPrior = $false",
        "  $movedCandidate = $false",
        "  try {",
        "    if ($hadPrior) {",
        "      Move-Item -LiteralPath $Destination -Destination $Backup",
        "      $movedPrior = $true",
        "    }",
        "    Move-Item -LiteralPath $Candidate -Destination $Destination",
        "    $movedCandidate = $true",
        "    & $Verify $Destination",
        "  } catch {",
        "    $replacementError = $_.Exception.Message",
        "    if (Test-Path -LiteralPath $Candidate) {",
        (
            "      Remove-Item -LiteralPath $Candidate -Force "
            "-ErrorAction SilentlyContinue"
        ),
        "    }",
        "    try {",
        "      if ($movedCandidate -and (Test-Path -LiteralPath $Destination)) {",
        "        Remove-Item -LiteralPath $Destination -Force",
        "      }",
        "      if ($movedPrior -and (Test-Path -LiteralPath $Backup)) {",
        "        Move-Item -LiteralPath $Backup -Destination $Destination",
        "      }",
        "    } catch {",
        (
            "      throw ('Launcher update failed and exact rollback also failed: ' + "
            "$replacementError)"
        ),
        "    }",
        "    if ($hadPrior) {",
        (
            "      throw ('Launcher update failed; prior launcher was preserved: ' + "
            "$replacementError)"
        ),
        "    }",
        "    throw ('Launcher update failed; no launcher was installed: ' + $replacementError)",
        "  }",
        "  if (Test-Path -LiteralPath $Backup) {",
        (
            "    Remove-Item -LiteralPath $Backup -Force "
            "-ErrorAction SilentlyContinue"
        ),
        "  }",
        "}",
        "# END RESEARCH DIGEST LAUNCHER FILE TRANSACTION",
    ]


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


def _shortcut_state_from_payload(payload: Mapping[str, object]) -> WindowsShortcutState:
    path = _required_payload_string(payload, "path")
    exists = payload.get("exists")
    if not isinstance(exists, bool):
        raise WindowsLauncherError("Windows launcher inspection is missing exists")
    if not exists:
        return WindowsShortcutState(path=path, exists=False)
    values: dict[str, str] = {}
    for key in ("description", "target", "arguments"):
        value = payload.get(key)
        if not isinstance(value, str):
            raise WindowsLauncherError(
                f"Windows launcher inspection is missing {key}"
            )
        values[key] = value
    return WindowsShortcutState(
        path=path,
        exists=True,
        description=values["description"],
        target=values["target"],
        arguments=values["arguments"],
    )


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        check=False,
    )
