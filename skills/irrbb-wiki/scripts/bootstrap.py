#!/usr/bin/env python3
"""
Bootstrap script for the IRRBB Risk Knowledge Wiki.

Creates the full directory structure, schema files (AGENTS.md + CLAUDE.md),
and initial wiki files (index.md, log.md, overview.md).

Usage:
    python bootstrap.py [target_directory]

    If no target directory is specified, creates the wiki in the current directory
    under a folder called 'irrbb-wiki'.
"""

import sys
from datetime import date
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# Directory structure
# ─────────────────────────────────────────────────────────────

DIRECTORIES = [
    # Raw sources (immutable, human-owned)
    "raw/regulatory/bcbs",
    "raw/regulatory/osfi",
    "raw/regulatory/fed",
    "raw/regulatory/eba",
    "raw/regulatory/other-regulators",
    "raw/internal/methodology",
    "raw/internal/policy",
    "raw/internal/models",
    "raw/internal/reviews",
    "raw/internal/meeting-notes",
    "raw/research/papers",
    "raw/research/articles",
    "raw/research/presentations",
    "raw/vendor/model-docs",
    "raw/vendor/release-notes",
    "raw/assets/images",
    # Wiki pages (LLM-owned)
    "wiki/entities",
    "wiki/concepts",
    "wiki/regulations",
    "wiki/models",
    "wiki/comparisons",
    "wiki/open-questions",
    # Tools
    "tools",
]

# ─────────────────────────────────────────────────────────────
# Schema file content (shared between AGENTS.md and CLAUDE.md)
# ─────────────────────────────────────────────────────────────

SCHEMA_CONTENT = """\
# IRRBB Risk Knowledge Wiki

You are a disciplined wiki maintainer for an IRRBB (Interest Rate Risk in the Banking Book)
knowledge base. Your job is to build and maintain a persistent, interlinked collection of
markdown pages that synthesize knowledge from curated source documents.

## Principles

1. **The wiki compounds.** Every ingest and every good answer makes the wiki richer. Never
   discard synthesis that could be filed as a page.
2. **Sources are immutable.** Never modify files in `raw/`. Read from them, cite them, but
   the human owns that layer.
3. **Attribution is mandatory.** Every factual claim in the wiki must trace to a specific
   source in `raw/`. Use the Source Log table on each page.
4. **Contradictions are features.** When sources disagree, flag both positions explicitly.
   Never silently resolve contradictions by picking a side.
5. **Wikilinks must resolve.** Before writing `[[any-link]]`, verify the target exists in
   `index.md`. If it doesn't, create a stub or use plain text with `[stub]`.
6. **Respect classification.** Never synthesize `confidential` source content into wiki pages.
   Mark claims derived from `internal` sources with `[internal]`.

## Directory Layout

- `raw/` — Immutable source documents (regulatory, internal, research, vendor)
- `wiki/` — LLM-maintained knowledge pages
- `wiki/index.md` — Categorized catalog of all pages (read this FIRST on any query)
- `wiki/log.md` — Append-only chronological record of operations
- `tools/` — CLI helpers (lint, search)

## Source Taxonomy

Sources in `raw/` are organized by provenance:

| Directory | Content | Classification |
|-----------|---------|----------------|
| `raw/regulatory/` | BCBS, OSFI, Fed, EBA standards | `public` |
| `raw/internal/methodology/` | Bank risk methodology docs | `internal` |
| `raw/internal/policy/` | Board-approved risk policies | `internal` |
| `raw/internal/models/` | Model documentation | `internal` or `confidential` |
| `raw/internal/reviews/` | Independent review & challenge | `internal` or `confidential` |
| `raw/internal/meeting-notes/` | Risk committee minutes | `internal` |
| `raw/research/` | Academic/industry research | `public` |
| `raw/vendor/` | Vendor model docs, release notes | `internal` |

### Classification Rules

| Level | Rule |
|-------|------|
| `public` | Freely synthesize into wiki pages |
| `internal` | Synthesize but tag derived claims with `[internal]` |
| `confidential` | Reference by title only — do NOT synthesize content into wiki pages |

## Source Frontmatter

Every source in `raw/` should have YAML frontmatter:

```yaml
---
title: "Document Title"
source_type: regulatory       # regulatory | internal | research | vendor
issuer: "BCBS"
date_published: 2016-04-01
date_ingested: 2026-04-09
status: current               # current | superseded | draft
supersedes: ""
superseded_by: ""
classification: public        # public | internal | confidential
tags: [irrbb, eve, nii]
summary: ""
---
```

## Wiki Page Conventions

### Frontmatter (required on every page)

```yaml
---
page_type: concept            # entity | concept | regulation | model | comparison | open-question
title: "Page Title"
aliases: []
created: 2026-04-09
last_updated: 2026-04-09
source_count: 0
sources: []
tags: []
confidence: medium            # high | medium | low | contested
provenance: public            # public | internal | mixed
---
```

### Sections (standard structure)

1. **Summary** — 2-3 sentence overview
2. **Key Points** — Core content
3. **Regulatory Context** — How regulators treat this topic
4. **Internal Position** — Bank methodology (tagged `[internal]`)
5. **Cross-References** — Wikilinks to related pages
6. **Source Log** — Table of sources and their contributions
7. **Open Issues** — Unresolved questions as checklist items

### Wikilink Rules

- Use `[[kebab-case-filename]]` syntax (no directory prefix)
- BEFORE writing any `[[link]]`, verify the target exists in `wiki/index.md`
- If the target doesn't exist, either create a stub page or use: `topic name [stub]`
- NEVER leave broken wikilinks

### Contradiction Handling

When sources disagree, use a callout:

```markdown
> [!warning] Contradiction
> **Claim A**: [statement] (Source: [source X])
> **Claim B**: [statement] (Source: [source Y])
> **Status**: Unresolved — requires human judgment
```

## Workflows

### Ingest (human adds a source to raw/)

1. Read the source fully
2. Discuss key takeaways with the human
3. Add YAML frontmatter to the source if missing
4. Create/update wiki pages — summaries, concepts, entities, models
5. Flag contradictions with callouts
6. Create stubs for new concepts not yet covered
7. Update `wiki/index.md` and append to `wiki/log.md`
8. Validate all wikilinks resolve

**Self-check after ingest:**
- [ ] Source frontmatter complete?
- [ ] All new claims attributed to specific source?
- [ ] Contradictions with existing pages flagged?
- [ ] Internal-sourced claims tagged `[internal]`?
- [ ] All wikilinks resolve?
- [ ] Index updated?
- [ ] Log entry appended?

### Query

1. Read `wiki/index.md` → identify relevant pages → read them
2. Synthesize answer citing wiki pages and raw sources
3. If the answer is a novel synthesis, offer to file it as a new page
4. If filed, update index and log

### Lint (run weekly or every ~5 ingests)

Run `python tools/lint_wiki.py` from the repo root, or perform manually:

1. Orphan pages (no inbound links)
2. Broken wikilinks
3. Stale claims (superseded sources)
4. Contradictions across pages
5. Coverage gaps (mentioned concepts without own page)
6. Confidence downgrades (single-source or old-source pages)
7. Internal leakage (confidential content in wiki pages)

## Domain Context

This wiki covers IRRBB including but not limited to:

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
"""

