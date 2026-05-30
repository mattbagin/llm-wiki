"""Tiered fetch layer: RSS → requests → Chromium.

RSS is the default and preferred strategy. Tier 2 (requests) is used for
sources without RSS and for lazy full-content fetches. Tier 3 (Chromium)
is a fallback for JS-rendered or bot-protected sites and is loaded lazily
so the package works without Playwright installed.

Politeness: same-domain requests are spaced by `request_delay_seconds` and
Tier 2 retries with exponential backoff. Set the delay via the registry's
global_settings (passed through by the workflow modules).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

if TYPE_CHECKING:
    from .registry import SourceConfig

logger = logging.getLogger("search.fetch")

DEFAULT_TIMEOUT = 30
DEFAULT_DELAY = 2
MAX_LISTING_LINKS = 60

# Per-domain politeness clock, shared across calls in a single run.
_DOMAIN_LAST_HIT: dict[str, float] = {}


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


def _polite_wait(url: str, delay: int = DEFAULT_DELAY) -> None:
    """Block until `delay` seconds have elapsed since the last hit to this domain."""
    domain = urlparse(url).netloc
    last = _DOMAIN_LAST_HIT.get(domain)
    now = time.monotonic()
    if last is not None:
        wait = delay - (now - last)
        if wait > 0:
            time.sleep(wait)
    _DOMAIN_LAST_HIT[domain] = time.monotonic()


# ── Tier 1: RSS ──────────────────────────────────────────────────────────────


def fetch_rss(rss_url: str, source_id: str) -> list[FeedItem]:
    """Fetch and parse an RSS/Atom feed. Returns metadata only — no full content.

    Lazy-imports feedparser so the package imports without it installed.
    Returns [] (and logs) on any parse failure so one bad feed doesn't abort a run.
    """
    try:
        import feedparser
    except ImportError:
        logger.error("feedparser not installed — `pip install feedparser` to enable RSS sources")
        return []

    parsed = feedparser.parse(rss_url)
    if getattr(parsed, "bozo", 0) and not parsed.entries:
        logger.warning("feed parse problem for %s: %s", source_id, getattr(parsed, "bozo_exception", "?"))
        return []

    items: list[FeedItem] = []
    for entry in parsed.entries:
        published = None
        struct = entry.get("published_parsed") or entry.get("updated_parsed")
        if struct:
            try:
                published = datetime(*struct[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                published = None
        items.append(
            FeedItem(
                source_id=source_id,
                title=entry.get("title", "").strip(),
                url=entry.get("link", "").strip(),
                published=published,
                summary=re.sub(r"<[^>]+>", " ", entry.get("summary", "")).strip(),
            )
        )
    return items


# ── Tier 2: requests ─────────────────────────────────────────────────────────


def fetch_requests(
    url: str,
    expected_content_type: str = "html",
    delay: int = DEFAULT_DELAY,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = 2,
) -> FetchResult:
    """Polite httpx fetch with per-domain delay and exponential-backoff retry.

    Reuses research.fetch_url's HTML→text extraction when importable (so RSS-item
    full-content fetches return clean text), falling back to a local httpx GET.
    """
    _polite_wait(url, delay)

    # Prefer research.fetch_url — it strips nav/script/style and decodes entities.
    research = _import_research()
    if research is not None:
        last_err = ""
        for attempt in range(retries + 1):
            res = research.fetch_url(url)
            if res.success:
                return FetchResult(
                    url=url,
                    status_code=200,
                    content_type="text/plain",
                    body=res.content,
                    fetched_at=datetime.now(tz=timezone.utc),
                )
            last_err = res.error or "unknown"
            if attempt < retries:
                time.sleep(2 ** attempt)
        logger.warning("fetch_requests failed for %s: %s", url, last_err)
        return FetchResult(url, 0, "", "", datetime.now(tz=timezone.utc))

    # Fallback: raw httpx GET (no text extraction).
    import httpx

    headers = {"User-Agent": "LLM-Wiki-Research/1.0", "Accept": "text/html,application/xhtml+xml"}
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
            return FetchResult(
                url=url,
                status_code=resp.status_code,
                content_type=resp.headers.get("content-type", ""),
                body=resp.text,
                fetched_at=datetime.now(tz=timezone.utc),
            )
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if attempt < retries:
                time.sleep(2 ** attempt)
    logger.warning("fetch_requests failed for %s: %s", url, last_exc)
    return FetchResult(url, 0, "", "", datetime.now(tz=timezone.utc))


def _import_research():
    """Best-effort import of the sibling research module (tools/research.py)."""
    try:
        import research  # type: ignore
        return research
    except ImportError:
        return None


# ── Tier 3: Chromium ─────────────────────────────────────────────────────────


def fetch_chromium(
    url: str,
    wait_for_selector: str | None = None,
    headers: dict | None = None,
    headless: bool = True,
    timeout: int = DEFAULT_TIMEOUT,
) -> FetchResult:
    """Playwright/Chromium fetch for JS-rendered or bot-protected sites.

    Lazy-imports playwright. Callers should catch ImportError and route to manual
    collection (fetch_source does this). Custom headers help when a site blocks the
    default headless UA.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ImportError(
            "Playwright not installed. `pip install playwright && playwright install chromium`, "
            "or mark the source for manual collection."
        ) from e

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            context = browser.new_context(
                user_agent=(headers or {}).get("User-Agent"),
                extra_http_headers={k: v for k, v in (headers or {}).items() if k != "User-Agent"} or None,
            )
            page = context.new_page()
            page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            if wait_for_selector:
                page.wait_for_selector(wait_for_selector, timeout=timeout * 1000)
            body = page.content()
        finally:
            browser.close()

    return FetchResult(
        url=url,
        status_code=200,
        content_type="text/html",
        body=body,
        fetched_at=datetime.now(tz=timezone.utc),
    )


