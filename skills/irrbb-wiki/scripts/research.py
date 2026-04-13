#!/usr/bin/env python3
"""
Research pipeline for the AI in Banking Knowledge Wiki.

A modular tool that fetches web content, summarizes it with Claude, generates
source frontmatter, and optionally drafts wiki page updates.

Each function is a self-contained step that maps to a LangGraph node:
  fetch_url       → Fetch and extract text from a URL
  summarize       → LLM summarizes the content
  generate_source → Create a frontmatter-tagged source file in raw/
  draft_updates   → LLM drafts wiki page updates based on the source
  commentary      → LLM generates analytical commentary/narrative

Usage:
    # Ingest a single URL
    python tools/research.py ingest https://example.com/article --bank rbc

    # Ingest with commentary
    python tools/research.py ingest https://example.com/article --bank rbc --commentary

    # Generate commentary on an existing source
    python tools/research.py commentary raw/banks/rbc/article.md

    # Batch ingest from a file of URLs
    python tools/research.py batch urls.txt --bank rbc

    # Interactive mode — paste URLs, get summaries, decide what to keep
    python tools/research.py interactive

Environment:
    ANTHROPIC_API_KEY — Required. Your Anthropic API key.

Dependencies:
    pip install anthropic httpx
"""

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from textwrap import dedent
from typing import Optional
from urllib.parse import urlparse

import httpx

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("research")

TODAY = date.today().isoformat()

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

DEFAULT_MODEL = "claude-sonnet-4-20250514"
MAX_CONTENT_CHARS = 80_000  # Truncate fetched content to fit context window

PEER_BANKS = {
    "rbc": "Royal Bank of Canada",
    "td": "TD Bank",
    "scotiabank": "Scotiabank",
    "bmo": "Bank of Montreal",
    "jpmorgan": "JP Morgan",
    "wells-fargo": "Wells Fargo",
    "bofa": "Bank of America",
    "goldman-sachs": "Goldman Sachs",
    "barclays": "Barclays",
    "westpac": "Westpac",
}

SOURCE_TYPE_MAP = {
    # Domain patterns → source_type guesses
    "reuters.com": "media-article",
    "bloomberg.com": "media-article",
    "ft.com": "media-article",
    "wsj.com": "media-article",
    "cnbc.com": "media-article",
    "bnnbloomberg.ca": "media-article",
    "theglobeandmail.com": "media-article",
    "arxiv.org": "research-paper",
    "ssrn.com": "research-paper",
    "mckinsey.com": "research-paper",
    "celent.com": "research-paper",
    "osfi-bsif.gc.ca": "regulatory-guidance",
    "federalreserve.gov": "regulatory-guidance",
    "occ.gov": "regulatory-guidance",
    "bis.org": "regulatory-guidance",
    "rbc.com": "bank-announcement",
    "td.com": "bank-announcement",
    "scotiabank.com": "bank-announcement",
    "bmo.com": "bank-announcement",
    "jpmorganchase.com": "bank-announcement",
    "wellsfargo.com": "bank-announcement",
    "bankofamerica.com": "bank-announcement",
    "goldmansachs.com": "bank-announcement",
    "barclays.com": "bank-announcement",
    "westpac.com.au": "bank-announcement",
}


# ─────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────


@dataclass
class FetchResult:
    """Result from fetching a URL."""

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
    """Generated metadata for a source file."""

    title: str
    source_type: str
    source_quality: str
    issuer: str
    date_published: str
    bank_tags: list[str]
    topic_tags: list[str]
    summary: str
    url: str


@dataclass
class ResearchResult:
    """Complete result from the research pipeline."""

    fetch: FetchResult
    metadata: Optional[SourceMetadata] = None
    source_path: Optional[str] = None
    wiki_updates: Optional[str] = None
    commentary: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# Step 1: Fetch URL
# ─────────────────────────────────────────────────────────────


