"""Owned user-local macOS application bundle for everyday UI launching."""

from __future__ import annotations

import json
import os
import plistlib
import shlex
import shutil
import sys
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from research_digest import __version__
from research_digest.config import AppConfig, load_config
from research_digest.executable_environment import (
    ExecutableEnvironmentError,
    build_runtime_path,
)

MACOS_LAUNCHER_ID = "org.research-digest.launcher.v1"
MACOS_BUNDLE_IDENTIFIER = "org.research-digest.app"
MACOS_LAUNCHER_NAME = "Research Digest.app"
MACOS_EXECUTABLE_NAME = "research-digest-launcher"
MACOS_MARKER_NAME = "research-digest-launcher.json"
MACOS_DEFAULT_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


class MacLauncherError(RuntimeError):
    """Raised when the owned macOS app bundle cannot be managed safely."""


@dataclass(frozen=True)
class MacLauncherRequest:
    bundle_path: Path
    command_executable: str
    codex_executable: str | None
    environment: Mapping[str, str]
    log_path: Path


@dataclass(frozen=True)
class MacLauncherResult:
    operation: str
    installed: bool
    path: str
    launcher_type: str = "app_bundle"
    target: str | None = None

    def to_mapping(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "installed": self.installed,
            "path": self.path,
            "launcher_type": self.launcher_type,
            "platform": "macos",
            "target": self.target,
        }


class MacLauncherBackend:
    """Install/update/remove only the exact Research Digest-owned app bundle."""

    def install(self, request: MacLauncherRequest) -> MacLauncherResult:
        bundle = request.bundle_path.expanduser().absolute()
        if bundle.is_symlink():
            raise MacLauncherError(
                f"Refusing to replace {bundle}; launcher bundles may not be symbolic links."
            )
        if bundle.exists() and not _bundle_is_owned(bundle):
            raise MacLauncherError(
                f"Refusing to overwrite {bundle}; it is not owned by Research Digest."
            )
        bundle.parent.mkdir(parents=True, exist_ok=True)
        temporary = bundle.with_name(f".{bundle.name}.{uuid4()}.tmp")
        backup = bundle.with_name(f".{bundle.name}.{uuid4()}.backup")
        try:
            _write_bundle(temporary, request)
            if bundle.exists():
                bundle.replace(backup)
            temporary.replace(bundle)
        except BaseException:
            try:
                if backup.exists() and not bundle.exists():
                    backup.replace(bundle)
            except OSError as rollback_exc:
                raise MacLauncherError(
                    "macOS launcher update failed and exact rollback also failed."
                ) from rollback_exc
            if temporary.exists():
                with suppress(OSError):
                    shutil.rmtree(temporary)
            raise
        if backup.exists():
            # The owned launcher swap is already committed. Failure to remove
            # the hidden backup must not report activation failure while the
            # new launcher is live; a later installer run can clean it up.
            with suppress(OSError):
                shutil.rmtree(backup)
        return MacLauncherResult(
            operation="installed_or_updated",
            installed=True,
            path=str(bundle),
            target=request.command_executable,
        )

    def uninstall(self, *, bundle_path: Path | None = None) -> MacLauncherResult:
        bundle = (bundle_path or default_macos_launcher_path()).expanduser().absolute()
        if bundle.is_symlink():
            raise MacLauncherError(
                f"Refusing to remove {bundle}; launcher bundles may not be symbolic links."
            )
        if not bundle.exists():
            return MacLauncherResult(
                operation="not_installed",
                installed=False,
                path=str(bundle),
            )
        if not _bundle_is_owned(bundle):
            raise MacLauncherError(
                f"Refusing to remove {bundle}; it is not owned by Research Digest."
            )
        shutil.rmtree(bundle)
        return MacLauncherResult(
            operation="removed",
            installed=False,
            path=str(bundle),
        )


def build_macos_launcher_request(
    *,
    config: AppConfig | None = None,
    bundle_path: Path | None = None,
    command_executable: str | None = None,
    codex_executable: str | None = None,
) -> MacLauncherRequest:
    active_config = config or load_config()
    resolved_command = command_executable or resolve_research_digest_command()
    resolved_codex = codex_executable
    if resolved_codex is None:
        candidate = shutil.which("codex")
        if candidate is not None:
            resolved_codex = _validated_codex_executable(candidate)
        elif active_config.analyzer_provider == "codex":
            resolved_codex = resolve_codex_executable()
    environment = {
        "RESEARCH_DIGEST_CONFIG_DIR": str(active_config.config_dir.resolve()),
        "RESEARCH_DIGEST_DATA_DIR": str(active_config.data_dir.resolve()),
        "RESEARCH_DIGEST_DB": str(active_config.db_path.resolve()),
        "PATH": _launcher_path(
            command_executable=resolved_command,
            codex_executable=resolved_codex,
        ),
    }
    return MacLauncherRequest(
        bundle_path=bundle_path or default_macos_launcher_path(),
        command_executable=resolved_command,
        codex_executable=resolved_codex,
        environment=environment,
        log_path=active_config.data_dir.resolve() / "ui" / "macos-launcher.log",
    )


