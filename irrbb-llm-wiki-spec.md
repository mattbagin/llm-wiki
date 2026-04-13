# IRRBB Risk Knowledge Wiki — Specification

## Overview

This document specifies a persistent, LLM-maintained knowledge wiki for Interest Rate Risk in the Banking Book (IRRBB). The wiki follows the "LLM Wiki" pattern: rather than re-deriving knowledge from raw sources on every query (RAG), the LLM incrementally builds and maintains a structured, interlinked collection of markdown files that compound over time.

The wiki is designed to operate in a bank's GitHub enterprise environment with GitHub Copilot as the primary LLM agent, while remaining portable to Claude Code for personal use.

---

## 1. Architecture

### 1.1 Three-Layer Model

```
irrbb-wiki/
├── AGENTS.md              # Schema file for GitHub Copilot
├── CLAUDE.md              # Schema file for Claude Code (symlink or copy of AGENTS.md)
├── raw/                   # Layer 1: Immutable source documents
│   ├── regulatory/
│   ├── internal/
│   ├── research/
│   ├── vendor/
│   └── assets/            # Images, diagrams downloaded from sources
├── wiki/                  # Layer 2: LLM-generated knowledge pages
│   ├── index.md
│   ├── log.md
│   ├── overview.md
│   ├── entities/
│   ├── concepts/
│   ├── regulations/
│   ├── models/
│   ├── comparisons/
│   └── open-questions/
└── tools/                 # Optional: CLI helpers (search, lint scripts)
```

### 1.2 Layer Responsibilities

| Layer | Owner | Mutability | Purpose |
|-------|-------|------------|---------|
| `raw/` | Human | Immutable (LLM reads, never writes) | Source of truth — regulatory docs, internal methodology, research papers |
| `wiki/` | LLM | LLM-writable (human reads, rarely writes) | Synthesized, interlinked knowledge pages |
| `AGENTS.md` / `CLAUDE.md` | Co-evolved (human + LLM) | Both can propose changes | Schema — conventions, workflows, page formats |

---

## 2. Source Taxonomy

Sources in `raw/` are organized by provenance. This distinction is critical: when the wiki flags contradictions or evolving guidance, you need to know whether a claim traces to Basel, OSFI, or your team's internal position.

### 2.1 Source Categories

```
raw/
├── regulatory/
│   ├── bcbs/              # Basel Committee standards (BCBS 368, etc.)
│   ├── osfi/              # OSFI guidelines (B-12, etc.)
│   ├── fed/               # Federal Reserve guidance (SR letters, etc.)
│   ├── eba/               # EBA guidelines (if relevant for comparison)
│   └── other-regulators/
├── internal/
│   ├── methodology/       # Internal risk methodology documents
│   ├── policy/            # Board-approved risk policies
│   ├── models/            # Model documentation (behavioral, NII, EVE)
│   ├── reviews/           # Independent review & challenge reports
│   └── meeting-notes/     # Risk committee minutes, working group notes
├── research/
│   ├── papers/            # Academic and industry research
│   ├── articles/          # Industry commentary, blog posts
│   └── presentations/     # Conference slides, webinars
├── vendor/
│   ├── model-docs/        # Vendor model documentation (QRM, Moody's, etc.)
│   └── release-notes/     # System release notes affecting risk measurement
└── assets/
    └── images/            # Downloaded images referenced by sources
```

### 2.2 Source Frontmatter

Every source file in `raw/` should have YAML frontmatter added upon ingest:

```yaml
---
title: "BCBS 368 - Interest Rate Risk in the Banking Book"
source_type: regulatory    # regulatory | internal | research | vendor
issuer: BCBS
date_published: 2016-04-01
date_ingested: 2026-04-09
status: current            # current | superseded | draft
supersedes: "BCBS 108"     # if applicable
superseded_by: ""          # populated when newer version arrives
classification: public     # public | internal | confidential
tags: [irrbb, eve, nii, standardized-framework, outlier-test]
summary: ""                # Populated by LLM during ingest
---
```

### 2.3 Source Classification Rules

| Classification | Description | Handling |
|----------------|-------------|----------|
| `public` | Published regulatory docs, academic papers | No restrictions on wiki synthesis |
| `internal` | Bank methodology, policy, review docs | Wiki pages must tag derived claims as `[internal]` |
| `confidential` | Sensitive model parameters, audit findings | Do NOT synthesize into wiki pages — reference only by title |

---

## 3. Wiki Page Types

### 3.1 Page Taxonomy

