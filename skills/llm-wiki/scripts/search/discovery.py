"""Discovery workflow: bounded web search for new sources matching topics.

For each due discovery_topic:
  1. LLM formulates up to MAX_QUERIES_PER_TOPIC search queries (bounded budget)
  2. Run each query through the configured web search provider (websearch.py)
  3. Filter results against state.json seen URLs AND registered source URLs
     (so discovery doesn't re-find what polling already covers)
  4. Funnel survivors through the shared pipeline (classify → fetch → evaluate → queue)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from . import llm, pipeline, websearch
from .polling import is_source_due  # cadence check is identical
from .queue import ApprovalQueue, SourceState
from .registry import DiscoveryTopic, Registry

logger = logging.getLogger("search.discovery")

MAX_QUERIES_PER_TOPIC = 3
MAX_RESULTS_PER_QUERY = 10


def formulate_queries(topic: DiscoveryTopic) -> list[str]:
    """Ask the LLM to expand a topic into up to MAX_QUERIES_PER_TOPIC searches.

    The expansion is constrained to keep cost bounded; we do not let the agent
    iterate on queries within a single run. Falls back to the raw topic string.
    """
    entity_hint = f" Entities of interest: {', '.join(topic.entity_tags)}." if topic.entity_tags else ""
    prompt = (
        "You are planning web searches to find authoritative sources for a knowledge wiki.\n\n"
        f'Topic: "{topic.topic}".{entity_hint}\n\n'
        f"Write up to {MAX_QUERIES_PER_TOPIC} focused search queries that would surface "
        "primary sources and high-quality coverage on this topic. Prefer precise, "
        "specific phrasing over broad terms.\n\n"
        'Respond with ONLY a JSON array of strings, e.g. ["query one", "query two"].'
    )
    try:
        data = llm.extract_json(llm.call_text(prompt, model=llm.PASS2_MODEL, max_tokens=300))
        queries = [str(q).strip() for q in data if str(q).strip()]
        return queries[:MAX_QUERIES_PER_TOPIC] or [topic.topic]
    except Exception as e:  # noqa: BLE001
        logger.warning("query formulation failed for %r: %s — using raw topic", topic.topic, e)
        return [topic.topic]


def _registered_urls(registry: Registry) -> set[str]:
    urls: set[str] = set()
    for s in registry.sources:
        for u in (s.url, s.rss_url):
            if u:
                urls.add(u)
    return urls


def run_discovery(
    registry: Registry,
    wiki_root: Path,
    inbox_root: Path,
    dry_run: bool = False,
) -> dict:
    """Run a discovery pass across all discovery_topics due by cadence."""
    queue = ApprovalQueue(inbox_root)
    state = queue.load_state()
    settings = registry.global_settings
    budget = settings.max_pages_per_run
    max_results = getattr(settings, "max_results_per_query", MAX_RESULTS_PER_QUERY)
    provider = getattr(settings, "search_provider", None)
    registered = _registered_urls(registry)
    processed = 0
    summary: dict = {}
    now_iso = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for topic in registry.discovery_topics:
        topic_key = f"discovery:{topic.topic}"
        ts = state.sources.setdefault(topic_key, SourceState())
        if not _topic_due(topic, ts.last_scan):
            continue
        row = {"queries": 0, "found": 0, "queued": 0, "skipped": 0, "errors": 0}
        summary[topic.topic] = row
        if not dry_run:
            ts.last_scan = now_iso

        queries = formulate_queries(topic)
        row["queries"] = len(queries)
        source = pipeline.PseudoSource(
            id=f"discovery:{pipeline.slugify(topic.topic)}",
            name=f"Discovery: {topic.topic}",
            source_quality="reference",
            topic_filter=topic.topic.split(),
            entity_tags=topic.entity_tags,
        )

        for query in queries:
            try:
                results = websearch.search(query, max_results=max_results, provider=provider)
            except Exception as e:  # noqa: BLE001
                logger.warning("search failed for %r: %s", query, e)
                row["errors"] += 1
                continue
            for r in results:
                if processed >= budget:
                    break
                if r.url in registered or r.url in state.seen_urls:
                    continue
                processed += 1
                row["found"] += 1
                item = pipeline.fetch.FeedItem(
                    source_id=source.id, title=r.title or r.url, url=r.url,
                    published=None, summary=r.snippet,
                )
                try:
                    status = pipeline.process_item(
                        item, source, wiki_root, queue, state,
                        delay=settings.request_delay_seconds, dry_run=dry_run,
                        extra_entity_tags=topic.entity_tags,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning("processing failed for %s: %s", r.url, e)
                    row["errors"] += 1
                    continue
                if status in ("queued", "queued-dry"):
                    row["queued"] += 1
                    ts.items_seen += 1
                else:
                    row["skipped"] += 1
            if processed >= budget:
                break
        if processed >= budget:
            logger.info("max_pages_per_run (%d) reached — stopping discovery", budget)
            break

    if not dry_run:
        queue.save_state(state)

    summary["_totals"] = {
        "topics_due": len([k for k in summary if k != "_totals"]),
        "items_processed": processed,
        "queued": sum(r["queued"] for k, r in summary.items() if k != "_totals"),
        "dry_run": dry_run,
    }
    return summary


def _topic_due(topic: DiscoveryTopic, last_scan_iso: str | None) -> bool:
    """Reuse the source cadence check by adapting the DiscoveryTopic shape."""
    class _C:
        cadence = topic.cadence
    return is_source_due(_C(), last_scan_iso)  # type: ignore[arg-type]
