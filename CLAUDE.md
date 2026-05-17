# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

This is a **skill repository** — it contains the tooling and Claude Code skill definition to bootstrap and maintain an LLM-managed IRRBB (Interest Rate Risk in the Banking Book) knowledge wiki. It does not contain the wiki itself. The wiki is created as a separate directory/repo via `bootstrap.py`.

Key files:
- `irrbb-llm-wiki-spec.md` — Full design specification for the wiki system
- `skills/irrbb-wiki/SKILL.md` — Claude Code skill definition (what agents see when the skill loads)
- `skills/irrbb-wiki/scripts/bootstrap.py` — One-time setup script; creates the full wiki directory structure, schema files, and initial wiki pages
- `skills/irrbb-wiki/scripts/lint_wiki.py` — Health-check tool for a live wiki instance
- `skills/irrbb-wiki/scripts/mcp_server.py` — MCP server providing API access to the wiki
- `skills/irrbb-wiki/scripts/research.py` — Web research pipeline: fetches content, summarizes via Claude, drafts source frontmatter and wiki page updates

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

### Cross-Reference Convention

Wikilinks use `[[kebab-case-filename]]` (Obsidian-compatible). Always verify a link target exists in `wiki/index.md` before writing it. Use `topic name [stub]` for concepts not yet covered.

## LLM Wiki Operating Principles

When working in a bootstrapped wiki instance:

1. **Read `wiki/index.md` first** on any query — it's the map of all pages.
2. **Never modify `raw/`** — it's the human's source of truth.
3. **Contradictions are features** — flag them with `> [!warning] Contradiction` callouts; never silently resolve by picking a side.
4. **Ingest checklist**: source frontmatter complete → claims attributed → contradictions flagged → `[internal]` tags on internal claims → all wikilinks resolve → `index.md` updated → `log.md` entry appended.
5. **After ~5 ingests**, run `python tools/lint_wiki.py` to check for orphan pages, broken links, stale sources, and confidence issues.
