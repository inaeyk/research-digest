"""arXiv source adapter using the official arXiv API."""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final

from research_digest import __version__
from research_digest.models import (
    SOURCE_DATE_TIMEZONE,
    Article,
    ArxivSourceConfig,
    DateSelection,
    DateSelectionKind,
    datetime_from_db,
    ensure_utc,
    normalize_whitespace,
    source_date_from_datetime,
    utc_now,
)
from research_digest.sources.base import SourceError

ARXIV_API_URL: Final = "https://export.arxiv.org/api/query"
ARXIV_SOURCE_NAME: Final = "arxiv"
DEFAULT_USER_AGENT: Final = (
    f"ResearchDigest/{__version__} "
    "(personal research digest; contact: research-digest@example.invalid)"
)
DEFAULT_DATE_PAGE_SIZE: Final = 500
MAX_DATE_PAGE_SIZE: Final = 2000
DEFAULT_DATE_RETRIEVAL_SAFETY_LIMIT: Final = 2000

ATOM_NS: Final = {"atom": "http://www.w3.org/2005/Atom"}
_VERSION_SUFFIX_RE = re.compile(r"v\d+$")
ARXIV_DATE_QUERY_PADDING: Final = timedelta(hours=6)


@dataclass(frozen=True)
class ArxivDateRetrievalResult:
    """Date-native arXiv retrieval result with explicit coverage metadata."""

    selection: DateSelection
    articles: tuple[Article, ...]
    requested_dates: tuple[date, ...]
    covered_dates: tuple[date, ...]
    empty_dates: tuple[date, ...]
    incomplete_dates: tuple[date, ...]
    latest_available_date: date | None
    retrieved_count: int
    safety_limit: int
    safety_limit_reached: bool

    @property
    def complete(self) -> bool:
        return not self.incomplete_dates and not self.safety_limit_reached


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

    def fetch_date_selection(
        self,
        config: ArxivSourceConfig,
        selection: DateSelection,
        *,
        page_size: int = DEFAULT_DATE_PAGE_SIZE,
        safety_limit: int = DEFAULT_DATE_RETRIEVAL_SAFETY_LIMIT,
    ) -> ArxivDateRetrievalResult:
        """Fetch all eligible arXiv articles for selected Chicago source date(s)."""

        if not config.enabled:
            return ArxivDateRetrievalResult(
                selection=selection,
                articles=(),
                requested_dates=(),
                covered_dates=(),
                empty_dates=(),
                incomplete_dates=(),
                latest_available_date=None,
                retrieved_count=0,
                safety_limit=safety_limit,
                safety_limit_reached=False,
            )
        _validate_date_retrieval_limits(page_size=page_size, safety_limit=safety_limit)
        if selection.kind == DateSelectionKind.LATEST_AVAILABLE:
            return self._fetch_latest_available_date(
                config,
                selection,
                page_size=page_size,
                safety_limit=safety_limit,
            )
        requested_dates = selection.selected_dates()
        if selection.kind == DateSelectionKind.EXPLICIT_DATES:
            articles, incomplete_dates, safety_limit_reached = self._fetch_explicit_dates(
                config,
                requested_dates=requested_dates,
                page_size=page_size,
                safety_limit=safety_limit,
            )
        else:
            articles, safety_limit_reached = self._fetch_dates(
                config,
                requested_dates=requested_dates,
                page_size=page_size,
                safety_limit=safety_limit,
            )
            incomplete_dates = requested_dates if safety_limit_reached else ()
        return _build_date_result(
            selection=selection,
            articles=articles,
            requested_dates=requested_dates,
            incomplete_dates=incomplete_dates,
            latest_available_date=None,
            safety_limit=safety_limit,
            safety_limit_reached=safety_limit_reached,
        )

    def resolve_latest_available_date(self, config: ArxivSourceConfig) -> date | None:
        """Return the latest Chicago source date with eligible material."""

        if not config.enabled:
            return None
        first_page = self._fetch_page(
            build_arxiv_date_url(
                config,
                endpoint=self.endpoint,
                start=0,
                max_results=1,
                selected_dates=None,
            )
        )
        if not first_page:
            return None
        return arxiv_source_date_from_datetime(first_page[0].published_at)

    def _fetch_latest_available_date(
        self,
        config: ArxivSourceConfig,
        selection: DateSelection,
        *,
        page_size: int,
        safety_limit: int,
    ) -> ArxivDateRetrievalResult:
        latest_date = self.resolve_latest_available_date(config)
        if latest_date is None:
            return ArxivDateRetrievalResult(
                selection=selection,
                articles=(),
                requested_dates=(),
                covered_dates=(),
                empty_dates=(),
                incomplete_dates=(),
                latest_available_date=None,
                retrieved_count=0,
                safety_limit=safety_limit,
                safety_limit_reached=False,
            )
        articles, safety_limit_reached = self._fetch_dates(
            config,
            requested_dates=(latest_date,),
            page_size=page_size,
            safety_limit=safety_limit,
        )
        return _build_date_result(
            selection=selection,
            articles=articles,
            requested_dates=(latest_date,),
            incomplete_dates=(latest_date,) if safety_limit_reached else (),
            latest_available_date=latest_date,
            safety_limit=safety_limit,
            safety_limit_reached=safety_limit_reached,
        )

    def _fetch_explicit_dates(
        self,
        config: ArxivSourceConfig,
        *,
        requested_dates: tuple[date, ...],
        page_size: int,
        safety_limit: int,
    ) -> tuple[tuple[Article, ...], tuple[date, ...], bool]:
        articles: list[Article] = []
        seen_ids: set[str] = set()
        incomplete_dates: list[date] = []
        for index, requested_date in enumerate(requested_dates):
            remaining = safety_limit - len(articles)
            if remaining <= 0:
                incomplete_dates.extend(requested_dates[index:])
                break
            page_articles, safety_limit_reached = self._fetch_dates(
                config,
                requested_dates=(requested_date,),
                page_size=page_size,
                safety_limit=remaining,
            )
            for article in page_articles:
                if article.source_article_id in seen_ids:
                    continue
                seen_ids.add(article.source_article_id)
                articles.append(article)
            if safety_limit_reached:
                incomplete_dates.extend(requested_dates[index:])
                break
        return (
            tuple(_sort_date_articles(articles)),
            tuple(sorted(set(incomplete_dates))),
            bool(incomplete_dates),
        )

    def _fetch_dates(
        self,
        config: ArxivSourceConfig,
        *,
        requested_dates: tuple[date, ...],
        page_size: int,
        safety_limit: int,
    ) -> tuple[tuple[Article, ...], bool]:
        if not requested_dates:
            return (), False
        start = 0
        articles: list[Article] = []
        seen_ids: set[str] = set()
        safety_limit_reached = False
        while True:
            remaining = safety_limit - len(articles)
            if remaining <= 0:
                safety_limit_reached = True
                break
            current_page_size = min(page_size, remaining)
            url = build_arxiv_date_url(
                config,
                endpoint=self.endpoint,
                start=start,
                max_results=current_page_size,
                selected_dates=requested_dates,
            )
            page = self._fetch_page(url)
            if not page:
                break
            for article in page:
                if arxiv_source_date_from_datetime(article.published_at) not in requested_dates:
                    continue
                if article.source_article_id in seen_ids:
                    continue
                seen_ids.add(article.source_article_id)
                articles.append(article)
            if len(page) < current_page_size:
                break
            start += current_page_size
            if len(articles) >= safety_limit:
                safety_limit_reached = True
                break
        return tuple(_sort_date_articles(articles)), safety_limit_reached

    def _fetch_page(self, url: str) -> list[Article]:
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
            return parse_arxiv_atom(payload)
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


