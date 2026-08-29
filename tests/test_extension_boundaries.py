from __future__ import annotations

import tempfile
import unittest
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from research_digest.ai_providers import LibrarySummaryProvider, ResearchConversationProvider
from research_digest.analysis.base import LLMAnalyzer, article_analysis_key
from research_digest.analysis.providers import (
    AnalyzerConnection,
    AnalyzerRegistry,
    build_configured_analyzer,
    build_default_analyzer_registry,
)
from research_digest.boundaries import (
    ContentReader,
    DigestDelivery,
    ResearchMemoryStore,
    RetrievedArticleContent,
)
from research_digest.config import AnalyzerProvider, AppConfig
from research_digest.db import Database
from research_digest.models import (
    AnalysisResult,
    Article,
    InterestProfile,
)
from research_digest.service import run_digest_for_profile
from research_digest.sources.registry import (
    SourceDefinition,
    SourceRunRequest,
    build_default_source_registry,
)
from research_digest.synthesis import CrossPaperSynthesis


@dataclass(frozen=True)
class DummySourceConfig:
    enabled: bool = True


class DummySource:
    def __init__(self, articles: Sequence[Article] = ()) -> None:
        self._articles = tuple(articles)

    def fetch(
        self,
        config: DummySourceConfig,
        *,
        now: datetime | None = None,
    ) -> list[Article]:
        if not config.enabled:
            return []
        return list(self._articles)


class DummyAnalyzer(LLMAnalyzer):
    def analyze(self, *, profile: InterestProfile, article: Article) -> AnalysisResult:
        return AnalysisResult(
            relevance_score=0.9,
            relevance_reason=f"Matched {profile.name}.",
            matched_topics=[profile.name],
            summary=f"Summary for {article.title}.",
            why_it_matters="It matches the configured profile.",
            reading_priority="HIGH",
        )

    def analyze_many(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> Mapping[str, AnalysisResult]:
        return {
            article_analysis_key(article): self.analyze(profile=profile, article=article)
            for article in articles
        }


class CustomSynthesizer:
    def build(
        self,
        *,
        items: Sequence[object],
        threshold: float,
    ) -> CrossPaperSynthesis:
        return CrossPaperSynthesis(
            analyzed_count=len(items),
            relevant_count=42,
            recurring_topics=(),
            high_priority_titles=("custom synthesis",),
            category_counts=(),
        )


def sample_article(source: str = "arxiv", source_article_id: str = "2608.00001") -> Article:
    return Article(
        id=None,
        source=source,
        source_article_id=source_article_id,
        title="Warped gravity",
        authors=["Ada Lovelace"],
        abstract="Higher-dimensional gravity and black branes.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
        abstract_url=f"https://example.invalid/{source_article_id}",
        pdf_url=None,
    )


class ExtensionBoundaryTests(unittest.TestCase):
    def test_source_registry_exposes_arxiv_and_accepts_additive_source(self) -> None:
        registry = build_default_source_registry()
        self.assertEqual(registry.names(), ("arxiv",))

        dummy_definition = SourceDefinition[DummySourceConfig](
            name="dummy",
            adapter_factory=DummySource,
            config_loader=lambda db: DummySourceConfig(),
        )
        registry.register(dummy_definition)

        self.assertEqual(registry.names(), ("arxiv", "dummy"))
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "test.sqlite3")
            definition = registry.require("dummy")
            self.assertIsInstance(definition.load_config(db), DummySourceConfig)
            self.assertIsInstance(definition.build_adapter(), DummySource)

    def test_analyzer_registry_preserves_defaults_and_accepts_added_provider(self) -> None:
        default_registry = build_default_analyzer_registry()
        self.assertEqual(default_registry.names(), ("codex", "openai"))

        registry = AnalyzerRegistry()
        registry.register("dummy", lambda config: AnalyzerConnection(DummyAnalyzer(), None))
        config = _app_config(analyzer_provider=cast(AnalyzerProvider, "dummy"))

        connection = build_configured_analyzer(config, registry=registry)

        self.assertIsInstance(connection.analyzer, DummyAnalyzer)
        self.assertIsNone(connection.message)

    def test_analyzer_registry_rejects_unsupported_provider_clearly(self) -> None:
        connection = build_configured_analyzer(
            _app_config(analyzer_provider=cast(AnalyzerProvider, "missing")),
            registry=AnalyzerRegistry(),
        )

        self.assertIsNone(connection.analyzer)
        self.assertEqual(connection.message, "Unsupported analyzer provider: missing")

    def test_service_accepts_alternate_synthesis_builder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "test.sqlite3")
            profile = db.create_interest_profile(
                name="Gravity",
                description="Higher-dimensional gravity.",
            )
            source = DummySource([sample_article(source="dummy")])
            result = run_digest_for_profile(
                db=db,
                source=source,
                analyzer=DummyAnalyzer(),
                profile_id=profile.id or 0,
                source_request=SourceRunRequest(
                    source_name="dummy",
                    adapter=source,
                    config=DummySourceConfig(),
                ),
                synthesis_builder=CustomSynthesizer(),
            )

        self.assertEqual(result.synthesis.relevant_count, 42)
        self.assertEqual(result.synthesis.high_priority_titles, ("custom synthesis",))
        self.assertIsInstance(result.digest.source_config, DummySourceConfig)

    def test_future_extension_protocols_are_importable(self) -> None:
        self.assertIsNotNone(ContentReader)
        self.assertIsNotNone(DigestDelivery)
        self.assertIsNotNone(ResearchMemoryStore)
        self.assertIsNotNone(RetrievedArticleContent)
        self.assertIsNotNone(LibrarySummaryProvider)
        self.assertIsNotNone(ResearchConversationProvider)


def _app_config(*, analyzer_provider: AnalyzerProvider) -> AppConfig:
    return AppConfig(
        db_path=Path("test.sqlite3"),
        data_dir=Path("."),
        config_dir=Path("."),
        analyzer_provider=analyzer_provider,
        openai_api_key=None,
        openai_model="gpt-test",
        codex_model="gpt-test",
        codex_timeout_seconds=12,
    )


if __name__ == "__main__":
    unittest.main()
