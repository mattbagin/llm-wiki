"""Polling workflow: scheduled scans of registered sources.

For each due source:
  1. Fetch via configured strategy
  2. Filter against state.json to remove already-seen URLs
  3. Apply topic_filter regex pre-pass (free)
  4. Run Pass 1 classifier (Haiku)
  5. For consider/recommend items, fetch full content + run Pass 2
  6. Write evaluation + content to inbox/pending/
  7. Update state.json
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from . import fetch, pipeline
from .queue import ApprovalQueue, SourceState
from .registry import Registry, SourceConfig

logger = logging.getLogger("search.polling")

# Failure thresholds (see references/agentic-search.md "Failure handling").
WARN_AFTER_FAILURES = 3
DISABLE_AFTER_FAILURES = 7


def is_source_due(source: SourceConfig, last_scan_iso: str | None) -> bool:
    """Return True if `source.cadence` has elapsed since `last_scan_iso`."""
    if last_scan_iso is None:
        return True
    last = datetime.fromisoformat(last_scan_iso.replace("Z", "+00:00"))
    now = datetime.now(tz=timezone.utc)
    elapsed_days = (now - last).total_seconds() / 86400
    thresholds = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 90}
    return elapsed_days >= thresholds[source.cadence]


def run_polling(
    registry: Registry,
    wiki_root: Path,
    inbox_root: Path,
    dry_run: bool = False,
) -> dict:
    """Run a polling pass across all enabled, due sources.

    Returns a summary dict: {source_id: {fetched, queued, skipped, errors}} plus
    a `_totals` row. Honors global_settings.max_pages_per_run across the whole run.
    """
    queue = ApprovalQueue(inbox_root)
    state = queue.load_state()
    settings = registry.global_settings
    budget = settings.max_pages_per_run
    processed = 0
    summary: dict = {}

    now_iso = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for source in registry.enabled_sources():
        src_state = state.sources.setdefault(source.id, SourceState())
        if not is_source_due(source, src_state.last_scan):
            continue

        row = {"fetched": 0, "queued": 0, "skipped": 0, "errors": 0}
        summary[source.id] = row
        if not dry_run:
            src_state.last_scan = now_iso

        try:
            items = fetch.fetch_source(source)
        except Exception as e:  # noqa: BLE001 — one bad source must not abort the run
            logger.warning("fetch failed for %s: %s", source.id, e)
            row["errors"] += 1
            src_state.consecutive_failures += 1
            _check_failure_thresholds(source.id, src_state)
            continue

        row["fetched"] = len(items)
        if not dry_run:
            src_state.consecutive_failures = 0
            src_state.last_successful_scan = now_iso

        for item in items:
            if processed >= budget:
                logger.info("max_pages_per_run (%d) reached — stopping", budget)
                break
            processed += 1
            try:
                status = pipeline.process_item(
                    item, source, wiki_root, queue, state,
                    delay=settings.request_delay_seconds, dry_run=dry_run,
                    extra_entity_tags=source.entity_tags,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("processing failed for %s: %s", item.url, e)
                row["errors"] += 1
                continue
            if status in ("queued", "queued-dry"):
                row["queued"] += 1
                src_state.items_seen += 1
            elif status in ("skipped", "seen", "duplicate", "manual"):
                row["skipped"] += 1
        if processed >= budget:
            break

    if not dry_run:
        queue.save_state(state)

    summary["_totals"] = {
        "sources_due": len([k for k in summary if k != "_totals"]),
        "items_processed": processed,
        "queued": sum(r["queued"] for k, r in summary.items() if k != "_totals"),
        "dry_run": dry_run,
    }
    return summary


def _check_failure_thresholds(source_id: str, src_state: SourceState) -> None:
    n = src_state.consecutive_failures
    if n >= DISABLE_AFTER_FAILURES:
        logger.error(
            "source %s has failed %d times — set `enabled: false` in source_registry.yaml "
            "until investigated", source_id, n,
        )
    elif n >= WARN_AFTER_FAILURES:
        logger.warning("source %s has failed %d consecutive times", source_id, n)
