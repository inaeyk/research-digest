from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from research_digest import __version__


class ReleaseDocsTests(unittest.TestCase):
    def test_release_version_and_notes_are_consistent(self) -> None:
        project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        readme = Path("README.md").read_text(encoding="utf-8")
        changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
        release_notes = Path("docs/releases/V0.4.0.md").read_text(encoding="utf-8")

        self.assertEqual(project["project"]["version"], "0.4.0")
        self.assertEqual(__version__, "0.4.0")
        self.assertTrue(readme.startswith("# Research Digest v0.4.0\n"))
        self.assertIn("## [0.4.0] - 2026-08-27", changelog)
        self.assertIn("Windows Task Scheduler", release_notes)
        self.assertIn("macOS launchd", release_notes)
        self.assertIn("Closing the browser does not cancel", release_notes)
        self.assertIn("`ui-stop` does not cancel", release_notes)
        self.assertIn("Cancel digest does not disable", release_notes)
        self.assertIn("Python 3.11 or newer", release_notes)
        self.assertIn("wsl --shutdown", release_notes)
        self.assertIn("macOS login/logout or full restart", release_notes)

    def test_readme_documents_release_cli_surface(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")

        for command in (
            "research-digest serve",
            "research-digest run",
            "research-digest status",
            "research-digest doctor",
            "research-digest backup",
            "research-digest schedule install",
            "research-digest schedule status",
            "research-digest schedule remove",
        ):
            self.assertIn(command, readme)

        self.assertNotIn("streamlit run src/research_digest/ui/app.py", readme)
        self.assertIn("latest available arXiv source date", readme)
        self.assertIn("contiguous source-date range", readme)
        self.assertIn("Settings -> Automation", readme)
        self.assertIn("Settings -> Data", readme)
        self.assertIn("arXiv is the only source pool", readme)
        self.assertIn("full-paper/PDF deep reading is deferred", readme)
        self.assertIn("not long-term semantic memory", readme)

    def test_macos_clean_install_docs_match_published_smoke(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        acceptance = Path(
            "docs/campaigns/macos/V0.4.0_CLEAN_INSTALL_SMOKE.md"
        ).read_text(encoding="utf-8")

        self.assertIn("--branch v0.4.0", readme)
        self.assertIn("./scripts/bootstrap_macos.sh", readme)
        self.assertNotIn("RESEARCH_DIGEST_PYTHON=/path/to/", readme)
        self.assertIn(
            "RESEARCH_DIGEST_PYTHON=/opt/homebrew/bin/python3.12", readme
        )
        self.assertIn("Failures: 0", readme)
        self.assertIn("~/Applications/Research Digest.app", readme)
        self.assertIn("codex login status", readme)
        self.assertIn("Closing the browser does not stop or cancel", readme)
        self.assertIn("ui-stop` stops only the UI server", readme)
        self.assertIn("does not disable its schedule", readme)
        self.assertIn("History does not gain a no-op run", readme)

        for evidence in (
            "Acceptance date: 2026-08-28",
            "macOS 15.5, build `24F74`, arm64",
            "Published tag: `v0.4.0`",
            "b137a977d4adbc7701b520a75ebb7a3165be9ee0",
            "Finder -> Research Digest.app",
            "real Codex CLI",
            "`CANCELLED`",
            "org.research-digest.daily.plist",
            "macOS login/logout or a full restart",
        ):
            self.assertIn(evidence, acceptance)

        self.assertNotIn("/Users/", acceptance)
        self.assertNotIn("research-digest-install-smoke", acceptance)


if __name__ == "__main__":
    unittest.main()
