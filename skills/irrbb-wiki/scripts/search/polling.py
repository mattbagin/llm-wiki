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

from datetime import datetime, timezone
from pathlib import Path

from . import evaluator, fetch
from .queue import ApprovalQueue
from .registry import Registry, SourceConfig


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

    Returns a summary dict: {source_id: {fetched: int, queued: int, errors: int}}.
    """
    raise NotImplementedError(
        "Wire fetch.fetch_source → evaluator.classify_item → evaluator.evaluate_item → queue.write_pending"
    )