def default_macos_launcher_path() -> Path:
    return Path.home() / "Applications" / MACOS_LAUNCHER_NAME


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
    raise MacLauncherError(
        "The installed research-digest command could not be found. Install the package, "
        "then run research-digest install-launcher again."
    )


def resolve_codex_executable() -> str:
    resolved = shutil.which("codex")
    if resolved is None:
        raise MacLauncherError(
            "Codex is configured, but the codex executable was not found on PATH. Install "
            "and authenticate Codex CLI from Terminal, then run research-digest "
            "install-launcher again so Finder launches capture its exact location."
        )
    return _validated_codex_executable(resolved)


def _validated_codex_executable(resolved: str) -> str:
    # Preserve an npm/nvm or Homebrew shim path while separately resolving the
    # interpreter named by any ``/usr/bin/env`` shebang for the captured PATH.
    path = Path(resolved).expanduser().absolute()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise MacLauncherError("The resolved codex executable is not an executable file.")
    return str(path)


def _write_bundle(bundle: Path, request: MacLauncherRequest) -> None:
    executable_dir = bundle / "Contents" / "MacOS"
    resource_dir = bundle / "Contents" / "Resources"
    executable_dir.mkdir(parents=True)
    resource_dir.mkdir(parents=True)
    plist_path = bundle / "Contents" / "Info.plist"
    with plist_path.open("wb") as handle:
        plistlib.dump(_info_plist(), handle, sort_keys=True)
    executable_path = executable_dir / MACOS_EXECUTABLE_NAME
    executable_path.write_text(_launcher_script(request), encoding="utf-8")
    executable_path.chmod(0o755)
    marker = {
        "application": "research-digest",
        "bundle_identifier": MACOS_BUNDLE_IDENTIFIER,
        "command_executable": request.command_executable,
        "launcher_id": MACOS_LAUNCHER_ID,
        "version": 1,
    }
    (resource_dir / MACOS_MARKER_NAME).write_text(
        json.dumps(marker, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _info_plist() -> dict[str, object]:
    return {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": "Research Digest",
        "CFBundleExecutable": MACOS_EXECUTABLE_NAME,
        "CFBundleIdentifier": MACOS_BUNDLE_IDENTIFIER,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "Research Digest",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "LSUIElement": True,
    }


def _launcher_script(request: MacLauncherRequest) -> str:
    exports = [
        f"export {key}={shlex.quote(value)}"
        for key, value in sorted(request.environment.items())
    ]
    log_dir = shlex.quote(str(request.log_path.parent))
    log_path = shlex.quote(str(request.log_path))
    command = " ".join(
        (
            shlex.quote(request.command_executable),
            "launch",
            "--launcher-id",
            shlex.quote(MACOS_LAUNCHER_ID),
        )
    )
    return "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            *exports,
            f"mkdir -p {log_dir}",
            f"{command} >>{log_path} 2>&1",
            "exit 0",
            "",
        ]
    )


def _launcher_path(*, command_executable: str, codex_executable: str | None) -> str:
    executables = [command_executable]
    if codex_executable is not None:
        executables.insert(0, codex_executable)
    try:
        return build_runtime_path(
            executables=executables,
            default_path=MACOS_DEFAULT_PATH,
        )
    except ExecutableEnvironmentError as exc:
        raise MacLauncherError(
            f"The Finder launcher environment is incomplete: {exc} "
            "Install the required executable runtime, then run "
            "research-digest install-launcher again."
        ) from exc


def _bundle_is_owned(bundle: Path) -> bool:
    marker_path = bundle / "Contents" / "Resources" / MACOS_MARKER_NAME
    plist_path = bundle / "Contents" / "Info.plist"
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        with plist_path.open("rb") as handle:
            plist = plistlib.load(handle)
    except (OSError, ValueError, json.JSONDecodeError, plistlib.InvalidFileException):
        return False
    return bool(
        isinstance(marker, dict)
        and marker.get("launcher_id") == MACOS_LAUNCHER_ID
        and marker.get("version") == 1
        and plist.get("CFBundleIdentifier") == MACOS_BUNDLE_IDENTIFIER
        and plist.get("CFBundleExecutable") == MACOS_EXECUTABLE_NAME
    )