| Page Type | Directory | Purpose | Example |
|-----------|-----------|---------|---------|
| **Entity** | `wiki/entities/` | A specific organization, framework, or system | `osfi.md`, `bcbs.md`, `qrm-alm-system.md` |
| **Concept** | `wiki/concepts/` | A risk concept or technique | `eve-sensitivity.md`, `nmd-behavioral-modeling.md`, `repricing-gap.md` |
| **Regulation** | `wiki/regulations/` | A specific regulatory standard or guideline | `bcbs-368.md`, `osfi-b12.md` |
| **Model** | `wiki/models/` | An internal or vendor risk model | `nmd-decay-model.md`, `mortgage-prepayment-model.md` |
| **Comparison** | `wiki/comparisons/` | Side-by-side analysis | `eve-vs-nii.md`, `osfi-vs-fed-irrbb.md` |
| **Open Question** | `wiki/open-questions/` | Unresolved analytical questions | `nmd-stability-assumption-validity.md` |

### 3.2 Page Template

Every wiki page uses this structure:

```markdown
---
page_type: concept         # entity | concept | regulation | model | comparison | open-question
title: "EVE Sensitivity"
aliases: [economic-value-of-equity, eve-risk]
created: 2026-04-09
last_updated: 2026-04-09
source_count: 3
sources: ["raw/regulatory/bcbs/bcbs-368.md", "raw/internal/methodology/eve-methodology-v2.md"]
tags: [eve, irrbb, market-risk, interest-rate-sensitivity]
confidence: high           # high | medium | low | contested
provenance: mixed          # public | internal | mixed
---

# EVE Sensitivity

## Summary
[2-3 sentence overview of the concept]

## Key Points
[Core content — structured as the topic demands]

## Regulatory Context
[How regulators treat this topic — cite specific standards]

## Internal Position
[How the bank's methodology addresses this — tagged as internal]

## Cross-References
- Related: [[nii-sensitivity]], [[repricing-gap]], [[behavioral-modeling]]
- Contrasts with: [[earnings-at-risk]]
- Regulated by: [[bcbs-368]], [[osfi-b12]]

## Source Log
| Source | Date Ingested | Key Contribution |
|--------|--------------|------------------|
| BCBS 368 | 2026-04-09 | Standardized EVE framework definition |
| Internal EVE Methodology v2 | 2026-04-09 | Bank-specific calculation approach |

## Open Issues
- [ ] Confirm whether OSFI B-12 update changes the EVE outlier test threshold
- [ ] Reconcile internal EVE methodology with BCBS standardized approach on NMD treatment
```

### 3.3 Cross-Reference Convention

Use `[[wiki-link]]` syntax (Obsidian-compatible). The LLM must validate links against existing pages before writing them:

- **Before creating a `[[link]]`**, check `wiki/index.md` to confirm the target page exists.
- If the target doesn't exist yet, either create it as a stub or use plain text with a `[stub]` marker: `EVE sensitivity [stub]`.
- Never leave broken wikilinks. This is the #1 failure mode in practice.

---

## 4. Index and Log

### 4.1 index.md

The index is a categorized catalog of all wiki pages. The LLM reads this first when answering queries to find relevant pages.

```markdown
# IRRBB Wiki Index

Last updated: 2026-04-09 | Total pages: 47 | Sources ingested: 23

## Regulations
- [[bcbs-368]] — Basel IRRBB standard (2016), defines EVE/NII frameworks — 5 sources
- [[osfi-b12]] — OSFI guideline on IRRBB, Canadian implementation of BCBS 368 — 3 sources

## Concepts
- [[eve-sensitivity]] — Economic value of equity risk measure — 3 sources
- [[nii-sensitivity]] — Net interest income risk measure — 4 sources
- [[nmd-behavioral-modeling]] — Non-maturity deposit behavioral assumptions — 6 sources
- [[repricing-gap]] — Static repricing gap analysis — 2 sources

## Models
- [[nmd-decay-model]] — Internal NMD decay/runoff model — 2 sources
- [[mortgage-prepayment-model]] — Prepayment behavioral model — 3 sources

## Entities
- [[osfi]] — Office of the Superintendent of Financial Institutions — 2 sources
- [[bcbs]] — Basel Committee on Banking Supervision — 3 sources

## Comparisons
- [[eve-vs-nii]] — Complementary risk measures comparison — 2 sources
- [[osfi-vs-fed-irrbb]] — Cross-jurisdictional regulatory comparison — 4 sources

## Open Questions
- [[nmd-stability-assumption-validity]] — Is the core deposit stability assumption still defensible? — 2 sources
```

