from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path

WHEEL_BACKEND_SPEC = importlib.util.spec_from_file_location(
    "_research_digest_build",
    Path("_research_digest_build.py"),
)
assert WHEEL_BACKEND_SPEC is not None and WHEEL_BACKEND_SPEC.loader is not None
wheel_backend = importlib.util.module_from_spec(WHEEL_BACKEND_SPEC)
WHEEL_BACKEND_SPEC.loader.exec_module(wheel_backend)


class DistributionWheelTests(unittest.TestCase):
    def test_wheel_is_exact_runtime_package_plus_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / wheel_backend.build_wheel(tmp)
            with zipfile.ZipFile(wheel) as archive:
                names = set(archive.namelist())

        expected_package = {
            path.relative_to("src").as_posix()
            for path in Path("src/research_digest").rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
            and path.as_posix() != "src/research_digest/analysis/fake.py"
        }
        metadata = {
            "research_digest-0.5.0.dist-info/METADATA",
            "research_digest-0.5.0.dist-info/WHEEL",
            "research_digest-0.5.0.dist-info/entry_points.txt",
            "research_digest-0.5.0.dist-info/RECORD",
        }
        self.assertEqual(names, expected_package | metadata)
        self.assertFalse(any(name.startswith("tests/") for name in names))
        self.assertFalse(any(name.startswith("docs/") for name in names))
        self.assertFalse(any(name.startswith(".github/") for name in names))
        self.assertNotIn("AGENTS.md", names)
        self.assertNotIn("research_digest/analysis/fake.py", names)

    def test_wheel_build_is_byte_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_wheel = Path(first) / wheel_backend.build_wheel(first)
            second_wheel = Path(second) / wheel_backend.build_wheel(second)

            self.assertEqual(first_wheel.read_bytes(), second_wheel.read_bytes())

    def test_installed_wheel_runs_with_repository_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wheelhouse = root / "wheelhouse"
            target = root / "isolated install with spaces"
            unrelated_cwd = root / "empty working directory"
            wheelhouse.mkdir()
            unrelated_cwd.mkdir()
            wheel = wheelhouse / wheel_backend.build_wheel(str(wheelhouse))
            subprocess.run(
                [
                    os.fspath(Path(sys.executable)),
                    "-m",
                    "pip",
                    "install",
                    "--no-deps",
                    "--target",
                    os.fspath(target),
                    os.fspath(wheel),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            environment = dict(os.environ)
            fake_bin = root / "fake bin"
            fake_bin.mkdir()
            codex = fake_bin / "codex"
            codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            codex.chmod(0o755)
            environment.update(
                {
                    "PYTHONPATH": str(target),
                    "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
                    "RESEARCH_DIGEST_DATA_DIR": str(root / "data"),
                    "RESEARCH_DIGEST_CONFIG_DIR": str(root / "config"),
                }
            )
            script = textwrap.dedent(
                f"""
                import io
                import json
                import pathlib
                import research_digest
                import research_digest.cli as cli

                target = pathlib.Path({str(target)!r})
                assert pathlib.Path(research_digest.__file__).is_relative_to(target)
                outputs = {{}}
                for name, arguments in (
                    ("version", ["--version"]),
                    ("doctor", ["doctor"]),
                    ("ui", ["ui-status", "--json"]),
                ):
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    code = cli.run_cli(argv=arguments, stdout=stdout, stderr=stderr)
                    assert code == 0, (name, code, stdout.getvalue(), stderr.getvalue())
                    outputs[name] = stdout.getvalue()
                assert outputs["version"].strip() == "research-digest 0.5.0"
                assert "Failures: 0" in outputs["doctor"]
                assert json.loads(outputs["ui"])["status"] == "completed"
                print(outputs["version"], end="")
                """
            )
            completed = subprocess.run(
                [os.fspath(Path(sys.executable)), "-c", script],
                cwd=unrelated_cwd,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertFalse((root / "data" / "research_digest.sqlite3").exists())

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "research-digest 0.5.0")


if __name__ == "__main__":
    unittest.main()