def fetch_url(url: str) -> FetchResult:
    """Fetch and extract text content from a URL.

    LangGraph node: stateless, takes URL, returns FetchResult.
    """
    domain = urlparse(url).netloc.replace("www.", "")
    logger.info(f"Fetching: {url}")

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; AI-Banking-Wiki-Research/1.0; "
                "+https://github.com/placeholder)"
            ),
            "Accept": "text/html,application/xhtml+xml,text/plain",
        }
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        raw_text = response.text

        # Basic HTML → text extraction (no BeautifulSoup dependency)
        if "html" in content_type:
            text = _extract_text_from_html(raw_text)
            title = _extract_title_from_html(raw_text)
        else:
            text = raw_text
            title = ""

        # Truncate to fit in context window
        if len(text) > MAX_CONTENT_CHARS:
            text = text[:MAX_CONTENT_CHARS] + "\n\n[... truncated ...]"

        return FetchResult(
            url=url,
            title=title or domain,
            content=text,
            fetch_date=TODAY,
            content_length=len(text),
            domain=domain,
            success=True,
        )

    except httpx.HTTPStatusError as e:
        return FetchResult(
            url=url,
            title="",
            content="",
            fetch_date=TODAY,
            content_length=0,
            domain=domain,
            success=False,
            error=f"HTTP {e.response.status_code}",
        )
    except Exception as e:
        return FetchResult(
            url=url,
            title="",
            content="",
            fetch_date=TODAY,
            content_length=0,
            domain=domain,
            success=False,
            error=str(e),
        )


