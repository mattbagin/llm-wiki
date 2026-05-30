"""Load and validate `source_registry.yaml`.

The registry is the single source of truth for what to monitor. The agent does
NOT discover sources autonomously. This module loads the YAML, coerces it into
dataclasses, and applies schema validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

FetchStrategy = Literal["rss", "requests", "chromium"]
SourceQuality = Literal["authoritative", "primary", "media", "reference"]
Cadence = Literal["daily", "weekly", "monthly", "quarterly"]


@dataclass
class SourceConfig:
    id: str
    name: str
    fetch_strategy: FetchStrategy
    cadence: Cadence
    source_quality: SourceQuality
    enabled: bool = True
    rss_url: str | None = None
    url: str | None = None
    topic_filter: list[str] = field(default_factory=list)
    entity_tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.fetch_strategy == "rss" and not self.rss_url:
            raise ValueError(f"source {self.id}: rss_url required for fetch_strategy=rss")
        if self.fetch_strategy in ("requests", "chromium") and not self.url:
            raise ValueError(
                f"source {self.id}: url required for fetch_strategy={self.fetch_strategy}"
            )


@dataclass
class DiscoveryTopic:
    topic: str
    cadence: Cadence
    entity_tags: list[str] = field(default_factory=list)


@dataclass
class GlobalSettings:
    user_agent: str = "LLM-Wiki-Research/1.0"
    request_timeout_seconds: int = 30
    request_delay_seconds: int = 2
    chromium_headless: bool = True
    max_pages_per_run: int = 50
    approval_queue_retention_days: int = 14
    # Web search (discovery/targeted). Provider may also be set via SEARCH_PROVIDER env.
    search_provider: str = "ddg"          # ddg | brave | serper | tavily
    max_results_per_query: int = 10


@dataclass
class Registry:
    sources: list[SourceConfig]
    discovery_topics: list[DiscoveryTopic]
    global_settings: GlobalSettings

    def enabled_sources(self) -> list[SourceConfig]:
        return [s for s in self.sources if s.enabled]

    def source_by_id(self, source_id: str) -> SourceConfig | None:
        return next((s for s in self.sources if s.id == source_id), None)


def load_registry(path: str | Path) -> Registry:
    """Load and validate the YAML registry."""
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    sources = [SourceConfig(**s) for s in data.get("sources", [])]
    seen_ids: set[str] = set()
    for s in sources:
        if s.id in seen_ids:
            raise ValueError(f"duplicate source id: {s.id}")
        seen_ids.add(s.id)

    topics = [DiscoveryTopic(**t) for t in data.get("discovery_topics", [])]
    settings = GlobalSettings(**data.get("global_settings", {}))

    return Registry(sources=sources, discovery_topics=topics, global_settings=settings)
