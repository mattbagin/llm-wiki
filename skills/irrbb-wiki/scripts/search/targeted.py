"""Targeted workflow: on-demand research for a specific event.

Use case: user sees a headline (e.g., "Deutsche Bank Q1 EVE breach"), wants
the agent to find primary source + secondary coverage and queue them grouped.
"""

from __future__ import annotations

from pathlib import Path

from .registry import Registry


def run_targeted(
    description: str,
    registry: Registry,
    wiki_root: Path,
    inbox_root: Path,
    bank_hint: str | None = None,
    max_results: int = 5,
    dry_run: bool = False,
) -> dict:
    """Run a targeted search for a single event/announcement.

    Returns: summary with the chosen primary source candidate and the list of
    secondary coverage items queued.
    """
    raise NotImplementedError(
        "Wire LLM query formulation → web_search → primary-vs-secondary classification → queue"
    )
