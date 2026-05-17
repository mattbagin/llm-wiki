# Agentic Search Feature — Specification

## Overview

This document specifies an agentic search and monitoring feature for the IRRBB
(Interest Rate Risk in the Banking Book) Knowledge Wiki. The feature periodically scans
for new sources and updates to existing sources, evaluates them against the wiki's
current content, and queues recommendations for human approval before anything enters
the wiki.

The feature is composed of three distinct workflows that share infrastructure:

| Workflow | Trigger | Autonomy | Purpose |
|----------|---------|----------|---------|
| **Polling** | Scheduled (cron) | Low | Check known sources for new items |
| **Discovery** | Scheduled or on-demand | Medium | Find new sources matching topics of interest |
| **Targeted** | On-demand (event-triggered) | Medium | Research a specific event or announcement |

All three workflows feed into the same **approval queue** — the human reviews recommendations
and approves what enters `raw/`. Nothing is auto-ingested.

---

## 1. Architecture

### 1.1 Component Diagram

```
                            ┌─────────────────────────┐
                            │  source_registry.yaml   │  ← Source of truth for what to scan
                            └────────────┬────────────┘
                                         │
              ┌──────────────────────────┼──────────────────────────┐
              │                          │                          │
              ▼                          ▼                          ▼
      ┌───────────────┐         ┌────────────────┐         ┌────────────────┐
      │  Polling      │         │  Discovery     │         │  Targeted      │
      │  Workflow     │         │  Workflow      │         │  Workflow      │
      └───────┬───────┘         └────────┬───────┘         └────────┬───────┘
              │                          │                          │
              └──────────────────────────┼──────────────────────────┘
                                         ▼
                            ┌─────────────────────────┐
                            │   Fetch Layer           │  ← RSS → requests → Chromium
                            └────────────┬────────────┘
                                         │
                                         ▼
                            ┌─────────────────────────┐
                            │   Evaluator             │  ← LLM: relevant? novel? duplicate?
                            └────────────┬────────────┘
                                         │
                                         ▼
                            ┌─────────────────────────┐
                            │   Approval Queue        │  ← inbox/ directory + CLI review
                            └────────────┬────────────┘
                                         │
                                         ▼ (after human approval)
                            ┌─────────────────────────┐
                            │   Existing research.py  │  ← Full ingest pipeline
                            └─────────────────────────┘
```

### 1.2 Directory Layout

```
irrbb-wiki/
├── tools/
│   ├── research.py              # Existing — single-source ingest
│   ├── lint_wiki.py             # Existing
│   ├── mcp_server.py            # Existing
│   ├── search/                  # NEW — agentic search package
│   │   ├── __init__.py
│   │   ├── registry.py          # Load and validate source_registry.yaml
│   │   ├── fetch.py             # Tiered fetch layer (RSS, requests, Chromium)
│   │   ├── evaluator.py         # LLM-based scoring and dedup
│   │   ├── queue.py             # Approval queue management
│   │   ├── polling.py           # Polling workflow
│   │   ├── discovery.py         # Discovery workflow
│   │   ├── targeted.py          # Targeted workflow
│   │   └── cli.py               # CLI entry points
│   └── source_registry.yaml     # NEW — what to scan, how, how often
├── inbox/                       # NEW — approval queue
│   ├── pending/                 # Awaiting human review
│   ├── approved/                # Approved, ready for ingest
│   ├── rejected/                # Rejected (kept briefly for audit)
│   └── state.json               # Workflow state (last scan times, seen URLs)
└── ...
```

The `inbox/` directory is git-ignored by default. The registry is committed.

---

## 2. Source Registry

The registry is the single source of truth for what to monitor. The agent does NOT discover
sources autonomously — you maintain this file and the agent reads from it. This bounds
cost, ensures predictable coverage, and keeps the human in control of scope.

### 2.1 Schema

