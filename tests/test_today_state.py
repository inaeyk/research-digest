from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

from research_digest.calibration import build_calibration_summary
from research_digest.db import Database
from research_digest.models import (
    AnalysisOrigin,
    AnalysisResult,
    Article,
    ArxivSourceConfig,
    DateSelection,
    DigestItem,
    DigestResult,
    InterestProfile,
    RunOrigin,
    profile_semantic_fingerprint,
)
from research_digest.ui.pages.today import (
    _coerce_date_range_input,
    coerce_date_selection_mode,
    coerce_digest_view,
    digest_input_signature,
    digest_period_label,
    digest_view_counts,
    digest_view_items,
    digest_view_label,
    is_current_digest_result,
    load_feedback_by_article_id,
    persist_feedback_selection,
    profile_fingerprint,
    resolve_latest_available_source_date,
    result_period_label,
    source_config_fingerprint,
)


def _article(source_article_id: str, title: str, published_hour: int) -> Article:
    return Article(
        id=published_hour,
        source="arxiv",
        source_article_id=source_article_id,
        title=title,
        authors=["Ada Lovelace"],
        abstract=f"{title} abstract.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, published_hour, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, published_hour, 10, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


def _analysis(score: float) -> AnalysisResult:
    return AnalysisResult(
        relevance_score=score,
        relevance_reason=f"Score {score}.",
        matched_topics=["gravity"] if score >= 0.6 else [],
        summary=f"Summary for {score}.",
        why_it_matters=f"Reason for {score}.",
        reading_priority="HIGH" if score >= 0.8 else "MEDIUM" if score >= 0.6 else "LOW",
    )


def _profile(
    *,
    profile_id: int | None = 1,
    name: str = "Gravity",
    description: str = "Higher-dimensional gravity.",
    threshold: float = 0.6,
) -> InterestProfile:
    return InterestProfile(
        id=profile_id,
        name=name,
        description=description,
        relevance_threshold=threshold,
    )


class LatestDateSource:
    def __init__(self, latest_date: date | None) -> None:
        self.latest_date = latest_date
        self.configs: list[ArxivSourceConfig] = []

    def resolve_latest_available_date(self, config: ArxivSourceConfig) -> date | None:
        self.configs.append(config)
        return self.latest_date


def _digest_result() -> DigestResult:
    profile = _profile()
    source_config = ArxivSourceConfig(categories=["hep-th"], lookback_hours=24, max_results=10)
    items = [
        DigestItem(
            article=_article("2608.00003", "Low score", 8),
            analysis=_analysis(0.2),
            analysis_origin=AnalysisOrigin.REUSED,
        ),
        DigestItem(
            article=_article("2608.00001", "High score", 10),
            analysis=_analysis(0.9),
            analysis_origin=AnalysisOrigin.NEW_THIS_RUN,
        ),
        DigestItem(
            article=_article("2608.00002", "Boundary score", 9),
            analysis=_analysis(0.6),
            analysis_origin=AnalysisOrigin.NEW_THIS_RUN,
        ),
    ]
    return DigestResult(
        run_id=23,
        profile=profile,
        source_config=source_config,
        retrieved_count=3,
        stored_count=3,
        preselected_count=2,
        skipped_analysis_count=1,
        analyzed_count=3,
        new_analysis_count=2,
        reused_analysis_count=1,
        above_threshold_count=2,
        analysis_available=True,
        items=items,
        started_at=datetime(2026, 8, 14, 11, 40, tzinfo=UTC),
        completed_at=datetime(2026, 8, 14, 11, 42, tzinfo=UTC),
        run_origin=RunOrigin.MANUAL,
        date_selection=DateSelection.single_date(date(2026, 8, 14)),
        requested_source_dates=(date(2026, 8, 14),),
        covered_source_dates=(date(2026, 8, 14),),
    )


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

        selection = DateSelection.latest_available()

        self.assertEqual(
            source_config_fingerprint(first, selection),
            source_config_fingerprint(second, selection),
        )

    def test_source_config_fingerprint_ignores_legacy_lookback_and_max_results(self) -> None:
        first = ArxivSourceConfig(
            enabled=True,
            categories=["hep-th"],
            lookback_hours=24,
            max_results=10,
        )
        second = ArxivSourceConfig(
            enabled=True,
            categories=["hep-th"],
            lookback_hours=72,
            max_results=100,
        )
        selection = DateSelection.single_date(date(2026, 8, 14))

        self.assertEqual(
            source_config_fingerprint(first, selection),
            source_config_fingerprint(second, selection),
        )

    def test_profile_fingerprint_is_deterministic_for_semantically_identical_profiles(
        self,
    ) -> None:
        first = _profile()
        second = InterestProfile(
            id=1,
            name="Gravity",
            description="Higher-dimensional gravity.",
            relevance_threshold=0.6,
        )

        self.assertEqual(profile_fingerprint(first), profile_fingerprint(second))

    def test_digest_input_signature_matches_for_unchanged_profile_and_source(self) -> None:
        source = ArxivSourceConfig(categories=["hep-th"], lookback_hours=24, max_results=10)
        same = ArxivSourceConfig(categories=["hep-th"], lookback_hours=24, max_results=10)
        first = _profile()
        second = _profile()
        selection = DateSelection.latest_available()

        self.assertEqual(
            digest_input_signature(first, source, selection),
            digest_input_signature(second, same, selection),
        )

    def test_digest_input_signature_changes_when_threshold_is_edited_in_place(self) -> None:
        source = ArxivSourceConfig(categories=["hep-th"], lookback_hours=24, max_results=10)
        original = _profile(threshold=0.6)
        changed = _profile(threshold=0.7)

        self.assertNotEqual(
            digest_input_signature(
                original,
                source,
                DateSelection.single_date(date(2026, 8, 14)),
            ),
            digest_input_signature(
                changed,
                source,
                DateSelection.single_date(date(2026, 8, 14)),
            ),
        )

    def test_digest_input_signature_changes_when_description_is_edited_in_place(self) -> None:
        source = ArxivSourceConfig(categories=["hep-th"], lookback_hours=24, max_results=10)
        original = _profile(description="Higher-dimensional gravity.")
        changed = _profile(description="Condensed matter dualities.")

        self.assertNotEqual(
            digest_input_signature(original, source, DateSelection.latest_available()),
            digest_input_signature(changed, source, DateSelection.latest_available()),
        )

    def test_digest_input_signature_changes_when_prompt_visible_name_changes(self) -> None:
        source = ArxivSourceConfig(categories=["hep-th"], lookback_hours=24, max_results=10)
        original = _profile(name="Gravity")
        changed = _profile(name="Quantum gravity")

        self.assertNotEqual(
            digest_input_signature(original, source, DateSelection.latest_available()),
            digest_input_signature(changed, source, DateSelection.latest_available()),
        )

    def test_digest_input_signature_changes_with_profile_id_or_source_config(self) -> None:
        source = ArxivSourceConfig(categories=["hep-th"], lookback_hours=24, max_results=10)
        changed_source = ArxivSourceConfig(
            categories=["gr-qc"],
            lookback_hours=24,
            max_results=10,
        )
        profile = _profile(profile_id=1)
        changed_profile_id = _profile(profile_id=2)

        self.assertNotEqual(
            digest_input_signature(profile, source, DateSelection.latest_available()),
            digest_input_signature(changed_profile_id, source, DateSelection.latest_available()),
        )
        self.assertNotEqual(
            digest_input_signature(profile, source, DateSelection.latest_available()),
            digest_input_signature(profile, changed_source, DateSelection.latest_available()),
        )
        self.assertNotEqual(
            digest_input_signature(profile, source, DateSelection.single_date(date(2026, 8, 14))),
            digest_input_signature(profile, source, DateSelection.single_date(date(2026, 8, 15))),
        )

    def test_digest_result_current_check_rejects_stale_signature(self) -> None:
        result = _digest_result()
        selection = result.date_selection or DateSelection.latest_available()
        current = digest_input_signature(result.profile, result.source_config, selection)
        changed_profile_id = digest_input_signature(
            _profile(profile_id=2),
            result.source_config,
            selection,
        )
        changed_threshold = digest_input_signature(
            _profile(threshold=0.7),
            result.source_config,
            selection,
        )
        changed_description = digest_input_signature(
            _profile(description="Condensed matter dualities."),
            result.source_config,
            selection,
        )
        changed_name = digest_input_signature(
            _profile(name="Quantum gravity"),
            result.source_config,
            selection,
        )
        changed_source = digest_input_signature(
            result.profile,
            ArxivSourceConfig(categories=["gr-qc"], lookback_hours=24, max_results=10),
            selection,
        )
        changed_selection = digest_input_signature(
            result.profile,
            result.source_config,
            DateSelection.single_date(date(2026, 8, 15)),
        )

        self.assertTrue(is_current_digest_result(result, current, current))
        self.assertFalse(is_current_digest_result(result, changed_profile_id, current))
        self.assertFalse(is_current_digest_result(result, changed_threshold, current))
        self.assertFalse(is_current_digest_result(result, changed_description, current))
        self.assertFalse(is_current_digest_result(result, changed_name, current))
        self.assertFalse(is_current_digest_result(result, changed_source, current))
        self.assertFalse(is_current_digest_result(result, changed_selection, current))
        self.assertFalse(is_current_digest_result(object(), current, current))

    def test_digest_period_labels_are_date_oriented(self) -> None:
        self.assertEqual(
            digest_period_label(DateSelection.latest_available()),
            "Latest available source date",
        )
        self.assertEqual(
            digest_period_label(DateSelection.single_date(date(2026, 8, 17))),
            "Aug 17, 2026",
        )
        self.assertEqual(
            digest_period_label(DateSelection.date_range(date(2026, 8, 14), date(2026, 8, 17))),
            "Aug 14, 2026 to Aug 17, 2026",
        )
        self.assertEqual(
            digest_period_label(
                DateSelection.explicit_dates([date(2026, 8, 12), date(2026, 8, 17)])
            ),
            "Aug 12, 2026, Aug 17, 2026",
        )

    def test_result_period_label_resolves_latest_available_run_dates(self) -> None:
        result = DigestResult(
            run_id=24,
            profile=_profile(),
            source_config=ArxivSourceConfig(categories=["hep-th"]),
            retrieved_count=0,
            stored_count=0,
            preselected_count=0,
            skipped_analysis_count=0,
            analyzed_count=0,
            new_analysis_count=0,
            reused_analysis_count=0,
            above_threshold_count=0,
            analysis_available=True,
            items=[],
            started_at=datetime(2026, 8, 17, tzinfo=UTC),
            completed_at=datetime(2026, 8, 17, tzinfo=UTC),
            run_origin=RunOrigin.MANUAL,
            date_selection=DateSelection.latest_available(),
            requested_source_dates=(date(2026, 8, 17),),
            covered_source_dates=(date(2026, 8, 17),),
        )

        self.assertEqual(result_period_label(result), "Aug 17, 2026")

    def test_latest_available_source_date_uses_source_resolver(self) -> None:
        config = ArxivSourceConfig(categories=["hep-th"])
        source = LatestDateSource(date(2026, 8, 16))

        self.assertEqual(resolve_latest_available_source_date(source, config), date(2026, 8, 16))
        self.assertEqual(source.configs, [config])

    def test_latest_available_source_date_allows_no_available_material(self) -> None:
        config = ArxivSourceConfig(categories=["hep-th"])

        self.assertIsNone(resolve_latest_available_source_date(LatestDateSource(None), config))

    def test_incomplete_date_range_input_is_pending_not_an_exception(self) -> None:
        self.assertIsNone(_coerce_date_range_input(()))
        self.assertIsNone(_coerce_date_range_input((date(2026, 8, 14),)))
        self.assertIsNone(_coerce_date_range_input([]))
        self.assertIsNone(_coerce_date_range_input([date(2026, 8, 14)]))

    def test_complete_date_range_input_accepts_tuple_or_list(self) -> None:
        start = date(2026, 8, 14)
        end = date(2026, 8, 17)

        self.assertEqual(_coerce_date_range_input((start, end)), (start, end))
        self.assertEqual(_coerce_date_range_input([start, end]), (start, end))

    def test_coerce_date_selection_mode_defaults_to_latest(self) -> None:
        self.assertEqual(coerce_date_selection_mode("date_range"), "date_range")
        self.assertEqual(coerce_date_selection_mode("other"), "latest_available")

    def test_digest_view_counts_labels_and_sorted_items(self) -> None:
        result = _digest_result()

        self.assertEqual(
            digest_view_counts(result),
            {"relevant": 2, "all_analyzed": 3, "below_threshold": 1},
        )
        self.assertEqual(digest_view_label("relevant", 2), "Relevant (2)")
        self.assertEqual(
            [item.article.source_article_id for item in digest_view_items(result, "relevant")],
            ["2608.00001", "2608.00002"],
        )
        self.assertEqual(
            [item.article.source_article_id for item in digest_view_items(result, "all_analyzed")],
            ["2608.00001", "2608.00002", "2608.00003"],
        )
        self.assertEqual(
            [
                item.article.source_article_id
                for item in digest_view_items(result, "below_threshold")
            ],
            ["2608.00003"],
        )

    def test_coerce_digest_view_defaults_to_relevant_for_unexpected_value(self) -> None:
        self.assertEqual(coerce_digest_view("all_analyzed"), "all_analyzed")
        self.assertEqual(coerce_digest_view(None), "relevant")

    def test_first_feedback_selection_is_visible_to_rebuilt_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "test.sqlite3")
            profile = db.create_interest_profile(
                name="Gravity",
                description="Higher-dimensional gravity.",
                relevance_threshold=0.6,
            )
            article, _ = db.upsert_article(_article("2608.03000", "High score", 10))
            item = DigestItem(
                article=article,
                analysis=_analysis(0.9),
                analysis_origin=AnalysisOrigin.NEW_THIS_RUN,
            )
            result = DigestResult(
                run_id=99,
                profile=profile,
                source_config=ArxivSourceConfig(
                    categories=["hep-th"],
                    lookback_hours=24,
                    max_results=10,
                ),
                retrieved_count=1,
                stored_count=1,
                preselected_count=1,
                skipped_analysis_count=0,
                analyzed_count=1,
                new_analysis_count=1,
                reused_analysis_count=0,
                above_threshold_count=1,
                analysis_available=True,
                items=[item],
                started_at=datetime(2026, 8, 14, 11, 40, tzinfo=UTC),
                completed_at=datetime(2026, 8, 14, 11, 42, tzinfo=UTC),
            )

            changed = persist_feedback_selection(
                item=item,
                db=db,
                profile=profile,
                profile_fingerprint_value=profile_semantic_fingerprint(profile),
                current_feedback=None,
                selected="NOT_RELEVANT",
            )
            feedback_by_article_id = load_feedback_by_article_id(db, result)
            summary = build_calibration_summary(
                items=result.items,
                feedback_by_article_id=feedback_by_article_id,
                threshold=profile.relevance_threshold,
            )

            self.assertTrue(changed)
            self.assertEqual(summary.feedback_count, 1)
            self.assertEqual(summary.false_positive_count, 1)
            self.assertEqual(summary.precision, 0.0)


if __name__ == "__main__":
    unittest.main()
