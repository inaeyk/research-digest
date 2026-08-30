from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast
from unittest import mock

INSTALLER_SPEC = importlib.util.spec_from_file_location(
    "install_research_digest",
    Path("installers/install_research_digest.py"),
)
assert INSTALLER_SPEC is not None and INSTALLER_SPEC.loader is not None
installer = importlib.util.module_from_spec(INSTALLER_SPEC)
sys.modules[INSTALLER_SPEC.name] = installer
INSTALLER_SPEC.loader.exec_module(installer)
TEST_WHEEL_SHA256 = "a" * 64


@contextmanager
def wsl_environment(environment: dict[str, str]) -> Iterator[None]:
    """Run one installer boundary with deterministic WSL platform selection."""

    with (
        mock.patch.dict(os.environ, environment, clear=True),
        mock.patch.object(installer.sys, "platform", "linux"),
    ):
        yield


def write_owned(path: Path, **extra: object) -> None:
    if path.name == installer.VERSION_MARKER:
        extra.setdefault("wheel_sha256", TEST_WHEEL_SHA256)
    path.write_text(
        json.dumps(
            {
                "schema_version": installer.STATE_SCHEMA,
                "owner": installer.OWNER,
                **extra,
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)


def release_assets(root: Path, content: bytes = b"qualified wheel") -> Path:
    assets = root / "release assets"
    assets.mkdir()
    wheel = assets / installer.WHEEL_NAME
    wheel.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    (assets / installer.MANIFEST_NAME).write_text(
        f"{digest}  {installer.WHEEL_NAME}\n",
        encoding="ascii",
    )
    return assets


def fake_create(root: Path, wheel_path: Path, wheel_sha256: str) -> Path:
    version_root = root / installer.VERSION
    command = version_root / "venv" / "bin" / "research-digest"
    command.parent.mkdir(parents=True)
    version_root.chmod(0o700)
    command.write_text("#!/bin/sh\n", encoding="utf-8")
    command.chmod(0o755)
    self_digest = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
    if self_digest != wheel_sha256:
        raise AssertionError("installer passed the wrong verified wheel digest")
    write_owned(
        version_root / installer.VERSION_MARKER,
        version=installer.VERSION,
        wheel_sha256=wheel_sha256,
    )
    return cast(Path, command.resolve())


class EndUserInstallerTests(unittest.TestCase):
    def prepare_owned_install(self, home: Path) -> tuple[Path, Path]:
        root = home / ".local" / "share" / "research-digest" / "runtime"
        version_root = root / "0.5.0"
        command = version_root / "venv" / "bin" / "research-digest"
        command.parent.mkdir(parents=True)
        root.chmod(0o700)
        version_root.chmod(0o700)
        command.write_text("#!/bin/sh\n", encoding="utf-8")
        command.chmod(0o755)
        write_owned(root / installer.ROOT_MARKER)
        write_owned(version_root / installer.VERSION_MARKER, version="0.5.0")
        write_owned(
            root / installer.CURRENT_STATE,
            version="0.5.0",
            command=str(command),
        )
        return root, command

    def install_with_fakes(self, home: Path, assets: Path) -> dict[str, object]:
        environment = {
            "HOME": str(home),
            "WSL_DISTRO_NAME": "Research Debian",
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_CONFIG_HOME": str(home / ".config"),
        }
        with (
            wsl_environment(environment),
            mock.patch.object(installer, "_create_versioned_runtime", side_effect=fake_create),
            mock.patch.object(
                installer,
                "verify_runtime",
                return_value={"version": "research-digest 0.5.0", "doctor_failures": 0},
            ),
            mock.patch.object(
                installer,
                "_activate_runtime",
                return_value={"status": "completed", "schedule_migrated": False},
            ),
        ):
            return cast(
                dict[str, object],
                installer.install(asset_dir=assets, distro="Research Debian"),
            )

    def test_fresh_install_is_private_preserves_data_and_source_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "User Home With Spaces"
            home.mkdir()
            assets = release_assets(Path(tmp))
            data = home / ".local" / "share" / "research-digest" / "library.bin"
            data.parent.mkdir(parents=True)
            data.write_bytes(b"\x00existing-library\xff")
            checkout = home / "researchrepo" / "research-digest" / "tests"
            checkout.mkdir(parents=True)
            source_file = checkout / "do-not-delete.txt"
            source_file.write_text("historical qualification", encoding="utf-8")

            result = self.install_with_fakes(home, assets)

            command = Path(str(result["command"]))
            self.assertEqual(
                command,
                home
                / ".local"
                / "share"
                / "research-digest"
                / "runtime"
                / "0.5.0"
                / "venv"
                / "bin"
                / "research-digest",
            )
            self.assertEqual(data.read_bytes(), b"\x00existing-library\xff")
            self.assertEqual(source_file.read_text(encoding="utf-8"), "historical qualification")

    def test_idempotent_same_version_reuses_qualified_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            home.mkdir()
            assets = release_assets(Path(tmp))
            first = self.install_with_fakes(home, assets)
            with mock.patch.object(
                installer,
                "_create_versioned_runtime",
                side_effect=AssertionError("must not replace version in place"),
            ):
                second = self.install_with_fakes(home, assets)

            self.assertEqual(first["command"], second["command"])
            self.assertTrue(second["reused"])

    def test_same_version_with_different_wheel_hash_is_not_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            home.mkdir()
            first_assets = release_assets(Path(tmp), b"first qualified wheel")
            self.install_with_fakes(home, first_assets)
            second_root = Path(tmp).resolve() / "second"
            second_root.mkdir()
            second_assets = release_assets(second_root, b"different wheel bytes")
            environment = {
                "HOME": str(home),
                "WSL_DISTRO_NAME": "Research Debian",
                "XDG_DATA_HOME": str(home / ".local" / "share"),
                "XDG_CONFIG_HOME": str(home / ".config"),
            }

            with (
                wsl_environment(environment),
                mock.patch.object(
                    installer,
                    "_activate_runtime",
                    side_effect=AssertionError("mismatched runtime must not activate"),
                ),
                self.assertRaisesRegex(installer.InstallError, "does not match"),
            ):
                installer.install(asset_dir=second_assets, distro="Research Debian")

    def test_corrupt_checksum_is_rejected_before_runtime_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            home.mkdir()
            assets = release_assets(Path(tmp), b"corrupt")
            (assets / installer.MANIFEST_NAME).write_text(
                f"{'0' * 64}  {installer.WHEEL_NAME}\n",
                encoding="ascii",
            )
            environment = {
                "HOME": str(home),
                "WSL_DISTRO_NAME": "Research Debian",
                "XDG_DATA_HOME": str(home / ".local" / "share"),
            }
            with (
                wsl_environment(environment),
                mock.patch.object(
                    installer,
                    "_create_versioned_runtime",
                    side_effect=AssertionError("checksum must fail first"),
                ),
                self.assertRaisesRegex(installer.InstallError, "SHA-256 verification failed"),
            ):
                installer.install(asset_dir=assets, distro="Research Debian")

            runtime = home / ".local" / "share" / "research-digest" / "runtime"
            self.assertFalse(runtime.exists())

    def test_failed_candidate_verification_leaves_v041_current_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            home.mkdir()
            assets = release_assets(Path(tmp))
            environment = {
                "HOME": str(home),
                "WSL_DISTRO_NAME": "Research Debian",
                "XDG_DATA_HOME": str(home / ".local" / "share"),
            }
            root = home / ".local" / "share" / "research-digest" / "runtime"
            root.mkdir(parents=True)
            root.chmod(0o700)
            write_owned(root / installer.ROOT_MARKER)
            previous_command = root / "0.4.1" / "venv" / "bin" / "research-digest"
            previous_command.parent.mkdir(parents=True)
            (root / "0.4.1").chmod(0o700)
            previous_command.write_text("working", encoding="utf-8")
            previous_command.chmod(0o755)
            write_owned(root / "0.4.1" / installer.VERSION_MARKER, version="0.4.1")
            write_owned(
                root / installer.CURRENT_STATE,
                version="0.4.1",
                command=str(previous_command),
            )
            before = (root / installer.CURRENT_STATE).read_bytes()

            with (
                wsl_environment(environment),
                mock.patch.object(
                    installer,
                    "_create_versioned_runtime",
                    side_effect=installer.InstallError(
                        "simulated candidate verification failure"
                    ),
                ),
                self.assertRaisesRegex(
                    installer.InstallError,
                    "simulated candidate verification failure",
                ),
            ):
                installer.install(asset_dir=assets, distro="Research Debian")

            self.assertEqual((root / installer.CURRENT_STATE).read_bytes(), before)
            self.assertTrue(previous_command.exists())

    def test_launcher_round_trip_failure_cannot_report_installation_completed(self) -> None:
        with (
            mock.patch.object(
                installer,
                "install",
                side_effect=installer.InstallError(
                    "Windows launcher round-trip verification failed."
                ),
            ),
            mock.patch("builtins.print") as print_output,
        ):
            exit_code = installer.main(["install"])

        self.assertEqual(exit_code, 1)
        rendered = "\n".join(
            " ".join(str(value) for value in call.args)
            for call in print_output.call_args_list
        )
        self.assertIn("round-trip verification failed", rendered)
        self.assertNotIn("installation completed", rendered.lower())

    def test_launcher_failure_leaves_new_runtime_inactive_and_data_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            home.mkdir()
            assets = release_assets(Path(tmp))
            data = home / ".local" / "share" / "research-digest" / "library.bin"
            data.parent.mkdir(parents=True)
            data.write_bytes(b"existing research data")
            environment = {
                "HOME": str(home),
                "WSL_DISTRO_NAME": "Research Debian",
                "XDG_DATA_HOME": str(home / ".local" / "share"),
                "XDG_CONFIG_HOME": str(home / ".config"),
            }

            with (
                wsl_environment(environment),
                mock.patch.object(
                    installer,
                    "_create_versioned_runtime",
                    side_effect=fake_create,
                ),
                mock.patch.object(
                    installer,
                    "verify_runtime",
                    return_value={
                        "version": "research-digest 0.5.0",
                        "doctor_failures": 0,
                    },
                ),
                mock.patch.object(
                    installer,
                    "_activate_runtime",
                    side_effect=installer.InstallError(
                        "Windows launcher round-trip verification failed."
                    ),
                ),
                self.assertRaisesRegex(installer.InstallError, "round-trip verification"),
            ):
                installer.install(asset_dir=assets, distro="Research Debian")

            runtime_root = data.parent / "runtime"
            self.assertTrue((runtime_root / "0.5.0").is_dir())
            self.assertFalse((runtime_root / installer.CURRENT_STATE).exists())
            self.assertEqual(data.read_bytes(), b"existing research data")

    def test_manifest_rejects_paths_and_duplicates(self) -> None:
        digest = "a" * 64
        with self.assertRaisesRegex(installer.InstallError, "Malformed"):
            installer.parse_sha256_manifest(f"{digest}  ../wheel.whl\n")
        with self.assertRaisesRegex(installer.InstallError, "Duplicate"):
            installer.parse_sha256_manifest(f"{digest}  wheel.whl\n{digest}  wheel.whl\n")

    def test_real_wheel_venv_is_built_at_its_final_shebang_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "private runtime with spaces"
            root.mkdir()
            assets = Path(tmp) / "assets"
            subprocess.run(
                [
                    sys.executable,
                    "scripts/build_release_assets.py",
                    "--output",
                    str(assets),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            original_run = installer._run_checked
            observed: list[Path] = []

            def run_without_dependencies(executable: Path, *arguments: str) -> object:
                values = list(arguments)
                if "install" in values:
                    values.insert(values.index("install") + 1, "--no-deps")
                return original_run(executable, *values)

            def inspect_command(command: Path) -> dict[str, object]:
                observed.append(command)
                script = command.read_text(encoding="utf-8")
                expected_python = root / "0.5.0" / "venv" / "bin" / "python"
                # pip uses a /bin/sh trampoline when the absolute shebang path
                # contains spaces, but the embedded interpreter must still be
                # the final version path rather than a renamed staging path.
                self.assertIn(str(expected_python), script)
                self.assertNotIn("installing", script)
                return {"version": "research-digest 0.5.0"}

            with (
                mock.patch.object(installer, "_run_checked", side_effect=run_without_dependencies),
                mock.patch.object(installer, "verify_runtime", side_effect=inspect_command),
            ):
                command = installer._create_versioned_runtime(
                    root=root,
                    wheel_path=assets / installer.WHEEL_NAME,
                    wheel_sha256=hashlib.sha256(
                        (assets / installer.WHEEL_NAME).read_bytes()
                    ).hexdigest(),
                )

            self.assertEqual(observed, [command])
            self.assertNotIn("installing", str(command))
            self.assertTrue((root / "0.5.0" / installer.VERSION_MARKER).exists())

    def test_self_verification_invokes_no_scientific_work(self) -> None:
        command = Path("/private/runtime/research-digest")
        calls: list[tuple[str, ...]] = []

        def completed(executable: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
            del executable
            calls.append(tuple(arguments))
            if arguments == ("--version",):
                output = "research-digest 0.5.0\n"
            elif arguments == ("doctor",):
                output = "Research Digest doctor\nFailures: 0; warnings: 6\n"
            else:
                output = '{"status":"completed","state":"stopped"}\n'
            return subprocess.CompletedProcess([], 0, output, "")

        with mock.patch.object(installer, "_run_checked", side_effect=completed):
            result = installer.verify_runtime(command)

        self.assertEqual(
            calls,
            [("--version",), ("doctor",), ("ui-status", "--json")],
        )
        self.assertEqual(result["doctor_failures"], 0)
        self.assertNotIn(("run",), calls)

    def test_normal_uninstall_removes_only_owned_runtime_and_preserves_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            home.mkdir()
            environment = {
                "HOME": str(home),
                "WSL_DISTRO_NAME": "Research Debian",
                "XDG_DATA_HOME": str(home / ".local" / "share"),
                "XDG_CONFIG_HOME": str(home / ".config"),
            }
            root = home / ".local" / "share" / "research-digest" / "runtime"
            command = root / "0.5.0" / "venv" / "bin" / "research-digest"
            command.parent.mkdir(parents=True)
            root.chmod(0o700)
            (root / "0.5.0").chmod(0o700)
            command.write_text("#!/bin/sh\n", encoding="utf-8")
            command.chmod(0o755)
            write_owned(root / installer.ROOT_MARKER)
            write_owned(root / "0.5.0" / installer.VERSION_MARKER, version="0.5.0")
            write_owned(
                root / installer.CURRENT_STATE,
                version="0.5.0",
                command=str(command),
            )
            data = root.parent / "library.bin"
            data.write_bytes(b"preserve")
            unrelated = home / "unrelated.txt"
            unrelated.write_text("untouched", encoding="utf-8")

            def cli_json(executable: Path, *arguments: str) -> dict[str, object]:
                del executable
                if arguments[:2] == ("schedule", "status"):
                    return {"installed": False}
                if arguments[:2] == ("status", "--json"):
                    return {"run_lock": None}
                raise AssertionError(arguments)

            with (
                wsl_environment(environment),
                mock.patch.object(installer, "_run_json", side_effect=cli_json),
                mock.patch.object(installer, "_run_checked") as run_checked,
            ):
                result = installer.uninstall(
                    remove_schedule=False,
                    purge_data=False,
                    confirmation=None,
                )

            self.assertTrue(result["removed"])
            self.assertFalse(root.exists())
            self.assertEqual(data.read_bytes(), b"preserve")
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "untouched")
            commands = [call.args[1:3] for call in run_checked.call_args_list]
            self.assertIn(("ui-stop", "--json"), commands)
            self.assertIn(("uninstall-launcher", "--json"), commands)

    def test_custom_database_active_run_blocks_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            home.mkdir()
            root = home / ".local" / "share" / "research-digest" / "runtime"
            command = root / "0.5.0" / "venv" / "bin" / "research-digest"
            command.parent.mkdir(parents=True)
            root.chmod(0o700)
            (root / "0.5.0").chmod(0o700)
            command.write_text("#!/bin/sh\n", encoding="utf-8")
            command.chmod(0o755)
            write_owned(root / installer.ROOT_MARKER)
            write_owned(root / "0.5.0" / installer.VERSION_MARKER, version="0.5.0")
            write_owned(
                root / installer.CURRENT_STATE,
                version="0.5.0",
                command=str(command),
            )
            custom_db = home / "databases" / "custom.sqlite3"
            custom_db.parent.mkdir()
            custom_db.write_bytes(b"exists")
            environment = {
                "HOME": str(home),
                "WSL_DISTRO_NAME": "Research Debian",
                "XDG_DATA_HOME": str(home / ".local" / "share"),
                "RESEARCH_DIGEST_DB": str(custom_db),
            }
            with (
                wsl_environment(environment),
                mock.patch.object(
                    installer,
                    "_run_json",
                    return_value={"run_lock": {"run_id": 42}},
                ) as run_json,
                mock.patch.object(installer, "_run_checked") as run_checked,
                self.assertRaisesRegex(installer.InstallError, "digest is active"),
            ):
                installer.uninstall(
                    remove_schedule=False,
                    purge_data=False,
                    confirmation=None,
                )

            run_json.assert_called_once_with(command.resolve(), "status", "--json")
            run_checked.assert_not_called()
            self.assertTrue(root.exists())

    def test_uninstall_rejects_symlinked_current_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            home.mkdir()
            root = home / ".local" / "share" / "research-digest" / "runtime"
            version_root = root / "0.5.0"
            command = version_root / "venv" / "bin" / "research-digest"
            unrelated = home / "unrelated-command"
            command.parent.mkdir(parents=True)
            root.chmod(0o700)
            version_root.chmod(0o700)
            unrelated.write_text("#!/bin/sh\n", encoding="utf-8")
            unrelated.chmod(0o755)
            command.symlink_to(unrelated)
            write_owned(root / installer.ROOT_MARKER)
            write_owned(version_root / installer.VERSION_MARKER, version="0.5.0")
            write_owned(
                root / installer.CURRENT_STATE,
                version="0.5.0",
                command=str(command),
            )
            environment = {
                "HOME": str(home),
                "WSL_DISTRO_NAME": "Research Debian",
                "XDG_DATA_HOME": str(home / ".local" / "share"),
            }

            with (
                wsl_environment(environment),
                self.assertRaisesRegex(installer.InstallError, "outside the owned runtime"),
            ):
                installer.uninstall(
                    remove_schedule=False,
                    purge_data=False,
                    confirmation=None,
                )

            self.assertTrue(unrelated.exists())
            self.assertTrue(root.exists())

    def test_uninstall_rejects_symlinked_runtime_bin_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            home.mkdir()
            root, command = self.prepare_owned_install(home)
            bin_directory = command.parent
            command.unlink()
            bin_directory.rmdir()
            outside_bin = home / "outside-bin"
            outside_bin.mkdir()
            outside_command = outside_bin / "research-digest"
            outside_command.write_text("#!/bin/sh\n", encoding="utf-8")
            outside_command.chmod(0o755)
            bin_directory.symlink_to(outside_bin, target_is_directory=True)
            environment = {
                "HOME": str(home),
                "WSL_DISTRO_NAME": "Research Debian",
                "XDG_DATA_HOME": str(home / ".local" / "share"),
            }

            with (
                wsl_environment(environment),
                mock.patch.object(installer, "_run_json") as run_json,
                self.assertRaisesRegex(installer.InstallError, "outside the owned runtime"),
            ):
                installer.uninstall(
                    remove_schedule=False,
                    purge_data=False,
                    confirmation=None,
                )

            run_json.assert_not_called()
            self.assertTrue(outside_command.exists())

    def test_uninstall_rejects_nonprivate_root_before_cli_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            home.mkdir()
            root, _ = self.prepare_owned_install(home)
            root.chmod(0o770)
            environment = {
                "HOME": str(home),
                "WSL_DISTRO_NAME": "Research Debian",
                "XDG_DATA_HOME": str(home / ".local" / "share"),
            }
            with (
                wsl_environment(environment),
                mock.patch.object(installer, "_run_json") as run_json,
                self.assertRaisesRegex(installer.InstallError, "mode 0700"),
            ):
                installer.uninstall(
                    remove_schedule=False,
                    purge_data=False,
                    confirmation=None,
                )

            run_json.assert_not_called()
            self.assertTrue(root.exists())

    def test_uninstall_rejects_symlinked_state_file_before_cli_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            home.mkdir()
            root, _ = self.prepare_owned_install(home)
            current = root / installer.CURRENT_STATE
            outside = home / "outside-state.json"
            outside.write_bytes(current.read_bytes())
            outside.chmod(0o600)
            current.unlink()
            current.symlink_to(outside)
            environment = {
                "HOME": str(home),
                "WSL_DISTRO_NAME": "Research Debian",
                "XDG_DATA_HOME": str(home / ".local" / "share"),
            }
            with (
                wsl_environment(environment),
                mock.patch.object(installer, "_run_json") as run_json,
                self.assertRaisesRegex(installer.InstallError, "symbolic link"),
            ):
                installer.uninstall(
                    remove_schedule=False,
                    purge_data=False,
                    confirmation=None,
                )

            run_json.assert_not_called()
            self.assertTrue(outside.exists())

    def test_uninstall_rejects_nonprivate_previous_state_before_cli_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            home.mkdir()
            root, command = self.prepare_owned_install(home)
            previous = root / installer.PREVIOUS_STATE
            write_owned(
                previous,
                version="0.5.0",
                command=str(command),
            )
            previous.chmod(0o666)
            environment = {
                "HOME": str(home),
                "WSL_DISTRO_NAME": "Research Debian",
                "XDG_DATA_HOME": str(home / ".local" / "share"),
            }

            with (
                wsl_environment(environment),
                mock.patch.object(installer, "_run_json") as run_json,
                self.assertRaisesRegex(installer.InstallError, "mode 0600"),
            ):
                installer.uninstall(
                    remove_schedule=False,
                    purge_data=False,
                    confirmation=None,
                )

            run_json.assert_not_called()
            self.assertTrue(root.exists())

    def test_uninstall_rejects_mismatched_version_marker_before_cli_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            home.mkdir()
            root, _ = self.prepare_owned_install(home)
            write_owned(
                root / "0.5.0" / installer.VERSION_MARKER,
                version="9.9.9",
            )
            environment = {
                "HOME": str(home),
                "WSL_DISTRO_NAME": "Research Debian",
                "XDG_DATA_HOME": str(home / ".local" / "share"),
            }
            with (
                wsl_environment(environment),
                mock.patch.object(installer, "_run_json") as run_json,
                self.assertRaisesRegex(installer.InstallError, "does not match"),
            ):
                installer.uninstall(
                    remove_schedule=False,
                    purge_data=False,
                    confirmation=None,
                )

            run_json.assert_not_called()

    def test_uninstall_rejects_unknown_runtime_entry_before_cli_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            home.mkdir()
            root, _ = self.prepare_owned_install(home)
            unknown = root / "do-not-delete.txt"
            unknown.write_text("unrelated", encoding="utf-8")
            environment = {
                "HOME": str(home),
                "WSL_DISTRO_NAME": "Research Debian",
                "XDG_DATA_HOME": str(home / ".local" / "share"),
            }
            with (
                wsl_environment(environment),
                mock.patch.object(installer, "_run_json") as run_json,
                self.assertRaisesRegex(installer.InstallError, "Unowned runtime entry"),
            ):
                installer.uninstall(
                    remove_schedule=False,
                    purge_data=False,
                    confirmation=None,
                )

            run_json.assert_not_called()
            self.assertEqual(unknown.read_text(encoding="utf-8"), "unrelated")

    def test_uninstall_rejects_group_writable_command_before_cli_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            home.mkdir()
            root, command = self.prepare_owned_install(home)
            command.chmod(0o775)
            environment = {
                "HOME": str(home),
                "WSL_DISTRO_NAME": "Research Debian",
                "XDG_DATA_HOME": str(home / ".local" / "share"),
            }
            with (
                wsl_environment(environment),
                mock.patch.object(installer, "_run_json") as run_json,
                self.assertRaisesRegex(installer.InstallError, "group/other writable"),
            ):
                installer.uninstall(
                    remove_schedule=False,
                    purge_data=False,
                    confirmation=None,
                )

            run_json.assert_not_called()
            self.assertTrue(root.exists())

    def test_destructive_purge_is_separate_confirmed_and_works_without_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            data = home / ".local" / "share" / "research-digest"
            config = home / ".config" / "research-digest"
            data.mkdir(parents=True)
            config.mkdir(parents=True)
            (data / "research_digest.sqlite3").write_bytes(b"personal database")
            (config / "config.json").write_text("{}", encoding="utf-8")
            environment = {
                "HOME": str(home),
                "WSL_DISTRO_NAME": "Research Debian",
                "XDG_DATA_HOME": str(home / ".local" / "share"),
                "XDG_CONFIG_HOME": str(home / ".config"),
            }
            with (
                wsl_environment(environment),
                self.assertRaisesRegex(installer.InstallError, "requires --confirm"),
            ):
                installer.uninstall(
                    remove_schedule=False,
                    purge_data=True,
                    confirmation="not the phrase",
                )
            self.assertTrue(data.exists())
            self.assertTrue(config.exists())

            with wsl_environment(environment):
                result = installer.uninstall(
                    remove_schedule=False,
                    purge_data=True,
                    confirmation=installer.PURGE_CONFIRMATION,
                )

            self.assertFalse(result["data_preserved"])
            self.assertFalse(data.exists())
            self.assertFalse(config.exists())

    def test_destructive_purge_removes_external_custom_database_only_when_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            data = home / ".local" / "share" / "research-digest"
            config = home / ".config" / "research-digest"
            external = home / "custom databases" / "digest.db"
            data.mkdir(parents=True)
            config.mkdir(parents=True)
            external.parent.mkdir(parents=True)
            external.write_bytes(b"database")
            external.with_name(external.name + "-wal").write_bytes(b"wal")
            external.with_name(external.name + "-shm").write_bytes(b"shm")
            external.with_name(external.name + "-journal").write_bytes(b"journal pages")
            sibling = external.parent / "keep.txt"
            sibling.write_text("unrelated", encoding="utf-8")
            environment = {
                "HOME": str(home),
                "WSL_DISTRO_NAME": "Research Debian",
                "XDG_DATA_HOME": str(home / ".local" / "share"),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "RESEARCH_DIGEST_DB": str(external),
            }

            with wsl_environment(environment):
                result = installer.uninstall(
                    remove_schedule=False,
                    purge_data=True,
                    confirmation=installer.PURGE_CONFIRMATION,
                )

            self.assertFalse(result["data_preserved"])
            self.assertFalse(external.exists())
            self.assertFalse(external.with_name(external.name + "-wal").exists())
            self.assertFalse(external.with_name(external.name + "-shm").exists())
            self.assertFalse(external.with_name(external.name + "-journal").exists())
            self.assertEqual(sibling.read_text(encoding="utf-8"), "unrelated")


if __name__ == "__main__":
    unittest.main()
