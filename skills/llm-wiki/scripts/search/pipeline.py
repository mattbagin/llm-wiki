"""Shared item-processing pipeline used by all three workflows.

Each workflow (polling, discovery, targeted) produces `FeedItem`s from a
different source, then funnels them through the same gate:

    dedup (url + content-hash) → Pass 1 classify → (consider/recommend) lazy
    full-content fetch → load wiki context → Pass 2 evaluate → write to queue

Keeping this in one place means cost-discipline and the inbox YAML schema stay
consistent regardless of how an item was discovered.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import evaluator, fetch
from .queue import ApprovalQueue, QueueState

logger = logging.getLogger("search.pipeline")


@dataclass
class PseudoSource:
    """Duck-typed stand-in for registry.SourceConfig, for items that don't come
    from a registered source (discovery/targeted). classify_item only reads
    name/source_quality/topic_filter."""

    id: str
    name: str
    source_quality: str = "media"
    topic_filter: list[str] = field(default_factory=list)
    entity_tags: list[str] = field(default_factory=list)


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug[:60] or "item"


def make_item_id(item: fetch.FeedItem) -> str:
    day = (item.published or datetime.now(tz=timezone.utc)).strftime("%Y%m%d")
    return f"{day}-{slugify(item.title)}"


def content_hash(title: str, content: str) -> str:
    h = hashlib.sha256()
    h.update((title.strip().lower() + "\n" + content[:500]).encode("utf-8", "replace"))
    return h.hexdigest()[:16]


def process_item(
    item: fetch.FeedItem,
    source,                       # SourceConfig or PseudoSource (duck-typed)
    wiki_root: Path,
    queue: ApprovalQueue,
    state: QueueState,
    delay: int = fetch.DEFAULT_DELAY,
    dry_run: bool = False,
    extra_entity_tags: list[str] | None = None,
) -> str:
    """Run one candidate through the gate. Returns a status string:
    'seen' | 'manual' | 'skipped' | 'duplicate' | 'queued' | 'queued-dry'."""
    if item.needs_manual_collection:
        return "manual"
    if not item.url or item.url in state.seen_urls:
        return "seen"

    # Pass 1 — cheap classifier on title + summary.
    classification = evaluator.classify_item(item, source)
    if classification.status == "skip":
        if not dry_run:
            state.seen_urls.append(item.url)
        return "skipped"

    # Lazy full-content fetch (only for items that cleared Pass 1).
    content = item.content
    if not content:
        result = fetch.fetch_requests(item.url, delay=delay)
        content = result.body
    if not content:
        logger.warning("no content fetched for %s — skipping", item.url)
        if not dry_run:
            state.seen_urls.append(item.url)
        return "skipped"

    # Content-hash dedup (cosmetic re-publishes, errata).
    chash = content_hash(item.title, content)
    if chash in state.content_hashes:
        if not dry_run:
            state.seen_urls.append(item.url)
        return "duplicate"

    # Pass 2 — full evaluation with wiki context.
    hint_tags = list(getattr(source, "topic_filter", []) or [])
    wiki_context = evaluator.load_wiki_context(wiki_root, hint_tags)
    evaluation = evaluator.evaluate_item(item, content, wiki_context)
    evaluation.pass_1_score = classification.score
    evaluation.pass_1_reason = classification.reason

    entity_tags = list(dict.fromkeys((evaluation.entity_tags or []) + (extra_entity_tags or [])))
    item_id = make_item_id(item)
    record = {
        "item": {
            "title": item.title,
            "url": item.url,
            "source_id": source.id,
            "fetched_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "content_path": f"inbox/pending/{item_id}.md",
        },
        "evaluation": {
            "pass_1_score": evaluation.pass_1_score,
            "pass_1_reason": evaluation.pass_1_reason,
            "pass_2_status": evaluation.pass_2_status,
            "pass_2_confidence": evaluation.pass_2_confidence,
            "novelty": evaluation.novelty,
            "duplicate_of": evaluation.duplicate_of,
            "recommended_action": evaluation.recommended_action,
            "affected_wiki_pages": evaluation.affected_wiki_pages,
            "contradictions_with_wiki": evaluation.contradictions_with_wiki,
            "entity_tags": entity_tags,
            "topic_tags": evaluation.topic_tags,
            "agent_notes": evaluation.agent_notes,
        },
    }

    if dry_run:
        logger.info("[dry-run] would queue %s (score=%s, %s)", item_id, classification.score, evaluation.pass_2_status)
        return "queued-dry"

    queue.write_pending(item_id, record, content)
    state.seen_urls.append(item.url)
    state.content_hashes[chash] = item.url
    return "queued"
