---
name: llm-wiki
description: >
  Use this skill to build and maintain a persistent, LLM-managed knowledge wiki on ANY
  topic — the domain-agnostic generalization of the "LLM wiki" pattern (incrementally
  synthesized, interlinked markdown that compounds over time instead of re-deriving
  knowledge from raw sources on every query). Triggers when the user wants to: start or
  bootstrap a knowledge base / wiki / "second brain" from documents; ingest and convert
  web pages, .docx, or .pdf files into wiki pages; synthesize, cross-reference, or
  organize notes and sources into a maintained knowledge base; browse or query such a
  wiki; or set up monitoring/discovery of new sources for a wiki. Provides a converter
  (web/.docx/.pdf → markdown), an ingest pipeline, a lint tool, an MCP server, a local
  browse/synthesis UI, and an opt-in agentic search package. For the IRRBB-specific
  banking-risk version, use the `irrbb-wiki` skill instead.
version: "1.0.0"
access: read-write
---

# LLM Knowledge Wiki — Agent Skill

## What This Skill Provides

Tooling and conventions for an LLM-maintained knowledge wiki on any subject. The wiki is a
three-layer artifact:

| Layer | Owner | Mutability |
|-------|-------|------------|
| `raw/` | Human | Immutable — the agent reads, never writes |
| `wiki/` | LLM | Synthesized, interlinked knowledge pages |
| `AGENTS.md` / `CLAUDE.md` | Co-evolved | The schema both follow |

Pages are organized by type: `entities/`, `concepts/`, `topics/`, `comparisons/`,
`open-questions/`. Cross-references use `[[kebab-case]]` wikilinks — a plain-markdown
convention rendered by the bundled UI. **No Obsidian dependency.**

## Available Scripts

> **Paths:** the source lives under `scripts/`; `bootstrap.py` copies it into a new wiki
> repo under `tools/`. Commands run inside a bootstrapped wiki use `tools/...`.

- [Bootstrap](./scripts/bootstrap.py) — Create a new wiki repo (structure, schema, initial pages, tools).
- [Convert](./scripts/convert.py) — Web page / .docx / .pdf / office files → Markdown (markitdown + fallbacks).
- [Research / Ingest](./scripts/research.py) — Fetch or convert a source, summarize it, draft wiki updates.
- [Wiki UI](./scripts/wiki_ui.py) — Local Flask app: browse, search, and synthesize new pages.
- [Lint](./scripts/lint_wiki.py) — Wiki health check (broken links, orphans, stale sources, leakage).
- [MCP Server](./scripts/mcp_server.py) — Expose the wiki to MCP agents (search/read/list/index).
- [Agentic Search](./scripts/search/cli.py) — Opt-in polling/discovery/targeted source monitoring.
- [Source Registry](./scripts/source_registry.yaml) — Hand-maintained list of sources to monitor.

## Setup & Dependencies

| Capability | Install | Env |
|------------|---------|-----|
| Convert (`convert.py`) | `pip install markitdown` (or `mammoth` / `pdfplumber`) | — |
| Ingest (`research.py`) | `pip install anthropic httpx` | `ANTHROPIC_API_KEY` |
| UI (`wiki_ui.py`) | `pip install flask markdown` | `ANTHROPIC_API_KEY` (synthesis) |
| Agentic search | `pip install -r tools/search/requirements.txt` | `ANTHROPIC_API_KEY`; optional `SEARCH_PROVIDER`+`SEARCH_API_KEY` |
| MCP server | `pip install mcp` | — |
| Lint | none (stdlib) | — |

Or install everything: `pip install -r tools/requirements.txt`. Override ingest/search models
with `WIKI_INGEST_MODEL` / `WIKI_PASS1_MODEL` / `WIKI_PASS2_MODEL`.

## Getting Started

```bash
python skills/llm-wiki/scripts/bootstrap.py ./my-wiki   # create the wiki repo
cd my-wiki && pip install -r tools/requirements.txt
python tools/convert.py paper.pdf -o raw/documents/paper.md   # convert a source
python tools/research.py ingest --file raw/documents/paper.md # summarize + draft updates
python tools/wiki_ui.py                                       # browse + synthesize
```

## Operating Principles