```yaml
# tools/source_registry.yaml

sources:
  - id: bcbs-publications
    name: "BCBS Publications (Basel Committee)"
    fetch_strategy: rss
    rss_url: "https://www.bis.org/list/bcbs/index.rss"
    cadence: weekly
    topic_filter: [irrbb, interest-rate-risk, banking-book, basel, d368, eve, nii]
    bank_tags: []
    source_quality: authoritative
    enabled: true

  - id: osfi-publications
    name: "OSFI Guidelines and Advisories"
    fetch_strategy: rss
    rss_url: "https://www.osfi-bsif.gc.ca/en/data-forms-publications/rss-feeds"
    cadence: weekly
    topic_filter: [irrbb, b-12, interest-rate, alm, asset-liability, banking-book]
    bank_tags: []
    source_quality: authoritative
    enabled: true

  - id: eba-publications
    name: "EBA IRRBB Guidelines and Updates"
    fetch_strategy: rss
    rss_url: "https://www.eba.europa.eu/rss.xml"
    cadence: weekly
    topic_filter: [irrbb, interest-rate-risk, banking-book, sot, supervisory-outlier]
    bank_tags: []
    source_quality: authoritative
    enabled: true

  - id: fed-sr-letters
    name: "Federal Reserve SR Letters"
    fetch_strategy: requests
    url: "https://www.federalreserve.gov/supervisionreg/srletters/srletters.htm"
    cadence: weekly
    topic_filter: [interest-rate-risk, irr, alm, banking-book, eve, nii]
    bank_tags: []
    source_quality: authoritative
    enabled: true

  - id: occ-bulletins
    name: "OCC Bulletins"
    fetch_strategy: rss
    rss_url: "https://www.occ.gov/news-issuances/bulletins/index-bulletins.rss"
    cadence: weekly
    topic_filter: [interest-rate-risk, irr, irrbb, alm, banking-book]
    bank_tags: []
    source_quality: authoritative
    enabled: true

  - id: rbc-investor-relations
    name: "RBC Investor Relations (Q-reports, Pillar 3)"
    fetch_strategy: rss
    rss_url: "https://www.rbc.com/investor-relations/rss/quarterly-results.xml"
    cadence: quarterly
    topic_filter: [irrbb, interest-rate, eve, nii, sensitivity, basis-risk]
    bank_tags: [rbc]
    source_quality: primary
    enabled: true

  - id: jpm-investor-relations
    name: "JP Morgan Quarterly Filings"
    fetch_strategy: requests
    url: "https://www.jpmorganchase.com/ir/quarterly-earnings"
    cadence: quarterly
    topic_filter: [irrbb, interest-rate-risk, nii-sensitivity, eve, alm]
    bank_tags: [jpmorgan]
    source_quality: primary
    enabled: true

  - id: risk-net-irrbb
    name: "Risk.net IRRBB Coverage"
    fetch_strategy: rss
    rss_url: "https://www.risk.net/feed/topic/interest-rate-risk-banking-book"
    cadence: daily
    topic_filter: [irrbb, interest-rate, alm, hedging, behavioral-models, nmd]
    bank_tags: []
    source_quality: media
    enabled: true

  - id: ssrn-irrbb
    name: "SSRN — Interest Rate Risk Working Papers"
    fetch_strategy: rss
    rss_url: "https://papers.ssrn.com/sol3/JELJOUR_Results.cfm?form_name=journalBrowse&journal_id=irrbb"
    cadence: weekly
    topic_filter: [irrbb, term-structure, behavioral, nmd, prepayment, optionality]
    bank_tags: []
    source_quality: reference
    enabled: false                  # Disabled until ready for paper volume

  - id: ecb-banking-supervision
    name: "ECB Banking Supervision Publications"
    fetch_strategy: chromium        # JS-rendered listing page
    url: "https://www.bankingsupervision.europa.eu/press/publications/html/index.en.html"
    cadence: weekly
    topic_filter: [irrbb, interest-rate-risk, srep, ilaap, banking-book]
    bank_tags: []
    source_quality: authoritative
    enabled: false                  # Phase 2 — needs Chromium setup

discovery_topics:
  # Topics for the discovery workflow to search against (web search, not specific URLs)
  - topic: "Canadian bank IRRBB disclosures EVE NII sensitivity"
    bank_tags: [rbc, td, scotiabank, bmo, cibc, nbc]
    cadence: quarterly
  - topic: "supervisory outlier test SOT 15% threshold breach"
    bank_tags: []
    cadence: monthly
  - topic: "behavioral models non-maturity deposits NMD assumptions"
    bank_tags: []
    cadence: monthly
  - topic: "OSFI B-12 amendments interest rate risk banking book"
    bank_tags: []
    cadence: weekly
  - topic: "BCBS d368 implementation Basel IRRBB standards"
    bank_tags: []
    cadence: monthly

global_settings:
  user_agent: "IRRBB-Wiki-Research/1.0 (personal research)"
  request_timeout_seconds: 30
  request_delay_seconds: 2          # Politeness — between requests to same domain
  chromium_headless: true
  max_pages_per_run: 50             # Cap on items processed per workflow run
  approval_queue_retention_days: 14 # How long approved/rejected items stay in inbox/
```