### 4.2 log.md

Append-only chronological record. Each entry uses a consistent prefix for `grep`-ability.

```markdown
# Wiki Log

## [2026-04-09] ingest | BCBS 368 — Interest Rate Risk in the Banking Book
- Created: wiki/regulations/bcbs-368.md
- Created: wiki/concepts/eve-sensitivity.md
- Created: wiki/concepts/nii-sensitivity.md
- Updated: wiki/index.md (3 new pages)
- Sources touched: 1 | Pages created: 3 | Pages updated: 1

## [2026-04-09] query | How does OSFI's NMD treatment differ from BCBS?
- Answer filed as: wiki/comparisons/osfi-vs-bcbs-nmd.md
- Updated: wiki/concepts/nmd-behavioral-modeling.md (added cross-reference)

## [2026-04-10] lint | Weekly health check
- Found: 2 orphan pages (no inbound links)
- Found: 1 stale claim in nmd-decay-model.md (superseded by updated methodology doc)
- Action: Added cross-references, flagged stale claim with [needs-review] tag
```

---

## 5. Operations

### 5.1 Ingest Workflow

When a new source is added to `raw/`:

1. **Read** the source document fully.
2. **Discuss** key takeaways with the human — what's novel, what confirms/contradicts existing wiki content.
3. **Add frontmatter** to the source file (if not already present).
4. **Write or update wiki pages:**
   - Create a summary page if the source is a major document (e.g., a new regulation).
   - Update existing concept, entity, and model pages with new information.
   - Flag contradictions explicitly: add a `> [!warning] Contradiction` callout with both claims and their sources.
   - Create stub pages for important new concepts mentioned but not yet covered.
5. **Update `index.md`** — add new pages, update source counts.
6. **Append to `log.md`** — record what was ingested and what changed.
7. **Validate all wikilinks** — confirm every `[[link]]` resolves to an existing page.

**Ingest checklist (LLM self-check):**
- [ ] Source frontmatter complete?
- [ ] All new claims attributed to specific source?
- [ ] Contradictions with existing pages flagged?
- [ ] Internal-sourced claims tagged `[internal]`?
- [ ] All wikilinks resolve?
- [ ] Index updated?
- [ ] Log entry appended?

### 5.2 Query Workflow

When the human asks a question:

1. **Read `index.md`** to identify relevant pages.
2. **Read the relevant pages** (typically 3-8 pages for a substantive question).
3. **Synthesize an answer** with citations to both wiki pages and underlying raw sources.
4. **Assess whether the answer is worth filing.** If it produces a novel comparison, synthesis, or analytical insight, offer to save it as a new wiki page (e.g., in `comparisons/` or `open-questions/`).
5. **If filed**, update index and log.

### 5.3 Lint Workflow

Run periodically (suggest weekly or after every ~5 ingests):

1. **Orphan check** — pages with no inbound `[[links]]` from other pages.
2. **Broken link check** — `[[links]]` that don't resolve to existing pages.
3. **Staleness check** — pages whose sources have been superseded (check `superseded_by` in source frontmatter).
4. **Contradiction scan** — look for pages making conflicting claims about the same topic.
5. **Coverage gaps** — important concepts mentioned in page body text but lacking their own page.
6. **Confidence downgrade** — pages with `confidence: high` but only 1 source, or whose source is > 2 years old.
7. **Internal leakage check** — ensure no `confidential`-classified source content has been synthesized into wiki page body text.

Output lint results to `log.md` and present a summary to the human.

---

## 6. Schema File (AGENTS.md / CLAUDE.md)

The schema file is the operational brain — it tells the LLM how to behave as a wiki maintainer. Below is the full schema. Copy this to `AGENTS.md` at the repo root for Copilot, and optionally symlink or copy to `CLAUDE.md` for Claude Code.