# ─────────────────────────────────────────────────────────────
# Initial wiki files
# ─────────────────────────────────────────────────────────────

TODAY = date.today().isoformat()


def index_content() -> str:
    return f"""\
---
page_type: index
title: "IRRBB Wiki Index"
created: {TODAY}
last_updated: {TODAY}
---

# IRRBB Wiki Index

Last updated: {TODAY} | Total pages: 1 | Sources ingested: 0

## Regulations

_No pages yet. Ingest your first regulatory source to get started._

## Concepts

_No pages yet._

## Models

_No pages yet._

## Entities

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
- Created directory structure
- Created AGENTS.md and CLAUDE.md schema files
- Created index.md, log.md, overview.md
- Ready for first source ingest
"""


def overview_content() -> str:
    return f"""\
---
page_type: overview
title: "IRRBB Risk Knowledge Wiki — Overview"
created: {TODAY}
last_updated: {TODAY}
confidence: high
provenance: public
---

# IRRBB Risk Knowledge Wiki

## Purpose

This wiki is a persistent, compounding knowledge base covering Interest Rate Risk in the
Banking Book (IRRBB). It is maintained by an LLM agent (GitHub Copilot or Claude Code)
and read by the human operator.

The wiki sits between raw source documents and the human's analytical work. Rather than
re-deriving knowledge from scratch on every question, the LLM incrementally builds and
maintains interlinked markdown pages that synthesize regulatory guidance, internal
methodology, research, and vendor documentation.

## Scope

- **Regulatory frameworks**: BCBS 368, OSFI B-12, Fed SR letters, EBA guidelines
- **Risk measures**: EVE sensitivity, NII sensitivity, earnings-at-risk
- **Behavioral modeling**: NMD decay, mortgage prepayment, term deposit early redemption
- **Risk types**: Repricing risk, basis risk, optionality risk, yield curve risk
- **Methodology**: Standardized vs internal model approaches, stress testing, scenario design
- **Governance**: Second-line independent review and challenge, Pillar 2, SOT

## How to Use

1. **Add sources** to `raw/` in the appropriate subdirectory
2. **Tell the LLM agent to ingest** — it will read, summarize, cross-reference, and update the wiki
3. **Ask questions** — the agent reads the wiki index, finds relevant pages, and synthesizes answers
4. **Run lint** periodically — `python tools/lint_wiki.py` checks wiki health
5. **Browse in Obsidian** (optional) — open the repo as a vault for graph view and navigation

## Conventions

See `AGENTS.md` (or `CLAUDE.md`) for the full schema: page formats, workflows, and rules.
"""


