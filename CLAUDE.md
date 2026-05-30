# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

This is a **skill repository** — it contains the tooling and Claude Code skill definitions to bootstrap and maintain LLM-managed knowledge wikis. It does not contain a wiki itself; a wiki is created as a separate directory/repo via a skill's `bootstrap.py`.

Two skills live here:
- **`skills/irrbb-wiki/`** — domain-specific wiki for IRRBB (Interest Rate Risk in the Banking Book).
- **`skills/llm-wiki/`** — domain-agnostic generalization (any topic), Obsidian-free, with document→markdown conversion (`convert.py`) and a local browse/synthesis UI (`wiki_ui.py`).

Key files (irrbb-wiki):
- `irrbb-llm-wiki-spec.md` — Full design specification for the wiki system
- `agentic-search-spec.md` — Design spec for the agentic search / monitoring feature
- `skills/irrbb-wiki/SKILL.md` — Claude Code skill definition (what agents see when the skill loads)
- `skills/irrbb-wiki/scripts/bootstrap.py` — One-time setup; creates the wiki directory structure, schema files, initial pages, the `inbox/` queue, and the `tools/search/` package
- `skills/irrbb-wiki/scripts/lint_wiki.py` — Health-check tool for a live wiki instance
- `skills/irrbb-wiki/scripts/mcp_server.py` — MCP server providing API access to the wiki (BM25 search, read, list, index, optional ingest)
- `skills/irrbb-wiki/scripts/research.py` — Web research pipeline: fetches content, summarizes via Claude, drafts source frontmatter and wiki page updates
- `skills/irrbb-wiki/scripts/search/` — Agentic search package (polling / discovery / targeted), feeding an approval queue that hands off to `research.py`
- `skills/irrbb-wiki/scripts/source_registry.yaml` — Hand-maintained registry of sources to monitor
- `skills/irrbb-wiki/references/agentic-search.md` — Reference for the search package (module map, providers, setup)

## Common Commands

Bootstrap a new wiki:
```bash
python skills/irrbb-wiki/scripts/bootstrap.py [target_directory]
# Default target: ./irrbb-wiki
```

