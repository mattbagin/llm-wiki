#!/usr/bin/env python3
"""
Bootstrap script for an LLM Knowledge Wiki (domain-agnostic).

Creates the directory structure, schema files (AGENTS.md + CLAUDE.md), initial
wiki files (index.md, log.md, overview.md), the inbox/ approval queue, and copies
the tooling (research.py, convert.py, wiki_ui.py, lint_wiki.py, mcp_server.py and
the agentic-search package) into tools/.

Usage:
    python bootstrap.py [target_directory]    # default: ./llm-wiki

No Obsidian dependency — [[wikilinks]] are a plain-markdown convention rendered
by the bundled UI (tools/wiki_ui.py).
"""

import sys
from datetime import date
from pathlib import Path

DIRECTORIES = [
    # Raw sources (immutable, human-owned) — organized by ingest form, not domain.
    "raw/documents",      # converted .docx/.pdf/office files
    "raw/web",            # fetched web articles/pages
    "raw/pdf",            # pdf-derived markdown
    "raw/notes",          # personal notes, transcripts, clippings
    "raw/assets",         # images and other binaries referenced by sources
    # Wiki pages (LLM-owned)
    "wiki/entities",
    "wiki/concepts",
    "wiki/topics",
    "wiki/comparisons",
    "wiki/open-questions",
    # Tools
    "tools",
    "tools/search",
    # Approval queue for the agentic search feature (git-ignored)
    "inbox/pending",
    "inbox/approved",
    "inbox/rejected",
]

