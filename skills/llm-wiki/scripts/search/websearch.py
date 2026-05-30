"""Pluggable web search for the discovery and targeted workflows.

The package does NOT use Claude's hosted web_search tool — search is home-grown
so it works across the same three tiers the fetch layer uses (RSS handled in
fetch.py; here we cover requests-based and browser-based search). A small
provider interface lets you swap the no-key DuckDuckGo default for an API-backed
provider on environments where scraping DDG is blocked.

Environment:
    SEARCH_PROVIDER  — ddg (default) | brave | serper | tavily
    SEARCH_API_KEY   — required for brave/serper/tavily

Tiers:
    Tier 2 (requests): DuckDuckGoProvider / API providers via httpx.
    Tier 3 (browser):  browser_search() renders the DDG results page with
                       Playwright when requests is bot-blocked or JS-gated.
"""

from __future__ import annotations

import html
import logging
import os
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qs, unquote, urlparse

import httpx

logger = logging.getLogger("search.websearch")

DEFAULT_PROVIDER = "ddg"
DEFAULT_MAX_RESULTS = 10
_USER_AGENT = "Mozilla/5.0 (compatible; LLM-Wiki-Research/1.0)"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str = "web"


class BotBlocked(RuntimeError):
    """Raised by the requests tier when the engine returns a block/CAPTCHA so
    callers can fall back to the browser tier."""


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, max_results: int = DEFAULT_MAX_RESULTS) -> list[SearchResult]:
        ...


# ── Tier 2: requests-based providers ─────────────────────────────────────────


class DuckDuckGoProvider:
    """No-API-key search via DuckDuckGo's HTML endpoint.

    Parses the lite HTML results page. Raises BotBlocked on 403/429 or an
    obvious CAPTCHA/anomaly page so the caller can escalate to browser_search().
    """

    name = "ddg"
    ENDPOINT = "https://html.duckduckgo.com/html/"

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    def search(self, query: str, max_results: int = DEFAULT_MAX_RESULTS) -> list[SearchResult]:
        headers = {"User-Agent": _USER_AGENT, "Accept": "text/html"}
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.post(self.ENDPOINT, data={"q": query}, headers=headers)
        except httpx.HTTPError as e:
            raise BotBlocked(f"DDG request failed: {e}") from e

        if resp.status_code in (403, 429):
            raise BotBlocked(f"DDG returned {resp.status_code}")
        body = resp.text
        if "anomaly" in body.lower() or "captcha" in body.lower():
            raise BotBlocked("DDG returned an anomaly/CAPTCHA page")

        return _parse_ddg_html(body, max_results)


class _ApiProvider:
    """Shared base for JSON-API providers that need SEARCH_API_KEY."""

    name = "api"

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.api_key = os.environ.get("SEARCH_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                f"SEARCH_PROVIDER={self.name} requires SEARCH_API_KEY to be set."
            )