```markdown
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

## Workflows

### On ingest (human adds a source to raw/)
1. Read the source fully
2. Discuss key takeaways with the human
3. Add YAML frontmatter to the source if missing
4. Create/update wiki pages — summaries, concepts, entities, models
5. Flag contradictions with `> [!warning] Contradiction` callouts
6. Create stubs for new concepts not yet covered
7. Update index.md and append to log.md
8. Validate all wikilinks resolve

### On query
1. Read index.md → identify relevant pages → read them
2. Synthesize answer citing wiki pages and raw sources
3. If the answer is a novel synthesis, offer to file it as a new page

### On lint (run weekly or every ~5 ingests)
1. Orphan pages (no inbound links)
2. Broken wikilinks
3. Stale claims (superseded sources)
4. Contradictions across pages
5. Coverage gaps (mentioned concepts without own page)
6. Confidence downgrades (single-source or old-source pages)
7. Internal leakage (confidential content in wiki pages)

## Page Conventions

- YAML frontmatter on every page (page_type, title, aliases, created, last_updated,
  source_count, sources, tags, confidence, provenance)
- Sections: Summary, Key Points, Regulatory Context, Internal Position, Cross-References,
  Source Log, Open Issues
- Wikilinks use `[[kebab-case-filename]]` without directory prefix
- Contradiction callout format: `> [!warning] Contradiction: [claim A] (Source X) vs [claim B] (Source Y)`

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
```

---

## 7. Portability Notes

### 7.1 Copilot vs Claude Code

| Concern | GitHub Copilot | Claude Code |
|---------|---------------|-------------|
| Schema file | `AGENTS.md` at repo root | `CLAUDE.md` at repo root |
| File access | Reads/writes via repo | Reads/writes via filesystem |
| Context limits | Check current model limits | ~200k tokens context |
| Tool use | Terminal, file edit | Bash, file edit, MCP tools |
| Search at scale | Add `qmd` or custom script | Add `qmd` MCP server or grep |

### 7.2 Keeping Schemas in Sync

The simplest approach: maintain one canonical file (e.g., `AGENTS.md`) and symlink or copy:

```bash
# In the repo root
ln -s AGENTS.md CLAUDE.md
```

Or if your environment doesn't support symlinks, add a CI check that the two files are identical.

---

## 8. Scaling Considerations

### 8.1 When index.md Alone Isn't Enough

At ~100+ pages, the flat index becomes unwieldy. Options:

1. **Hierarchical index** — split into sub-indexes per category (e.g., `wiki/regulations/index.md`).
2. **Search tooling** — integrate `qmd` (local markdown search with BM25 + vector) or build a simple Python search script using the wiki's YAML frontmatter.
3. **Tag-based navigation** — use Obsidian's Dataview plugin to query page frontmatter dynamically.

### 8.2 Token Budget

For Copilot sessions, the LLM won't be able to hold the entire wiki in context. The index-first pattern is critical:

1. Read `index.md` (~1-2k tokens for ~100 pages)
2. Selectively read only the 3-8 most relevant pages
3. Synthesize from those pages, not from raw sources

This keeps each operation within reasonable token budgets even as the wiki grows.

---

## 9. Getting Started — Bootstrap Sequence

To initialize the wiki from scratch:

1. **Create the directory structure** (Section 1.1).
2. **Copy the schema** (Section 6) into `AGENTS.md` and `CLAUDE.md`.
3. **Create empty `index.md` and `log.md`** with header templates.
4. **Create `overview.md`** — a high-level page describing the wiki's scope and purpose.
5. **Ingest your first source.** Start with something foundational like BCBS 368 or OSFI B-12. Walk through the full ingest workflow (Section 5.1) to establish conventions.
6. **Ingest 2-3 more sources** from different categories (one internal methodology doc, one research paper). This forces cross-referencing and surfaces the first contradictions.
7. **Run your first lint** after ~5 sources to establish the health-check habit.
8. **Iterate on the schema** — after 5-10 ingests, revisit `AGENTS.md` and refine conventions based on what's working.

---

## 10. Risk-Specific Design Decisions

### 10.1 Why Separate Regulatory Context and Internal Position

In IRRBB, there is frequently a gap between what the regulation requires and how the bank implements it. Keeping these as separate sections on every page forces the LLM to make this distinction explicit, which is exactly the value proposition for a second-line risk function: you want to see where your methodology aligns with regulatory expectations and where it diverges.

### 10.2 Confidence and Provenance as First-Class Metadata

The `confidence` and `provenance` fields in page frontmatter serve the lint workflow:
- A page marked `confidence: high` but with only one source should be downgraded.
- A page marked `provenance: internal` reminds the LLM (and the reader) that the claims depend on the bank's own methodology, not external authority.
- A page marked `confidence: contested` signals an active disagreement that requires human judgment.

### 10.3 Open Questions as a Page Type

IRRBB is full of judgment calls — NMD stability assumptions, prepayment model calibration, the appropriate stress scenarios. Capturing these explicitly as `open-question` pages prevents the wiki from presenting false certainty. It also gives the human a natural backlog of analytical work to pursue.
