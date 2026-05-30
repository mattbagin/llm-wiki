---
name: irrbb-wiki
description: >
  Use this skill whenever the user or agent needs IRRBB (Interest Rate Risk in the Banking Book)
  domain knowledge. Triggers include: any question about EVE, NII, behavioral modeling, NMD,
  prepayment risk, repricing risk, basis risk, yield curve risk, OSFI B-12, BCBS 368, Fed SR
  letters, stress testing for IRRBB, Pillar 2 / SOT, ALM risk measurement, or any regulatory
  or methodological question in the IRRBB domain. Also triggers when an agent needs to understand
  internal risk methodology, compare regulatory approaches across jurisdictions, or check whether
  a claim about IRRBB is consistent with current regulatory guidance. Additionally triggers for
  agentic search operations on the wiki — scanning registered sources for new IRRBB publications
  (polling), discovering new sources by topic (discovery), or finding the primary source for a
  specific IRRBB-related event (targeted). Do NOT use for credit risk, operational risk, market
  risk trading book, or liquidity risk unless the question specifically intersects with IRRBB
  (e.g., basis risk between funding and lending rates).
version: "1.2.0"
access: read-only
---

# IRRBB Risk Knowledge Wiki — Agent Skill

## What This Skill Provides

A persistent, interlinked knowledge base covering Interest Rate Risk in the Banking Book.
The wiki contains pre-synthesized knowledge from regulatory documents, internal methodology,
research papers, and vendor documentation. It is maintained by an LLM agent and updated
incrementally as new sources are ingested.

**Use this wiki instead of reasoning from first principles.** The synthesis, cross-references,
and contradiction flags are already done. Your job is to navigate, retrieve, and apply.

## Available Scripts

> **Paths:** in this skill the tooling lives under `scripts/`. `bootstrap.py` copies
> it into a new wiki repo under `tools/` — so commands you run inside a bootstrapped
> wiki use `tools/...`, while the source you edit when extending the skill is under
> `scripts/...`. The `tools/references/` docs in a bootstrapped wiki are copies of this
> skill's `references/`.

- [Bootstrap Directory Structure](./scripts/bootstrap.py) — Creates the full directory structure, schema files (AGENTS.md + CLAUDE.md), initial wiki files (index.md, log.md, overview.md), the `inbox/` approval queue, and the `tools/search/` agentic search package. Run once at project start.
- [Wiki Linter](./scripts/lint_wiki.py) — Lint tool for the IRRBB Risk Knowledge Wiki. Checks wiki health across multiple dimensions, run after any ingest or update.
- [MCP Server](./scripts/mcp_server.py) — Provides API access to the wiki for agents without filesystem access. Start the server and connect with the provided tools.
- [Research Pipeline](./scripts/research.py) — Single-source ingest: fetches web content, summarizes it with Claude, generates source frontmatter, and optionally drafts wiki page updates.
- [Agentic Search CLI](./scripts/search/cli.py) — Three-workflow scanner (polling, discovery, targeted) that queues source recommendations to `inbox/pending/` for human approval. Feeds approved items into the `research.py` pipeline. See [references/agentic-search.md](./references/agentic-search.md) for the full design and CLI reference.
- [Source Registry](./scripts/source_registry.yaml) — Starter registry of authoritative IRRBB sources (BCBS, OSFI, EBA, OCC, Fed, Risk.net). Edited by hand; the agent does NOT discover sources autonomously.

## Setup & Dependencies

Read-only wiki navigation needs nothing beyond filesystem access. The pipelines have
incremental dependencies:

| Capability | Install | Env vars |
|------------|---------|----------|
| Ingest pipeline (`research.py`) | `pip install anthropic httpx` | `ANTHROPIC_API_KEY` |
| Agentic search | `pip install -r tools/search/requirements.txt` | `ANTHROPIC_API_KEY`; optional `SEARCH_PROVIDER` (`ddg` default / `brave` / `serper` / `tavily`) + `SEARCH_API_KEY` |
| MCP server | `pip install mcp` | — |
| Browser fetch (Tier 3) | `pip install playwright && playwright install chromium` | — |
| Lint | none (stdlib only) | — |

No-LLM search commands (`queue`, `review`, `approve`, `reject`) need no API key.
`poll --dry-run` / `discover --dry-run` exercise fetch + evaluation without writing to
the queue. Models default to Haiku (Pass 1) and Sonnet (Pass 2); override with
`IRRBB_PASS1_MODEL` / `IRRBB_PASS2_MODEL`.

## How to Use the Wiki

### Step 1: Read the Index

Always start here. The index is the map of everything in the wiki.

```
wiki/index.md
```

The index lists every page organized by category (Regulations, Concepts, Models, Entities,
Comparisons, Open Questions) with a one-line summary and source count. Scan it to find the
pages relevant to your query.

### Step 2: Read Relevant Pages

Based on the index, read the 2-5 most relevant wiki pages. Each page follows a standard
structure:

- **Summary** — 2-3 sentence overview (start here for quick answers)
- **Key Points** — Core content
- **Regulatory Context** — What regulators require
- **Internal Position** — How the bank implements it (tagged `[internal]`)
- **Cross-References** — Follow `[[wikilinks]]` to related pages
- **Source Log** — Which raw sources support each claim
- **Open Issues** — Unresolved questions

### Step 3: Follow Cross-References

Wiki pages link to each other with `[[wikilinks]]`. Follow these to build a complete picture.
For example, `[[eve-sensitivity]]` links to `[[nii-sensitivity]]`, `[[repricing-gap]]`, and
`[[bcbs-368]]`. A question about EVE methodology might require reading 3-4 linked pages.

### Step 4: Cite Your Sources

When answering questions using wiki content, cite:
1. The wiki page you drew from (e.g., "per the EVE Sensitivity wiki page")
2. The underlying raw source (e.g., "BCBS 368, Section 4.2") from the page's Source Log

## Directory Layout

```
irrbb-wiki/
├── wiki/                    # <-- Your primary read target
│   ├── index.md             # START HERE — catalog of all pages
│   ├── log.md               # Chronological record of changes
│   ├── overview.md          # Wiki scope and purpose
│   ├── entities/            # Organizations, frameworks, systems
│   ├── concepts/            # Risk concepts and techniques
│   ├── regulations/         # Specific regulatory standards
│   ├── models/              # Internal and vendor risk models
│   ├── comparisons/         # Side-by-side analyses
│   └── open-questions/      # Unresolved analytical questions
├── raw/                     # Source documents (DO NOT MODIFY)
│   ├── regulatory/          # BCBS, OSFI, Fed, EBA
│   ├── internal/            # Bank methodology, policy, reviews
│   ├── research/            # Academic and industry research
│   └── vendor/              # Vendor model docs
└── tools/                   # CLI helpers (lint, search)
```

## Classification Rules

Wiki pages contain content derived from sources with different classification levels.
**You must respect these rules:**

| Classification | What You Can Do | What You Cannot Do |
|----------------|-----------------|-------------------|
| `public` | Freely use, quote, and reference in any context | — |
| `internal` | Use in internal-facing responses; always note `[internal]` | Share externally or with unauthorized users |
| `confidential` | Acknowledge existence by title only | Reveal content, parameters, or specifics |

### Verbatim / Protected Sources

Independent of classification, a source may be flagged `verbatim: true` (internal policies,
board-approved mandates, contracts, legal text). Its text is authoritative **as written**:

- Reproduce it **only as exact quotes**, inside a `> [!quote] Verbatim — do not edit` callout —
  never paraphrase, condense, reorder, or reword it (a reworded policy misstates the policy).
- **Comparing it against regulatory guidance is encouraged** (e.g. internal NMD policy vs.
  OSFI B-12 / BCBS 368) — do that on a separate `comparisons/` or `open-questions/` page, quoting
  the protected text verbatim and tagging your own analysis `[internal]` / `[inference]`.
- `classification` and `verbatim` are independent — an internal policy is typically both
  `classification: internal` **and** `verbatim: true`.

Check the `provenance` field in each page's frontmatter:
- `provenance: public` — safe for any context
- `provenance: internal` — internal use only
- `provenance: mixed` — contains both; check individual claims

## Page Frontmatter Reference

Every wiki page has YAML frontmatter with these fields:

```yaml
page_type: concept         # entity | concept | regulation | model | comparison | open-question
title: "EVE Sensitivity"
aliases: [...]             # Alternative names for search
confidence: high           # high | medium | low | contested
provenance: public         # public | internal | mixed
source_count: 3            # Number of supporting sources
tags: [eve, irrbb, ...]   # Topic tags
```

**Confidence levels guide how much weight to give claims:**
- `high` — Well-supported by multiple sources, no known contradictions
- `medium` — Supported but limited sources or some ambiguity
- `low` — Single source or preliminary analysis
- `contested` — Active disagreement between sources (check Open Issues)

## Handling Contradictions

When the wiki has flagged a contradiction, you'll see:

```markdown
> [!warning] Contradiction
> **Claim A**: [statement] (Source: [source X])
> **Claim B**: [statement] (Source: [source Y])
> **Status**: Unresolved
```

**Do not resolve contradictions yourself.** Present both positions to the user with their
sources and let the human apply judgment. This is especially important for regulatory
interpretations where reasonable people disagree.

## Query Patterns

### Simple factual lookup
1. Read `wiki/index.md`
2. Find the relevant page
3. Read the Summary section
4. Answer with citation

### Cross-cutting question (e.g., "How does NMD treatment differ between OSFI and BCBS?")
1. Read `wiki/index.md`
2. Check `wiki/comparisons/` for an existing comparison page
3. If none exists, read both `wiki/regulations/osfi-b12.md` and `wiki/regulations/bcbs-368.md`
4. Follow `[[nmd-behavioral-modeling]]` cross-references
5. Synthesize from the pre-built wiki pages

### Methodology question (e.g., "What assumptions does our NMD model make?")
1. Read `wiki/index.md`
2. Read the relevant `wiki/models/` page
3. Note the `provenance` and `classification` — this is likely `internal`
4. Tag your answer as `[internal]`