class BraveProvider(_ApiProvider):
    name = "brave"
    ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    def search(self, query: str, max_results: int = DEFAULT_MAX_RESULTS) -> list[SearchResult]:
        headers = {"X-Subscription-Token": self.api_key, "Accept": "application/json"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(self.ENDPOINT, params={"q": query, "count": max_results}, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        results = []
        for r in data.get("web", {}).get("results", [])[:max_results]:
            results.append(SearchResult(
                title=r.get("title", ""), url=r.get("url", ""), snippet=r.get("description", "")
            ))
        return results


class SerperProvider(_ApiProvider):
    name = "serper"
    ENDPOINT = "https://google.serper.dev/search"

    def search(self, query: str, max_results: int = DEFAULT_MAX_RESULTS) -> list[SearchResult]:
        headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self.ENDPOINT, json={"q": query, "num": max_results}, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        results = []
        for r in data.get("organic", [])[:max_results]:
            results.append(SearchResult(
                title=r.get("title", ""), url=r.get("link", ""), snippet=r.get("snippet", "")
            ))
        return results


class TavilyProvider(_ApiProvider):
    name = "tavily"
    ENDPOINT = "https://api.tavily.com/search"

    def search(self, query: str, max_results: int = DEFAULT_MAX_RESULTS) -> list[SearchResult]:
        payload = {"api_key": self.api_key, "query": query, "max_results": max_results}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self.ENDPOINT, json=payload)
            resp.raise_for_status()
            data = resp.json()
        results = []
        for r in data.get("results", [])[:max_results]:
            results.append(SearchResult(
                title=r.get("title", ""), url=r.get("url", ""), snippet=r.get("content", "")
            ))
        return results


_PROVIDERS = {
    "ddg": DuckDuckGoProvider,
    "brave": BraveProvider,
    "serper": SerperProvider,
    "tavily": TavilyProvider,
}


def get_provider(name: str | None = None) -> SearchProvider:
    """Resolve a provider by explicit name, else SEARCH_PROVIDER env, else ddg."""
    key = (name or os.environ.get("SEARCH_PROVIDER") or DEFAULT_PROVIDER).lower()
    provider_cls = _PROVIDERS.get(key)
    if provider_cls is None:
        raise ValueError(
            f"unknown search provider: {key!r} (expected one of {sorted(_PROVIDERS)})"
        )
    return provider_cls()


def search(query: str, max_results: int = DEFAULT_MAX_RESULTS, provider: str | None = None) -> list[SearchResult]:
    """Search with the configured provider; on BotBlocked from DDG, escalate to
    the browser tier. API providers are not retried via the browser."""
    prov = get_provider(provider)
    try:
        return prov.search(query, max_results)
    except BotBlocked as e:
        if prov.name == "ddg":
            logger.warning("DDG blocked (%s) — falling back to browser tier", e)
            return browser_search(query, max_results)
        raise


# ── Tier 3: browser-based search fallback ────────────────────────────────────


def browser_search(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> list[SearchResult]:
    """Render the DDG results page with Playwright. Used when the requests tier
    is bot-blocked or the engine is JS-gated. Returns [] if Playwright is absent."""
    from . import fetch

    if not fetch.is_playwright_available():
        logger.warning("Playwright not installed — browser_search returns no results")
        return []
    url = f"https://duckduckgo.com/html/?q={httpx.QueryParams({'q': query})['q']}"
    try:
        result = fetch.fetch_chromium(url, headers={"User-Agent": _USER_AGENT})
    except Exception as e:  # noqa: BLE001 — browser tier is best-effort
        logger.warning("browser_search failed: %s", e)
        return []
    return _parse_ddg_html(result.body, max_results)


# ── HTML parsing ─────────────────────────────────────────────────────────────

# DDG HTML wraps each hit's link in <a class="result__a" href="...">title</a>
_DDG_LINK = re.compile(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
_DDG_SNIPPET = re.compile(r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    return html.unescape(_TAG.sub("", text)).strip()


def _unwrap_ddg_url(href: str) -> str:
    """DDG HTML links are redirects like //duckduckgo.com/l/?uddg=<encoded>."""
    if "uddg=" in href:
        parsed = urlparse(href if href.startswith("http") else "https:" + href)
        uddg = parse_qs(parsed.query).get("uddg")
        if uddg:
            return unquote(uddg[0])
    if href.startswith("//"):
        return "https:" + href
    return href


def _parse_ddg_html(body: str, max_results: int) -> list[SearchResult]:
    links = _DDG_LINK.findall(body)
    snippets = [_clean(s) for s in _DDG_SNIPPET.findall(body)]
    results: list[SearchResult] = []
    seen: set[str] = set()
    for i, (href, title) in enumerate(links):
        url = _unwrap_ddg_url(href)
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        snippet = snippets[i] if i < len(snippets) else ""
        results.append(SearchResult(title=_clean(title), url=url, snippet=snippet))
        if len(results) >= max_results:
            break
    return results
