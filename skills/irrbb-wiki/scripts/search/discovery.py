"""Discovery workflow: bounded web search for new sources matching topics.

For each discovery_topic:
  1. LLM formulates 2-3 search queries (bounded budget)
  2. Run web searches via web_search tool or search API
  3. Filter results against state.json seen URLs and registered source URLs
  4. Pass 1 classifier → consider/recommend → fetch + Pass 2 → queue
"""

from __future__ import annotations

from pathlib import Path

from .registry import DiscoveryTopic, Registry

MAX_QUERIES_PER_TOPIC = 3
MAX_RESULTS_PER_QUERY = 10


def formulate_queries(topic: DiscoveryTopic) -> list[str]:
    """Ask the LLM to expand a topic into up to MAX_QUERIES_PER_TOPIC searches.

    The expansion is constrained to keep cost bounded; we do not let the agent
    iterate on queries within a single run.
    """
    raise NotImplementedError("Implement with Anthropic SDK; cap at MAX_QUERIES_PER_TOPIC")


def run_discovery(
    registry: Registry,
    wiki_root: Path,
    inbox_root: Path,
    dry_run: bool = False,
) -> dict:
    """Run a discovery pass across all discovery_topics due by cadence."""
    raise NotImplementedError(
        "Wire formulate_queries → web_search → dedup → classify → evaluate → queue"
    )
