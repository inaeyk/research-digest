from __future__ import annotations

import json
import os
import plistlib
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Literal
from unittest import mock

from research_digest.config import AppConfig
from research_digest.macos_launcher import (
    MACOS_BUNDLE_IDENTIFIER,
    MACOS_EXECUTABLE_NAME,
    MACOS_LAUNCHER_ID,
    MACOS_MARKER_NAME,
    MacLauncherBackend,
    MacLauncherError,
    MacLauncherRequest,
    build_macos_launcher_request,
    resolve_codex_executable,
)


def _config(
    root: Path,
    *,
    provider: Literal["codex", "openai"] = "codex",
) -> AppConfig:
    return AppConfig(
        db_path=root / "Application Support" / "digest.sqlite3",
        data_dir=root / "Application Support",
        config_dir=root / "Application Support" / "config",
        analyzer_provider=provider,
        openai_api_key="sk-secret-that-must-not-be-embedded",
        openai_model="gpt-test",
        codex_model="codex-test",
        codex_timeout_seconds=10,
        automatic_coverage_start_date=date(2026, 8, 27),
    )


class MacLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.bundle = self.root / "Applications With Spaces" / "Research Digest.app"
        self.command = self.root / "venv with spaces" / "bin" / "research-digest"
        self.codex = self.root / "node tools" / "bin" / "codex"
        self.command.parent.mkdir(parents=True)
        self.codex.parent.mkdir(parents=True)
        for executable in (self.command, self.codex):
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def request(self) -> MacLauncherRequest:
        return build_macos_launcher_request(
            config=_config(self.root),
            bundle_path=self.bundle,
            command_executable=str(self.command),
            codex_executable=str(self.codex),
        )

    def test_install_creates_valid_owned_deterministic_app_bundle(self) -> None:
        backend = MacLauncherBackend()
        request = self.request()

        first = backend.install(request)
        plist_path = self.bundle / "Contents" / "Info.plist"
        executable_path = self.bundle / "Contents" / "MacOS" / MACOS_EXECUTABLE_NAME
        marker_path = self.bundle / "Contents" / "Resources" / MACOS_MARKER_NAME
        first_plist = plist_path.read_bytes()
        first_script = executable_path.read_text(encoding="utf-8")
        second = backend.install(request)

        with plist_path.open("rb") as handle:
            plist = plistlib.load(handle)
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        self.assertEqual(plist["CFBundleIdentifier"], MACOS_BUNDLE_IDENTIFIER)
        self.assertEqual(plist["CFBundleExecutable"], MACOS_EXECUTABLE_NAME)
        self.assertEqual(marker["launcher_id"], MACOS_LAUNCHER_ID)
        self.assertEqual(first_plist, plist_path.read_bytes())
        self.assertEqual(first_script, executable_path.read_text(encoding="utf-8"))
        self.assertTrue(os.access(executable_path, os.X_OK))
        self.assertEqual(first.path, second.path)

    def test_launcher_targets_exact_entrypoint_and_captured_codex_without_shell_init(self) -> None:
        MacLauncherBackend().install(self.request())
        script = (
            self.bundle / "Contents" / "MacOS" / MACOS_EXECUTABLE_NAME
        ).read_text(encoding="utf-8")

        self.assertIn(str(self.command), script)
        self.assertIn(str(self.codex.parent), script)
        self.assertIn("launch --launcher-id", script)
        self.assertIn(MACOS_LAUNCHER_ID, script)
        self.assertNotIn(".zshrc", script)
        self.assertNotIn(".zprofile", script)
        self.assertNotIn("source ", script)
        self.assertNotIn("sk-secret", script)
        self.assertNotIn("OPENAI_API_KEY", script)
        self.assertNotIn("/opt/homebrew", script)
        self.assertNotIn("x86_64", script)
        self.assertNotIn("arm64", script)
        self.assertNotIn(" cancel ", script)
        self.assertNotIn(" schedule ", script)
        self.assertNotIn(" run >>", script)
        syntax = subprocess.run(  # noqa: S603 - fixed system shell syntax check.
            ["/bin/sh", "-n", str(self.bundle / "Contents" / "MacOS" / MACOS_EXECUTABLE_NAME)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_owned_bundle_updates_exact_executable(self) -> None:
        backend = MacLauncherBackend()
        backend.install(self.request())
        replacement = self.root / "new install" / "bin" / "research-digest"
        replacement.parent.mkdir(parents=True)
        replacement.write_text("#!/bin/sh\n", encoding="utf-8")
        replacement.chmod(0o755)
        updated = build_macos_launcher_request(
            config=_config(self.root),
            bundle_path=self.bundle,
            command_executable=str(replacement),
            codex_executable=str(self.codex),
        )

        backend.install(updated)

        script = (
            self.bundle / "Contents" / "MacOS" / MACOS_EXECUTABLE_NAME
        ).read_text(encoding="utf-8")
        self.assertIn(str(replacement), script)
        self.assertNotIn(str(self.command), script)

    def test_unrelated_bundle_is_never_overwritten_or_removed(self) -> None:
        self.bundle.mkdir(parents=True)
        unrelated = self.bundle / "unrelated.txt"
        unrelated.write_text("keep", encoding="utf-8")
        backend = MacLauncherBackend()

        with self.assertRaisesRegex(MacLauncherError, "Refusing to overwrite"):
            backend.install(self.request())
        with self.assertRaisesRegex(MacLauncherError, "Refusing to remove"):
            backend.uninstall(bundle_path=self.bundle)

        self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")

    def test_uninstall_removes_only_owned_bundle_and_is_idempotent(self) -> None:
        backend = MacLauncherBackend()
        backend.install(self.request())
        sibling = self.bundle.parent / "Other.app"
        sibling.mkdir()

        removed = backend.uninstall(bundle_path=self.bundle)
        absent = backend.uninstall(bundle_path=self.bundle)

        self.assertEqual(removed.operation, "removed")
        self.assertEqual(absent.operation, "not_installed")
        self.assertFalse(self.bundle.exists())
        self.assertTrue(sibling.exists())

    def test_missing_codex_is_actionable_for_gui_launch_environment(self) -> None:
        with mock.patch(
            "research_digest.macos_launcher.shutil.which",
            return_value=None,
        ), self.assertRaisesRegex(MacLauncherError, "install-launcher again"):
            build_macos_launcher_request(
                config=_config(self.root),
                bundle_path=self.bundle,
                command_executable=str(self.command),
            )

    def test_codex_resolution_preserves_npm_or_homebrew_shim_directory(self) -> None:
        target = self.root / "node_modules" / "codex.js"
        target.parent.mkdir()
        target.write_text("#!/usr/bin/env node\n", encoding="utf-8")
        target.chmod(0o755)
        shim = self.root / "nvm" / "bin" / "codex"
        shim.parent.mkdir(parents=True)
        shim.symlink_to(target)
        with mock.patch(
            "research_digest.macos_launcher.shutil.which",
            return_value=str(shim),
        ):
            resolved = resolve_codex_executable()
        self.assertEqual(resolved, str(shim))
        self.assertNotEqual(Path(resolved).parent, target.parent)

    def test_finder_path_executes_env_shebang_without_interactive_shell(self) -> None:
        node = self.root / "Homebrew Runtime" / "bin" / "node"
        node.parent.mkdir(parents=True)
        node.write_text(
            "#!/bin/sh\nprintf 'node-ran:%s\\n' \"$1\"\n",
            encoding="utf-8",
        )
        node.chmod(0o755)
        self.codex.write_text("#!/usr/bin/env node\n", encoding="utf-8")

        def find_runtime(name: str) -> str | None:
            return str(node) if name == "node" else None

        with mock.patch(
            "research_digest.executable_environment.shutil.which",
            side_effect=find_runtime,
        ):
            request = self.request()
        MacLauncherBackend().install(request)

        completed = subprocess.run(  # noqa: S603 - exact owned test executable.
            [str(self.codex), "--version"],
            env={"PATH": request.environment["PATH"]},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(f"node-ran:{self.codex}", completed.stdout)
        self.assertIn(str(node.parent), request.environment["PATH"].split(os.pathsep))
        script = (
            self.bundle / "Contents" / "MacOS" / MACOS_EXECUTABLE_NAME
        ).read_text(encoding="utf-8")
        self.assertIn(str(node.parent), script)

    def test_openai_launcher_does_not_require_codex_or_embed_api_key(self) -> None:
        with mock.patch("research_digest.macos_launcher.shutil.which", return_value=None):
            request = build_macos_launcher_request(
                config=_config(self.root, provider="openai"),
                bundle_path=self.bundle,
                command_executable=str(self.command),
            )
        MacLauncherBackend().install(request)
        script = (
            self.bundle / "Contents" / "MacOS" / MACOS_EXECUTABLE_NAME
        ).read_text(encoding="utf-8")
        self.assertIsNone(request.codex_executable)
        self.assertNotIn("sk-secret", script)

    def test_openai_launcher_optionally_captures_codex_for_library_features(self) -> None:
        with mock.patch(
            "research_digest.macos_launcher.shutil.which",
            return_value=str(self.codex),
        ):
            request = build_macos_launcher_request(
                config=_config(self.root, provider="openai"),
                bundle_path=self.bundle,
                command_executable=str(self.command),
            )

        self.assertEqual(request.codex_executable, str(self.codex))
        self.assertIn(str(self.codex.parent), request.environment["PATH"])


if __name__ == "__main__":
    unittest.main()
