"""Feedback calibration summaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from research_digest.models import ArticleFeedback, DigestItem, is_above_threshold


@dataclass(frozen=True)
class CalibrationSummary:
    feedback_count: int
    predicted_relevant_count: int
    actual_relevant_count: int
    true_positive_count: int
    false_positive_count: int
    false_negative_count: int
    true_negative_count: int

    @property
    def precision(self) -> float | None:
        denominator = self.true_positive_count + self.false_positive_count
        if denominator == 0:
            return None
        return self.true_positive_count / denominator

    @property
    def recall(self) -> float | None:
        denominator = self.true_positive_count + self.false_negative_count
        if denominator == 0:
            return None
        return self.true_positive_count / denominator


def build_calibration_summary(
    *,
    items: Sequence[DigestItem],
    feedback_by_article_id: Mapping[int, ArticleFeedback],
    threshold: float,
) -> CalibrationSummary:
    true_positive_count = 0
    false_positive_count = 0
    false_negative_count = 0
    true_negative_count = 0

    for item in items:
        if item.article.id is None:
            continue
        feedback = feedback_by_article_id.get(item.article.id)
        if feedback is None or feedback.profile_match is None:
            continue
        predicted_relevant = is_above_threshold(item, threshold)
        actual_relevant = feedback.profile_match == "YES"
        if predicted_relevant and actual_relevant:
            true_positive_count += 1
        elif predicted_relevant and not actual_relevant:
            false_positive_count += 1
        elif not predicted_relevant and actual_relevant:
            false_negative_count += 1
        else:
            true_negative_count += 1

    feedback_count = (
        true_positive_count
        + false_positive_count
        + false_negative_count
        + true_negative_count
    )
    predicted_relevant_count = true_positive_count + false_positive_count
    actual_relevant_count = true_positive_count + false_negative_count
    return CalibrationSummary(
        feedback_count=feedback_count,
        predicted_relevant_count=predicted_relevant_count,
        actual_relevant_count=actual_relevant_count,
        true_positive_count=true_positive_count,
        false_positive_count=false_positive_count,
        false_negative_count=false_negative_count,
        true_negative_count=true_negative_count,
    )
