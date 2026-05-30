# The Wiki UI — Reference

`tools/wiki_ui.py` is a thin local Flask app for **reading the wiki and creating new pages by
synthesis**. Conversions, ingest, and web search deliberately stay in the CLI — the UI is just
"browse what's there + write new pages from what's already in the wiki".

## Running it

```bash
pip install flask markdown        # markdown optional (UI falls back to <pre> without it)
python tools/wiki_ui.py           # http://127.0.0.1:8000
python tools/wiki_ui.py --port 8080 --repo-root /path/to/wiki
```

Synthesis (and any LLM call) needs `ANTHROPIC_API_KEY`.

## What you can do

- **Browse** — pages grouped by type in the sidebar; click to read. Markdown is rendered to
  HTML and `[[wikilinks]]` become clickable in-app links.
- **Search** — type in the search box; results come from the same BM25 index as the MCP server
  (`mcp_server.WikiIndex`), ranked by title/alias/tag/body match.
- **Synthesize a new page** — click "+ Synthesize page", ask a question. The app finds the most
  relevant existing pages, asks the LLM to draft a new page grounded **only** in that content
  (citing pages with `[[wikilinks]]`), and shows you the draft. Edit it, set a name + page type,
  and **Save** writes it to `wiki/<type-dir>/<name>.md`, appends a `log.md` entry, and best-effort
  adds it to `index.md` under the matching section.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Single-page browser (HTML/JS, no build step) |
| GET | `/api/pages` | List pages (name, title, page_type) |
| GET | `/api/page/<name>` | Rendered page HTML + metadata |
| GET | `/api/search?q=` | Ranked search results |
| POST | `/api/synthesize` | `{question}` → drafts a page from relevant pages |
| POST | `/api/save` | `{name, page_type, content}` → writes the page |

## Design notes

- Reuses `mcp_server.WikiIndex` for parsing/search and `research.get_client` + `research.DEFAULT_MODEL`
  for synthesis — no duplicate logic. (The skill's `mcp_server.py` defers its `mcp` import so it can
  be imported here without the `mcp` package installed.)
- Synthesis is grounded: the prompt instructs the model to use only the provided pages and to put
  unknowns in an Open Issues section rather than inventing facts. **Review every draft before saving** —
  it's a starting point, not an authority.
- The whole frontend is one inline HTML/JS string (`INDEX_HTML`) — easy to customize, no toolchain.
