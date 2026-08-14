"""User-safe error formatting."""

from __future__ import annotations

import re
from pathlib import Path

_API_KEY_RE = re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_-]{8,}\b")
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_ENV_SECRET_RE = re.compile(
    r"\b(OPENAI_API_KEY|CODEX_API_KEY)\b\s*[:=]\s*['\"]?[^'\"\s,;}]+",
    re.IGNORECASE,
)
_HOME_PATH_RE = re.compile(r"/home/[^/\s'\"<>]+(?:/[^\s'\"<>]*)?")
_WHITESPACE_RE = re.compile(r"\s+")
_MAX_ERROR_LENGTH = 500


def sanitize_error(error: BaseException | str) -> str:
    """Return an error message safe for UI display and persistence."""

    return sanitize_error_text(str(error))


def sanitize_error_text(value: str, *, max_length: int = _MAX_ERROR_LENGTH) -> str:
    text = value.strip()
    if not text:
        return "An unknown error occurred."

    text = _API_KEY_RE.sub("[REDACTED_API_KEY]", text)
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _ENV_SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED_API_KEY]", text)
    text = _redact_home_paths(text)
    text = _WHITESPACE_RE.sub(" ", text).strip()

    if len(text) > max_length:
        return text[:max_length].rstrip() + " ... [truncated]"
    return text


def _redact_home_paths(value: str) -> str:
    home = str(Path.home())
    text = value
    if home:
        text = text.replace(home, "[HOME]")
    return _HOME_PATH_RE.sub("[HOME]", text)