### "What don't we know?" question
1. Read `wiki/open-questions/` pages
2. Check `wiki/log.md` for recent lint findings
3. Present the gaps and unresolved issues

## Ingest Workflow (Requires Explicit Permission)

By default, this skill provides **read-only** access to the wiki. If the user or operator
explicitly requests an ingest, follow this workflow:

### Prerequisites
- The user has placed a new source file in `raw/`
- The user has explicitly said to ingest it (e.g., "ingest raw/regulatory/bcbs/new-doc.md")

### Ingest Steps
1. Read the source fully
2. Discuss key takeaways with the user before writing anything
3. Add YAML frontmatter to the source if missing:
   ```yaml
   ---
   title: "Document Title"
   source_type: regulatory|internal|research|vendor
   issuer: "Issuing body"
   date_published: YYYY-MM-DD
   date_ingested: YYYY-MM-DD
   status: current|superseded|draft
   classification: public|internal|confidential
   verbatim: false   # true for policies/mandates/contracts — quote only, never reword
   tags: []
   summary: ""
   ---
   ```
4. Create or update wiki pages — summaries, concepts, entities, models.
   For a `verbatim: true` source, reproduce its text only as exact quotes in a
   `> [!quote] Verbatim` block; put regulatory comparison/analysis on a separate page.
5. Flag contradictions with `> [!warning] Contradiction` callouts
6. Create stub pages for new concepts not yet covered
7. Validate all `[[wikilinks]]` resolve to existing pages
8. Update `wiki/index.md` — add new pages, update source counts
9. Append to `wiki/log.md`

### Ingest Self-Check
Before completing an ingest, verify:
- [ ] Source frontmatter is complete
- [ ] All new claims attributed to a specific source
- [ ] Contradictions with existing pages flagged
- [ ] `[internal]` tag on claims from internal sources
- [ ] Verbatim-protected text quoted exactly (not reworded)
- [ ] All `[[wikilinks]]` resolve (no broken links)
- [ ] `wiki/index.md` updated
- [ ] `wiki/log.md` entry appended

## MCP Server (Alternative Access)

If you don't have filesystem access to the wiki, connect to the MCP server:

```
MCP Server: irrbb-wiki-mcp
Transport: stdio
Command: python tools/mcp_server.py
```

Available tools:
- `wiki_search(query, tags?, page_type?)` — Search wiki pages
- `wiki_read(page_name)` — Read a specific page by name
- `wiki_list(page_type?, tag?)` — List pages with optional filters
- `wiki_ingest(source_path)` — Ingest a source (requires explicit permission)

## Agentic Search (Source Discovery & Monitoring)

The wiki ships with an agentic search package at `tools/search/` that scans for
new IRRBB sources and queues them for human approval before ingest. Three workflows
share the same approval queue:

| Workflow | When to use it |
|----------|----------------|
| **polling** | "Check what's new from BCBS / OSFI / EBA / OCC / Fed / Risk.net" — scheduled scan of registered sources |
| **discovery** | "Find sources about [topic]" without a specific URL — bounded web search against `discovery_topics` |
| **targeted** | "Find the primary source for [headline / event]" — on-demand research for a single announcement |

Nothing is auto-ingested. All items land in `inbox/pending/` and require approval
before being handed to `research.py`.

### Quick commands

```bash
python tools/search/cli.py poll                 # run polling against due sources
python tools/search/cli.py discover             # run discovery topics
python tools/search/cli.py target --description "BCBS d579 IRRBB consultation"
python tools/search/cli.py queue                # list pending items
python tools/search/cli.py review <item_id>     # show evaluation + content
python tools/search/cli.py approve <item_id>
python tools/search/cli.py reject <item_id> --reason "..."
python tools/search/cli.py approve-all --min-score 9
python tools/search/cli.py ingest-approved      # hand off to research.py pipeline
```

### When to read the reference

For any of the following, load [references/agentic-search.md](./references/agentic-search.md):
- Adding or modifying entries in `tools/source_registry.yaml`
- Implementing or debugging any module under `tools/search/`
- Understanding the two-pass evaluator output format
- Operator workflow (when to poll, approve, ingest, lint)
- Troubleshooting fetch failures or `consecutive_failures` warnings

### What this feature does NOT do

- Does not touch `raw/` directly — only writes to `inbox/`
- Does not fetch `internal` or `confidential` sources — those still come in via
  manual `research.py ingest --file`
- Does not discover sources autonomously — the registry is hand-maintained
- Does not modify wiki pages — that remains the ingest pipeline's job after approval

## Domain Scope

This wiki covers IRRBB including:
- EVE and NII sensitivity measurement
- Behavioral modeling (NMD, prepayments, term deposits)
- Repricing risk, basis risk, optionality risk, yield curve risk
- OSFI B-12, BCBS 368, Fed SR guidance
- Standardized vs internal model approaches
- Stress testing and scenario design
- Second-line independent review and challenge
- Pillar 2 / Supervisory Outlier Test (SOT)
- MSR classification and valuation
- SOFR/GC repo basis risk
