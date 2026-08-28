"""Platform-dispatched desktop launcher installation boundary."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Protocol, TypeAlias

from research_digest.config import AppConfig
from research_digest.macos_launcher import (
    MacLauncherBackend,
    MacLauncherRequest,
    MacLauncherResult,
    build_macos_launcher_request,
)
from research_digest.platform_runtime import is_wsl
from research_digest.windows_launcher import (
    WindowsLauncherController,
    WindowsLauncherResult,
    build_windows_launcher_request,
    select_windows_launcher_backend,
)

LauncherResult: TypeAlias = WindowsLauncherResult | MacLauncherResult


class MacLauncherController(Protocol):
    def install(self, request: MacLauncherRequest) -> MacLauncherResult:
        """Install/update the owned app bundle."""

    def uninstall(self, *, bundle_path: Path | None = None) -> MacLauncherResult:
        """Remove only the owned app bundle."""


class LauncherPlatformError(RuntimeError):
    """Raised for unsupported launcher installation platforms."""


def install_launcher(
    *,
    config: AppConfig | None,
    distro: str | None = None,
    windows_backend: WindowsLauncherController | None = None,
    macos_backend: MacLauncherController | None = None,
    platform: str | None = None,
    command_executable: str | None = None,
) -> LauncherResult:
    selected = platform or sys.platform
    if selected == "darwin":
        macos_request = build_macos_launcher_request(
            config=config,
            command_executable=command_executable,
        )
        return (macos_backend or MacLauncherBackend()).install(macos_request)
    if selected.startswith("linux") and (is_wsl() or windows_backend is not None):
        windows_request = build_windows_launcher_request(
            config=config,
            distro=distro,
            command_executable=command_executable,
        )
        return (windows_backend or select_windows_launcher_backend()).install(windows_request)
    raise LauncherPlatformError(
        "Launcher installation is supported on macOS and on Windows through WSL."
    )


def uninstall_launcher(
    *,
    windows_backend: WindowsLauncherController | None = None,
    macos_backend: MacLauncherController | None = None,
    platform: str | None = None,
) -> LauncherResult:
    selected = platform or sys.platform
    if selected == "darwin":
        return (macos_backend or MacLauncherBackend()).uninstall()
    if selected.startswith("linux") and (is_wsl() or windows_backend is not None):
        return (windows_backend or select_windows_launcher_backend()).uninstall()
    raise LauncherPlatformError(
        "Launcher removal is supported on macOS and on Windows through WSL."
    )