def _extract_text_from_html(html: str) -> str:
    """Minimal HTML → text extraction without BeautifulSoup."""
    # Remove script and style blocks
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<nav[^>]*>.*?</nav>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<footer[^>]*>.*?</footer>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<header[^>]*>.*?</header>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    # Convert block elements to newlines
    text = re.sub(r"<(?:p|div|h[1-6]|li|tr|br)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Remove remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode common entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip()


def _extract_title_from_html(html: str) -> str:
    """Extract <title> from HTML."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    if match:
        title = match.group(1).strip()
        title = re.sub(r"<[^>]+>", "", title)  # Remove nested tags
        return title.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
    return ""


# ─────────────────────────────────────────────────────────────
# Step 2: Summarize with LLM
# ─────────────────────────────────────────────────────────────


def get_client():
    """Get Anthropic client. Lazy-loaded to allow import without API key."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)
    return anthropic.Anthropic(api_key=api_key)


def summarize(
    fetch_result: FetchResult,
    bank_hint: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> SourceMetadata:
    """Use Claude to summarize content and generate source metadata.

    LangGraph node: takes FetchResult, returns SourceMetadata.
    """
    logger.info("Summarizing with Claude...")

    bank_context = ""
    if bank_hint and bank_hint in PEER_BANKS:
        bank_context = f"\nThe user indicated this source is primarily about: {PEER_BANKS[bank_hint]} ({bank_hint})"

    peer_list = ", ".join(f"{slug} ({name})" for slug, name in PEER_BANKS.items())

    prompt = dedent(f"""\
        You are a research assistant for a knowledge base tracking AI adoption in banking.

        Analyze the following web content and produce structured metadata.
        {bank_context}

        The peer group of banks to watch for: {peer_list}

        Content title: {fetch_result.title}
        Source URL: {fetch_result.url}
        Source domain: {fetch_result.domain}

        <content>
        {fetch_result.content[:60000]}
        </content>

        Respond with ONLY a JSON object (no markdown, no backticks, no preamble):
        {{
            "title": "Clear descriptive title for this source",
            "source_type": "one of: regulatory-guidance, bank-announcement, earnings-transcript, annual-report, press-release, research-paper, vendor-report, media-article, conference-notes, concept-reference",
            "source_quality": "one of: authoritative, primary, secondary, vendor, media, reference",
            "issuer": "Organization that published this (bank name, regulator, research firm, media outlet)",
            "date_published": "YYYY-MM-DD if identifiable, otherwise {TODAY}",
            "bank_tags": ["list of bank slugs discussed: rbc, td, scotiabank, bmo, jpmorgan, wells-fargo, bofa, goldman-sachs, barclays, westpac"],
            "topic_tags": ["3-8 topic tags like: genai, llm, agentic-ai, fraud-detection, risk-management, chatbot, code-generation, governance, cloud, talent"],
            "summary": "2-3 sentence summary of the key points relevant to AI in banking"
        }}
    """)

    client = get_client()
    response = client.messages.create(
        model=model,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text.strip()
    # Strip markdown fences if present
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
    raw_text = re.sub(r"\s*```$", "", raw_text)

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        logger.error(f"Raw response: {raw_text[:500]}")
        # Return minimal metadata
        return SourceMetadata(
            title=fetch_result.title,
            source_type=_guess_source_type(fetch_result.domain),
            source_quality="media",
            issuer=fetch_result.domain,
            date_published=TODAY,
            bank_tags=[bank_hint] if bank_hint else [],
            topic_tags=["ai-in-banking"],
            summary="Summary generation failed — manual review needed.",
            url=fetch_result.url,
        )

    return SourceMetadata(
        title=data.get("title", fetch_result.title),
        source_type=data.get("source_type", _guess_source_type(fetch_result.domain)),
        source_quality=data.get("source_quality", "media"),
        issuer=data.get("issuer", fetch_result.domain),
        date_published=data.get("date_published", TODAY),
        bank_tags=data.get("bank_tags", []),
        topic_tags=data.get("topic_tags", []),
        summary=data.get("summary", ""),
        url=fetch_result.url,
    )


def _guess_source_type(domain: str) -> str:
    """Guess source type from domain if LLM fails."""
    for pattern, stype in SOURCE_TYPE_MAP.items():
        if pattern in domain:
            return stype
    return "media-article"


# ─────────────────────────────────────────────────────────────
# Step 3: Generate source file
# ─────────────────────────────────────────────────────────────


def generate_source_file(
    fetch_result: FetchResult,
    metadata: SourceMetadata,
    wiki_root: Path,
) -> Path:
    """Create a frontmatter-tagged source file in raw/.

    LangGraph node: takes FetchResult + SourceMetadata, writes file, returns path.
    """
    # Determine directory based on source type and bank tags
    if metadata.source_type == "regulatory-guidance":
        subdir = "raw/regulatory/other"
        # Try to place in specific regulator dir
        issuer_lower = metadata.issuer.lower()
        if "osfi" in issuer_lower:
            subdir = "raw/regulatory/osfi"
        elif "fed" in issuer_lower or "federal reserve" in issuer_lower:
            subdir = "raw/regulatory/fed"
        elif "occ" in issuer_lower:
            subdir = "raw/regulatory/occ"
    elif metadata.source_type in ("bank-announcement", "earnings-transcript", "annual-report", "press-release"):
        bank = metadata.bank_tags[0] if metadata.bank_tags else "other"
        subdir = f"raw/banks/{bank}"
    elif metadata.source_type in ("research-paper", "vendor-report"):
        subdir = f"raw/industry/{'vendor' if metadata.source_type == 'vendor-report' else 'research'}"
    elif metadata.source_type == "conference-notes":
        subdir = "raw/industry/conferences"
    else:
        subdir = "raw/industry/media"

    # Create directory if needed
    dir_path = wiki_root / subdir
    dir_path.mkdir(parents=True, exist_ok=True)

    # Generate filename from title
    slug = re.sub(r"[^\w\s-]", "", metadata.title.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    slug = slug[:80]  # Reasonable filename length
    filename = f"{metadata.date_published}-{slug}.md"

    # Build frontmatter
    bank_tags_str = json.dumps(metadata.bank_tags)
    topic_tags_str = json.dumps(metadata.topic_tags)

    content = f"""\
---
title: "{metadata.title}"
source_type: {metadata.source_type}
source_quality: {metadata.source_quality}
issuer: "{metadata.issuer}"
date_published: {metadata.date_published}
date_ingested: {TODAY}
bank_tags: {bank_tags_str}
topic_tags: {topic_tags_str}
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
    logger.info(f"Source file created: {file_path.relative_to(wiki_root)}")

    return file_path


# ─────────────────────────────────────────────────────────────
# Step 4: Draft wiki page updates
# ─────────────────────────────────────────────────────────────


def draft_updates(
    fetch_result: FetchResult,
    metadata: SourceMetadata,
    wiki_root: Path,
    model: str = DEFAULT_MODEL,
) -> str:
    """Use Claude to draft wiki page updates based on the new source.

    LangGraph node: takes FetchResult + SourceMetadata + wiki context, returns markdown.
    Does NOT write to wiki — returns draft for human review.
    """
    logger.info("Drafting wiki page updates...")

    # Read relevant existing wiki pages for context
    existing_context = _gather_wiki_context(metadata, wiki_root)

    prompt = dedent(f"""\
        You are a wiki maintainer for an AI in Banking knowledge base.

        A new source has been ingested:
        - Title: {metadata.title}
        - Type: {metadata.source_type}
        - Banks discussed: {', '.join(metadata.bank_tags) or 'none specified'}
        - Topics: {', '.join(metadata.topic_tags)}
        - Summary: {metadata.summary}

        <source_content>
        {fetch_result.content[:40000]}
        </source_content>

        <existing_wiki_context>
        {existing_context}
        </existing_wiki_context>

        Based on this source, draft the specific updates that should be made to the wiki.
        For each update, specify:
        1. Which page to update (or create)
        2. Which section to modify
        3. The exact content to add or change
        4. Any new cross-references ([[wikilinks]]) to add

        Use the wiki's conventions:
        - Tag inferences with [inference]
        - Tag dated claims with [dated: YYYY-MM]
        - Use [[kebab-case]] wikilinks
        - Note contradictions with existing content using > [!warning] Contradiction callouts

        Format your response as a structured markdown document that a human can review
        before applying the changes.
    """)

    client = get_client()
    response = client.messages.create(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text


def _gather_wiki_context(metadata: SourceMetadata, wiki_root: Path) -> str:
    """Read relevant existing wiki pages for context during update drafting."""
    context_parts: list[str] = []
    wiki_dir = wiki_root / "wiki"

    # Always include the index
    index_path = wiki_dir / "index.md"
    if index_path.exists():
        context_parts.append(f"--- wiki/index.md ---\n{index_path.read_text()[:3000]}")

    # Include bank profile pages for mentioned banks
    for bank_slug in metadata.bank_tags:
        bank_page = wiki_dir / "banks" / f"{bank_slug}.md"
        if bank_page.exists():
            context_parts.append(
                f"--- wiki/banks/{bank_slug}.md ---\n{bank_page.read_text()[:2000]}"
            )

    # Include any existing pages with matching topic tags (scan index for relevant links)
    # Simple approach: scan wiki dir for pages with matching tags in frontmatter
    for md_file in wiki_dir.rglob("*.md"):
        if md_file.name in ("index.md", "log.md") or "banks/" in str(md_file):
            continue  # Already handled
        try:
            content = md_file.read_text()[:1500]
            # Check if any topic tags appear in the page
            for tag in metadata.topic_tags[:3]:  # Limit to avoid scanning too much
                if tag in content.lower():
                    context_parts.append(
                        f"--- {md_file.relative_to(wiki_root)} ---\n{content}"
                    )
                    break
        except OSError:
            continue

    # Cap total context
    full_context = "\n\n".join(context_parts)
    if len(full_context) > 15000:
        full_context = full_context[:15000] + "\n\n[... context truncated ...]"

    return full_context or "No existing wiki pages found."


# ─────────────────────────────────────────────────────────────
# Step 5: Generate commentary/narrative
# ─────────────────────────────────────────────────────────────


def generate_commentary(
    fetch_result: FetchResult,
    metadata: SourceMetadata,
    wiki_root: Path,
    focus: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> str:
    """Use Claude to generate analytical commentary on the source.

    LangGraph node: produces a narrative suitable for filing as a wiki page
    in comparisons/ or trends/.
    """
    logger.info("Generating commentary...")

    existing_context = _gather_wiki_context(metadata, wiki_root)

    focus_instruction = ""
    if focus:
        focus_instruction = f"\nFocus your analysis on: {focus}"

    prompt = dedent(f"""\
        You are a senior analyst tracking AI adoption in banking. You work at RBC and are
        building a competitive intelligence knowledge base.

        A new source has been ingested:
        - Title: {metadata.title}
        - Type: {metadata.source_type}
        - Banks discussed: {', '.join(metadata.bank_tags) or 'none specified'}
        - Topics: {', '.join(metadata.topic_tags)}
        - Summary: {metadata.summary}
        {focus_instruction}

        <source_content>
        {fetch_result.content[:40000]}
        </source_content>

        <existing_wiki_context>
        {existing_context}
        </existing_wiki_context>

        Write an analytical commentary (500-800 words) that:
        1. Identifies the key strategic implications for the banking industry
        2. Compares the developments to what's known about RBC's position
        3. Notes any competitive advantages or gaps this reveals
        4. Identifies questions worth investigating further
        5. Suggests what this means for AI adoption trends

        Use the wiki's conventions:
        - Tag inferences with [inference]
        - Tag dated claims with [dated: {TODAY[:7]}]
        - Reference other wiki pages with [[wikilinks]] where relevant
        - Be specific about which banks and which capabilities

        Format as a wiki page that could be filed in wiki/trends/ or wiki/comparisons/:

        ---
        page_type: trend or comparison (pick the best fit)
        title: "Your chosen title"
        created: {TODAY}
        last_updated: {TODAY}
        source_count: 1
        sources: ["(source path will be filled in)"]
        bank_tags: {json.dumps(metadata.bank_tags)}
        topic_tags: {json.dumps(metadata.topic_tags)}
        confidence: low
        provenance: public
        ---

        Then the full commentary with proper headings.
    """)

    client = get_client()
    response = client.messages.create(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text


# ─────────────────────────────────────────────────────────────
# Pipeline orchestration
# ─────────────────────────────────────────────────────────────


def run_file_ingest_pipeline(
    file_path: Path,
    wiki_root: Path,
    bank_hint: Optional[str] = None,
    url_ref: str = "",
    with_updates: bool = True,
    with_commentary: bool = False,
    commentary_focus: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> ResearchResult:
    """Run the ingest pipeline from a local file (skips fetch step).

    Use this when:
    - A website blocks automated fetching (government, bank sites)
    - You've saved a PDF as text or markdown
    - You're ingesting personal notes or clipped articles
    - You've used browser save-as to capture content

    Usage:
        python tools/research.py ingest --file article.md --bank rbc
        python tools/research.py ingest --file occ-handbook.md --url-ref "https://occ.gov/..."
    """
    logger.info(f"Ingesting local file: {file_path}")

    content = file_path.read_text(encoding="utf-8", errors="replace")

    # Build a FetchResult from the local file
    fetch_result = FetchResult(
        url=url_ref,
        title=file_path.stem.replace("-", " ").replace("_", " ").title(),
        content=content,
        fetch_date=TODAY,
        content_length=len(content),
        domain=urlparse(url_ref).netloc.replace("www.", "") if url_ref else "local",
        success=True,
    )

    # Step 2: Summarize + metadata (LLM call)
    metadata = summarize(fetch_result, bank_hint=bank_hint, model=model)

    # Override URL with the reference URL if provided
    if url_ref:
        metadata.url = url_ref

    # Step 3: Generate source file
    source_path = generate_source_file(fetch_result, metadata, wiki_root)

    result = ResearchResult(
        fetch=fetch_result,
        metadata=metadata,
        source_path=str(source_path.relative_to(wiki_root)),
    )

    # Step 4: Draft wiki updates
    if with_updates:
        result.wiki_updates = draft_updates(fetch_result, metadata, wiki_root, model=model)

    # Step 5: Commentary
    if with_commentary:
        result.commentary = generate_commentary(
            fetch_result, metadata, wiki_root,
            focus=commentary_focus, model=model,
        )

    return result


def run_ingest_pipeline(
    url: str,
    wiki_root: Path,
    bank_hint: Optional[str] = None,
    with_updates: bool = True,
    with_commentary: bool = False,
    commentary_focus: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> ResearchResult:
    """Run the full ingest pipeline: fetch → summarize → file → draft updates.

    This is the main orchestrator. In a LangGraph migration, this becomes the
    graph definition connecting the nodes.
    """
    # Step 1: Fetch
    fetch_result = fetch_url(url)
    if not fetch_result.success:
        logger.error(f"Fetch failed: {fetch_result.error}")
        return ResearchResult(fetch=fetch_result)

    # Step 2: Summarize + metadata
    metadata = summarize(fetch_result, bank_hint=bank_hint, model=model)

    # Step 3: Generate source file
    source_path = generate_source_file(fetch_result, metadata, wiki_root)

    result = ResearchResult(
        fetch=fetch_result,
        metadata=metadata,
        source_path=str(source_path.relative_to(wiki_root)),
    )

    # Step 4: Draft wiki updates
    if with_updates:
        result.wiki_updates = draft_updates(fetch_result, metadata, wiki_root, model=model)

    # Step 5: Commentary
    if with_commentary:
        result.commentary = generate_commentary(
            fetch_result, metadata, wiki_root,
            focus=commentary_focus, model=model,
        )

    return result


def run_commentary_on_existing(
    source_path: Path,
    wiki_root: Path,
    focus: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> str:
    """Generate commentary on an existing source file in raw/."""
    content = source_path.read_text(encoding="utf-8")

    # Parse existing frontmatter
    from tools_shared import parse_frontmatter_simple
    fm = _parse_fm(content)

    fetch_result = FetchResult(
        url=fm.get("url", ""),
        title=fm.get("title", source_path.stem),
        content=content,
        fetch_date=TODAY,
        content_length=len(content),
        domain="",
        success=True,
    )

    bank_tags = _parse_yaml_list(fm.get("bank_tags", "[]"))
    topic_tags = _parse_yaml_list(fm.get("topic_tags", "[]"))

    metadata = SourceMetadata(
        title=fm.get("title", source_path.stem),
        source_type=fm.get("source_type", "unknown"),
        source_quality=fm.get("source_quality", "unknown"),
        issuer=fm.get("issuer", "unknown"),
        date_published=fm.get("date_published", TODAY),
        bank_tags=bank_tags,
        topic_tags=topic_tags,
        summary=fm.get("summary", ""),
        url=fm.get("url", ""),
    )

    return generate_commentary(fetch_result, metadata, wiki_root, focus=focus, model=model)


def _parse_fm(content: str) -> dict[str, str]:
    """Simple frontmatter parser (no PyYAML dependency)."""
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return {}
    fm: dict[str, str] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if ":" in line and not line.startswith("-"):
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip().strip('"').strip("'")
    return fm


def _parse_yaml_list(value: str) -> list[str]:
    """Parse a simple YAML inline list like [a, b, c]."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        items = value[1:-1].split(",")
        return [item.strip().strip('"').strip("'") for item in items if item.strip()]
    return []


# ─────────────────────────────────────────────────────────────
# Output formatting
# ─────────────────────────────────────────────────────────────


def print_result(result: ResearchResult, wiki_root: Path) -> None:
    """Print pipeline results to stdout."""
    print("\n" + "=" * 60)
    print("  Research Pipeline Result")
    print("=" * 60)

    if not result.fetch.success:
        print(f"\n  FETCH FAILED: {result.fetch.error}")
        return

    print(f"\n  Source: {result.fetch.url}")
    print(f"  Title: {result.metadata.title if result.metadata else 'N/A'}")

    if result.metadata:
        m = result.metadata
        print(f"  Type: {m.source_type} ({m.source_quality})")
        print(f"  Issuer: {m.issuer}")
        print(f"  Banks: {', '.join(m.bank_tags) or 'none'}")
        print(f"  Topics: {', '.join(m.topic_tags)}")
        print(f"\n  Summary: {m.summary}")

    if result.source_path:
        print(f"\n  Filed to: {result.source_path}")

    if result.wiki_updates:
        print(f"\n{'─' * 60}")
        print("  DRAFT WIKI UPDATES (review before applying)")
        print(f"{'─' * 60}\n")
        print(result.wiki_updates)

    if result.commentary:
        print(f"\n{'─' * 60}")
        print("  COMMENTARY")
        print(f"{'─' * 60}\n")
        print(result.commentary)

    print()


# ─────────────────────────────────────────────────────────────
# Interactive mode
# ─────────────────────────────────────────────────────────────


def interactive_mode(wiki_root: Path, model: str = DEFAULT_MODEL) -> None:
    """Interactive research session — paste URLs, get summaries, decide what to keep."""
    print("\n  AI in Banking Wiki — Interactive Research Mode")
    print("  Type a URL to ingest, or 'quit' to exit.\n")

    while True:
        try:
            user_input = input("  URL> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Goodbye.")
            break

        if not user_input or user_input.lower() in ("quit", "exit", "q"):
            break

        if not user_input.startswith("http"):
            print("  Please enter a valid URL (starting with http/https)")
            continue

        # Ask for optional bank hint
        bank = input("  Bank hint (slug or Enter to skip)> ").strip() or None

        # Run pipeline
        result = run_ingest_pipeline(
            url=user_input,
            wiki_root=wiki_root,
            bank_hint=bank,
            with_updates=True,
            with_commentary=False,
            model=model,
        )
        print_result(result, wiki_root)

        # Ask about commentary
        if result.fetch.success:
            do_commentary = input("  Generate commentary? (y/N)> ").strip().lower()
            if do_commentary == "y":
                focus = input("  Commentary focus (or Enter for general)> ").strip() or None
                result.commentary = generate_commentary(
                    result.fetch, result.metadata, wiki_root,
                    focus=focus, model=model,
                )
                print(f"\n{'─' * 60}")
                print("  COMMENTARY")
                print(f"{'─' * 60}\n")
                print(result.commentary)

        print()


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────


def find_wiki_root() -> Path:
    """Walk up from cwd looking for the wiki repo root."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / "AGENTS.md").exists() or (parent / "CLAUDE.md").exists():
            return parent
        if (parent / "wiki").is_dir() and (parent / "raw").is_dir():
            return parent
    return current


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Research pipeline for the AI in Banking Knowledge Wiki"
    )
    parser.add_argument(
        "--wiki-root",
        type=Path,
        default=None,
        help="Path to wiki repo root (default: auto-detect)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Claude model to use (default: {DEFAULT_MODEL})",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # ingest command
    ingest_parser = subparsers.add_parser("ingest", help="Ingest a URL or local file into the wiki")
    ingest_parser.add_argument("url", nargs="?", default=None, help="URL to fetch and ingest")
    ingest_parser.add_argument("--file", type=Path, dest="local_file",
                               help="Local file to ingest instead of fetching a URL (markdown, text, or pre-extracted PDF content)")
    ingest_parser.add_argument("--url-ref", dest="url_ref",
                               help="Original URL for attribution when using --file (recorded in frontmatter)")
    ingest_parser.add_argument("--bank", help="Bank slug hint (e.g., rbc, jpmorgan)")
    ingest_parser.add_argument(
        "--commentary", action="store_true", help="Also generate analytical commentary"
    )
    ingest_parser.add_argument(
        "--commentary-focus", help="Focus area for commentary"
    )
    ingest_parser.add_argument(
        "--no-updates", action="store_true", help="Skip drafting wiki updates"
    )

    # commentary command
    commentary_parser = subparsers.add_parser(
        "commentary", help="Generate commentary on an existing source"
    )
    commentary_parser.add_argument("source", type=Path, help="Path to source file in raw/")
    commentary_parser.add_argument("--focus", help="Focus area for commentary")

    # batch command
    batch_parser = subparsers.add_parser("batch", help="Batch ingest URLs from a file")
    batch_parser.add_argument("file", type=Path, help="File with one URL per line")
    batch_parser.add_argument("--bank", help="Bank slug hint for all URLs")

    # interactive command
    subparsers.add_parser("interactive", help="Interactive research session")

    args = parser.parse_args()
    wiki_root = args.wiki_root or find_wiki_root()

    if not args.command:
        parser.print_help()
        return

    if args.command == "ingest":
        if args.local_file:
            # Local file ingest — skip fetch, read from disk
            if not args.local_file.exists():
                logger.error(f"File not found: {args.local_file}")
                sys.exit(1)
            result = run_file_ingest_pipeline(
                file_path=args.local_file,
                wiki_root=wiki_root,
                bank_hint=args.bank,
                url_ref=args.url_ref or "",
                with_updates=not args.no_updates,
                with_commentary=args.commentary,
                commentary_focus=args.commentary_focus,
                model=args.model,
            )
        elif args.url:
            result = run_ingest_pipeline(
                url=args.url,
                wiki_root=wiki_root,
                bank_hint=args.bank,
                with_updates=not args.no_updates,
                with_commentary=args.commentary,
                commentary_focus=args.commentary_focus,
                model=args.model,
            )
        else:
            logger.error("Provide either a URL or --file path")
            sys.exit(1)
        print_result(result, wiki_root)

    elif args.command == "commentary":
        commentary = run_commentary_on_existing(
            source_path=args.source,
            wiki_root=wiki_root,
            focus=args.focus,
            model=args.model,
        )
        print(commentary)

    elif args.command == "batch":
        urls = [
            line.strip()
            for line in args.file.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        logger.info(f"Batch ingesting {len(urls)} URLs...")
        for i, url in enumerate(urls, 1):
            print(f"\n  [{i}/{len(urls)}] {url}")
            result = run_ingest_pipeline(
                url=url,
                wiki_root=wiki_root,
                bank_hint=args.bank,
                with_updates=False,  # Skip updates in batch mode for speed
                model=args.model,
            )
            if result.metadata:
                print(f"    → {result.metadata.title}")
                print(f"    → Filed: {result.source_path}")
            else:
                print(f"    → FAILED: {result.fetch.error}")

    elif args.command == "interactive":
        interactive_mode(wiki_root, model=args.model)


if __name__ == "__main__":
    main()