Lint an existing wiki (run from the wiki's repo root, not this repo):
```bash
python tools/lint_wiki.py
python tools/lint_wiki.py --wiki-dir ./wiki --raw-dir ./raw
python tools/lint_wiki.py --json           # Machine-readable output
```

Start the MCP server (from within a bootstrapped wiki repo):
```bash
python tools/mcp_server.py                 # Read-only
python tools/mcp_server.py --allow-ingest  # With write access
```

Agentic search (from within a bootstrapped wiki repo; needs `ANTHROPIC_API_KEY`):
```bash
pip install -r tools/search/requirements.txt
python tools/search/cli.py poll            # Scan registered sources by cadence
python tools/search/cli.py poll --dry-run  # Fetch + evaluate, write nothing
python tools/search/cli.py discover        # Bounded web search over discovery_topics
python tools/search/cli.py target --description "BCBS d579 IRRBB consultation"
python tools/search/cli.py queue           # List pending items (no API key needed)
python tools/search/cli.py approve <id>    # / review / reject / approve-all --min-score N
python tools/search/cli.py ingest-approved # Hand approved items to research.py
```

Generalized `llm-wiki` skill extras (from a bootstrapped llm-wiki repo):
```bash
python tools/convert.py <file-or-url> -o out.md   # docx/pdf/web → markdown
python tools/wiki_ui.py                            # Local browse + synthesis UI (localhost:8000)
```

Environment variables:
- `ANTHROPIC_API_KEY` — required for `research.py`, agentic-search LLM calls, and UI synthesis.
- `SEARCH_PROVIDER` (`ddg` default | `brave` | `serper` | `tavily`) + `SEARCH_API_KEY` — discovery/targeted web search.
- `IRRBB_PASS1_MODEL` / `IRRBB_PASS2_MODEL` — override the search classifier/evaluator models.

## Architecture

### Three-Layer Wiki Model

Once bootstrapped, a wiki instance has three layers:

| Layer | Owner | Mutability |
|-------|-------|------------|
| `raw/` | Human | Immutable — LLM reads, never writes |
| `wiki/` | LLM | LLM-writable — synthesized knowledge pages |
| `AGENTS.md` / `CLAUDE.md` | Co-evolved | Both can propose changes |

### Wiki Page Types

Pages live under `wiki/` organized by type: `entities/`, `concepts/`, `regulations/`, `models/`, `comparisons/`, `open-questions/`. Every page has YAML frontmatter with `page_type`, `confidence` (high/medium/low/contested), and `provenance` (public/internal/mixed).

### Source Classification

Sources in `raw/` carry a `classification` field:
- `public` — freely synthesize into wiki
- `internal` — synthesize but tag derived claims with `[internal]`
- `confidential` — reference by title only, never synthesize content

They also carry an independent `verbatim` flag. `verbatim: true` (internal policies, board mandates, contracts, legal text) means the text is authoritative *as written*: reproduce it only as exact quotes in a `> [!quote] Verbatim` block, never paraphrase it — though comparing it against external/regulatory guidance on a separate page is encouraged. `classification` governs *whether/how* a source is synthesized; `verbatim` governs *whether its wording may change*. Ingest with `research.py ingest ... --classification internal --verbatim`; both skills' lint tools surface `verbatim: true` sources for review.

### Cross-Reference Convention

Wikilinks use `[[kebab-case-filename]]`. Always verify a link target exists in `wiki/index.md` before writing it. Use `topic name [stub]` for concepts not yet covered. (The `llm-wiki` skill renders these links in its UI; neither skill requires Obsidian.)

### Agentic Search Package (`scripts/search/`)

A monitoring/discovery layer that feeds the human-approval queue, never `raw/` directly. Pipeline:

```
source_registry.yaml → fetch (RSS / requests / Chromium) → Pass 1 classify (Haiku)
  → lazy full-content fetch → Pass 2 evaluate w/ wiki context (Sonnet)
  → inbox/pending/ (approval queue) → research.py ingest (after human approval)
```

Module map: `registry.py` (config), `fetch.py` (tiered fetch + listing parse), `websearch.py` (pluggable search for discovery/targeted), `llm.py` (shared Anthropic client + models), `evaluator.py` (two-pass + wiki-context), `pipeline.py` (shared dedup→classify→fetch→evaluate→queue gate), `polling.py`/`discovery.py`/`targeted.py` (workflows), `queue.py` (filesystem queue + `state.json`), `cli.py` (entry points + `ingest-approved`). Cost discipline: regex topic-filter pre-pass, Haiku→Sonnet two-pass, `max_pages_per_run`, URL+content-hash dedup, per-domain delay, bounded discovery queries. Full reference: `skills/irrbb-wiki/references/agentic-search.md`.

## Developing the Scripts (for coding agents)

- **Dependencies are lazy where possible.** `anthropic`, `feedparser`, `playwright`, `markitdown`, `mammoth`, `pdfplumber`, `flask` are imported inside functions so the package imports and the no-LLM commands run without them. Keep new optional deps lazy.
- **`raw/` is immutable** — scripts must only read it. Writes go to `wiki/`, `inbox/`, or stdout drafts.
- **Smoke-testing without API/network:** `python -m py_compile scripts/**/*.py`; `load_registry` on `source_registry.yaml`; `ApprovalQueue` write→approve round-trip in a temp dir; `topic_filter_match` / `is_source_due`; `websearch.get_provider()`. Use `cli.py ... --dry-run` for fetch+evaluate without writes. End-to-end runs need `ANTHROPIC_API_KEY` and network.
- **Two skills share the same patterns.** When changing a shared convention (page frontmatter, wikilink rules, queue schema), update both `skills/irrbb-wiki/` and `skills/llm-wiki/`, plus their `bootstrap.py` schema strings.

## LLM Wiki Operating Principles

When working in a bootstrapped wiki instance:

1. **Read `wiki/index.md` first** on any query — it's the map of all pages.
2. **Never modify `raw/`** — it's the human's source of truth.
3. **Contradictions are features** — flag them with `> [!warning] Contradiction` callouts; never silently resolve by picking a side.
4. **Ingest checklist**: source frontmatter complete → claims attributed → contradictions flagged → `[internal]` tags on internal claims → all wikilinks resolve → `index.md` updated → `log.md` entry appended.
5. **After ~5 ingests**, run `python tools/lint_wiki.py` to check for orphan pages, broken links, stale sources, and confidence issues.
