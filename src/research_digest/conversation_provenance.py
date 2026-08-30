"""Structured provenance for exact rolling-conversation coverage."""

from __future__ import annotations

import hashlib
import re

ROLLING_SUMMARY_FINGERPRINT_VERSION = "conversation-summary-boundary-v1"

_ROLLING_FINGERPRINT = re.compile(
    rf"{re.escape(ROLLING_SUMMARY_FINGERPRINT_VERSION)}:"
    r"conversation=(?P<conversation_id>[1-9][0-9]*):"
    r"through=(?P<through>[1-9][0-9]*):sha256=(?P<digest>[0-9a-f]{64})"
)


def rolling_summary_input_fingerprint(
    *,
    conversation_id: int,
    summarized_through_sequence: int,
    compression_context: str,
) -> str:
    if conversation_id <= 0:
        raise ValueError("rolling-summary conversation id must be positive")
    if summarized_through_sequence <= 0:
        raise ValueError("rolling-summary boundary must be positive")
    digest = hashlib.sha256(compression_context.encode("utf-8")).hexdigest()
    return (
        f"{ROLLING_SUMMARY_FINGERPRINT_VERSION}:conversation={conversation_id}:"
        f"through={summarized_through_sequence}:sha256={digest}"
    )


def parse_rolling_summary_boundary(
    *,
    conversation_id: int,
    input_fingerprint: str,
) -> int:
    match = _ROLLING_FINGERPRINT.fullmatch(input_fingerprint)
    if match is None or int(match.group("conversation_id")) != conversation_id:
        raise ValueError("rolling-summary boundary provenance is invalid")
    return int(match.group("through"))
