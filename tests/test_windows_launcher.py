from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import cast
from unittest import mock

from research_digest.config import AppConfig
from research_digest.windows_launcher import (
    WINDOWS_LAUNCHER_DESCRIPTION,
    WINDOWS_LAUNCHER_FILENAME,
    WINDOWS_LAUNCHER_ID,
    WindowsLauncherBackend,
    WindowsLauncherError,
    WindowsLauncherRequest,
    _launcher_file_transaction_function,
    build_windows_launcher_request,
    resolve_research_digest_command,
    run_windows_powershell,
)

WINDOWS_POWERSHELL = Path(
    "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
)


class RecordingRunner:
    def __init__(self, outputs: list[str], *, returncode: int = 0, stderr: str = "") -> None:
        self.outputs = list(outputs)
        self.returncode = returncode
        self.stderr = stderr
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command: object) -> subprocess.CompletedProcess[str]:
        values: tuple[str, ...] = tuple(cast(Sequence[str], command))
        self.commands.append(values)
        stdout = self.outputs.pop(0) if self.outputs else ""
        return subprocess.CompletedProcess(
            args=list(values),
            returncode=self.returncode,
            stdout=stdout,
            stderr=self.stderr,
        )


class WindowsLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.config = AppConfig(
            db_path=self.root / "Data Folder" / "digest.sqlite3",
            data_dir=self.root / "Data Folder",
            config_dir=self.root / "Config Folder",
            analyzer_provider="codex",
            openai_api_key="sk-never-embed-this",
            openai_model="gpt-test",
            codex_model=None,
            codex_timeout_seconds=1,
            automatic_coverage_start_date=date(2026, 8, 27),
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def request(self) -> WindowsLauncherRequest:
        return build_windows_launcher_request(
            config=self.config,
            distro="Research Ubuntu 24.04",
            wsl_executable="C:\\Windows\\System32\\wsl.exe",
            command_executable="/home/person/Research Digest/.venv/bin/research-digest",
        )

    def test_request_quotes_spaces_and_targets_discovered_distro_and_entry_point(self) -> None:
        request = self.request()

        self.assertEqual(request.distro, "Research Ubuntu 24.04")
        self.assertEqual(request.wsl_arguments[:4], ["-d", request.distro, "--exec", "env"])
        self.assertIn(
            "/home/person/Research Digest/.venv/bin/research-digest",
            request.wsl_arguments,
        )
        self.assertEqual(
            request.wsl_arguments[-3:],
            ["launch", "--launcher-id", WINDOWS_LAUNCHER_ID],
        )
        self.assertIn('"Research Ubuntu 24.04"', request.windows_arguments)
        self.assertIn(
            '"/home/person/Research Digest/.venv/bin/research-digest"',
            request.windows_arguments,
        )
        self.assertNotIn("sk-never-embed-this", request.windows_arguments)
        self.assertNotIn("OPENAI_API_KEY", request.windows_arguments)

    def test_request_uses_current_wsl_distribution_without_hard_coding_ubuntu(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "WSL_DISTRO_NAME": "Debian Research",
                "PATH": "/home/researcher/.nvm/bin:/usr/bin:/bin",
            },
            clear=True,
        ):
            request = build_windows_launcher_request(
                config=self.config,
                wsl_executable="wsl.exe",
                command_executable="/opt/research digest/bin/research-digest",
            )

        self.assertEqual(request.distro, "Debian Research")
        self.assertNotIn("Ubuntu", request.windows_arguments)
        self.assertEqual(request.environment["PATH"], "/home/researcher/.nvm/bin:/usr/bin:/bin")

    def test_missing_wsl_distribution_fails_actionably(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(WindowsLauncherError, "WSL_DISTRO_NAME"),
        ):
            build_windows_launcher_request(
                config=self.config,
                wsl_executable="wsl.exe",
                command_executable="/opt/research-digest",
            )

    def test_installed_entry_point_resolves_next_to_active_python_without_activation(self) -> None:
        bin_dir = self.root / "venv with spaces" / "bin"
        bin_dir.mkdir(parents=True)
        python = bin_dir / "python"
        command = bin_dir / "research-digest"
        python.write_text("", encoding="utf-8")
        command.write_text("#!/bin/sh\n", encoding="utf-8")
        command.chmod(0o755)
        with (
            mock.patch("research_digest.windows_launcher.sys.argv", ["python", "-m"]),
            mock.patch("research_digest.windows_launcher.sys.executable", str(python)),
            mock.patch("research_digest.windows_launcher.shutil.which", return_value=None),
        ):
            resolved = resolve_research_digest_command()

        self.assertEqual(resolved, str(command.resolve()))

    def test_install_script_is_idempotent_and_refuses_unowned_overwrite(self) -> None:
        windows_path = "C:\\Users\\Researcher\\Desktop\\Research Digest.lnk"
        runner = RecordingRunner(
            [
                f'{{"path":"{windows_path.replace(chr(92), chr(92) * 2)}","installed":true}}',
                f'{{"path":"{windows_path.replace(chr(92), chr(92) * 2)}","installed":true}}',
            ]
        )
        backend = WindowsLauncherBackend(powershell_path="powershell.exe", runner=runner)

        first = backend.install(self.request())
        second = backend.install(self.request())

        self.assertEqual(first.path, windows_path)
        self.assertEqual(second.path, windows_path)
        self.assertEqual(len(runner.commands), 2)
        script = runner.commands[0][-1]
        self.assertIn(WINDOWS_LAUNCHER_FILENAME, script)
        self.assertIn(WINDOWS_LAUNCHER_DESCRIPTION, script)
        self.assertIn(WINDOWS_LAUNCHER_ID, script)
        self.assertIn("Refusing to overwrite", script)
        self.assertIn("WindowStyle = 7", script)
        self.assertIn("Install-ResearchDigestLauncherFile", script)
        self.assertIn("Move-Item -LiteralPath $Candidate -Destination $Destination", script)
        self.assertIn("Move-Item -LiteralPath $Backup -Destination $Destination", script)
        self.assertIn("-ErrorAction SilentlyContinue", script)
        self.assertNotIn("sk-never-embed-this", script)

    @unittest.skipUnless(
        os.environ.get("RESEARCH_DIGEST_RUN_WINDOWS_NATIVE_TESTS") == "1"
        and WINDOWS_POWERSHELL.exists(),
        "requires explicitly enabled native Windows PowerShell boundary",
    )
    def test_native_launcher_file_transaction_restores_prior_file_on_swap_failure(
        self,
    ) -> None:
        function = "\n".join(_launcher_file_transaction_function())
        test_script = "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                function,
                "$root = Join-Path ([IO.Path]::GetTempPath()) "
                "('rd-launcher-test-' + [guid]::NewGuid().ToString('N'))",
                "New-Item -ItemType Directory -Path $root | Out-Null",
                "try {",
                "  $destination = Join-Path $root 'Research Digest.lnk'",
                "  $candidate = Join-Path $root 'candidate.lnk'",
                "  $backup = Join-Path $root 'backup.lnk'",
                "  [IO.File]::WriteAllText($destination, 'old launcher')",
                "  [IO.File]::WriteAllText($candidate, 'new launcher')",
                "  $script:moveCalls = 0",
                "  function Move-Item {",
                "    param([string]$LiteralPath, [string]$Destination)",
                "    $script:moveCalls += 1",
                "    if ($script:moveCalls -eq 2) { throw 'injected candidate swap failure' }",
                "    Microsoft.PowerShell.Management\\Move-Item "
                "-LiteralPath $LiteralPath -Destination $Destination",
                "  }",
                "  try {",
                "    Install-ResearchDigestLauncherFile -Candidate $candidate "
                "-Destination $destination -Backup $backup",
                "    throw 'expected launcher transaction failure'",
                "  } catch {",
                "    if ($_.Exception.Message -notlike '*prior launcher was preserved*') { throw }",
                "  }",
                "  if ([IO.File]::ReadAllText($destination) "
                "-ne 'old launcher') { throw 'prior launcher was not restored' }",
                "  if (Test-Path -LiteralPath $candidate) { throw 'candidate was not cleaned' }",
                "  Write-Output 'native launcher rollback: passed'",
                "} finally {",
                "  Microsoft.PowerShell.Management\\Remove-Item "
                "-LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue",
                "}",
            ]
        )

        completed = subprocess.run(
            [
                str(WINDOWS_POWERSHELL),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                test_script,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("native launcher rollback: passed", completed.stdout)

    def test_uninstall_checks_ownership_and_removes_only_owned_shortcut(self) -> None:
        runner = RecordingRunner(
            ['{"path":"C:\\\\Users\\\\Me\\\\Desktop\\\\Research Digest.lnk","removed":true}']
        )
        backend = WindowsLauncherBackend(powershell_path="powershell.exe", runner=runner)

        result = backend.uninstall()

        self.assertTrue(result.operation == "removed")
        script = runner.commands[0][-1]
        self.assertIn(WINDOWS_LAUNCHER_DESCRIPTION, script)
        self.assertIn(WINDOWS_LAUNCHER_ID, script)
        self.assertIn("wsl.exe", script)
        self.assertIn("Refusing to remove", script)
        self.assertIn("Remove-Item -LiteralPath $path", script)

    def test_uninstall_is_idempotent_when_launcher_is_absent(self) -> None:
        runner = RecordingRunner(
            ['{"path":"C:\\\\Users\\\\Me\\\\Desktop\\\\Research Digest.lnk","removed":false}']
        )
        result = WindowsLauncherBackend(
            powershell_path="powershell.exe",
            runner=runner,
        ).uninstall()

        self.assertEqual(result.operation, "not_installed")
        self.assertFalse(result.installed)

    def test_windows_failure_is_sanitized(self) -> None:
        runner = RecordingRunner(
            [],
            returncode=1,
            stderr="failed OPENAI_API_KEY=sk-secret123456789",
        )
        backend = WindowsLauncherBackend(powershell_path="powershell.exe", runner=runner)

        with self.assertRaises(WindowsLauncherError) as caught:
            backend.install(self.request())

        self.assertNotIn("sk-secret", str(caught.exception))
        self.assertIn("[REDACTED_API_KEY]", str(caught.exception))

    def test_windows_browser_uses_default_url_handler_and_not_hard_coded_browser(self) -> None:
        runner = RecordingRunner([""])

        run_windows_powershell(
            "Start-Process -FilePath 'http://localhost:8502'",
            powershell_path="powershell.exe",
            runner=runner,
        )

        command = runner.commands[0]
        self.assertEqual(command[0], "powershell.exe")
        self.assertIn("Start-Process", command[-1])
        self.assertIn("http://localhost:8502", command[-1])
        self.assertNotIn("chrome", command[-1].lower())


if __name__ == "__main__":
    unittest.main()