def gitignore_content() -> str:
    return """\
# OS
.DS_Store
Thumbs.db

# Editors
*.swp
*.swo
*~
.idea/
.vscode/

# Python
__pycache__/
*.pyc
.venv/
venv/

# Search index (regenerated)
.qmd/
"""


def gitkeep_readme(directory_purpose: str) -> str:
    """Small README for empty directories so git tracks them."""
    return f"# {directory_purpose}\n\nPlace source files here.\n"


# ─────────────────────────────────────────────────────────────
# Bootstrap logic
# ─────────────────────────────────────────────────────────────


def bootstrap(target: Path) -> None:
    if target.exists() and any(target.iterdir()):
        print(f"Error: {target} already exists and is not empty.")
        print("Delete it or choose a different directory.")
        sys.exit(1)

    print(f"Bootstrapping IRRBB wiki in: {target.resolve()}\n")

    # Create directories
    for d in DIRECTORIES:
        dir_path = target / d
        dir_path.mkdir(parents=True, exist_ok=True)

    # Create .gitkeep READMEs in leaf raw/ directories so git tracks them
    raw_leaves = [
        ("raw/regulatory/bcbs", "BCBS Standards"),
        ("raw/regulatory/osfi", "OSFI Guidelines"),
        ("raw/regulatory/fed", "Federal Reserve Guidance"),
        ("raw/regulatory/eba", "EBA Guidelines"),
        ("raw/regulatory/other-regulators", "Other Regulators"),
        ("raw/internal/methodology", "Internal Methodology Documents"),
        ("raw/internal/policy", "Board-Approved Risk Policies"),
        ("raw/internal/models", "Model Documentation"),
        ("raw/internal/reviews", "Independent Review & Challenge"),
        ("raw/internal/meeting-notes", "Risk Committee Minutes"),
        ("raw/research/papers", "Academic & Industry Research"),
        ("raw/research/articles", "Industry Articles & Commentary"),
        ("raw/research/presentations", "Conference Presentations"),
        ("raw/vendor/model-docs", "Vendor Model Documentation"),
        ("raw/vendor/release-notes", "Vendor Release Notes"),
        ("raw/assets/images", "Downloaded Images from Sources"),
    ]
    for rel_path, purpose in raw_leaves:
        readme_path = target / rel_path / "README.md"
        readme_path.write_text(gitkeep_readme(purpose))

    # Schema files
    (target / "AGENTS.md").write_text(SCHEMA_CONTENT)
    (target / "CLAUDE.md").write_text(SCHEMA_CONTENT)
    print("  Created AGENTS.md")
    print("  Created CLAUDE.md")

    # Wiki files
    (target / "wiki" / "index.md").write_text(index_content())
    print("  Created wiki/index.md")

    (target / "wiki" / "log.md").write_text(log_content())
    print("  Created wiki/log.md")

    (target / "wiki" / "overview.md").write_text(overview_content())
    print("  Created wiki/overview.md")

    # .gitignore
    (target / ".gitignore").write_text(gitignore_content())
    print("  Created .gitignore")

    # Copy tool scripts if they exist alongside this bootstrap script
    script_dir = Path(__file__).parent
    tools_to_copy = [
        ("lint_wiki.py", "tools/lint_wiki.py"),
        ("mcp_server.py", "tools/mcp_server.py"),
    ]
    for src_name, dest_rel in tools_to_copy:
        src = script_dir / src_name
        if src.exists():
            dest = target / dest_rel
            dest.write_text(src.read_text())
            print(f"  Created {dest_rel}")

    # Copy SKILL.md if it exists alongside this bootstrap script
    skill_src = script_dir / "SKILL.md"
    if skill_src.exists():
        (target / "SKILL.md").write_text(skill_src.read_text())
        print("  Created SKILL.md")

    # Summary
    dir_count = len(DIRECTORIES)
    print(f"\nDone. Created {dir_count} directories and initial files.")
    print(f"\nNext steps:")
    print(f"  1. cd {target}")
    print(f"  2. git init && git add -A && git commit -m 'Bootstrap IRRBB wiki'")
    print(f"  3. Drop your first source into raw/ (e.g., raw/regulatory/bcbs/)")
    print(f"  4. Open the repo in your LLM agent and say: 'Ingest raw/regulatory/bcbs/bcbs-368.md'")
    print(f"  5. Open in Obsidian to browse the wiki as it grows (optional)")
    print(f"\nTools:")
    print(f"  python tools/lint_wiki.py           # Check wiki health")
    print(f"  python tools/mcp_server.py          # Start MCP server (read-only)")
    print(f"  python tools/mcp_server.py --allow-ingest  # MCP with write access")


def main() -> None:
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
    else:
        target = Path.cwd() / "irrbb-wiki"

    bootstrap(target)


if __name__ == "__main__":
    main()
