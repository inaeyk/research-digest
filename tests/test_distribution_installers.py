from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

WINDOWS_POWERSHELL = Path(
    "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
)


class MacDistributionInstallerTests(unittest.TestCase):
    def make_command(self, path: Path, body: str) -> None:
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o755)

    def run_installer(
        self,
        root: Path,
        *,
        valid_fallback: bool,
        override: Path | None = None,
        corrupt: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        commands = root / "fake commands"
        commands.mkdir()
        log = root / "python.log"
        core = b"print('verified installer core')\n"
        digest = hashlib.sha256(core).hexdigest()
        if corrupt:
            digest = "0" * 64
        manifest = f"{digest}  install-research-digest.py\n"
        self.make_command(commands / "uname", "printf 'Darwin\\n'\n")
        self.make_command(
            commands / "curl",
            (
                "output=''\n"
                "while [ \"$#\" -gt 0 ]; do\n"
                "  if [ \"$1\" = '--output' ]; then output=$2; shift 2; continue; fi\n"
                "  url=$1; shift\n"
                "done\n"
                "case \"$url\" in\n"
                f"  */SHA256SUMS) printf '%s' '{manifest}' > \"$output\" ;;\n"
                "  */install-research-digest.py) "
                f"printf '%s\\n' \"{core.decode().strip()}\" > \"$output\" ;;\n"
                "  */research_digest-0.4.1-py3-none-any.whl) "
                "printf '%s' 'wheel' > \"$output\" ;;\n"
                "  *) exit 3 ;;\n"
                "esac\n"
            ),
        )
        self.make_command(
            commands / "python3",
            "if [ \"${1:-}\" = '-c' ]; then printf '3.10.9\\n'; exit 1; fi\nexit 9\n",
        )
        for name in ("python3.14", "python3.13", "python3.11"):
            self.make_command(
                commands / name,
                (
                    "if [ \"${1:-}\" = '-c' ]; then "
                    "printf '3.10.9\\n'; exit 1; fi\nexit 9\n"
                ),
            )
        fallback_body = (
            "if [ \"${1:-}\" = '-c' ]; then printf '3.12.13\\n'; exit 0; fi\n"
            f"printf '%s\\n' \"$*\" >> '{log}'\n"
        )
        if not valid_fallback:
            fallback_body = (
                "if [ \"${1:-}\" = '-c' ]; then printf '3.10.9\\n'; exit 1; fi\n"
                "exit 9\n"
            )
        self.make_command(commands / "python3.12", fallback_body)
        environment = dict(os.environ)
        environment["PATH"] = f"{commands}:{environment['PATH']}"
        if override is not None:
            environment["RESEARCH_DIGEST_PYTHON"] = str(override)
        script = Path("installers/install-research-digest-macos.sh").resolve()
        return subprocess.run(
            ["/bin/sh", str(script), "install"],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_old_default_python_uses_compatible_versioned_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            completed = self.run_installer(root, valid_fallback=True)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Using Python 3.12.13", completed.stdout)
            self.assertIn("install", (root / "python.log").read_text(encoding="utf-8"))

    def test_explicit_interpreter_override_and_paths_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            override = root / "Compatible Python With Spaces"
            log = root / "override.log"
            self.make_command(
                override,
                (
                    "if [ \"${1:-}\" = '-c' ]; then printf '3.11.9\\n'; exit 0; fi\n"
                    f"printf '%s\\n' \"$*\" > '{log}'\n"
                ),
            )
            completed = self.run_installer(
                root,
                valid_fallback=False,
                override=override,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Using Python 3.11.9", completed.stdout)
            self.assertTrue(log.exists())

    def test_unsupported_python_fails_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            completed = self.run_installer(
                root,
                valid_fallback=False,
                override=root / "fake commands" / "python3",
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn("requires Python 3.11 or newer", completed.stderr)
            self.assertFalse((root / "python.log").exists())

    def test_corrupt_installer_checksum_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            completed = self.run_installer(root, valid_fallback=True, corrupt=True)

            self.assertEqual(completed.returncode, 1)
            self.assertIn("SHA-256 verification failed", completed.stderr)
            self.assertFalse((root / "python.log").exists())


class WindowsDistributionInstallerTests(unittest.TestCase):
    def discovery_script(self) -> str:
        text = Path("installers/install-research-digest-windows.ps1").read_text(
            encoding="utf-8"
        )
        return text.split("$DiscoveryScript = @'\n", maxsplit=1)[1].split(
            "\n'@",
            maxsplit=1,
        )[0]

    def make_command(self, path: Path, body: str) -> None:
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o755)

    def installer_environment_function(self) -> str:
        text = Path("installers/install-research-digest-windows.ps1").read_text(
            encoding="utf-8"
        )
        return text.split(
            "# BEGIN RESEARCH DIGEST INSTALLER ENVIRONMENT\n",
            maxsplit=1,
        )[1].split(
            "\n# END RESEARCH DIGEST INSTALLER ENVIRONMENT",
            maxsplit=1,
        )[0]

    def test_script_is_distro_explicit_quoted_and_private_runtime_delegated(self) -> None:
        script = Path("installers/install-research-digest-windows.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("Get-InstalledWslDistributions", script)
        self.assertIn("$Distributions.Count -eq 0", script)
        self.assertIn("$_ -ceq $Distribution", script)
        self.assertIn("-Distribution", script)
        self.assertIn("--distro", script)
        self.assertIn("@InstallerEnvironment $Python @InstallerArguments", script)
        self.assertIn("$LoginShell -lic env", script)
        self.assertIn("env @InstallerEnvironment /bin/sh -c $DiscoveryScript", script)
        for name in (
            "XDG_DATA_HOME",
            "XDG_CONFIG_HOME",
            "RESEARCH_DIGEST_DATA_DIR",
            "RESEARCH_DIGEST_CONFIG_DIR",
            "RESEARCH_DIGEST_DB",
            "RESEARCH_DIGEST_PYTHON",
        ):
            self.assertIn(f'"{name}"', script)
        self.assertNotIn("Ubuntu", script)
        self.assertNotIn("researchrepo", script)
        self.assertNotIn("pip install", script)
        self.assertNotIn("OPENAI_API_KEY", script)
        self.assertNotIn("CODEX_API_KEY", script)

    def test_embedded_wsl_discovery_skips_old_default_for_versioned_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            commands = Path(tmp) / "commands"
            commands.mkdir()
            self.make_command(
                commands / "python3",
                "printf 'old' >/dev/null\nexit 1\n",
            )
            self.make_command(commands / "python3.12", "exit 0\n")
            self.make_command(commands / "codex", "exit 0\n")
            environment = {
                "PATH": str(commands),
            }

            completed = subprocess.run(
                ["/bin/sh", "-c", self.discovery_script()],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn(f"RD_PYTHON={commands / 'python3.12'}", completed.stdout)
            self.assertIn(f"RD_CODEX={commands / 'codex'}", completed.stdout)

    def test_embedded_wsl_discovery_honors_explicit_python_path_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            commands = Path(tmp) / "commands"
            commands.mkdir()
            override = Path(tmp) / "Compatible Python With Spaces"
            self.make_command(override, "exit 0\n")
            self.make_command(commands / "codex", "exit 0\n")
            environment = {
                "PATH": str(commands),
                "RESEARCH_DIGEST_PYTHON": str(override),
            }

            completed = subprocess.run(
                ["/bin/sh", "-c", self.discovery_script()],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn(f"RD_PYTHON={override}", completed.stdout)

    @unittest.skipUnless(
        os.environ.get("RESEARCH_DIGEST_RUN_WINDOWS_NATIVE_TESTS") == "1"
        and WINDOWS_POWERSHELL.exists(),
        "requires explicitly enabled native Windows PowerShell boundary",
    )
    def test_native_environment_forwarding_preserves_custom_paths_without_secrets(
        self,
    ) -> None:
        test_script = "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                self.installer_environment_function(),
                "$login = @(",
                "  'PATH=/home/person/npm/bin:/usr/bin',",
                "  'XDG_DATA_HOME=/home/person/data with spaces',",
                "  'RESEARCH_DIGEST_DB=/home/person/custom db/digest.sqlite3',",
                "  'RESEARCH_DIGEST_PYTHON=/opt/python builds/python3.12',",
                "  'OPENAI_API_KEY=must-not-cross-boundary'",
                ")",
                "$result = @(Get-ResearchDigestInstallerEnvironment -LoginEnvironment $login)",
                "if ($result -notcontains "
                "'XDG_DATA_HOME=/home/person/data with spaces') "
                "{ throw 'data path missing' }",
                "if ($result -notcontains "
                "'RESEARCH_DIGEST_DB=/home/person/custom db/digest.sqlite3') "
                "{ throw 'db path missing' }",
                "if ($result -notcontains "
                "'RESEARCH_DIGEST_PYTHON=/opt/python builds/python3.12') "
                "{ throw 'python override missing' }",
                "if (($result -join [Environment]::NewLine) "
                "-like '*OPENAI_API_KEY*') { throw 'secret crossed boundary' }",
                "Write-Output 'native environment forwarding: passed'",
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
        self.assertIn("native environment forwarding: passed", completed.stdout)

    def test_wrapper_and_core_embed_no_credentials_or_user_specific_runtime_path(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                Path("installers/install_research_digest.py"),
                Path("installers/install-research-digest-macos.sh"),
                Path("installers/install-research-digest-windows.ps1"),
            )
        )
        self.assertNotIn("sk-", text)
        self.assertNotIn("ChatGPT token", text)
        self.assertNotIn("~/researchrepo", text)
        self.assertNotIn("~/research-digest/.venv", text)


if __name__ == "__main__":
    unittest.main()
