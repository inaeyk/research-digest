from __future__ import annotations

import unittest

from research_digest.models import ArxivSourceConfig
from research_digest.ui.pages.today import digest_input_signature, source_config_fingerprint


class TodayStateTests(unittest.TestCase):
    def test_source_config_fingerprint_is_deterministic(self) -> None:
        first = ArxivSourceConfig(
            enabled=True,
            categories=["hep-th", "gr-qc"],
            lookback_hours=48,
            max_results=50,
        )
        second = ArxivSourceConfig(
            enabled=True,
            categories=["hep-th", "gr-qc"],
            lookback_hours=48,
            max_results=50,
        )

        self.assertEqual(source_config_fingerprint(first), source_config_fingerprint(second))

    def test_digest_input_signature_changes_with_profile_or_source_config(self) -> None:
        source = ArxivSourceConfig(categories=["hep-th"], lookback_hours=24, max_results=10)
        same = ArxivSourceConfig(categories=["hep-th"], lookback_hours=24, max_results=10)
        changed = ArxivSourceConfig(categories=["gr-qc"], lookback_hours=24, max_results=10)

        self.assertEqual(digest_input_signature(1, source), digest_input_signature(1, same))
        self.assertNotEqual(digest_input_signature(1, source), digest_input_signature(2, source))
        self.assertNotEqual(digest_input_signature(1, source), digest_input_signature(1, changed))


if __name__ == "__main__":
    unittest.main()
