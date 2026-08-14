"""arXiv source adapter using the official arXiv API."""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Final

from research_digest.models import (
    Article,
    ArxivSourceConfig,
    datetime_from_db,
    ensure_utc,
    normalize_whitespace,
    utc_now,
)
from research_digest.sources.base import SourceError

ARXIV_API_URL: Final = "https://export.arxiv.org/api/query"
ARXIV_SOURCE_NAME: Final = "arxiv"
DEFAULT_USER_AGENT: Final = (
    "ResearchDigest/0.1 "
    "(personal research digest; contact: research-digest@example.invalid)"
)

ATOM_NS: Final = {"atom": "http://www.w3.org/2005/Atom"}
_VERSION_SUFFIX_RE = re.compile(r"v\d+$")


class ArxivSource:
    """Fetch and parse recent papers from the official arXiv Atom API."""

    def __init__(
        self,
        *,
        endpoint: str = ARXIV_API_URL,
        timeout_seconds: float = 20.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

    def fetch(self, config: ArxivSourceConfig, *, now: datetime | None = None) -> list[Article]:
        if not config.enabled:
            return []

        cutoff = ensure_utc(_coerce_now(now)) - timedelta(hours=config.lookback_hours)
        url = build_arxiv_url(config, endpoint=self.endpoint)
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            raise SourceError(f"arXiv API returned HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise SourceError(f"could not reach arXiv API: {exc.reason}") from exc
        except TimeoutError as exc:
            raise SourceError("arXiv API request timed out") from exc

        try:
            return parse_arxiv_atom(payload, cutoff=cutoff)
        except ET.ParseError as exc:
            raise SourceError("arXiv API returned malformed Atom XML") from exc


def build_arxiv_query(categories: list[str]) -> str:
    terms = [f"cat:{category}" for category in categories]
    return " OR ".join(terms)


def build_arxiv_url(config: ArxivSourceConfig, *, endpoint: str = ARXIV_API_URL) -> str:
    params = {
        "search_query": build_arxiv_query(config.categories or []),
        "start": "0",
        "max_results": str(config.max_results),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return f"{endpoint}?{urllib.parse.urlencode(params)}"


def parse_arxiv_atom(payload: bytes | str, *, cutoff: datetime | None = None) -> list[Article]:
    cutoff_dt = ensure_utc(cutoff) if cutoff is not None else None
    root = ET.fromstring(payload)
    articles = [_entry_to_article(entry) for entry in root.findall("atom:entry", ATOM_NS)]
    if cutoff_dt is not None:
        articles = [article for article in articles if article.published_at >= cutoff_dt]
    return sorted(articles, key=lambda article: article.published_at, reverse=True)


def stable_arxiv_id(raw_id: str) -> str:
    parsed = urllib.parse.urlparse(raw_id.strip())
    path = parsed.path.strip("/")
    candidate = path.removeprefix("abs/") if path else raw_id.strip()
    return _VERSION_SUFFIX_RE.sub("", candidate)


def _entry_to_article(entry: ET.Element) -> Article:
    raw_id = _required_text(entry, "atom:id")
    title = _required_text(entry, "atom:title")
    abstract = _required_text(entry, "atom:summary")
    published = datetime_from_db(_required_text(entry, "atom:published"))
    updated = datetime_from_db(_required_text(entry, "atom:updated"))
    authors = [
        normalize_whitespace(name.text or "")
        for name in entry.findall("atom:author/atom:name", ATOM_NS)
        if normalize_whitespace(name.text or "")
    ]
    categories = [
        normalize_whitespace(category.attrib.get("term", ""))
        for category in entry.findall("atom:category", ATOM_NS)
        if normalize_whitespace(category.attrib.get("term", ""))
    ]
    abstract_url = _abstract_url(entry, raw_id)
    pdf_url = _pdf_url(entry)
    return Article(
        id=None,
        source=ARXIV_SOURCE_NAME,
        source_article_id=stable_arxiv_id(raw_id),
        title=title,
        authors=authors,
        abstract=abstract,
        categories=categories,
        published_at=published,
        updated_at=updated,
        abstract_url=abstract_url,
        pdf_url=pdf_url,
    )


def _required_text(entry: ET.Element, path: str) -> str:
    node = entry.find(path, ATOM_NS)
    text = node.text if node is not None else None
    if text is None or not text.strip():
        raise SourceError(f"arXiv entry is missing required field {path}")
    return normalize_whitespace(text)


def _abstract_url(entry: ET.Element, raw_id: str) -> str:
    for link in entry.findall("atom:link", ATOM_NS):
        if link.attrib.get("rel") == "alternate" and link.attrib.get("href"):
            return link.attrib["href"]
    return raw_id


def _pdf_url(entry: ET.Element) -> str | None:
    for link in entry.findall("atom:link", ATOM_NS):
        if link.attrib.get("title") == "pdf" and link.attrib.get("href"):
            return link.attrib["href"]
        if link.attrib.get("type") == "application/pdf" and link.attrib.get("href"):
            return link.attrib["href"]
    return None


def _coerce_now(value: datetime | None) -> datetime:
    if value is None:
        return utc_now()
    return value
