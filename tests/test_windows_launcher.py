from __future__ import annotations

import hashlib
import json
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
from research_digest.errors import sanitize_error_text
from research_digest.windows_launcher import (
    WINDOWS_LAUNCHER_ARGUMENT_MAX,
    WINDOWS_LAUNCHER_DEFAULT_PATH,
    WINDOWS_LAUNCHER_DESCRIPTION,
    WINDOWS_LAUNCHER_FILENAME,
    WINDOWS_LAUNCHER_ID,
    WINDOWS_LEGACY_TRUNCATED_ARGUMENT_LENGTH,
    WindowsLauncherBackend,
    WindowsLauncherError,
    WindowsLauncherRequest,
    WindowsShortcutState,
    _launcher_file_transaction_function,
    _launcher_roundtrip_function,
    _round_trip_diagnostic,
    build_windows_launcher_request,
    classify_windows_shortcut,
    compare_windows_shortcut_round_trip,
    resolve_research_digest_command,
    run_windows_powershell,
)

WINDOWS_POWERSHELL = Path(
    "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
)


class RecordingRunner:
    def __init__(
        self,
        outputs: list[str],
        *,
        returncodes: list[int] | None = None,
        stderrs: list[str] | None = None,
    ) -> None:
        self.outputs = list(outputs)
        self.returncodes = list(returncodes or [])
        self.stderrs = list(stderrs or [])
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command: object) -> subprocess.CompletedProcess[str]:
        values: tuple[str, ...] = tuple(cast(Sequence[str], command))
        self.commands.append(values)
        return subprocess.CompletedProcess(
            args=list(values),
            returncode=self.returncodes.pop(0) if self.returncodes else 0,
            stdout=self.outputs.pop(0) if self.outputs else "",
            stderr=self.stderrs.pop(0) if self.stderrs else "",
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
        self.codex = self.root / "Codex Toolchain" / "bin" / "codex"
        self.codex.parent.mkdir(parents=True)
        self.codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.codex.chmod(0o755)
        self.windows_path = "C:\\Users\\Researcher\\Desktop\\Research Digest.lnk"

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def request(self) -> WindowsLauncherRequest:
        return build_windows_launcher_request(
            config=self.config,
            distro="Research Ubuntu 24.04",
            wsl_executable="C:\\Windows\\System32\\wsl.exe",
            command_executable=(
                "/home/person/.local/share/research-digest/runtime/0.4.1/venv/bin/"
                "research-digest"
            ),
            codex_executable=str(self.codex),
        )

    def actual_machine_request(self) -> WindowsLauncherRequest:
        command = (
            "/home/inaeyk/.local/share/research-digest/runtime/0.4.1/venv/bin/"
            "research-digest"
        )
        return WindowsLauncherRequest(
            distro="Ubuntu",
            wsl_executable="C:\\windows\\system32\\wsl.exe",
            command_executable=command,
            environment={
                "PATH": (
                    "/home/inaeyk/.local/share/research-digest/runtime/0.4.1/"
                    "venv/bin:/home/inaeyk/.nvm/versions/node/v22.22.2/bin:"
                    "/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin"
                ),
                "RESEARCH_DIGEST_CONFIG_DIR": "/home/inaeyk/.config/research-digest",
                "RESEARCH_DIGEST_DATA_DIR": "/home/inaeyk/.local/share/research-digest",
                "RESEARCH_DIGEST_DB": (
                    "/home/inaeyk/.local/share/research-digest/"
                    "research_digest.sqlite3"
                ),
            },
        )

    def shortcut_state(
        self,
        request: WindowsLauncherRequest,
        *,
        arguments: str | None = None,
        description: str = WINDOWS_LAUNCHER_DESCRIPTION,
        target: str | None = None,
    ) -> WindowsShortcutState:
        return WindowsShortcutState(
            path=self.windows_path,
            exists=True,
            description=description,
            target=target or request.wsl_executable,
            arguments=arguments if arguments is not None else request.windows_arguments,
        )

    def inspect_json(self, state: WindowsShortcutState) -> str:
        return json.dumps(
            {
                "path": state.path,
                "exists": state.exists,
                "description": state.description,
                "target": state.target,
                "arguments": state.arguments,
            }
        )

    def installed_json(self, request: WindowsLauncherRequest) -> str:
        return json.dumps(
            {
                "path": self.windows_path,
                "installed": True,
                "description": WINDOWS_LAUNCHER_DESCRIPTION,
                "target": request.wsl_executable,
                "arguments": request.windows_arguments,
            }
        )

    def legacy_truncated_arguments(self, request: WindowsLauncherRequest) -> str:
        historical = WindowsLauncherRequest(
            distro=request.distro,
            wsl_executable=request.wsl_executable,
            command_executable=request.command_executable,
            environment={
                "PATH": (
                    "/mnt/c/Program Files/Host Tool/bin:/mnt/c/Users/person/"
                    + "WindowsApps/"
                    + "x" * 1800
                ),
                "RESEARCH_DIGEST_CONFIG_DIR": str(self.config.config_dir),
                "RESEARCH_DIGEST_DATA_DIR": str(self.config.data_dir),
                "RESEARCH_DIGEST_DB": str(self.config.db_path),
            },
        )
        self.assertGreater(len(historical.windows_arguments), 1023)
        truncated = historical.windows_arguments[:1023]
        self.assertEqual(len(truncated), WINDOWS_LEGACY_TRUNCATED_ARGUMENT_LENGTH)
        self.assertNotIn(request.command_executable, truncated)
        self.assertNotIn(WINDOWS_LAUNCHER_ID, truncated)
        return truncated

    def test_request_quotes_spaces_and_targets_private_entry_point(self) -> None:
        request = self.request()

        self.assertEqual(request.distro, "Research Ubuntu 24.04")
        self.assertEqual(request.wsl_arguments[:4], ["-d", request.distro, "--exec", "env"])
        self.assertIn("runtime/0.4.1/venv/bin/research-digest", request.windows_arguments)
        self.assertEqual(
            request.wsl_arguments[-3:],
            ["launch", "--launcher-id", WINDOWS_LAUNCHER_ID],
        )
        self.assertIn('"Research Ubuntu 24.04"', request.windows_arguments)
        self.assertNotIn("sk-never-embed-this", request.windows_arguments)
        self.assertNotIn("OPENAI_API_KEY", request.windows_arguments)

    def test_request_uses_compact_deterministic_path_with_codex(self) -> None:
        request = self.request()
        path_entries = request.environment["PATH"].split(os.pathsep)

        self.assertIn(str(self.codex.parent), path_entries)
        self.assertIn(
            "/home/person/.local/share/research-digest/runtime/0.4.1/venv/bin",
            path_entries,
        )
        for entry in WINDOWS_LAUNCHER_DEFAULT_PATH.split(os.pathsep):
            self.assertIn(entry, path_entries)
        self.assertNotIn("/mnt/c/Program Files", request.environment["PATH"])
        self.assertLessEqual(len(request.windows_arguments), WINDOWS_LAUNCHER_ARGUMENT_MAX)

    def test_large_inherited_host_path_does_not_change_launcher(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": "/mnt/c/" + "z" * 10000}):
            request = self.request()
        baseline = self.request()

        self.assertEqual(request.environment["PATH"], baseline.environment["PATH"])
        self.assertEqual(request.windows_arguments, baseline.windows_arguments)
        self.assertNotIn("z" * 100, request.windows_arguments)

    def test_actual_machine_request_is_compact_and_exactly_reproduced(self) -> None:
        request = self.actual_machine_request()

        self.assertEqual(request.distro, "Ubuntu")
        self.assertEqual(request.wsl_executable, "C:\\windows\\system32\\wsl.exe")
        self.assertEqual(len(request.windows_arguments), 537)
        self.assertEqual(
            hashlib.sha256(request.windows_arguments.encode()).hexdigest(),
            "72e61cd413c981e17cf45ec20b7a7dde059e9280744963fbdb877ee500a23c4c",
        )
        self.assertTrue(
            request.windows_arguments.endswith(
                "launch --launcher-id research-digest-wsl-v1"
            )
        )
        self.assertIn(
            "/home/inaeyk/.nvm/versions/node/v22.22.2/bin",
            request.environment["PATH"],
        )

    def test_request_uses_current_distro_without_hard_coding_ubuntu(self) -> None:
        with mock.patch.dict(os.environ, {"WSL_DISTRO_NAME": "Debian Research"}, clear=True):
            request = build_windows_launcher_request(
                config=self.config,
                wsl_executable="wsl.exe",
                command_executable="/opt/research digest/bin/research-digest",
                codex_executable=str(self.codex),
            )

        self.assertEqual(request.distro, "Debian Research")
        self.assertNotIn("Ubuntu", request.windows_arguments)

    def test_missing_wsl_distribution_fails_actionably(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(WindowsLauncherError, "WSL_DISTRO_NAME"),
        ):
            build_windows_launcher_request(
                config=self.config,
                wsl_executable="wsl.exe",
                command_executable="/opt/research-digest",
                codex_executable=str(self.codex),
            )

    def test_installed_entry_point_resolves_next_to_active_python(self) -> None:
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

    def test_historical_1023_character_truncation_is_recognized_narrowly(self) -> None:
        request = self.request()
        truncated = self.legacy_truncated_arguments(request)
        state = self.shortcut_state(request, arguments=truncated)

        self.assertEqual(classify_windows_shortcut(state, request), "legacy_truncated")
        self.assertEqual(len(state.arguments or ""), 1023)

    def test_legacy_recognizer_refuses_wrong_description_target_or_shape(self) -> None:
        request = self.request()
        truncated = self.legacy_truncated_arguments(request)
        foreign_prefix = subprocess.list2cmdline(
            ["-d", "Other Research", "--exec", "env"]
        ) + ' "PATH='
        foreign_shape = foreign_prefix + "x" * (1023 - len(foreign_prefix))
        cases = (
            self.shortcut_state(request, arguments=truncated, description="Personal shortcut"),
            self.shortcut_state(request, arguments=truncated, target="C:\\Tools\\wsl.exe"),
            self.shortcut_state(request, arguments=foreign_shape),
            self.shortcut_state(request, arguments=truncated[:-1]),
        )

        for state in cases:
            with self.subTest(state=state):
                self.assertEqual(classify_windows_shortcut(state, request), "unowned")

    def test_same_name_unrelated_wsl_shortcut_is_refused_before_write(self) -> None:
        request = self.request()
        state = self.shortcut_state(request, arguments="-d Personal --exec /bin/true")
        runner = RecordingRunner([self.inspect_json(state)])

        with self.assertRaisesRegex(WindowsLauncherError, "not owned"):
            WindowsLauncherBackend(
                powershell_path="powershell.exe", runner=runner
            ).install(request)

        self.assertEqual(len(runner.commands), 1)

    def test_round_trip_accepts_only_windows_target_case_normalization(self) -> None:
        request = self.actual_machine_request()
        persisted = self.shortcut_state(
            request,
            target="C:\\Windows\\System32\\wsl.exe",
        )

        verification = compare_windows_shortcut_round_trip(request, persisted)

        self.assertTrue(verification.successful)
        self.assertTrue(verification.target_path_match)
        self.assertTrue(verification.arguments_match)
        self.assertEqual(verification.intended_arguments_length, 537)
        self.assertEqual(verification.persisted_arguments_length, 537)

        changed_target = compare_windows_shortcut_round_trip(
            request,
            self.shortcut_state(request, target="C:\\Tools\\wsl.exe"),
        )
        changed_description = compare_windows_shortcut_round_trip(
            request,
            self.shortcut_state(request, description="Personal WSL launcher"),
        )
        self.assertFalse(changed_target.successful)
        self.assertFalse(changed_target.target_path_match)
        self.assertFalse(changed_description.successful)
        self.assertFalse(changed_description.description_match)

    def test_round_trip_rejects_every_semantic_command_change(self) -> None:
        request = self.actual_machine_request()
        arguments = request.windows_arguments
        tampered = {
            "historical_truncation": self.legacy_truncated_arguments(request),
            "missing_launch_tail": arguments.removesuffix(
                " launch --launcher-id research-digest-wsl-v1"
            ),
            "changed_private_runtime": arguments.replace(
                "/runtime/0.4.1/", "/runtime/0.4.0/", 1
            ),
            "changed_distro": arguments.replace("-d Ubuntu", "-d Debian", 1),
            "changed_launcher_id": arguments.replace(
                "research-digest-wsl-v1", "personal-launcher", 1
            ),
            "missing_codex_path": arguments.replace(
                ":/home/inaeyk/.nvm/versions/node/v22.22.2/bin", "", 1
            ),
            "changed_required_environment": arguments.replace(
                "RESEARCH_DIGEST_CONFIG_DIR=/home/inaeyk/.config/research-digest",
                "RESEARCH_DIGEST_CONFIG_DIR=/tmp/unowned-config",
                1,
            ),
            "unexpected_extra_command": arguments + " --unexpected-content",
            "persisted_over_limit": arguments + " " + "x" * 901,
        }

        for name, persisted_arguments in tampered.items():
            with self.subTest(name=name):
                verification = compare_windows_shortcut_round_trip(
                    request,
                    self.shortcut_state(
                        request,
                        arguments=persisted_arguments,
                        target="C:\\Windows\\System32\\wsl.exe",
                    ),
                )
                self.assertFalse(verification.successful)
                self.assertFalse(verification.arguments_match)
                if name in {"historical_truncation", "persisted_over_limit"}:
                    self.assertFalse(verification.persisted_arguments_within_limit)

    def test_round_trip_diagnostic_is_structural_and_contains_no_argument_text(
        self,
    ) -> None:
        request = self.actual_machine_request()
        persisted_arguments = request.windows_arguments + " OPENAI_API_KEY=topsecret"
        verification = compare_windows_shortcut_round_trip(
            request,
            self.shortcut_state(request, arguments=persisted_arguments),
        )

        diagnostic = _round_trip_diagnostic(
            intended_arguments=request.windows_arguments,
            persisted_arguments=persisted_arguments,
            verification=verification,
        )

        for field in (
            "target_path_match=true",
            "arguments_match=false",
            "description_match=true",
            "intended_arguments_length=537",
            "persisted_arguments_length=562",
            "first_differing_index=537",
            "intended_sha256=",
            "persisted_sha256=",
            "intended_shape=",
            "persisted_shape=",
        ):
            self.assertIn(field, diagnostic)
        self.assertNotIn("OPENAI_API_KEY", diagnostic)
        self.assertNotIn("topsecret", diagnostic)
        surfaced = sanitize_error_text(
            "Windows launcher round-trip verification failed: " + diagnostic
        )
        self.assertNotIn("[truncated]", surfaced)
        self.assertIn("persisted_shape=", surfaced)

    def test_legacy_launcher_migrates_to_compact_round_trip_verified_launcher(self) -> None:
        request = self.request()
        legacy = self.shortcut_state(
            request,
            arguments=self.legacy_truncated_arguments(request),
        )
        runner = RecordingRunner([self.inspect_json(legacy), self.installed_json(request)])

        result = WindowsLauncherBackend(
            powershell_path="powershell.exe", runner=runner
        ).install(request)

        self.assertEqual(result.operation, "migrated_legacy_launcher")
        self.assertEqual(result.path, self.windows_path)
        self.assertEqual(result.arguments, request.windows_arguments)
        self.assertLessEqual(len(result.arguments or ""), WINDOWS_LAUNCHER_ARGUMENT_MAX)
        self.assertTrue((result.arguments or "").endswith(WINDOWS_LAUNCHER_ID))
        self.assertEqual(len(runner.commands), 2)
        script = runner.commands[1][-1]
        self.assertIn("Assert-ResearchDigestLauncherRoundTrip", script)
        self.assertIn("$stored.Arguments -ceq $Arguments", script)
        self.assertIn("$prior.Arguments -cne", script)

    def test_backend_accepts_native_wscript_target_path_casing(self) -> None:
        request = self.actual_machine_request()
        absent = WindowsShortcutState(path=self.windows_path, exists=False)
        payload = json.loads(self.installed_json(request))
        payload["target"] = "C:\\Windows\\System32\\wsl.exe"
        runner = RecordingRunner([self.inspect_json(absent), json.dumps(payload)])

        result = WindowsLauncherBackend(
            powershell_path="powershell.exe",
            runner=runner,
        ).install(request)

        self.assertTrue(result.installed)
        self.assertEqual(result.target, "C:\\Windows\\System32\\wsl.exe")

    def test_install_is_idempotent_and_round_trip_payload_is_exact(self) -> None:
        request = self.request()
        absent = WindowsShortcutState(path=self.windows_path, exists=False)
        current = self.shortcut_state(request)
        runner = RecordingRunner(
            [
                self.inspect_json(absent),
                self.installed_json(request),
                self.inspect_json(current),
                self.installed_json(request),
            ]
        )
        backend = WindowsLauncherBackend(powershell_path="powershell.exe", runner=runner)

        first = backend.install(request)
        second = backend.install(request)

        self.assertEqual(first.path, self.windows_path)
        self.assertEqual(second.path, self.windows_path)
        self.assertEqual(len(runner.commands), 4)
        script = runner.commands[1][-1]
        self.assertIn(WINDOWS_LAUNCHER_FILENAME, script)
        self.assertIn("WindowStyle = 7", script)
        self.assertIn("-Verify $verify", script)
        self.assertIn("Move-Item -LiteralPath $Backup -Destination $Destination", script)
        self.assertNotIn("sk-never-embed-this", script)

    def test_argument_limit_fails_before_inspection_or_write(self) -> None:
        request = self.request()
        oversized = WindowsLauncherRequest(
            distro=request.distro,
            wsl_executable=request.wsl_executable,
            command_executable=request.command_executable,
            environment={"PATH": "x" * 1000},
        )
        runner = RecordingRunner([])

        with self.assertRaisesRegex(WindowsLauncherError, "too long to store safely"):
            WindowsLauncherBackend(
                powershell_path="powershell.exe", runner=runner
            ).install(oversized)

        self.assertEqual(runner.commands, [])

    def test_round_trip_verification_failure_cannot_return_success(self) -> None:
        request = self.request()
        absent = WindowsShortcutState(path=self.windows_path, exists=False)
        runner = RecordingRunner(
            [self.inspect_json(absent), ""],
            returncodes=[0, 1],
            stderrs=["", "Windows launcher round-trip verification failed."],
        )

        with self.assertRaisesRegex(WindowsLauncherError, "round-trip verification"):
            WindowsLauncherBackend(
                powershell_path="powershell.exe", runner=runner
            ).install(request)

    def test_unexpected_readback_payload_is_rejected(self) -> None:
        request = self.request()
        absent = WindowsShortcutState(path=self.windows_path, exists=False)
        payload = json.loads(self.installed_json(request))
        payload["arguments"] = str(payload["arguments"])[:-1]
        runner = RecordingRunner([self.inspect_json(absent), json.dumps(payload)])

        with self.assertRaisesRegex(WindowsLauncherError, "unexpected values"):
            WindowsLauncherBackend(
                powershell_path="powershell.exe", runner=runner
            ).install(request)

    @unittest.skipUnless(
        os.environ.get("RESEARCH_DIGEST_RUN_WINDOWS_NATIVE_TESTS") == "1"
        and WINDOWS_POWERSHELL.exists(),
        "requires explicitly enabled native Windows PowerShell boundary",
    )
    def test_native_wscript_truncation_and_compact_round_trip(self) -> None:
        function = "\n".join(_launcher_roundtrip_function())
        request = self.actual_machine_request()
        compact = request.windows_arguments
        escaped_compact = compact.replace("'", "''")
        test_script = "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                function,
                "$unicodeShape = Get-ResearchDigestSafeArgumentShape "
                "-Value 'Sëcret秘密42' -Difference 0",
                "if ($unicodeShape -cne '@0:xxxxxxx') { "
                "throw ('unicode diagnostic masking failed: ' + $unicodeShape) }",
                "$root = Join-Path ([IO.Path]::GetTempPath()) "
                "('rd-shortcut-test-' + [guid]::NewGuid().ToString('N'))",
                "New-Item -ItemType Directory -Path $root | Out-Null",
                "try {",
                "  $shell = New-Object -ComObject WScript.Shell",
                "  $legacyPath = Join-Path $root 'legacy.lnk'",
                "  $legacy = $shell.CreateShortcut($legacyPath)",
                "  $legacy.TargetPath = 'C:\\Windows\\System32\\wsl.exe'",
                "  $legacy.Arguments = ('-d Research --exec env \"PATH=' + ('x' * 1800))",
                "  $legacy.Description = 'Research Digest Windows launcher v1'",
                "  $legacy.Save()",
                "  $storedLegacy = $shell.CreateShortcut($legacyPath)",
                "  if ($storedLegacy.Arguments.Length -ne 1023) { throw 'not truncated' }",
                "  if ($storedLegacy.Arguments -like '*research-digest-wsl-v1*') { "
                "throw 'tail survived' }",
                "  $compactPath = Join-Path $root 'compact.lnk'",
                "  $new = $shell.CreateShortcut($compactPath)",
                "  $new.TargetPath = 'C:\\windows\\system32\\wsl.exe'",
                f"  $new.Arguments = '{escaped_compact}'",
                "  $new.Description = 'Research Digest Windows launcher v1'",
                "  $new.Save()",
                "  $storedCompact = $shell.CreateShortcut($compactPath)",
                "  if ($storedCompact.TargetPath -cne "
                "'C:\\Windows\\System32\\wsl.exe') { throw 'target not canonicalized' }",
                f"  if ($storedCompact.Arguments -cne '{escaped_compact}') {{ "
                "throw 'arguments changed' }",
                "  Assert-ResearchDigestLauncherRoundTrip -Shell $shell "
                "-Path $compactPath -Target 'C:\\windows\\system32\\wsl.exe' "
                f"-Arguments '{escaped_compact}' "
                "-Description 'Research Digest Windows launcher v1' "
                "-MaximumArguments 900",
                "  try {",
                "    Assert-ResearchDigestLauncherRoundTrip -Shell $shell "
                "-Path $compactPath -Target 'C:\\windows\\system32\\wsl.exe' "
                f"-Arguments '{escaped_compact} --unexpected-content' "
                "-Description 'Research Digest Windows launcher v1' "
                "-MaximumArguments 900",
                "    throw 'expected semantic mismatch failure'",
                "  } catch {",
                "    if ($_.Exception.Message -notlike '*target_path_match=true*') { throw }",
                "    if ($_.Exception.Message -notlike '*arguments_match=false*') { throw }",
                "    if ($_.Exception.Message -notlike '*first_differing_index=*') { throw }",
                "    if ($_.Exception.Message -like '*Ubuntu*') { "
                "throw 'diagnostic exposed argument text' }",
                "  }",
                "  Write-Output 'native shortcut boundary: passed'",
                "} finally {",
                "  Remove-Item -LiteralPath $root -Recurse -Force "
                "-ErrorAction SilentlyContinue",
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
        self.assertIn("native shortcut boundary: passed", completed.stdout)

    @unittest.skipUnless(
        os.environ.get("RESEARCH_DIGEST_RUN_WINDOWS_NATIVE_TESTS") == "1"
        and WINDOWS_POWERSHELL.exists(),
        "requires explicitly enabled native Windows PowerShell boundary",
    )
    def test_native_transaction_restores_prior_shortcut_after_genuine_mismatch(
        self,
    ) -> None:
        function = "\n".join(
            [
                *_launcher_file_transaction_function(),
                *_launcher_roundtrip_function(),
            ]
        )
        arguments = self.actual_machine_request().windows_arguments.replace("'", "''")
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
                "  $shell = New-Object -ComObject WScript.Shell",
                "  $old = $shell.CreateShortcut($destination)",
                "  $old.TargetPath = 'C:\\Windows\\System32\\wsl.exe'",
                "  $old.Arguments = ('-d Ubuntu --exec env \"PATH=' + ('x' * 1800))",
                "  $old.Description = 'Research Digest Windows launcher v1'",
                "  $old.Save()",
                (
                    "  $priorBytes = [Convert]::ToBase64String("
                    "[IO.File]::ReadAllBytes($destination))"
                ),
                "  $new = $shell.CreateShortcut($candidate)",
                "  $new.TargetPath = 'C:\\windows\\system32\\wsl.exe'",
                f"  $new.Arguments = '{arguments} --unexpected-content'",
                "  $new.Description = 'Research Digest Windows launcher v1'",
                "  $new.Save()",
                "  $verify = {",
                "    param([string]$path)",
                "    Assert-ResearchDigestLauncherRoundTrip -Shell $shell "
                "-Path $path -Target 'C:\\windows\\system32\\wsl.exe' "
                f"-Arguments '{arguments}' "
                "-Description 'Research Digest Windows launcher v1' "
                "-MaximumArguments 900",
                "  }",
                "  try {",
                "    Install-ResearchDigestLauncherFile -Candidate $candidate "
                "-Destination $destination -Backup $backup -Verify $verify",
                "    throw 'expected launcher transaction failure'",
                "  } catch {",
                "    if ($_.Exception.Message -notlike '*prior launcher was preserved*') { "
                "throw }",
                "  }",
                (
                    "  $restoredBytes = [Convert]::ToBase64String("
                    "[IO.File]::ReadAllBytes($destination))"
                ),
                "  if ($restoredBytes -cne $priorBytes) { "
                "throw 'prior launcher bytes were not restored' }",
                "  $restored = $shell.CreateShortcut($destination)",
                "  if ($restored.Arguments.Length -ne 1023) { "
                "throw 'restored launcher was not the damaged historical shortcut' }",
                "  Write-Output 'native launcher rollback: passed'",
                "} finally {",
                "  Remove-Item -LiteralPath $root -Recurse -Force "
                "-ErrorAction SilentlyContinue",
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
            ['{"path":"C:\\\\Users\\\\Me\\\\Desktop\\\\Research Digest.lnk",'
             '"removed":true}']
        )
        backend = WindowsLauncherBackend(powershell_path="powershell.exe", runner=runner)

        result = backend.uninstall()

        self.assertEqual(result.operation, "removed")
        script = runner.commands[0][-1]
        self.assertIn(WINDOWS_LAUNCHER_DESCRIPTION, script)
        self.assertIn(WINDOWS_LAUNCHER_ID, script)
        self.assertIn("Refusing to remove", script)

    def test_uninstall_is_idempotent_when_launcher_is_absent(self) -> None:
        runner = RecordingRunner(
            ['{"path":"C:\\\\Users\\\\Me\\\\Desktop\\\\Research Digest.lnk",'
             '"removed":false}']
        )
        result = WindowsLauncherBackend(
            powershell_path="powershell.exe", runner=runner
        ).uninstall()

        self.assertEqual(result.operation, "not_installed")
        self.assertFalse(result.installed)

    def test_windows_failure_is_sanitized(self) -> None:
        runner = RecordingRunner(
            [""],
            returncodes=[1],
            stderrs=["failed OPENAI_API_KEY=sk-secret123456789"],
        )

        with self.assertRaises(WindowsLauncherError) as caught:
            WindowsLauncherBackend(
                powershell_path="powershell.exe", runner=runner
            ).install(self.request())

        self.assertNotIn("sk-secret", str(caught.exception))
        self.assertIn("[REDACTED_API_KEY]", str(caught.exception))

    def test_windows_browser_uses_default_url_handler(self) -> None:
        runner = RecordingRunner([""])

        run_windows_powershell(
            "Start-Process -FilePath 'http://localhost:8502'",
            powershell_path="powershell.exe",
            runner=runner,
        )

        command = runner.commands[0]
        self.assertIn("Start-Process", command[-1])
        self.assertNotIn("chrome", command[-1].lower())


if __name__ == "__main__":
    unittest.main()
