from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class MacBootstrapTests(unittest.TestCase):
    def test_python_310_is_rejected_before_virtualenv_creation(self) -> None:
        script = Path("scripts/bootstrap_macos.sh").resolve()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "Project With Spaces"
            project.mkdir()
            python_310 = root / "Anaconda Python 3.10"
            python_310.write_text(
                "#!/bin/sh\nprintf '3.10.9\\n'\nexit 1\n",
                encoding="utf-8",
            )
            python_310.chmod(0o755)
            environment = dict(os.environ)
            environment.update(
                {
                    "RESEARCH_DIGEST_PROJECT_ROOT": str(project),
                    "RESEARCH_DIGEST_PYTHON": str(python_310),
                }
            )

            completed = subprocess.run(  # noqa: S603 - exact repository script fixture.
                ["/bin/sh", str(script)],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn("requires Python 3.11 or newer", completed.stderr)
            self.assertIn("Found Python 3.10.9", completed.stderr)
            self.assertIn("No virtual environment was created", completed.stderr)
            self.assertFalse((project / ".venv").exists())


if __name__ == "__main__":
    unittest.main()
