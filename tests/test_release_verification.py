from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

VERIFIER_SPEC = importlib.util.spec_from_file_location(
    "verify_release_assets",
    Path("tests/support/verify_release_assets.py"),
)
assert VERIFIER_SPEC is not None and VERIFIER_SPEC.loader is not None
verifier = importlib.util.module_from_spec(VERIFIER_SPEC)
sys.modules[VERIFIER_SPEC.name] = verifier
VERIFIER_SPEC.loader.exec_module(verifier)


class ReleaseAssetVerifierTests(unittest.TestCase):
    def test_exact_inventory_manifest_and_hashes_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "qualified.whl"
            payload.write_bytes(b"hardware-qualified wheel")
            payload_digest = hashlib.sha256(payload.read_bytes()).hexdigest()
            manifest = root / verifier.MANIFEST_NAME
            manifest.write_text(
                f"{payload_digest}  {payload.name}\n",
                encoding="ascii",
            )
            expected = {
                payload.name: payload_digest,
                manifest.name: hashlib.sha256(manifest.read_bytes()).hexdigest(),
            }

            verifier.verify_assets(root, expected)

            (root / "unexpected.txt").write_text("not owned", encoding="utf-8")
            with self.assertRaisesRegex(verifier.VerificationError, "inventory differs"):
                verifier.verify_assets(root, expected)

    def test_manifest_must_equal_the_explicit_payload_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "qualified.whl"
            payload.write_bytes(b"hardware-qualified wheel")
            payload_digest = hashlib.sha256(payload.read_bytes()).hexdigest()
            manifest = root / verifier.MANIFEST_NAME
            manifest.write_text(f"{'0' * 64}  {payload.name}\n", encoding="ascii")
            expected = {
                payload.name: payload_digest,
                manifest.name: hashlib.sha256(manifest.read_bytes()).hexdigest(),
            }

            with self.assertRaisesRegex(verifier.VerificationError, "entries differ"):
                verifier.verify_assets(root, expected)


class ReleaseVerificationWorkflowTests(unittest.TestCase):
    def test_fixed_tag_workflow_separates_runtime_and_harness_provenance(self) -> None:
        workflow = Path(".github/workflows/release-verification.yml").read_text(
            encoding="utf-8"
        )
        exact_wheel_job = workflow.split("  macos-exact-release-wheel:\n", maxsplit=1)[1]
        exact_wheel_job = exact_wheel_job.split(
            "  macos-corrected-harness:\n", maxsplit=1
        )[0]

        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("v0.4.1", workflow)
        self.assertIn("a1ea31be368916b375e811feec571e936ba76798", workflow)
        self.assertIn(
            "69c8b7ab66e6d9c91de65bb98d824d074c615614067aa13e37fabd62353b7e31",
            workflow,
        )
        self.assertIn("git rev-parse \"${RELEASE_TAG}^{}\"", workflow)
        self.assertIn("git diff --exit-code \"$RELEASE_COMMIT\"", workflow)
        self.assertEqual(workflow.count("--json isDraft"), 2)
        self.assertEqual(workflow.count('--jq .isDraft)\" = \"true\"'), 2)
        self.assertIn("gh release download", workflow)
        self.assertEqual(workflow.count("contents: write"), 2)
        self.assertIn("macos-corrected-harness", workflow)
        corrected_harness = workflow.split("  macos-corrected-harness:\n", maxsplit=1)[1]
        self.assertNotIn("contents: write", corrected_harness)
        self.assertIn("runs-on: macos-latest", exact_wheel_job)
        self.assertIn("Install only the exact release wheel", exact_wheel_job)
        self.assertIn("research_digest.__file__", exact_wheel_job)
        self.assertIn("python\" -I -m pytest", exact_wheel_job)
        self.assertNotIn("pip install -e", exact_wheel_job)


if __name__ == "__main__":
    unittest.main()