SCHEMA_CONTENT = """\
# LLM Knowledge Wiki

You are a disciplined maintainer of a knowledge wiki. Your job is to build and maintain a
persistent, interlinked collection of markdown pages that synthesize knowledge from curated
source documents. The wiki COMPOUNDS: every ingest and every good answer makes it richer.

## Principles

1. **The wiki compounds.** Never discard synthesis that could be filed as a page.
2. **Sources are immutable.** Never modify files in `raw/`. Read, cite, but never edit them.
3. **Attribution is mandatory.** Every factual claim traces to a specific source in `raw/`,
   recorded in the page's Source Log.
4. **Contradictions are features.** When sources disagree, flag both positions with a
   `> [!warning] Contradiction` callout. Never silently pick a side.
5. **Wikilinks must resolve.** Before writing `[[any-link]]`, verify the target exists in
   `wiki/index.md`. If it doesn't, create a stub or use plain text with `topic [stub]`.
6. **Respect classification.** Never synthesize `confidential` source content into wiki pages.
   Mark claims from `internal` sources with `[internal]`.
7. **Verbatim sources are never reworded.** A source flagged `verbatim: true` (e.g. an internal
   policy, contract, or legal text) is authoritative as written. Reproduce its text only as exact
   quotes — never paraphrase, summarize-as-fact, condense, or "clarify" it. You ARE encouraged to
   analyze and compare it (see "Verbatim / protected sources" below).

## Directory Layout

- `raw/` — Immutable source documents (`documents/`, `web/`, `pdf/`, `notes/`, `assets/`)
- `wiki/` — LLM-maintained knowledge pages
- `wiki/index.md` — Categorized catalog of all pages (read this FIRST on any query)
- `wiki/log.md` — Append-only chronological record of operations
- `tools/` — CLI helpers (convert, research/ingest, lint, search) and the browse/synthesis UI

## Page Types

| Type | Directory | Purpose |
|------|-----------|---------|
| entity | `wiki/entities/` | A specific organization, person, product, place |
| concept | `wiki/concepts/` | A reusable idea, method, or definition |
| topic | `wiki/topics/` | A subject area or theme that gathers related material |
| comparison | `wiki/comparisons/` | Side-by-side analysis of two or more things |
| open-question | `wiki/open-questions/` | An unresolved question worth tracking |

## Source Frontmatter

```yaml
---
title: "Document Title"
source_type: web-article      # web-article | research-paper | official-document | report | documentation | reference | notes | transcript | other
source_quality: secondary     # authoritative | primary | secondary | reference | media
issuer: "Publisher or author"
date_published: 2026-01-01
date_ingested: 2026-01-01
status: current               # current | superseded | draft
classification: public        # public | internal | confidential
verbatim: false               # true = reproduce only as exact quotes; never reword (see below)
entity_tags: []
topic_tags: []
url: ""
summary: ""
---
```

`classification` and `verbatim` are independent. `classification` governs *whether/how* a source
may be synthesized or shared; `verbatim` governs *whether its wording may be changed*. An internal
policy is commonly `classification: internal` **and** `verbatim: true`.

## Verbatim / Protected Sources

Some documents are authoritative **as written** — internal policies, standards, contracts, legal
text. In a corporate setting a reworded policy is worse than no policy: it can misstate what the
document actually says. For any source with `verbatim: true`:

**Do:**
- Reproduce its text **only as exact quotes**, inside a callout that marks it protected:
  ```markdown
  > [!quote] Verbatim — internal policy, do not edit
  > <exact text, unchanged>
  ```
- **Compare and analyze it** against external sources — this is encouraged. File the analysis on a
  separate `comparisons/`, `topic`, or `open-question` page, quoting the policy verbatim where you
  reference it and clearly separating your analysis with `[analysis]` / `[inference]` tags.
- If you reproduce the document as its own wiki page (a *verbatim mirror*), keep the quoted policy
  text in the protected callout untouched; only the surrounding frontmatter, headings, Source Log,
  and Cross-References may be added or updated.

**Never:**
- Paraphrase, summarize-as-fact, condense, reorder, modernize, or "improve" the protected text.
- Merge protected text with your own wording so the two become indistinguishable.
- Edit the text inside a `> [!quote] Verbatim` block on any later pass.

A short, faithful *summary for navigation* is fine **only** if it is clearly labelled as your
summary (e.g. under a "Summary [analysis]" heading) and sits outside the protected quote block — the
policy's own words are never altered.

## Wiki Page Frontmatter (required on every page)

```yaml
---
page_type: concept            # entity | concept | topic | comparison | open-question
title: "Page Title"
aliases: []
created: 2026-01-01
last_updated: 2026-01-01
source_count: 0
sources: []
tags: []
confidence: medium            # high | medium | low | contested
provenance: public            # public | internal | mixed
---
```

Sections: Summary, Key Points, Cross-References, Source Log, Open Issues.

## Workflows

### Ingest (a source is added to raw/, or converted in via tools/convert.py)
1. Read the source fully
2. Discuss key takeaways with the human
3. Add/confirm source frontmatter (including `verbatim:` — ask if a policy/contract/standard)
4. Create/update wiki pages; flag contradictions; create stubs for new concepts.
   **If `verbatim: true`:** do NOT paraphrase the source into wiki prose. Instead reproduce it as
   exact quotes in a `> [!quote] Verbatim — do not edit` block, and put any comparison/analysis on a
   separate page (see "Verbatim / protected sources").
5. Update `wiki/index.md` and append to `wiki/log.md`
6. Validate all wikilinks resolve

### Query
1. Read `wiki/index.md` → read relevant pages → synthesize with citations
2. If the answer is a novel synthesis, offer to file it as a new page

### Lint (run weekly or every ~5 ingests): `python tools/lint_wiki.py`
Orphans, broken wikilinks, stale sources, confidence downgrades, coverage gaps, leakage.

## Tools

- `python tools/convert.py <file|url> -o out.md` — web/.docx/.pdf → markdown
- `python tools/research.py ingest <url|--file path>` — fetch/convert, summarize, draft updates
- `python tools/wiki_ui.py` — local browse + page-synthesis UI (http://127.0.0.1:8000)
- `python tools/lint_wiki.py` — wiki health check
- `python tools/search/cli.py poll|discover|target` — agentic source monitoring (opt-in)
"""

TODAY = date.today().isoformat()


def index_content() -> str:
    return f"""\
---
page_type: index
title: "Wiki Index"
created: {TODAY}
last_updated: {TODAY}
---

# Wiki Index

Last updated: {TODAY} | Total pages: 1 | Sources ingested: 0

## Entities

_No pages yet._

## Concepts

_No pages yet._

## Topics

_No pages yet._

## Comparisons

_No pages yet._

## Open Questions

_No pages yet._
"""


def log_content() -> str:
    return f"""\
# Wiki Log

## [{TODAY}] init | Wiki bootstrapped
- Created directory structure, schema files, and initial pages
- Ready for first source ingest
"""


def overview_content() -> str:
    return f"""\
---
page_type: overview
title: "Knowledge Wiki — Overview"
created: {TODAY}
last_updated: {TODAY}
confidence: high
provenance: public
---

# Knowledge Wiki

## Purpose

A persistent, compounding knowledge base maintained by an LLM agent and read by a human.
Rather than re-deriving knowledge from raw sources on every query, the agent incrementally
builds interlinked markdown pages that synthesize what the sources say.

## How to Use

1. **Add sources** — drop files in `raw/`, or run `python tools/convert.py <file|url>` then ingest.
2. **Ingest** — `python tools/research.py ingest ...`, or tell the agent to ingest a source.
3. **Ask questions** — the agent reads `wiki/index.md`, finds relevant pages, and synthesizes.
4. **Browse / synthesize** — `python tools/wiki_ui.py` for a local UI.
5. **Lint** — `python tools/lint_wiki.py` to check wiki health.

See `AGENTS.md` / `CLAUDE.md` for the full schema: page formats, workflows, and rules.
"""


