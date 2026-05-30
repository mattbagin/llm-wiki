"""Targeted workflow: on-demand research for a specific event.

Use case: user sees a headline or announcement, wants the agent to find the
primary source + secondary coverage and queue them grouped.

Flow: LLM formulates queries from the free-text description → web search →
classify each result as likely-primary vs. secondary coverage (domain heuristic)
→ funnel through the shared pipeline → return the chosen primary candidate.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

from . import llm, pipeline, websearch
from .queue import ApprovalQueue
from .registry import Registry

logger = logging.getLogger("search.targeted")

# Domain fragments we treat as likely PRIMARY sources (official/authoritative).
# Generic defaults — extend per wiki domain (add specific issuer/org domains).
_PRIMARY_DOMAIN_HINTS = (
    ".gov", ".edu", ".int", ".org", "official", "docs.", "investor", "ir.", "press.",
)


def _formulate_queries(description: str, entity_hint: str | None, max_queries: int = 3) -> list[str]:
    entity = f" The event concerns: {entity_hint}." if entity_hint else ""
    prompt = (
        "You are finding the primary source documents (and notable coverage) for a single "
        "event or announcement, for a knowledge wiki.\n\n"
        f'Event description: "{description}".{entity}\n\n'
        f"Write up to {max_queries} precise web search queries that would surface the actual "
        "primary source (the originating organization's publication/filing) and any key "
        "secondary coverage.\n\n"
        'Respond with ONLY a JSON array of strings.'
    )
    try:
        data = llm.extract_json(llm.call_text(prompt, model=llm.PASS2_MODEL, max_tokens=300))
        queries = [str(q).strip() for q in data if str(q).strip()]
        return queries[:max_queries] or [description]
    except Exception as e:  # noqa: BLE001
        logger.warning("targeted query formulation failed: %s — using raw description", e)
        return [description]


def _is_probable_primary(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return any(hint in netloc for hint in _PRIMARY_DOMAIN_HINTS)


def run_targeted(
    description: str,
    registry: Registry,
    wiki_root: Path,
    inbox_root: Path,
    entity_hint: str | None = None,
    max_results: int = 5,
    dry_run: bool = False,
) -> dict:
    """Run a targeted search for a single event/announcement.

    Returns: summary with the chosen primary source candidate and the list of
    items queued.
    """
    queue = ApprovalQueue(inbox_root)
    state = queue.load_state()
    settings = registry.global_settings
    provider = getattr(settings, "search_provider", None)

    queries = _formulate_queries(description, entity_hint, max_queries=3)

    # Gather and dedup candidates across all queries.
    candidates: list[websearch.SearchResult] = []
    seen: set[str] = set()
    for query in queries:
        try:
            results = websearch.search(query, max_results=max_results, provider=provider)
        except Exception as e:  # noqa: BLE001
            logger.warning("search failed for %r: %s", query, e)
            continue
        for r in results:
            if r.url not in seen and r.url.startswith("http"):
                seen.add(r.url)
                candidates.append(r)

    # Rank likely-primary domains first, then cap.
    candidates.sort(key=lambda r: (not _is_probable_primary(r.url)))
    candidates = candidates[:max_results]

    source = pipeline.PseudoSource(
        id=f"targeted:{pipeline.slugify(description)}",
        name=f"Targeted: {description[:60]}",
        source_quality="primary",
        topic_filter=description.split(),
        entity_tags=[entity_hint] if entity_hint else [],
    )

    queued: list[str] = []
    primary_candidate: str | None = None
    for r in candidates:
        if primary_candidate is None and _is_probable_primary(r.url):
            primary_candidate = r.url
        item = pipeline.fetch.FeedItem(
            source_id=source.id, title=r.title or r.url, url=r.url,
            published=None, summary=r.snippet,
        )
        try:
            status = pipeline.process_item(
                item, source, wiki_root, queue, state,
                delay=settings.request_delay_seconds, dry_run=dry_run,
                extra_entity_tags=source.entity_tags,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("processing failed for %s: %s", r.url, e)
            continue
        if status in ("queued", "queued-dry"):
            queued.append(r.url)

    if primary_candidate is None and candidates:
        primary_candidate = candidates[0].url

    if not dry_run:
        queue.save_state(state)

    return {
        "description": description,
        "queries": queries,
        "candidates_found": len(candidates),
        "primary_candidate": primary_candidate,
        "queued": queued,
        "dry_run": dry_run,
    }
