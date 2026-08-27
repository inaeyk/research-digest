"""Date-native adapter for reanalyzing complete source corpora from SQLite."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from research_digest.models import Article, ArxivSourceConfig, DateSelection
from research_digest.sources.base import SourceError


@dataclass(frozen=True)
class StoredDateRetrievalResult:
    selection: DateSelection
    articles: tuple[Article, ...]
    requested_dates: tuple[date, ...]
    covered_dates: tuple[date, ...]
    empty_dates: tuple[date, ...]
    incomplete_dates: tuple[date, ...] = ()
    safety_limit: int = 0
    safety_limit_reached: bool = False

    @property
    def complete(self) -> bool:
        return True


class StoredDateSource:
    """Serve a previously captured complete source-date article set."""

    def __init__(self, corpora: dict[date, tuple[Article, ...]]) -> None:
        self._corpora = dict(corpora)

    def fetch(
        self,
        config: ArxivSourceConfig,
        *,
        now: datetime | None = None,
    ) -> list[Article]:
        del config, now
        raise SourceError("stored source requires an explicit source-date selection")

    def fetch_date_selection(
        self,
        config: ArxivSourceConfig,
        selection: DateSelection,
    ) -> StoredDateRetrievalResult:
        del config
        requested_dates = selection.selected_dates()
        if not requested_dates or any(value not in self._corpora for value in requested_dates):
            raise SourceError("complete local source-date corpus is unavailable")
        articles_by_identity: dict[tuple[str, str], Article] = {}
        for source_date in requested_dates:
            for article in self._corpora[source_date]:
                articles_by_identity[(article.source, article.source_article_id)] = article
        articles = tuple(
            sorted(
                articles_by_identity.values(),
                key=lambda article: (
                    article.published_at,
                    article.source_article_id,
                ),
                reverse=True,
            )
        )
        return StoredDateRetrievalResult(
            selection=selection,
            articles=articles,
            requested_dates=requested_dates,
            covered_dates=requested_dates,
            empty_dates=tuple(
                value for value in requested_dates if not self._corpora[value]
            ),
        )
