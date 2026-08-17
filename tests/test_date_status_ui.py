from __future__ import annotations

import unittest
from datetime import date

from research_digest.coverage import DateCoverageStatus
from research_digest.ui.date_status import date_status_cell_label, date_status_detail_rows


class DateStatusUiTests(unittest.TestCase):
    def test_cell_labels_are_compact_and_include_selected_overlay(self) -> None:
        completed = DateCoverageStatus(
            source_date=date(2026, 8, 14),
            status="completed",
            label="Completed digest",
            selected=True,
        )
        pending = DateCoverageStatus(
            source_date=date(2026, 8, 15),
            status="pending",
            label="Pending/uncovered",
        )

        self.assertIn("Done", date_status_cell_label(completed))
        self.assertIn("Sel", date_status_cell_label(completed))
        self.assertIn("Pending", date_status_cell_label(pending))
        self.assertNotIn("Pending/uncovered", date_status_cell_label(pending))

    def test_detail_rows_preserve_full_status_text_outside_day_cell(self) -> None:
        rows = date_status_detail_rows(
            (
                DateCoverageStatus(
                    source_date=date(2026, 8, 14),
                    status="completed",
                    label="Completed digest",
                    selected=True,
                    run_id=30,
                    retrieved_count=19,
                    analyzed_count=17,
                    relevant_count=2,
                ),
                DateCoverageStatus(
                    source_date=date(2026, 8, 15),
                    status="out_of_scope",
                    label="Outside catch-up interval",
                ),
            )
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Status"], "Completed digest")
        self.assertEqual(rows[0]["Run"], "#30")
        self.assertEqual(rows[0]["Retrieved"], 19)


if __name__ == "__main__":
    unittest.main()
