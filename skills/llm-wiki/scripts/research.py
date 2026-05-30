#!/usr/bin/env python3
"""
Research / ingest pipeline for an LLM Knowledge Wiki (domain-agnostic).

Steps (each maps cleanly to a graph node):
  fetch_url        → Fetch and extract text from a URL
  summarize        → LLM summarizes content + generates source metadata
  generate_source  → Write a frontmatter-tagged source file into raw/
  draft_updates    → LLM drafts wiki page updates for human review (no writes)
  generate_commentary → LLM drafts an analytical page for comparisons/ or topics/

Non-text inputs (.docx/.pdf/...) are converted to Markdown first via convert.py.

Usage:
    python tools/research.py ingest https://example.com/article
    python tools/research.py ingest --file report.pdf --entity acme-corp
    python tools/research.py ingest --file notes.docx --url-ref "https://..."
    python tools/research.py commentary raw/web/article.md --focus "implications"
    python tools/research.py interactive

Environment:
    ANTHROPIC_API_KEY — required for the LLM steps.

Dependencies:
    pip install anthropic httpx   (+ markitdown/mammoth/pdfplumber for convert.py)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from textwrap import dedent
from typing import Optional
from urllib.parse import urlparse

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("research")

TODAY = date.today().isoformat()

DEFAULT_MODEL = os.environ.get("WIKI_INGEST_MODEL", "claude-sonnet-4-6")
MAX_CONTENT_CHARS = 80_000

# Generic source types and a coarse domain → type guess.
SOURCE_TYPES = [
    "web-article", "research-paper", "official-document", "report",
    "documentation", "reference", "notes", "transcript", "other",
]
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}


@dataclass
class FetchResult:
    url: str
    title: str
    content: str
    fetch_date: str
    content_length: int
    domain: str
    success: bool
    error: Optional[str] = None


@dataclass
class SourceMetadata:
    title: str
    source_type: str
    source_quality: str
    issuer: str
    date_published: str
    entity_tags: list[str]
    topic_tags: list[str]
    summary: str
    url: str


@dataclass
class ResearchResult:
    fetch: FetchResult
    metadata: Optional[SourceMetadata] = None
    source_path: Optional[str] = None
    wiki_updates: Optional[str] = None
    commentary: Optional[str] = None


# ── Step 1: Fetch ────────────────────────────────────────────────────────────


def fetch_url(url: str) -> FetchResult:
    """Fetch and extract text content from a URL."""
    domain = urlparse(url).netloc.replace("www.", "")
    logger.info("Fetching: %s", url)
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; LLM-Wiki-Research/1.0)",
            "Accept": "text/html,application/xhtml+xml,text/plain",
        }
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        raw_text = response.text
        if "html" in content_type:
            text = _extract_text_from_html(raw_text)
            title = _extract_title_from_html(raw_text)
        else:
            text, title = raw_text, ""
        if len(text) > MAX_CONTENT_CHARS:
            text = text[:MAX_CONTENT_CHARS] + "\n\n[... truncated ...]"
        return FetchResult(url, title or domain, text, TODAY, len(text), domain, True)
    except httpx.HTTPStatusError as e:
        return FetchResult(url, "", "", TODAY, 0, domain, False, f"HTTP {e.response.status_code}")
    except Exception as e:  # noqa: BLE001
        return FetchResult(url, "", "", TODAY, 0, domain, False, str(e))


def _extract_text_from_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<(?:nav|footer|header)[^>]*>.*?</(?:nav|footer|header)>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<(?:p|div|h[1-6]|li|tr|br)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")):
        text = text.replace(a, b)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n", "\n\n", text).strip()


def _extract_title_from_html(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    if not match:
        return ""
    title = re.sub(r"<[^>]+>", "", match.group(1)).strip()
    return title.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')


# ── Step 2: Summarize ────────────────────────────────────────────────────────


def get_client():
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)
    return anthropic.Anthropic(api_key=api_key)


def summarize(fetch_result: FetchResult, entity_hint: Optional[str] = None, model: str = DEFAULT_MODEL) -> SourceMetadata:
    """Use Claude to summarize content and generate generic source metadata."""
    logger.info("Summarizing with Claude...")
    hint = f"\nThe user indicated this source primarily concerns: {entity_hint}" if entity_hint else ""
    prompt = dedent(f"""\
        You are a research assistant maintaining a knowledge wiki. Analyze the
        content and produce structured metadata.{hint}

        Content title: {fetch_result.title}
        Source URL: {fetch_result.url}
        Source domain: {fetch_result.domain}

        <content>
        {fetch_result.content[:60000]}
        </content>

        Respond with ONLY a JSON object (no markdown, no backticks):
        {{
            "title": "Clear descriptive title for this source",
            "source_type": "one of: {', '.join(SOURCE_TYPES)}",
            "source_quality": "one of: authoritative, primary, secondary, reference, media",
            "issuer": "Organization or author that published this",
            "date_published": "YYYY-MM-DD if identifiable, otherwise {TODAY}",
            "entity_tags": ["kebab-case slugs of key named entities (orgs, people, products, places)"],
            "topic_tags": ["3-8 kebab-case topic tags"],
            "summary": "2-3 sentence summary of the key points"
        }}
    """)
    client = get_client()
    response = client.messages.create(model=model, max_tokens=1000, messages=[{"role": "user", "content": prompt}])
    raw = re.sub(r"^```(?:json)?\s*", "", response.content[0].text.strip())
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM metadata JSON: %s", e)
        return SourceMetadata(
            fetch_result.title, "other", "media", fetch_result.domain, TODAY,
            [entity_hint] if entity_hint else [], ["uncategorized"],
            "Summary generation failed — manual review needed.", fetch_result.url,
        )
    return SourceMetadata(
        title=data.get("title", fetch_result.title),
        source_type=data.get("source_type", "other"),
        source_quality=data.get("source_quality", "media"),
        issuer=data.get("issuer", fetch_result.domain),
        date_published=data.get("date_published", TODAY),
        entity_tags=data.get("entity_tags", []),
        topic_tags=data.get("topic_tags", []),
        summary=data.get("summary", ""),
        url=fetch_result.url,
    )


# ── Step 3: Write source file ────────────────────────────────────────────────


def generate_source_file(fetch_result: FetchResult, metadata: SourceMetadata, wiki_root: Path, category: str = "documents", classification: str = "public", verbatim: bool = False) -> Path:
    """Write a frontmatter-tagged source file into raw/<category>/.

    `verbatim=True` marks the source as protected: its text may only be reproduced
    as exact quotes in the wiki, never paraphrased (see SKILL.md / AGENTS.md
    "Verbatim / protected sources"). Use for internal policies, contracts, etc.
    """
    subdir = {
        "web-article": "raw/web",
        "media": "raw/web",
        "official-document": "raw/documents",
        "report": "raw/documents",
        "research-paper": "raw/documents",
        "documentation": "raw/documents",
        "notes": "raw/notes",
        "transcript": "raw/notes",
    }.get(metadata.source_type, f"raw/{category}")

    dir_path = wiki_root / subdir
    dir_path.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w\s-]", "", metadata.title.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")[:80] or "source"
    filename = f"{metadata.date_published}-{slug}.md"

    content = f"""\