def build_arxiv_date_query(
    categories: list[str],
    *,
    selected_dates: tuple[date, ...] | None,
) -> str:
    category_query = build_arxiv_query(categories)
    if selected_dates is None:
        return category_query
    start, end = arxiv_source_date_query_bounds(selected_dates)
    date_query = f"submittedDate:[{_arxiv_api_timestamp(start)} TO {_arxiv_api_timestamp(end)}]"
    return f"({category_query}) AND {date_query}"


def build_arxiv_date_url(
    config: ArxivSourceConfig,
    *,
    endpoint: str = ARXIV_API_URL,
    start: int,
    max_results: int,
    selected_dates: tuple[date, ...] | None,
) -> str:
    params = {
        "search_query": build_arxiv_date_query(
            config.categories or [],
            selected_dates=selected_dates,
        ),
        "start": str(start),
        "max_results": str(max_results),
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


def arxiv_source_date_from_datetime(value: datetime) -> date:
    """Return the Research Digest arXiv source date for a publication timestamp."""

    return source_date_from_datetime(value)


def arxiv_source_date_query_bounds(
    selected_dates: tuple[date, ...],
) -> tuple[datetime, datetime]:
    if not selected_dates:
        raise SourceError("arXiv date query requires at least one source date")
    start_date = min(selected_dates)
    end_date = max(selected_dates)
    start = _chicago_midnight(start_date) - ARXIV_DATE_QUERY_PADDING
    end = _chicago_midnight(end_date + timedelta(days=1)) + ARXIV_DATE_QUERY_PADDING
    return ensure_utc(start), ensure_utc(end)


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


def _validate_date_retrieval_limits(*, page_size: int, safety_limit: int) -> None:
    if page_size <= 0:
        raise SourceError("arXiv date retrieval page size must be positive")
    if page_size > MAX_DATE_PAGE_SIZE:
        raise SourceError(f"arXiv date retrieval page size must be at most {MAX_DATE_PAGE_SIZE}")
    if safety_limit <= 0:
        raise SourceError("arXiv date retrieval safety limit must be positive")


def _chicago_midnight(value: date) -> datetime:
    return datetime.combine(value, time.min, SOURCE_DATE_TIMEZONE)


def _arxiv_api_timestamp(value: datetime) -> str:
    return ensure_utc(value).strftime("%Y%m%d%H%M")


def _build_date_result(
    *,
    selection: DateSelection,
    articles: tuple[Article, ...],
    requested_dates: tuple[date, ...],
    incomplete_dates: tuple[date, ...],
    latest_available_date: date | None,
    safety_limit: int,
    safety_limit_reached: bool,
) -> ArxivDateRetrievalResult:
    article_dates = {arxiv_source_date_from_datetime(article.published_at) for article in articles}
    requested = tuple(sorted(set(requested_dates)))
    incomplete = tuple(sorted(set(incomplete_dates)))
    covered_dates = tuple(value for value in requested if value not in incomplete)
    empty_dates = tuple(value for value in covered_dates if value not in article_dates)
    return ArxivDateRetrievalResult(
        selection=selection,
        articles=articles,
        requested_dates=requested,
        covered_dates=covered_dates,
        empty_dates=empty_dates,
        incomplete_dates=incomplete,
        latest_available_date=latest_available_date,
        retrieved_count=len(articles),
        safety_limit=safety_limit,
        safety_limit_reached=safety_limit_reached,
    )


def _sort_date_articles(articles: list[Article]) -> list[Article]:
    return sorted(
        articles,
        key=lambda article: (
            arxiv_source_date_from_datetime(article.published_at),
            article.published_at,
            article.title,
            article.source_article_id,
        ),
        reverse=True,
    )