def is_playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


# ── Routing ──────────────────────────────────────────────────────────────────


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
        try:
            result = fetch_chromium(source.url)
        except ImportError:
            return [_stub_manual_collection_item(source)]
        return parse_listing_page(result, source)

    raise ValueError(f"unknown fetch_strategy: {source.fetch_strategy}")


# Anchor extraction for HTML listing pages.
_ANCHOR = re.compile(r'<a\s[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def parse_listing_page(result: FetchResult, source: "SourceConfig") -> list[FeedItem]:
    """Extract candidate items from an HTML listing page.

    Generic heuristic: pull anchors, keep those on the source's own domain OR
    whose link text matches a topic_filter term, dedup, and cap. This is a
    good-enough default for index pages (e.g. the Fed SR-letter list). For sites
    that need precise extraction, add a per-source CSS selector hook here — see
    references/agentic-search.md ("Listing-page parsing").
    """
    if not result.body:
        return []

    base = result.url
    source_domain = urlparse(base).netloc.replace("www.", "")
    topic_terms = [t.lower() for t in source.topic_filter]
    items: list[FeedItem] = []
    seen: set[str] = set()

    for href, raw_text in _ANCHOR.findall(result.body):
        text = _TAG.sub("", raw_text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text or len(text) < 8:
            continue
        url = urljoin(base, href)
        if not url.startswith("http") or url in seen:
            continue
        link_domain = urlparse(url).netloc.replace("www.", "")
        on_domain = link_domain == source_domain
        topic_hit = any(term in text.lower() or term in url.lower() for term in topic_terms)
        if not (on_domain or topic_hit):
            continue
        seen.add(url)
        items.append(
            FeedItem(
                source_id=source.id,
                title=text[:200],
                url=url,
                published=None,
                summary="",
            )
        )
        if len(items) >= MAX_LISTING_LINKS:
            break
    return items


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
