# The LLM Wiki Pattern — Reference

A persistent, compounding knowledge base maintained by an LLM. Instead of re-deriving
knowledge from raw documents on every query (the RAG approach), the agent incrementally
builds and maintains a structured, interlinked collection of markdown pages that **compound
over time**. (Pattern popularized by Andrej Karpathy's "LLM wiki" note.)

## Why it works

Knowledge-base maintenance is the tedious bookkeeping humans abandon: keeping
cross-references current, reconciling new sources against old, noticing contradictions,
filing things consistently. An LLM does this without fatigue. The division of labor:

| The LLM does | The human does |
|--------------|----------------|
| Summarize, cross-reference, file, lint | Curate sources, set direction |
| Flag contradictions and gaps | Resolve contradictions, make judgment calls |
| Keep the index and links consistent | Read, decide what matters |

## Three layers

1. **`raw/`** — immutable source documents. The agent reads, never writes.
2. **`wiki/`** — LLM-generated pages: summaries, entity/concept/topic pages, comparisons,
   open questions. Interlinked with `[[wikilinks]]`.
3. **Schema (`AGENTS.md` / `CLAUDE.md`)** — the conventions both human and agent follow.

## Core operations

- **Ingest** — a new source arrives; the agent reads it, summarizes, and updates the handful
  of wiki pages it touches (often creating stubs for newly-mentioned concepts).
- **Query** — answer from the wiki with citations; if the answer is a novel synthesis, file
  it back as a new page so the wiki gets richer.
- **Lint** — periodic health check: contradictions, stale claims, orphan pages, broken links,
  coverage gaps.

## Two key files

- **`index.md`** — a categorized catalog of every page with one-line summaries. The agent
  reads this FIRST on any query to find relevant pages. It's the navigation surface that keeps
  each operation within a sane token budget as the wiki grows.
- **`log.md`** — an append-only chronological record with grep-able entry prefixes
  (`ingest |`, `query |`, `lint |`, `synthesize |`).

## Page conventions

- Frontmatter on every page: `page_type, title, aliases, created, last_updated, source_count,
  sources, tags, confidence, provenance`.
- Sections: Summary · Key Points · Cross-References · Source Log · Open Issues.
- `confidence`: high | medium | low | contested. `provenance`: public | internal | mixed.
- **Contradictions are features** — never silently resolve; use a `> [!warning] Contradiction`
  callout naming both claims and their sources.
- **Wikilinks must resolve** — verify the target exists in `index.md` before writing `[[x]]`,
  else use `x [stub]`. Broken links are the #1 failure mode.

## No Obsidian dependency

`[[wikilinks]]` are just a markdown convention here. The bundled `tools/wiki_ui.py` renders
them as clickable links; `tools/lint_wiki.py` validates them. You can use any markdown editor
(or none). Obsidian works if you like it, but nothing requires it.

## Scaling

At ~100+ pages, supplement the flat `index.md` with the MCP server's BM25 search
(`tools/mcp_server.py`) or per-category sub-indexes. The index-first read pattern is what
keeps token usage bounded — don't load the whole wiki into context.
