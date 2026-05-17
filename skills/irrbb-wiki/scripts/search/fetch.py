"""Tiered fetch layer: RSS → requests → Chromium.

RSS is the default and preferred strategy. Tier 2 (requests) is used for
sources without RSS and for lazy full-content fetches. Tier 3 (Chromium)
is a fallback for JS-rendered or bot-protected sites and is loaded lazily
so the package works without Playwright installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import SourceConfig


@dataclass
class FeedItem:
    source_id: str
    title: str
    url: str
    published: datetime | None
    summary: str
    content: str | None = None        # Filled in by lazy full-content fetch
    needs_manual_collection: bool = False


@dataclass
class FetchResult:
    url: str
    status_code: int
    content_type: str
    body: str
    fetched_at: datetime


def fetch_rss(rss_url: str, source_id: str) -> list[FeedItem]:
    """Fetch and parse an RSS feed. Returns metadata only — no full content."""
    raise NotImplementedError("Implement with feedparser; see references/agentic-search.md")


def fetch_requests(url: str, expected_content_type: str = "html") -> FetchResult:
    """Standard httpx fetch with retry, polite delay, proper User-Agent.

    Reuse the existing `fetch_url` helper in research.py rather than rewriting.
    """
    raise NotImplementedError("Delegate to research.fetch_url with domain-rate-limit wrapper")


def fetch_chromium(url: str, wait_for_selector: str | None = None) -> FetchResult:
    """Playwright/Chromium fallback for JS-rendered or bot-protected sites.

    Lazy-imports playwright so the package works when it is not installed.
    Callers should handle ImportError by routing to manual collection.
    """
    raise NotImplementedError("Implement with Playwright; lazy-import playwright")


def is_playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def fetch_source(source: "SourceConfig") -> list[FeedItem]:
    """Route a source to the appropriate fetch strategy."""
    if source.fetch_strategy == "rss":
        assert source.rss_url is not None
        return fetch_rss(source.rss_url, source.id)

    if source.fetch_strategy == "requests":
        assert source.url is not None
        result = fetch_requests(source.url)
        return parse_listing_page(result, source)

    if source.fetch_strategy == "chromium":
        assert source.url is not None
        if not is_playwright_available():
            return [_stub_manual_collection_item(source)]
        result = fetch_chromium(source.url)
        return parse_listing_page(result, source)

    raise ValueError(f"unknown fetch_strategy: {source.fetch_strategy}")


def parse_listing_page(result: FetchResult, source: "SourceConfig") -> list[FeedItem]:
    """Extract a list of items from an HTML listing page.

    Per-source selectors live in the registry under a `selectors:` key (to be
    added when implementing). For now, raises so the caller falls back to
    manual collection.
    """
    raise NotImplementedError("Implement source-specific listing-page parsers")


def _stub_manual_collection_item(source: "SourceConfig") -> FeedItem:
    return FeedItem(
        source_id=source.id,
        title=f"[manual collection needed] {source.name}",
        url=source.url or "",
        published=None,
        summary=(
            f"Source `{source.id}` is configured as fetch_strategy=chromium but "
            "Playwright is not installed. Collect manually and ingest via research.py."
        ),
        needs_manual_collection=True,
    )