def gitignore_content() -> str:
    return """\
.DS_Store
Thumbs.db
*.swp
.idea/
.vscode/
__pycache__/
*.pyc
.venv/
venv/
.qmd/

# Agentic search approval queue — local-only, not committed
inbox/
"""


def initial_state_json() -> str:
    return '{\n  "schema_version": 1,\n  "last_updated": null,\n  "sources": {},\n  "seen_urls": [],\n  "content_hashes": {}\n}\n'


def gitkeep_readme(purpose: str) -> str:
    return f"# {purpose}\n\nPlace source files here.\n"


def bootstrap(target: Path) -> None:
    if target.exists() and any(target.iterdir()):
        print(f"Error: {target} already exists and is not empty.")
        sys.exit(1)

    print(f"Bootstrapping LLM wiki in: {target.resolve()}\n")
    for d in DIRECTORIES:
        (target / d).mkdir(parents=True, exist_ok=True)

    for rel, purpose in [
        ("raw/documents", "Converted Documents (.docx/.pdf/office)"),
        ("raw/web", "Fetched Web Articles"),
        ("raw/pdf", "PDF-Derived Markdown"),
        ("raw/notes", "Notes, Transcripts, Clippings"),
        ("raw/assets", "Images and Binaries"),
    ]:
        (target / rel / "README.md").write_text(gitkeep_readme(purpose), encoding="utf-8")

    (target / "AGENTS.md").write_text(SCHEMA_CONTENT, encoding="utf-8")
    (target / "CLAUDE.md").write_text(SCHEMA_CONTENT, encoding="utf-8")
    print("  Created AGENTS.md, CLAUDE.md")

    (target / "wiki" / "index.md").write_text(index_content(), encoding="utf-8")
    (target / "wiki" / "log.md").write_text(log_content(), encoding="utf-8")
    (target / "wiki" / "overview.md").write_text(overview_content(), encoding="utf-8")
    (target / ".gitignore").write_text(gitignore_content(), encoding="utf-8")
    print("  Created wiki/index.md, wiki/log.md, wiki/overview.md, .gitignore")

    script_dir = Path(__file__).parent
    for src_name, dest_rel in [
        ("lint_wiki.py", "tools/lint_wiki.py"),
        ("mcp_server.py", "tools/mcp_server.py"),
        ("research.py", "tools/research.py"),
        ("convert.py", "tools/convert.py"),
        ("wiki_ui.py", "tools/wiki_ui.py"),
        ("source_registry.yaml", "tools/source_registry.yaml"),
        ("requirements.txt", "tools/requirements.txt"),
    ]:
        src = script_dir / src_name
        if src.exists():
            (target / dest_rel).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"  Created {dest_rel}")

    search_src = script_dir / "search"
    if search_src.is_dir():
        search_dst = target / "tools" / "search"
        search_dst.mkdir(parents=True, exist_ok=True)
        for pattern in ("*.py", "requirements.txt"):
            for f in search_src.glob(pattern):
                (search_dst / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        print("  Created tools/search/ package")

    (target / "inbox" / "state.json").write_text(initial_state_json(), encoding="utf-8")
    for sub in ("pending", "approved", "rejected"):
        (target / "inbox" / sub / ".gitkeep").write_text("", encoding="utf-8")

    refs_src = script_dir.parent / "references"
    if refs_src.is_dir():
        refs_dst = target / "tools" / "references"
        refs_dst.mkdir(parents=True, exist_ok=True)
        for ref in refs_src.glob("*.md"):
            (refs_dst / ref.name).write_text(ref.read_text(encoding="utf-8"), encoding="utf-8")
        print("  Created tools/references/")

    print(f"\nDone. Created {len(DIRECTORIES)} directories and initial files.\n\nNext steps:")
    print(f"  1. cd {target}")
    print("  2. git init && git add -A && git commit -m 'Bootstrap LLM wiki'")
    print("  3. pip install -r tools/requirements.txt")
    print("  4. python tools/convert.py <file-or-url> -o raw/notes/source.md   # convert a source")
    print("  5. python tools/research.py ingest --file <doc.pdf>               # or ingest directly")
    print("  6. python tools/wiki_ui.py                                        # browse + synthesize")


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / "llm-wiki"
    bootstrap(target)


if __name__ == "__main__":
    main()