### 2.2 Registry Design Decisions

**Why config-driven rather than agent-discovered:**
- Predictable cost (no runaway searches)
- Predictable coverage (you know exactly what's monitored)
- Easy to disable/enable per source
- Version-controlled audit trail

**Why per-source cadence:**
- Risk.net and trade press: daily (event-driven coverage)
- Regulatory updates (BCBS, OSFI, EBA, OCC): weekly (slow-moving but high-signal)
- Bank quarterly disclosures (Q-reports, Pillar 3): quarterly (tied to earnings cycle)
- Academic papers (SSRN, working papers): weekly or biweekly (volume management)
- Conference proceedings (ALM conferences, GARP): event-triggered

**Why topic_filter:**
- A general EBA feed has many items per week, only a handful related to IRRBB
- The filter is a first-pass keyword check before invoking the LLM evaluator
- Cheap to run, prevents 95% of LLM calls on obvious noise (capital, AML, CCR, etc.)

---

## 3. Fetch Layer

A tiered fetch strategy with explicit routing per source.

### 3.1 Tier 1: RSS

```python
# tools/search/fetch.py

def fetch_rss(rss_url: str) -> list[FeedItem]:
    """Fetch an RSS feed and return parsed items.

    Returns title, link, published date, summary — no full content.
    Full content is fetched lazily only for items that pass evaluation.
    """
```

RSS is the default and preferred fetch strategy. Most high-signal sources have feeds:
- BCBS, BIS, EBA, OCC, ECB — all publish RSS for guidance and bulletins
- OSFI publishes RSS for guidelines and advisories
- Risk.net, Central Banking, GlobalCapital have topic-specific feeds
- SSRN journal-level feeds for working papers

**Dependencies:** `feedparser` (small, no native deps).

### 3.2 Tier 2: Requests

```python
def fetch_requests(url: str, expected_content_type: str = "html") -> FetchResult:
    """Standard httpx fetch with retry, polite delay, and proper headers.

    Used when:
    - Source has no RSS feed (e.g., Federal Reserve SR letter index page)
    - Lazily fetching full content of an RSS item
    - Fetching bank Pillar 3 reports or quarterly investor PDFs
    - Targeted workflow against a specific URL
    """
```

Reuses the existing `fetch_url` function from `research.py` with minor enhancements:
- Domain-level rate limiting (configurable delay between same-domain requests)
- Retry logic with exponential backoff
- Proper User-Agent identifying the tool
- PDF handling for regulatory documents and bank disclosures

### 3.3 Tier 3: Chromium (fallback only)

```python
def fetch_chromium(url: str, wait_for_selector: str = None) -> FetchResult:
    """Headless browser fetch for JS-rendered or bot-protected sites.

    Only used when:
    - Source's fetch_strategy is explicitly 'chromium' in the registry
    - Tier 2 returns a 403/429/Cloudflare challenge for a registered source
    """
```

**Dependencies:** Playwright with Chromium. Heavy install (~150MB) but only loaded when needed (lazy import). The function should fail gracefully if Playwright isn't installed and the source can fall back to "needs manual collection" status.

**Bank environment caveat:** If you can't install Playwright at work, the spec still works — sources marked `fetch_strategy: chromium` simply get flagged as "manual collection needed" in the queue. You'd handle them with the existing `research.py ingest --file` workflow.

### 3.4 Routing Logic

```python
def fetch_source(source: SourceConfig) -> list[FeedItem]:
    if source.fetch_strategy == "rss":
        return fetch_rss(source.rss_url)
    elif source.fetch_strategy == "requests":
        return parse_listing_page(fetch_requests(source.url))
    elif source.fetch_strategy == "chromium":
        if not is_playwright_available():
            return [stub_item_for_manual_collection(source)]
        return parse_listing_page(fetch_chromium(source.url))
```

---

## 4. Evaluator

The LLM-based component that decides whether an item is worth ingesting. This is where
cost discipline matters most.

### 4.1 Two-Pass Evaluation

**Pass 1 — Cheap classifier (always runs):**

```python
def classify_item(item: FeedItem, source: SourceConfig) -> Classification:
    """Quick LLM call on title + summary only.

    Inputs: ~200 tokens (title, summary, source context, topic filter)
    Output: relevance score 0-10, brief reason, suggested action

    Cost: ~$0.001 per item with Claude Haiku
    """
```

Returns one of: `skip` (score <4), `consider` (score 4-7), `recommend` (score 8+).

**Pass 2 — Full evaluation (only for `consider`/`recommend`):**

```python
def evaluate_item(item: FeedItem, full_content: str, wiki_context: str) -> Evaluation:
    """Full LLM call after fetching content and gathering wiki context.

    Determines:
    - Is this novel, or a duplicate of existing wiki content?
    - Which wiki pages would be affected (regulations/, concepts/, models/, entities/)?
    - What's the recommended action: ingest, ingest-with-commentary, skip?
    - Confidence in the recommendation
    - Whether the source supersedes an existing regulation page
    """
```

### 4.2 Deduplication Strategy

The hardest part of this system. Three layers:

**Layer 1 — URL exact match:** Trivial. Maintained in `inbox/state.json` as a set of seen URLs.

**Layer 2 — Content hash:** For RSS items that get re-published with cosmetic changes (regulatory revision tracking, errata). Hash the cleaned title + first 500 chars of content.

**Layer 3 — Semantic similarity (the hard one):** "BCBS proposes update to IRRBB standardized framework" might appear in BIS press release, Risk.net coverage, and a law-firm note within days. The evaluator's Pass 2 call should explicitly check the wiki for related claims and the inbox/approved/ directory for recent duplicates. Output identifies the primary source candidate (the BCBS document itself) vs. secondary coverage.

### 4.3 Evaluator Output Format

```yaml
# Saved as inbox/pending/{timestamp}-{slug}.yaml

item:
  title: "BCBS Consultation: Revisions to IRRBB Standardised Framework"
  url: "https://www.bis.org/bcbs/publ/d579.htm"
  source_id: bcbs-publications
  fetched_at: 2026-04-15T08:30:00Z
  content_path: "inbox/pending/content/20260415-bcbs-d579.md"

evaluation:
  pass_1_score: 10
  pass_1_reason: "BCBS consultation on IRRBB — primary regulatory source, direct hit"
  pass_2_status: recommend                  # recommend | consider | skip
  pass_2_confidence: high

  novelty: novel                            # novel | partial-duplicate | duplicate
  duplicate_of: null                        # If duplicate, link to wiki page or inbox item

  recommended_action: ingest-with-commentary
  affected_wiki_pages:
    - "wiki/regulations/bcbs-d368.md"       # Existing — would be cross-linked / superseded note
    - "wiki/regulations/bcbs-d579.md"       # New stub for the consultation
    - "wiki/concepts/standardized-framework.md"
    - "wiki/concepts/supervisory-outlier-test.md"

  contradictions_with_wiki:
    - page: "wiki/concepts/supervisory-outlier-test.md"
      claim: "SOT threshold of 15% of Tier 1 capital"
      conflict: "Consultation proposes alternative thresholds for non-systemic banks"

  bank_tags: []
  topic_tags: [bcbs, standardized-framework, sot, eve, consultation]

  agent_notes: |
    First substantive revision to the BCBS IRRBB framework since d368 (2016). The
    consultation introduces tiering for SOT thresholds and revisits behavioral
    assumptions for NMDs. Recommend ingesting with commentary that explicitly
    cross-references d368 and notes the proposed change is not yet in force.
    May warrant updating wiki/regulations/bcbs-d368.md with a "Proposed revisions"
    section linking to the new page.
```

---

## 5. Approval Queue

The interface between the agent and the human. Designed to minimize friction.

### 5.1 Queue Layout

```
inbox/
├── pending/                              # Items awaiting human decision
│   ├── 20260415-bcbs-d579.yaml          # Evaluation record
│   ├── 20260415-bcbs-d579.md            # Fetched content (for review)
│   ├── 20260415-osfi-b12-amendment.yaml
│   └── 20260415-osfi-b12-amendment.md
├── approved/                             # Approved, ready for ingest
│   └── (same structure, moved here on approval)
├── rejected/                             # Rejected (audit trail, auto-purged)
│   └── (same structure)
└── state.json                            # Seen URLs, last scan times
```

### 5.2 CLI Review Interface

```bash
# Show pending items with summaries
python tools/search/cli.py queue
# Output:
#  ID                              Score  Source         Title
#  20260415-bcbs-d579               10    bcbs-publi...  Revisions to IRRBB Standardised...
#  20260415-osfi-b12-amendment      9     osfi-publi...  OSFI B-12 Amendment — Behavioral...
#  20260415-risknet-eve-outlier     7     risk-net-i...  European banks face EVE outlier...

# Review a specific item — shows evaluation + content snippet
python tools/search/cli.py review 20260415-bcbs-d579

# Approve an item (moves to approved/)
python tools/search/cli.py approve 20260415-bcbs-d579

# Reject (with optional reason for the agent to learn from)
python tools/search/cli.py reject 20260415-risknet-eve-outlier --reason "duplicate of 20260410-eba-sot-survey"

# Bulk operations
python tools/search/cli.py approve-all --min-score 9
python tools/search/cli.py reject-all --max-score 5

# Trigger ingest of all approved items (calls research.py pipeline)
python tools/search/cli.py ingest-approved
```

### 5.3 Approval Friction Considerations

If reviewing each item takes 5 minutes, you'll abandon the system within two weeks. Design choices to keep friction low:

- **Single-screen review:** Show evaluation, content snippet, and decision buttons in one view
- **Default bias toward agent recommendation:** If agent says `recommend` with `high` confidence, approval is one keystroke
- **Bulk operations:** `--min-score 9` auto-approves obvious wins (e.g., direct BCBS or OSFI publications)
- **Smart batching:** Group by source or topic in the review view so context switches are minimized (e.g., review all NMD-related items together)
- **Rejection feedback:** Capture *why* you rejected so the evaluator can improve (logged but not auto-learned — that's a future iteration)

---

## 6. The Three Workflows

### 6.1 Polling Workflow

**Trigger:** Cron job (or manual `python tools/search/cli.py poll`)

**Logic:**
1. Load registry, filter to sources due based on cadence (daily/weekly/quarterly)
2. For each due source, fetch via configured strategy
3. Filter against `state.json` to remove already-seen URLs
4. Run Pass 1 classifier on each new item (title + summary only)
5. For items scoring `consider` or `recommend`, fetch full content
6. Run Pass 2 evaluation with wiki context
7. Write evaluation + content to `inbox/pending/`
8. Update `state.json` with seen URLs and last_scan timestamps

**Estimated cost per run:**
- 10 sources × ~15 new items/source = 150 Pass 1 calls × $0.001 = $0.15
- ~15 items pass to Pass 2 × $0.02 = $0.30
- Total: ~$0.45 per polling run, or ~$14/month for daily polling

### 6.2 Discovery Workflow

**Trigger:** Weekly cron or manual

**Logic:**
1. Load `discovery_topics` from registry
2. For each topic, formulate 2-3 web search queries (LLM-generated, bounded)
3. Run web searches (using web_search or a search API)
4. Filter results against state.json seen URLs and registered source URLs (to avoid re-finding what polling already covers)
5. Pass 1 classifier on each result
6. For passes, fetch and evaluate as in polling
7. Queue for approval

**Key design choice:** The LLM formulates search queries within a constrained budget (max 3 queries per topic per run). This prevents query explosion while still allowing some agent autonomy. Example expansion for "behavioral models non-maturity deposits": queries might target "NMD behavioral model assumptions 2026", "deposit pass-through rate empirical study", and "stable core deposits stratification IRRBB".

**Estimated cost per run:**
- 5 topics × 3 queries × 10 results = 150 candidates
- After dedup vs. state.json: ~40-60 new items
- Pass 1 + Pass 2 as above: ~$0.50 per discovery run, weekly = ~$2/month

### 6.3 Targeted Workflow

**Trigger:** On-demand from CLI

```bash
python tools/search/cli.py target \
  --description "Deutsche Bank Q1 reported EVE sensitivity above SOT threshold, find disclosure and analyst coverage" \
  --bank deutsche-bank \
  --max-results 5
```

**Logic:**
1. LLM formulates targeted search queries based on the description
2. Run searches, fetch top candidates
3. Identify likely primary source (bank disclosure, regulator publication) vs. secondary coverage
4. Run full evaluation
5. Queue with explicit grouping (primary + related)

**Use case:** You see a headline about an IRRBB-related event — a regulatory consultation, a bank's SOT breach, a methodology update — and want the agent to find the actual source documents and any related coverage. Faster than manual research, captures secondary sources you'd otherwise miss.

---

## 7. State Management

### 7.1 state.json Schema

```json
{
  "schema_version": 1,
  "last_updated": "2026-04-15T08:30:00Z",
  "sources": {
    "bcbs-publications": {
      "last_scan": "2026-04-15T08:30:00Z",
      "last_successful_scan": "2026-04-15T08:30:00Z",
      "consecutive_failures": 0,
      "items_seen": 412
    },
    "osfi-publications": {
      "last_scan": "2026-04-14T00:00:00Z",
      "last_successful_scan": "2026-04-14T00:00:00Z",
      "consecutive_failures": 0,
      "items_seen": 89
    }
  },
  "seen_urls": [
    "https://www.bis.org/bcbs/publ/d579.htm",
    "..."
  ],
  "content_hashes": {
    "a3f8...": "https://...",
    "...": "..."
  }
}
```

**Trade-off:** `seen_urls` can grow unbounded. Two options:
1. Truncate to last N=10,000 URLs (LRU)
2. Migrate to SQLite once the list exceeds 5,000 entries

Start with the in-memory list and migrate when it actually becomes a problem.

### 7.2 Failure Handling

If a source fails (network error, parse failure, auth issue):
- Increment `consecutive_failures`
- After 3 failures, log a warning and skip until manually investigated
- After 7 failures, mark source as `disabled: true` in registry (requires human action)

---

## 8. Integration Points

### 8.1 With existing research.py

The agentic search feature does NOT replace `research.py` — it feeds into it. Once an item is approved:

```python
# tools/search/cli.py ingest-approved
def ingest_approved():
    for item in iter_approved_items():
        # Reuse research.py's run_file_ingest_pipeline
        run_file_ingest_pipeline(
            file_path=item.content_path,
            wiki_root=wiki_root,
            bank_hint=item.bank_tags[0] if item.bank_tags else None,
            url_ref=item.url,
            with_updates=True,
            with_commentary=item.recommended_action == "ingest-with-commentary",
        )
        archive_item(item)
```

This means the heavy lifting (summarize, generate frontmatter, draft wiki updates) all reuses code you've already written and tested.

### 8.2 With the MCP server

The MCP server should expose three new tools so agents querying the wiki can also trigger search operations:

- `search_queue_status` — Returns count of pending/approved items (read-only)
- `search_trigger_targeted` — Trigger a targeted search (write, requires `--allow-ingest`)
- `search_register_source` — Add a source to the registry (write, requires `--allow-ingest`)

These let downstream agents say "check if there's been any recent regulatory updates on the standardized framework" or "find primary sources for this bank's latest EVE sensitivity disclosure" as part of a workflow.

### 8.3 With the lint tool

Add a new lint check: `inbox-staleness`. Flag pending items older than N days as needing review or rejection. Prevents the inbox from becoming a graveyard.

---

## 9. Cost and Volume Modeling

### 9.1 Conservative estimate (recommended starting config)

| Workflow | Frequency | Items/Run | Avg Cost/Run | Monthly Cost |
|----------|-----------|-----------|--------------|--------------|
| Polling (daily sources) | Daily | ~30 candidates, ~3 pass | $0.20 | $6 |
| Polling (weekly sources) | Weekly | ~80 candidates, ~8 pass | $0.40 | $2 |
| Polling (quarterly sources) | Quarterly | ~20 candidates, ~10 pass | $0.50 | $0.20 |
| Discovery | Weekly | ~50 candidates, ~6 pass | $0.50 | $2 |
| Targeted | On-demand (~4/month) | 5 results each | $0.20 | $1 |
| **Total** | | | | **~$11/month** |

Plus existing `research.py` ingest costs on approved items (~$0.10-0.50 per item depending on commentary). IRRBB volume is materially lower than AI/tech news — fewer items, but higher signal-to-noise on regulatory and primary-source content.

### 9.2 Cost discipline mechanisms

- `max_pages_per_run` cap in registry
- Two-pass classifier (Pass 1 with Haiku, Pass 2 with Sonnet)
- Topic filter pre-pass (regex, free) before any LLM call
- State.json deduplication
- Per-domain rate limiting (politeness + prevents runaway loops)

---

## 10. Implementation Phases

### Phase 1 — Foundation (week 1)
- Build registry schema and loader
- Implement RSS fetch (Tier 1 only)
- Build state.json + dedup
- Implement Pass 1 classifier
- Implement basic CLI queue + approve/reject

### Phase 2 — Polling MVP (week 2)
- Wire Pass 2 evaluator with wiki context
- Polling workflow end-to-end with 3-5 registered sources (start with BCBS, OSFI, OCC, EBA, Risk.net)
- Integration with existing `research.py` ingest pipeline
- Run for a week, calibrate evaluator thresholds

### Phase 3 — Discovery (week 3)
- Web search integration
- Discovery workflow with bounded query generation
- Discovery-specific dedup against registered sources

### Phase 4 — Hardening (week 4)
- Add requests fetcher (Tier 2) for non-RSS sources (Fed SR letters, bank IR pages)
- Targeted workflow
- Failure handling and source disabling
- Inbox staleness lint check
- Documentation

### Phase 5 — Optional (later)
- Chromium fetcher (Tier 3) — for ECB supervisory pages and similar JS-heavy regulator sites
- MCP server tools
- SQLite migration for state.json if URL list grows large
- Rejection feedback loop to improve evaluator over time
- PDF extraction for bank Pillar 3 disclosures and quarterly reports

---

## 11. Open Design Questions

These are worth thinking through before implementation, not after:

**Q1: How does the evaluator know what's in the wiki?**
Options: (a) Read `wiki/index.md` and a few targeted pages each call, (b) Embed the wiki and use vector search, (c) Use the MCP server's wiki_search tool. Recommendation: start with (a) — simpler, no embedding infrastructure, scales to your wiki size for now. The IRRBB wiki's organization by type (regulations/, concepts/, models/, entities/) maps cleanly to evaluator output, so the index is a reliable navigation surface.

**Q2: Should rejections feed back into the agent?**
Capturing rejection reasons is cheap. Actually using them to improve classification is harder (RLHF-style fine-tuning is overkill). Middle ground: include the last 10 rejection reasons in the Pass 1 prompt as "anti-examples." Test whether it actually helps before committing to the pattern.

**Q3: What about source archival and supersession?**
This matters more for IRRBB than for fast-moving topics — regulations supersede each other over years, not weeks (e.g., BCBS d368 superseding BCBS 2004 Principles, or OSFI B-12 revisions). When the agent detects a likely supersession, it should queue a flag rather than auto-archive. The original stays in `raw/` (per the wiki's immutability rule) and the derived wiki page gets a "Superseded by" cross-reference.

**Q4: Multi-language sources?**
Most authoritative IRRBB sources are published in English (BCBS, OSFI, EBA, OCC, ECB all publish English versions). Bank-level disclosures in non-English markets (Japan, Korea, parts of LatAm) may be EN-only or summary-only. Probably fine to scope English-only initially. Flag in the registry if a source is non-English so the evaluator can route appropriately.

**Q5: How do confidential / internal IRRBB sources fit?**
The wiki's source classification (`public` / `internal` / `confidential`) already handles this on the ingest side. The agentic search feature should NEVER fetch internal documents — those come in via the existing manual `research.py ingest --file` flow. The registry should only contain public-web sources. If you want to track an internal source (e.g., "internal ALM committee minutes"), do so in a separate manual workflow, not here.

**Q6: What's the failure mode if Claude API is down?**
The fetch layer should still run and queue raw items with `evaluation: null`. Human can then either wait for API to come back or manually triage.
