"""Two-pass LLM evaluator.

Pass 1: cheap classifier on title + summary only (Claude Haiku).
Pass 2: full evaluation with content + wiki context (Claude Sonnet).

The Pass 2 call is what decides novelty vs. duplication and what wiki pages
would be affected. The evaluator does NOT modify the wiki — it only writes
recommendation records to `inbox/pending/`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import Literal, TYPE_CHECKING

from . import llm

if TYPE_CHECKING:
    from .fetch import FeedItem
    from .registry import SourceConfig

logger = logging.getLogger("search.evaluator")

WIKI_CONTEXT_CHAR_CAP = 10_000

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
    entity_tags: list[str] = field(default_factory=list)
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


def _status_from_score(score: int) -> Pass1Status:
    if score < 4:
        return "skip"
    if score <= 7:
        return "consider"
    return "recommend"


def classify_item(item: "FeedItem", source: "SourceConfig") -> Classification:
    """Pass 1 — Haiku call on title + summary only.

    Returns skip (score <4), consider (4-7), or recommend (8+). On any LLM/parse
    failure, falls back to a conservative `skip` so a flaky call never queues noise.
    """
    prompt = dedent(f"""\
        You are a fast relevance classifier for a knowledge wiki. Score how relevant
        ONE candidate source is to this wiki's topics, from its title and summary alone.

        Source feed: {source.name} (quality: {source.source_quality})
        Topics this wiki tracks (from the feed's filter): {', '.join(source.topic_filter) or 'general — infer from the source feed name'}

        Candidate:
        Title: {item.title}
        Summary: {item.summary[:600]}

        Score 0-10 for relevance to the wiki's topics and ingest-worthiness:
        - 8-10: clearly on-topic, likely a primary/authoritative source — recommend
        - 4-7: plausibly relevant, needs a closer look — consider
        - 0-3: off-topic — skip

        Respond with ONLY JSON, no prose:
        {{"score": <int 0-10>, "reason": "<one short sentence>"}}
    """)
    try:
        data = llm.extract_json(llm.call_text(prompt, model=llm.PASS1_MODEL, max_tokens=150))
        score = int(data.get("score", 0))
        score = max(0, min(10, score))
        return Classification(score=score, status=_status_from_score(score), reason=str(data.get("reason", "")))
    except Exception as e:  # noqa: BLE001
        logger.warning("classify_item failed for %r: %s — defaulting to skip", item.title[:60], e)
        return Classification(score=0, status="skip", reason=f"classifier error: {e}")


def evaluate_item(
    item: "FeedItem",
    full_content: str,
    wiki_context: str,
) -> Evaluation:
    """Pass 2 — Sonnet call with full content and wiki context.

    `wiki_context` should be assembled from wiki/index.md plus the 2-5 most
    relevant wiki pages (see load_wiki_context). Returns an Evaluation matching
    the inbox/pending YAML schema in references/agentic-search.md.
    """
    prompt = dedent(f"""\
        You are the senior evaluator for a knowledge wiki. Decide whether a candidate
        source should be queued for human approval and ingest. You do NOT write to the
        wiki — you only produce a recommendation record. Judge relevance against the
        wiki's existing topics shown in the context below.

        <candidate>
        Title: {item.title}
        URL: {item.url}
        Summary: {item.summary[:1000]}
        </candidate>

        <candidate_content>
        {full_content[:40000]}
        </candidate_content>

        <wiki_context>
        {wiki_context}
        </wiki_context>

        Assess:
        1. Novelty vs. what the wiki already covers: novel | partial-duplicate | duplicate
        2. If duplicate/partial, which existing wiki page or inbox item it duplicates
        3. Which wiki pages this would affect or create (use paths like wiki/concepts/x.md)
        4. Any contradictions with existing wiki claims
        5. Recommended action: ingest | ingest-with-commentary | skip
           (use ingest-with-commentary when the source warrants analytical narrative,
            e.g. it revisits or challenges something the wiki already states)

        Respond with ONLY JSON, no prose:
        {{
          "pass_2_status": "recommend|consider|skip",
          "pass_2_confidence": "high|medium|low",
          "novelty": "novel|partial-duplicate|duplicate",
          "duplicate_of": "<wiki page/inbox id or null>",
          "recommended_action": "ingest|ingest-with-commentary|skip",
          "affected_wiki_pages": ["wiki/..."],
          "contradictions_with_wiki": [{{"page": "wiki/...", "claim": "...", "conflict": "..."}}],
          "entity_tags": ["..."],
          "topic_tags": ["..."],
          "agent_notes": "<2-4 sentences for the human reviewer>"
        }}
    """)
    try:
        data = llm.extract_json(llm.call_text(prompt, model=llm.PASS2_MODEL, max_tokens=1500))
    except Exception as e:  # noqa: BLE001
        logger.warning("evaluate_item failed for %r: %s", item.title[:60], e)
        return Evaluation(
            pass_1_score=0, pass_1_reason="", pass_2_status="consider",
            pass_2_confidence="low", novelty="novel", duplicate_of=None,
            recommended_action="ingest", agent_notes=f"Pass 2 evaluation failed ({e}); manual review needed.",
        )

    dup = data.get("duplicate_of")
    return Evaluation(
        pass_1_score=0,  # filled in by the workflow from the Pass 1 result
        pass_1_reason="",
        pass_2_status=data.get("pass_2_status", "consider"),
        pass_2_confidence=data.get("pass_2_confidence", "low"),
        novelty=data.get("novelty", "novel"),
        duplicate_of=(None if dup in (None, "null", "") else dup),
        recommended_action=data.get("recommended_action", "ingest"),
        affected_wiki_pages=list(data.get("affected_wiki_pages", []) or []),
        contradictions_with_wiki=list(data.get("contradictions_with_wiki", []) or []),
        entity_tags=list(data.get("entity_tags", []) or []),
        topic_tags=list(data.get("topic_tags", []) or []),
        agent_notes=str(data.get("agent_notes", "")),
    )


_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def _page_tags(content: str) -> list[str]:
    """Parse a page's `tags: [a, b]` frontmatter list (no PyYAML dependency)."""
    m = _FRONTMATTER.match(content)
    if not m:
        return []
    for line in m.group(1).splitlines():
        line = line.strip()
        if line.startswith("tags:"):
            _, _, value = line.partition(":")
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                return [t.strip().strip('"').strip("'") for t in value[1:-1].split(",") if t.strip()]
    return []


def load_wiki_context(wiki_root: Path, hint_tags: list[str]) -> str:
    """Assemble a context blob from wiki/index.md plus pages whose tags intersect
    `hint_tags`. Capped at WIKI_CONTEXT_CHAR_CAP to bound the Pass 2 prompt size.

    Deliberately simple — no embeddings/vector index. The index-first pattern
    scales to the wiki's current size; revisit only if it demonstrably fails.
    """
    wiki_dir = wiki_root / "wiki" if (wiki_root / "wiki").is_dir() else wiki_root
    parts: list[str] = []

    index_path = wiki_dir / "index.md"
    if index_path.exists():
        parts.append(f"--- wiki/index.md ---\n{index_path.read_text(encoding='utf-8', errors='replace')[:4000]}")

    hint_set = {t.lower() for t in hint_tags}
    if hint_set:
        for md_file in sorted(wiki_dir.rglob("*.md")):
            if md_file.name in ("index.md", "log.md", "overview.md"):
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if hint_set.intersection(t.lower() for t in _page_tags(content)):
                parts.append(f"--- {md_file.name} ---\n{content[:2500]}")

    blob = "\n\n".join(parts)
    if len(blob) > WIKI_CONTEXT_CHAR_CAP:
        blob = blob[:WIKI_CONTEXT_CHAR_CAP] + "\n\n[... wiki context truncated ...]"
    return blob or "No existing wiki pages found."
