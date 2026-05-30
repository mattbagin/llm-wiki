# Agentic Search — Reference

A scheduled / on-demand pipeline that scans for new sources, evaluates them
against the current wiki, and queues recommendations for human approval. Nothing
is auto-ingested. The feature complements (does not replace) `research.py`.

## Contents
- [When to use it](#when-to-use-it)
- [Three workflows](#three-workflows)
- [Source registry](#source-registry)
- [Fetch tiers](#fetch-tiers)
- [Two-pass evaluator](#two-pass-evaluator)
- [Approval queue](#approval-queue)
- [CLI commands](#cli-commands)
- [Integration with research.py](#integration-with-researchpy)
- [Cost discipline](#cost-discipline)
- [Operator workflow](#operator-workflow)

## When to use it

Trigger this feature when the user asks to:
- "Check what's new" / "scan sources" / "look for updates" → polling
- "Find sources about [topic]" without a specific URL → discovery
- "Find the primary source for [headline / event]" → targeted

Do NOT use this feature for:
- Direct single-source ingest (use `research.py` directly)
- Querying existing wiki content (use `wiki_search` / read `wiki/index.md`)
- Anything that touches internal or confidential sources (those never enter the
  agentic pipeline — they come in via manual `research.py ingest --file`)

## Three workflows

| Workflow | Trigger | Module | Purpose |
|----------|---------|--------|---------|
| Polling | cron / `cli.py poll` | `search/polling.py` | Scan registered sources by cadence |
| Discovery | cron / `cli.py discover` | `search/discovery.py` | Bounded web search for new sources |
| Targeted | `cli.py target --description ...` | `search/targeted.py` | One event, find primary + secondary |

All three workflows produce the same artifact: a YAML evaluation record + a
content Markdown file in `inbox/pending/`, awaiting human approval.

## Source registry

`tools/source_registry.yaml` — committed to the wiki repo. The agent does NOT
discover sources autonomously; the registry is the single source of truth.

### Source entry schema

```yaml
- id: example-source             # unique, kebab-case
  name: "Example Source"
  fetch_strategy: rss              # rss | requests | chromium
  rss_url: "..."                   # required if fetch_strategy=rss
  url: "..."                       # required if fetch_strategy=requests|chromium
  cadence: weekly                  # daily | weekly | monthly | quarterly
  topic_filter: [topic-a, topic-b]  # regex pre-pass before any LLM call
  entity_tags: []                  # optional; tagged onto items from this source
  source_quality: authoritative    # authoritative | primary | media | reference
  enabled: true
```

### Discovery topics

```yaml
discovery_topics:
  - topic: "a topic your wiki should track"
    cadence: monthly
    entity_tags: []
```

The LLM expands each topic into up to 3 web search queries (bounded budget).

### Global settings

```yaml
global_settings:
  user_agent: "LLM-Wiki-Research/1.0"
  request_timeout_seconds: 30
  request_delay_seconds: 2          # per-domain politeness
  max_pages_per_run: 50             # hard cap per workflow run
  approval_queue_retention_days: 14
```

## Fetch tiers

| Tier | Strategy | Use when |
|------|----------|----------|
| 1 | RSS (`feedparser`) | Preferred; many high-signal sources publish feeds |
| 2 | Requests (`httpx`) | No RSS, or lazy full-content fetch after RSS metadata pass |
| 3 | Chromium (`playwright`) | JS-rendered listing pages (e.g. a JS-heavy portal), 403/Cloudflare fallback |

Tier 3 is lazy-imported. If Playwright is not installed, `fetch_source` returns
a `needs_manual_collection=True` stub item so the human can ingest manually via
`research.py ingest --file` instead.

## Two-pass evaluator

To keep cost bounded, evaluation is split:

**Pass 1 — Haiku, title + summary only (~$0.001/call)**
Returns `Classification(score 0-10, status, reason)`. Status:
- `skip` (score <4) — never fetched, never queued
- `consider` (4-7) — fetched and Pass 2'd
- `recommend` (8+) — fetched, Pass 2'd, default-bias toward approval

**Pass 2 — Sonnet, full content + wiki context (~$0.02/call)**
Returns `Evaluation` with:
- `novelty`: novel | partial-duplicate | duplicate
- `duplicate_of`: wiki page or inbox item if duplicate
- `recommended_action`: ingest | ingest-with-commentary | skip
- `affected_wiki_pages`: list of page paths
- `contradictions_with_wiki`: list of `{page, claim, conflict}` records
- `entity_tags`, `topic_tags`, `agent_notes`

### Wiki context assembly

Pass 2 needs `wiki_context` — start simple:
1. Always include `wiki/index.md`
2. Plus any wiki page whose `tags:` frontmatter intersects with Pass 1's
   suggested topic tags
3. Cap total to ~10k tokens

Do NOT embed the wiki or build a vector index unless the simple approach
demonstrably fails.

### Evaluator output (`inbox/pending/{ts}-{slug}.yaml`)

```yaml
item:
  title: "..."
  url: "..."
  source_id: example-source
  fetched_at: 2026-04-15T08:30:00Z
  content_path: "inbox/pending/20260415-example.md"

evaluation:
  pass_1_score: 10
  pass_1_reason: "Primary source directly on a tracked topic"
  pass_2_status: recommend
  pass_2_confidence: high
  novelty: novel
  duplicate_of: null
  recommended_action: ingest-with-commentary
  affected_wiki_pages:
    - "wiki/concepts/example-concept.md"
    - "wiki/topics/example-topic.md"
  contradictions_with_wiki:
    - page: "wiki/concepts/example-concept.md"
      claim: "existing claim the wiki states"
      conflict: "how the new source contradicts it"
  entity_tags: []
  topic_tags: [topic-a, topic-b]
  agent_notes: "Why this matters and what to do with it..."
```

## Approval queue

Filesystem-backed at `inbox/`:

```
inbox/
├── pending/      # awaiting decision
├── approved/     # ready for ingest
├── rejected/     # audit trail, auto-purged after retention window
└── state.json    # seen URLs, last_scan per source, content hashes
```

### state.json schema

```json
{
  "schema_version": 1,
  "last_updated": "2026-04-15T08:30:00Z",
  "sources": {
    "<source_id>": {
      "last_scan": "2026-04-15T08:30:00Z",
      "last_successful_scan": "2026-04-15T08:30:00Z",
      "consecutive_failures": 0,
      "items_seen": 412
    }
  },
  "seen_urls": ["..."],
  "content_hashes": {"<hash>": "<url>"}
}
```

When `seen_urls` exceeds ~5,000 entries, migrate to SQLite.

### Dedup layers
1. URL exact match (state.json)
2. Content hash on title + first 500 chars
3. Semantic — Pass 2 checks wiki + inbox/approved for related claims

### Failure handling
- Increment `consecutive_failures` on fetch/parse error
- After 3 failures: log a warning, skip until investigated
- After 7 failures: mark `enabled: false` in registry (requires human action)

## CLI commands

```bash
# Polling / discovery / targeted
python tools/search/cli.py poll
python tools/search/cli.py discover
python tools/search/cli.py target --description "a specific announcement" --bank deutsche-bank

# Queue management
python tools/search/cli.py queue                              # list pending
python tools/search/cli.py review <item_id>                   # show evaluation + content
python tools/search/cli.py approve <item_id>
python tools/search/cli.py reject <item_id> --reason "..."

# Bulk operations
python tools/search/cli.py approve-all --min-score 9
python tools/search/cli.py reject-all --max-score 5

# Hand approved items to research.py
python tools/search/cli.py ingest-approved
```

## Integration with research.py

The handoff (`cmd_ingest_approved` in cli.py) loops approved items and calls
`research.run_file_ingest_pipeline` with:

```python
run_file_ingest_pipeline(
    file_path=item.content_path,
    wiki_root=wiki_root,
    bank_hint=item.entity_tags[0] if item.entity_tags else None,
    url_ref=item.url,
    with_updates=True,
    with_commentary=(item.recommended_action == "ingest-with-commentary"),
)
```

After successful ingest, the item is archived (moved out of `approved/`).

## Cost discipline

| Mechanism | Where |
|-----------|-------|
| Topic-filter regex pre-pass | `evaluator.topic_filter_match` — before any LLM |
| Two-pass classifier (Haiku → Sonnet) | `evaluator.classify_item` / `evaluate_item` |
| `max_pages_per_run` | `global_settings` cap per run |
| URL/hash dedup | `queue.ApprovalQueue` + `state.json` |
| Per-domain delay | `global_settings.request_delay_seconds` |
| Bounded discovery queries | `discovery.MAX_QUERIES_PER_TOPIC = 3` |

Target operating cost: ~$11/month for daily polling + weekly discovery + a few
targeted runs. Plus existing `research.py` cost on approved items only.

## Operator workflow

Typical week:
1. Daily cron runs `cli.py poll` → fills `inbox/pending/`
2. Weekly cron runs `cli.py discover` → adds more items
3. Operator runs `cli.py queue` to see what's waiting
4. Reviews high-score items one at a time with `cli.py review`
5. Bulk-approves obvious wins: `cli.py approve-all --min-score 9`
6. Bulk-rejects obvious noise: `cli.py reject-all --max-score 4`
7. Runs `cli.py ingest-approved` to hand off to research.py
8. After ~5 ingests, runs `python tools/lint_wiki.py`

### When rejecting, capture WHY

The `--reason` flag writes to `inbox/rejected/{item_id}.rejection-reason.txt`.
These rejections are NOT auto-fed back into the evaluator yet (that's Phase 5),
but the audit trail makes it cheap to spot evaluator drift.

## Module map

| Module | Responsibility |
|--------|----------------|
| `registry.py` | Load/validate `source_registry.yaml` into dataclasses |
| `fetch.py` | Tiered fetch (RSS / requests / Chromium) + listing-page parsing |
| `websearch.py` | Pluggable web search (discovery/targeted) — see below |
| `llm.py` | Shared Anthropic client, model constants, JSON extraction |
| `evaluator.py` | Two-pass classifier + wiki-context assembly |
| `pipeline.py` | Shared gate: dedup → classify → fetch → evaluate → queue |
| `polling.py` / `discovery.py` / `targeted.py` | The three workflows |
| `queue.py` | Filesystem approval queue + `state.json` |
| `cli.py` | CLI entry points + `ingest-approved` handoff to `research.py` |

## Web search providers

Discovery/targeted do NOT use Claude's hosted web_search tool — search is
home-grown (`websearch.py`) so it runs across the same fetch tiers. A small
`SearchProvider` interface lets you swap backends:

| Provider | Key needed | Notes |
|----------|-----------|-------|
| `ddg` (default) | none | DuckDuckGo HTML endpoint via httpx; falls back to the browser tier (`browser_search`) on bot-block |
| `brave` | `SEARCH_API_KEY` | Brave Search API |
| `serper` | `SEARCH_API_KEY` | Google results via serper.dev |
| `tavily` | `SEARCH_API_KEY` | Tavily search API |

Select via `global_settings.search_provider` in the registry or the
`SEARCH_PROVIDER` env var. The LLM only *formulates* queries (bounded to 3 per
topic); the actual searching/fetching is plain code.

## Listing-page parsing

`fetch.parse_listing_page` uses a generic anchor-extraction heuristic for
`requests`/`chromium` sources (keep links on the source domain or matching a
`topic_filter` term, dedup, cap). For a site that needs precise extraction, add
a per-source CSS-selector branch here — it's the intended extension point, not a
limitation to work around.

## Prompt templates

The Pass 1 / Pass 2 / query-formulation prompts live inline in `evaluator.py`,
`discovery.py`, and `targeted.py`. Pass 1 uses `llm.PASS1_MODEL` (Haiku); Pass 2
and query formulation use `llm.PASS2_MODEL` (Sonnet). Override with
`WIKI_PASS1_MODEL` / `WIKI_PASS2_MODEL`.

## Setup

```bash
pip install -r tools/search/requirements.txt          # anthropic, httpx, feedparser, pyyaml
export ANTHROPIC_API_KEY=sk-...                        # required for any LLM call
# optional: browser tier + API search providers
pip install playwright && playwright install chromium
export SEARCH_PROVIDER=ddg                             # or brave|serper|tavily (+ SEARCH_API_KEY)
```

No-LLM commands (`queue`, `review`, `approve`, `reject`) run without an API key.
Use `poll --dry-run` / `discover --dry-run` to exercise fetch + evaluation
without writing to the queue or `state.json`.

See `agentic-search-spec.md` in the repo root for the full design rationale,
implementation phases, and open design questions.