1. **Read `wiki/index.md` first** on any query — it's the map of all pages.
2. **Never modify `raw/`.**
3. **Attribute every claim** to a source via the page's Source Log.
4. **Contradictions are features** — flag them with `> [!warning] Contradiction` callouts; never silently resolve.
5. **Wikilinks must resolve** — verify the target exists in `index.md` before writing `[[link]]`, else use `name [stub]`.
6. **Respect classification** — never synthesize `confidential` content; tag `internal`-derived claims `[internal]`.
7. **Never reword verbatim sources** — a source flagged `verbatim: true` is reproduced only as exact quotes; compare and analyze it freely, but never paraphrase its text. See [Protected / Verbatim Sources](#protected--verbatim-sources).

## Protected / Verbatim Sources

Some documents are authoritative **as written** — internal policies, contracts, standards, legal
text. In a corporate setting a reworded policy can misstate the real policy, so these are flagged
`verbatim: true` in their source frontmatter and handled differently from ordinary sources.

| | Ordinary source | `verbatim: true` source |
|---|---|---|
| Wiki representation | Paraphrased/synthesized into wiki prose | Reproduced **only as exact quotes** in a `> [!quote] Verbatim — do not edit` block |
| Analysis & comparison | Yes | **Yes — encouraged** (e.g. policy vs. external regulation), on a *separate* page, quoting the protected text verbatim and tagging your words `[analysis]`/`[inference]` |
| Later edits to the text | Normal editing | The text in the verbatim block is **never** altered on any pass |

`classification` (public/internal/confidential) and `verbatim` are independent: an internal policy is
typically `classification: internal` **and** `verbatim: true`. Flag a source at ingest with
`python tools/research.py ingest --file policy.docx --classification internal --verbatim` — this
records the flags and makes the drafted updates quote-only instead of paraphrased.

## Workflows

### Ingest a source
1. Convert if needed (`convert.py`) or place markdown/text directly in `raw/`.
2. Read it fully; discuss key takeaways with the human. Confirm `classification` and whether it is
   `verbatim` (policy/contract/standard/legal text).
3. Create/update wiki pages (entities/concepts/topics/comparisons/open-questions).
   For a `verbatim` source, reproduce its text only as exact quotes in a `> [!quote] Verbatim` block
   and put comparison/analysis on a separate page.
4. Flag contradictions; create stubs for new concepts.
5. Update `wiki/index.md`; append to `wiki/log.md`; verify all wikilinks resolve.

**Self-check:** frontmatter complete · claims attributed · contradictions flagged · `[internal]` tags · verbatim text quoted (not reworded) · links resolve · index updated · log appended.

### Query
Read `index.md` → read the 3-8 most relevant pages → synthesize with citations to wiki pages and raw sources. If the answer is a novel synthesis, offer to file it (or use the UI's synthesize feature).

### Lint
Run `python tools/lint_wiki.py` after ~5 ingests. Fix broken links, orphans, stale sources, confidence/leakage findings.

## Converting Sources

`tools/convert.py` turns web pages, `.docx`, `.pdf`, and office files into Markdown:

```bash
python tools/convert.py https://example.com/article -o raw/web/article.md
python tools/convert.py report.docx -o raw/documents/report.md
python tools/convert.py paper.pdf                       # → stdout
```

It prefers Microsoft `markitdown` (one library for all formats) and falls back to
`mammoth` (.docx) / `pdfplumber` (.pdf) / a built-in HTML extractor, so it still works
where markitdown can't be installed. See [references/converting-sources.md](./references/converting-sources.md).

## The Wiki UI

`python tools/wiki_ui.py` serves a local browser at `http://127.0.0.1:8000` to read pages
(rendered markdown with clickable `[[wikilinks]]`), search, and **synthesize a new page**
(ask a question → it reads the most relevant existing pages → the LLM drafts a page → you
review and save it). Conversions/ingest/web-search stay in the CLI.
See [references/wiki-ui.md](./references/wiki-ui.md).

## Agentic Search (Opt-In Source Monitoring)

The wiki ships with `tools/search/` — polling (scan registered feeds), discovery (bounded
web search over topics of interest), and targeted (find the primary source for an event).
Everything lands in `inbox/pending/` for human approval before being handed to the ingest
pipeline; nothing is auto-ingested. Edit `tools/source_registry.yaml` to point it at sources
for your domain. Full reference: [references/agentic-search.md](./references/agentic-search.md).

## The Pattern

This skill implements the "LLM wiki" pattern: an LLM maintains the tedious bookkeeping
(cross-references, consistency, updates) that humans abandon, while the human curates and
directs. See [references/wiki-pattern.md](./references/wiki-pattern.md) for the rationale and
conventions.
