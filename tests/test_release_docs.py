from __future__ import annotations

import unittest
from pathlib import Path


class ReleaseDocsTests(unittest.TestCase):
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
        self.assertIn("arXiv is the only source pool", readme)
        self.assertIn("full-paper/PDF deep reading is deferred", readme)
        self.assertIn("not long-term semantic memory", readme)


if __name__ == "__main__":
    unittest.main()
