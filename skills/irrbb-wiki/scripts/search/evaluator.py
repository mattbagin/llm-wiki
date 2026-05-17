"""Two-pass LLM evaluator.

Pass 1: cheap classifier on title + summary only (Claude Haiku).
Pass 2: full evaluation with content + wiki context (Claude Sonnet).

The Pass 2 call is what decides novelty vs. duplication and what wiki pages
would be affected. The evaluator does NOT modify the wiki — it only writes
recommendation records to `inbox/pending/`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from .fetch import FeedItem
    from .registry import SourceConfig

Pass1Status = Literal["skip", "consider", "recommend"]
Pass2Status = Literal["skip", "consider", "recommend"]
Novelty = Literal["novel", "partial-duplicate", "duplicate"]
Action = Literal["ingest", "ingest-with-commentary", "skip"]
Confidence = Literal["high", "medium", "low"]


@dataclass
class Classification:
    score: int                       # 0–10
    status: Pass1Status
    reason: str


@dataclass
class Evaluation:
    pass_1_score: int
    pass_1_reason: str
    pass_2_status: Pass2Status
    pass_2_confidence: Confidence
    novelty: Novelty
    duplicate_of: str | None
    recommended_action: Action
    affected_wiki_pages: list[str] = field(default_factory=list)
    contradictions_with_wiki: list[dict] = field(default_factory=list)
    bank_tags: list[str] = field(default_factory=list)
    topic_tags: list[str] = field(default_factory=list)
    agent_notes: str = ""


def topic_filter_match(item: "FeedItem", source: "SourceConfig") -> bool:
    """Cheap regex pre-pass before any LLM call.

    Returns True if any topic_filter term appears in the title or summary.
    Empty topic_filter means "accept everything from this source".
    """
    if not source.topic_filter:
        return True
    haystack = f"{item.title}\n{item.summary}".lower()
    return any(term.lower() in haystack for term in source.topic_filter)


def classify_item(item: "FeedItem", source: "SourceConfig") -> Classification:
    """Pass 1 — Haiku call on title + summary.

    Should return one of: skip (score <4), consider (4-7), recommend (8+).
    Budget: ~200 input tokens, ~50 output tokens, ~$0.001 per call.
    """
    raise NotImplementedError(
        "Implement with Anthropic SDK; prompt template in references/agentic-search.md"
    )


def evaluate_item(
    item: "FeedItem",
    full_content: str,
    wiki_context: str,
) -> Evaluation:
    """Pass 2 — Sonnet call with full content and wiki context.

    `wiki_context` should be assembled from wiki/index.md plus the 2-5 most
    relevant wiki pages (selected by topic_tags or Pass 1 reason).
    """
    raise NotImplementedError(
        "Implement with Anthropic SDK; prompt template in references/agentic-search.md"
    )


def load_wiki_context(wiki_root: Path, hint_tags: list[str]) -> str:
    """Assemble a context blob from wiki/index.md plus relevant pages.

    Start simple: always include wiki/index.md, plus any pages whose tags
    intersect with `hint_tags`. Cap total size to avoid blowing the Sonnet
    context window.
    """
    raise NotImplementedError("Implement page selection heuristic")