---
title: "{metadata.title}"
source_type: {metadata.source_type}
source_quality: {metadata.source_quality}
issuer: "{metadata.issuer}"
date_published: {metadata.date_published}
date_ingested: {TODAY}
status: current
classification: {classification}
verbatim: {str(verbatim).lower()}
entity_tags: {json.dumps(metadata.entity_tags)}
topic_tags: {json.dumps(metadata.topic_tags)}
url: "{metadata.url}"
summary: "{metadata.summary}"
---

# {metadata.title}

Source: {metadata.url}
Retrieved: {fetch_result.fetch_date}

---

{fetch_result.content}
"""
    file_path = dir_path / filename
    file_path.write_text(content, encoding="utf-8")
    logger.info("Source file created: %s", file_path.relative_to(wiki_root))
    return file_path


# ── Step 4 & 5: Draft updates / commentary ───────────────────────────────────


def _gather_wiki_context(metadata: SourceMetadata, wiki_root: Path) -> str:
    parts: list[str] = []
    wiki_dir = wiki_root / "wiki"
    index_path = wiki_dir / "index.md"
    if index_path.exists():
        parts.append(f"--- wiki/index.md ---\n{index_path.read_text(encoding='utf-8', errors='replace')[:3000]}")
    tags = {t.lower() for t in (metadata.topic_tags + metadata.entity_tags)}
    if wiki_dir.is_dir():
        for md_file in wiki_dir.rglob("*.md"):
            if md_file.name in ("index.md", "log.md", "overview.md"):
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")[:1500]
            except OSError:
                continue
            if any(tag in content.lower() for tag in tags):
                parts.append(f"--- {md_file.relative_to(wiki_root)} ---\n{content}")
    blob = "\n\n".join(parts)
    return (blob[:15000] + "\n\n[... truncated ...]") if len(blob) > 15000 else (blob or "No existing wiki pages found.")


def draft_updates(fetch_result: FetchResult, metadata: SourceMetadata, wiki_root: Path, model: str = DEFAULT_MODEL, verbatim: bool = False) -> str:
    """Draft wiki page updates for human review. Does NOT write to the wiki.

    When `verbatim=True`, the source is protected: the draft must quote it exactly
    rather than paraphrase it into wiki prose, and put analysis on separate pages.
    """
    logger.info("Drafting wiki page updates...")
    existing = _gather_wiki_context(metadata, wiki_root)

    if verbatim:
        verbatim_rule = dedent("""\

            IMPORTANT — this source is flagged `verbatim: true` (protected). It is authoritative
            AS WRITTEN. In your draft you MUST:
            - Reproduce any of its text ONLY as exact quotes, inside a callout:
              `> [!quote] Verbatim — protected source, do not edit`
            - NOT paraphrase, summarize-as-fact, condense, reorder, or reword the protected text.
            - Put any comparison or analysis (e.g. against external/regulatory sources) on a SEPARATE
              `comparisons/`, `topic`, or `open-question` page, clearly tagging your own words with
              `[analysis]` / `[inference]` and quoting the protected text verbatim where referenced.
            - A short navigation summary is allowed only under a clearly-labelled "Summary [analysis]"
              heading OUTSIDE any verbatim quote block.""")
    else:
        verbatim_rule = ""

    prompt = dedent(f"""\
        You are a disciplined maintainer of a knowledge wiki. A new source was ingested:
        - Title: {metadata.title}
        - Type: {metadata.source_type}
        - Entities: {', '.join(metadata.entity_tags) or 'none'}
        - Topics: {', '.join(metadata.topic_tags)}
        - Summary: {metadata.summary}
        - Protected (verbatim): {str(verbatim).lower()}
        {verbatim_rule}

        <source_content>
        {fetch_result.content[:40000]}
        </source_content>

        <existing_wiki_context>
        {existing}
        </existing_wiki_context>

        Draft the specific wiki updates to make. For each: which page to create/update
        (page types: entities/, concepts/, topics/, comparisons/, open-questions/), which
        section, the exact content, and any new [[wikilinks]].

        Conventions:
        - [[kebab-case]] wikilinks; verify targets exist or mark `name [stub]`
        - Tag claims from a single/weak source as appropriate; cite the source in a Source Log
        - Flag contradictions with existing content using `> [!warning] Contradiction` callouts

        Output a structured markdown review a human can apply.
    """)
    client = get_client()
    response = client.messages.create(model=model, max_tokens=4000, messages=[{"role": "user", "content": prompt}])
    return response.content[0].text


def generate_commentary(fetch_result: FetchResult, metadata: SourceMetadata, wiki_root: Path, focus: Optional[str] = None, model: str = DEFAULT_MODEL) -> str:
    """Draft an analytical page suitable for comparisons/ or topics/."""
    logger.info("Generating commentary...")
    existing = _gather_wiki_context(metadata, wiki_root)
    focus_line = f"\nFocus your analysis on: {focus}" if focus else ""
    prompt = dedent(f"""\
        You are an analyst maintaining a knowledge wiki. A new source was ingested:
        - Title: {metadata.title}
        - Topics: {', '.join(metadata.topic_tags)}
        - Summary: {metadata.summary}{focus_line}

        <source_content>
        {fetch_result.content[:40000]}
        </source_content>

        <existing_wiki_context>
        {existing}
        </existing_wiki_context>

        Write a 400-700 word analytical page that synthesizes this source against what
        the wiki already covers: key takeaways, how it confirms/contradicts existing pages,
        and questions worth investigating. Use [[wikilinks]] where relevant. Begin with
        frontmatter (page_type: comparison or topic; title; created: {TODAY}; confidence: low;
        provenance: public) then the body with headings.
    """)
    client = get_client()
    response = client.messages.create(model=model, max_tokens=4000, messages=[{"role": "user", "content": prompt}])
    return response.content[0].text


# ── Orchestration ────────────────────────────────────────────────────────────


def run_ingest_pipeline(url: str, wiki_root: Path, entity_hint: Optional[str] = None, with_updates: bool = True, with_commentary: bool = False, commentary_focus: Optional[str] = None, model: str = DEFAULT_MODEL, classification: str = "public", verbatim: bool = False) -> ResearchResult:
    fetch_result = fetch_url(url)
    if not fetch_result.success:
        logger.error("Fetch failed: %s", fetch_result.error)
        return ResearchResult(fetch=fetch_result)
    return _finish_pipeline(fetch_result, wiki_root, entity_hint, with_updates, with_commentary, commentary_focus, model, category="web", classification=classification, verbatim=verbatim)


def run_file_ingest_pipeline(file_path: Path, wiki_root: Path, entity_hint: Optional[str] = None, url_ref: str = "", with_updates: bool = True, with_commentary: bool = False, commentary_focus: Optional[str] = None, model: str = DEFAULT_MODEL, classification: str = "public", verbatim: bool = False) -> ResearchResult:
    """Ingest a local file. Non-text files (.docx/.pdf/...) are converted to
    Markdown via convert.py first."""
    logger.info("Ingesting local file: %s", file_path)
    file_path = Path(file_path)
    if file_path.suffix.lower() in TEXT_SUFFIXES:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        category = "notes"
    else:
        import convert  # local module

        content = convert.convert(str(file_path))
        category = "pdf" if file_path.suffix.lower() == ".pdf" else "documents"

    fetch_result = FetchResult(
        url=url_ref,
        title=file_path.stem.replace("-", " ").replace("_", " ").title(),
        content=content,
        fetch_date=TODAY,
        content_length=len(content),
        domain=urlparse(url_ref).netloc.replace("www.", "") if url_ref else "local",
        success=True,
    )
    return _finish_pipeline(fetch_result, wiki_root, entity_hint, with_updates, with_commentary, commentary_focus, model, category=category, url_ref=url_ref, classification=classification, verbatim=verbatim)


def _finish_pipeline(fetch_result, wiki_root, entity_hint, with_updates, with_commentary, commentary_focus, model, category, url_ref="", classification="public", verbatim=False):
    metadata = summarize(fetch_result, entity_hint=entity_hint, model=model)
    if url_ref:
        metadata.url = url_ref
    source_path = generate_source_file(fetch_result, metadata, wiki_root, category=category, classification=classification, verbatim=verbatim)
    result = ResearchResult(fetch=fetch_result, metadata=metadata, source_path=str(source_path.relative_to(wiki_root)))
    if with_updates:
        result.wiki_updates = draft_updates(fetch_result, metadata, wiki_root, model=model, verbatim=verbatim)
    if with_commentary:
        result.commentary = generate_commentary(fetch_result, metadata, wiki_root, focus=commentary_focus, model=model)
    return result


# ── Output + CLI ─────────────────────────────────────────────────────────────


def print_result(result: ResearchResult) -> None:
    print("\n" + "=" * 60 + "\n  Ingest Pipeline Result\n" + "=" * 60)
    if not result.fetch.success:
        print(f"\n  FETCH FAILED: {result.fetch.error}")
        return
    m = result.metadata
    if m:
        print(f"\n  Title: {m.title}\n  Type: {m.source_type} ({m.source_quality})\n  Issuer: {m.issuer}")
        print(f"  Entities: {', '.join(m.entity_tags) or 'none'}\n  Topics: {', '.join(m.topic_tags)}")
        print(f"\n  Summary: {m.summary}")
    if result.source_path:
        print(f"\n  Filed to: {result.source_path}")
    if result.wiki_updates:
        print("\n" + "─" * 60 + "\n  DRAFT WIKI UPDATES (review before applying)\n" + "─" * 60 + "\n")
        print(result.wiki_updates)
    if result.commentary:
        print("\n" + "─" * 60 + "\n  COMMENTARY\n" + "─" * 60 + "\n")
        print(result.commentary)
    print()


def find_wiki_root() -> Path:
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / "AGENTS.md").exists() or (parent / "CLAUDE.md").exists():
            return parent
        if (parent / "wiki").is_dir() and (parent / "raw").is_dir():
            return parent
    return current


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Ingest pipeline for an LLM Knowledge Wiki")
    parser.add_argument("--wiki-root", type=Path, default=None, help="Wiki repo root (default: auto-detect)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    sub = parser.add_subparsers(dest="command")

    ing = sub.add_parser("ingest", help="Ingest a URL or local file")
    ing.add_argument("url", nargs="?", default=None)
    ing.add_argument("--file", type=Path, dest="local_file")
    ing.add_argument("--url-ref", dest="url_ref")
    ing.add_argument("--entity", dest="entity", help="Primary entity hint (slug)")
    ing.add_argument("--classification", choices=["public", "internal", "confidential"], default="public",
                     help="Source classification (default: public)")
    ing.add_argument("--verbatim", action="store_true",
                     help="Protected source: reproduce only as exact quotes, never paraphrase "
                          "(for internal policies, contracts, standards, legal text)")
    ing.add_argument("--commentary", action="store_true")
    ing.add_argument("--commentary-focus")
    ing.add_argument("--no-updates", action="store_true")

    com = sub.add_parser("commentary", help="Commentary on an existing source")
    com.add_argument("source", type=Path)
    com.add_argument("--focus")

    sub.add_parser("interactive", help="Interactive ingest session")

    args = parser.parse_args()
    wiki_root = args.wiki_root or find_wiki_root()
    if not args.command:
        parser.print_help()
        return

    if args.command == "ingest":
        if args.local_file:
            if not args.local_file.exists():
                logger.error("File not found: %s", args.local_file)
                sys.exit(1)
            result = run_file_ingest_pipeline(args.local_file, wiki_root, entity_hint=args.entity, url_ref=args.url_ref or "", with_updates=not args.no_updates, with_commentary=args.commentary, commentary_focus=args.commentary_focus, model=args.model, classification=args.classification, verbatim=args.verbatim)
        elif args.url:
            result = run_ingest_pipeline(args.url, wiki_root, entity_hint=args.entity, with_updates=not args.no_updates, with_commentary=args.commentary, commentary_focus=args.commentary_focus, model=args.model, classification=args.classification, verbatim=args.verbatim)
        else:
            logger.error("Provide a URL or --file path")
            sys.exit(1)
        print_result(result)

    elif args.command == "commentary":
        content = args.source.read_text(encoding="utf-8", errors="replace")
        fr = FetchResult("", args.source.stem, content, TODAY, len(content), "", True)
        md = SourceMetadata(args.source.stem, "other", "reference", "", TODAY, [], [], "", "")
        print(generate_commentary(fr, md, wiki_root, focus=args.focus, model=args.model))

    elif args.command == "interactive":
        print("\n  LLM Wiki — Interactive Ingest. Enter a URL or local path, or 'quit'.\n")
        while True:
            try:
                line = input("  source> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line or line.lower() in ("quit", "exit", "q"):
                break
            if line.startswith("http"):
                res = run_ingest_pipeline(line, wiki_root, model=args.model)
            else:
                p = Path(line)
                if not p.exists():
                    print("  not a URL or existing file"); continue
                res = run_file_ingest_pipeline(p, wiki_root, model=args.model)
            print_result(res)


if __name__ == "__main__":
    main()
