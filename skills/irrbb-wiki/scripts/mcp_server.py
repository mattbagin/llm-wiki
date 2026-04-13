#!/usr/bin/env python3
"""
MCP Server for the IRRBB Risk Knowledge Wiki.

Exposes the wiki as tools that any MCP-compatible agent can query:
  - wiki_search: Full-text search across wiki pages
  - wiki_read: Read a specific page by name
  - wiki_list: List pages with optional filters (page_type, tag)
  - wiki_index: Return the full index for navigation
  - wiki_ingest: Ingest a new source (requires explicit permission flag)

Transport: stdio (default) or SSE (with --sse flag)

Usage:
    python tools/mcp_server.py                     # stdio transport
    python tools/mcp_server.py --wiki-dir ./wiki   # explicit wiki path
    python tools/mcp_server.py --allow-ingest      # enable write operations

Dependencies:
    pip install mcp --break-system-packages

Architecture note:
    This server is intentionally simple — no embedding models, no vector DB.
    Search is BM25-style keyword matching over page content and frontmatter.
    For a wiki under ~500 pages, this is fast and sufficient. If you outgrow
    it, swap in qmd or a proper search backend behind the same tool interface.
"""

import argparse
import json
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass
from math import log as math_log
from pathlib import Path
from typing import Any, Optional

# ─────────────────────────────────────────────────────────────
# Attempt MCP import — fail gracefully with install instructions
# ─────────────────────────────────────────────────────────────

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool
except ImportError:
    print(
        "Error: MCP package not installed.\n"
        "Install with: pip install mcp --break-system-packages\n"
        "Or: pip install mcp  (if using a virtual environment)",
        file=sys.stderr,
    )
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("irrbb-wiki-mcp")

# ─────────────────────────────────────────────────────────────
# Wiki index and search
# ─────────────────────────────────────────────────────────────

FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
WIKILINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")


@dataclass
class WikiPage:
    """A parsed wiki page with frontmatter and content."""

    name: str  # filename stem, e.g. "eve-sensitivity"
    path: Path
    frontmatter: dict[str, str]
    content: str  # full content including frontmatter
    body: str  # content after frontmatter


def parse_frontmatter(content: str) -> dict[str, str]:
    """Extract YAML frontmatter as a flat dict."""
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        return {}
    fm: dict[str, str] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if ":" in line and not line.startswith("-"):
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip().strip('"').strip("'")
    return fm


def parse_list_field(content: str, field_name: str) -> list[str]:
    """Extract a YAML list field from frontmatter (e.g., tags: [a, b, c])."""
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        return []
    for line in match.group(1).splitlines():
        line = line.strip()
        if line.startswith(f"{field_name}:"):
            _, _, value = line.partition(":")
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                items = value[1:-1].split(",")
                return [item.strip().strip('"').strip("'") for item in items if item.strip()]
    return []


class WikiIndex:
    """In-memory index of all wiki pages with simple BM25-style search."""

    def __init__(self, wiki_dir: Path) -> None:
        self.wiki_dir = wiki_dir
        self.pages: dict[str, WikiPage] = {}
        self._rebuild()

    def _rebuild(self) -> None:
        """Scan wiki directory and index all pages."""
        self.pages.clear()
        if not self.wiki_dir.exists():
            logger.warning(f"Wiki directory not found: {self.wiki_dir}")
            return

        for md_file in self.wiki_dir.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                logger.warning(f"Could not read {md_file}: {e}")
                continue

            fm = parse_frontmatter(content)

            # Body is everything after frontmatter
            body = content
            fm_match = FRONTMATTER_PATTERN.match(content)
            if fm_match:
                body = content[fm_match.end() :].strip()

            page = WikiPage(
                name=md_file.stem,
                path=md_file,
                frontmatter=fm,
                content=content,
                body=body,
            )
            self.pages[page.name] = page

        logger.info(f"Indexed {len(self.pages)} wiki pages from {self.wiki_dir}")

    def refresh(self) -> None:
        """Re-scan the wiki directory (call after ingest)."""
        self._rebuild()

    def search(
        self,
        query: str,
        page_type: Optional[str] = None,
        tags: Optional[list[str]] = None,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Search wiki pages using BM25-style keyword matching.

        Searches across: title, aliases, tags, body content.
        Applies optional filters for page_type and tags.
        """
        query_terms = _tokenize(query.lower())
        if not query_terms:
            return []

        # Pre-filter by page_type and tags
        candidates = list(self.pages.values())
        if page_type:
            candidates = [
                p for p in candidates if p.frontmatter.get("page_type", "").lower() == page_type.lower()
            ]
        if tags:
            tag_set = {t.lower() for t in tags}
            candidates = [
                p
                for p in candidates
                if tag_set.intersection(
                    t.lower() for t in parse_list_field(p.content, "tags")
                )
            ]

        # Score each candidate
        scored: list[tuple[float, WikiPage]] = []
        for page in candidates:
            score = _score_page(page, query_terms)
            if score > 0:
                scored.append((score, page))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, page in scored[:max_results]:
            results.append(
                {
                    "name": page.name,
                    "title": page.frontmatter.get("title", page.name),
                    "page_type": page.frontmatter.get("page_type", "unknown"),
                    "confidence": page.frontmatter.get("confidence", "unknown"),
                    "provenance": page.frontmatter.get("provenance", "unknown"),
                    "tags": parse_list_field(page.content, "tags"),
                    "score": round(score, 3),
                    "summary": _extract_summary(page.body),
                }
            )
        return results

    def read_page(self, page_name: str) -> Optional[dict[str, Any]]:
        """Read a specific wiki page by name."""
        page = self.pages.get(page_name)
        if not page:
            # Try case-insensitive match
            for name, p in self.pages.items():
                if name.lower() == page_name.lower():
                    page = p
                    break
        if not page:
            return None

        return {
            "name": page.name,
            "title": page.frontmatter.get("title", page.name),
            "page_type": page.frontmatter.get("page_type", "unknown"),
            "confidence": page.frontmatter.get("confidence", "unknown"),
            "provenance": page.frontmatter.get("provenance", "unknown"),
            "tags": parse_list_field(page.content, "tags"),
            "sources": parse_list_field(page.content, "sources"),
            "cross_references": WIKILINK_PATTERN.findall(page.body),
            "content": page.content,
        }

    def list_pages(
        self,
        page_type: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> list[dict[str, str]]:
        """List all pages with optional filters."""
        results = []
        for page in self.pages.values():
            if page_type and page.frontmatter.get("page_type", "").lower() != page_type.lower():
                continue
            if tag:
                page_tags = [t.lower() for t in parse_list_field(page.content, "tags")]
                if tag.lower() not in page_tags:
                    continue
            results.append(
                {
                    "name": page.name,
                    "title": page.frontmatter.get("title", page.name),
                    "page_type": page.frontmatter.get("page_type", "unknown"),
                    "confidence": page.frontmatter.get("confidence", "unknown"),
                    "provenance": page.frontmatter.get("provenance", "unknown"),
                }
            )
        results.sort(key=lambda x: x["name"])
        return results


# ─────────────────────────────────────────────────────────────
# Simple BM25-style scoring
# ─────────────────────────────────────────────────────────────

_STOP_WORDS = frozenset(
    "the a an is are was were be been being have has had do does did "
    "will would shall should may might can could and or but if then else "
    "for in on at to from by with of this that these those it its".split()
)


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase words, removing stop words."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 1]


def _score_page(page: WikiPage, query_terms: list[str]) -> float:
    """Score a page against query terms with field weighting."""
    # Build weighted text fields
    title = page.frontmatter.get("title", "").lower()
    aliases_raw = page.frontmatter.get("aliases", "")
    tags_text = " ".join(parse_list_field(page.content, "tags")).lower()
    body = page.body.lower()

    # Tokenize fields
    title_tokens = Counter(_tokenize(title))
    alias_tokens = Counter(_tokenize(aliases_raw))
    tag_tokens = Counter(_tokenize(tags_text))
    body_tokens = Counter(_tokenize(body))

    # Field weights
    score = 0.0
    body_len = max(sum(body_tokens.values()), 1)

    for term in query_terms:
        # Title match (highest weight)
        if term in title_tokens:
            score += 10.0

        # Alias match
        if term in alias_tokens:
            score += 8.0

        # Tag match
        if term in tag_tokens:
            score += 6.0

        # Body match (BM25-ish: term frequency with diminishing returns)
        tf = body_tokens.get(term, 0)
        if tf > 0:
            # Saturating TF: tf / (tf + 1.2)
            k1 = 1.2
            normalized_tf = tf / (tf + k1 * (1.0 + body_len / 500.0))
            score += 3.0 * normalized_tf

    return score


def _extract_summary(body: str) -> str:
    """Extract the first meaningful paragraph as a summary."""
    lines = body.splitlines()
    summary_lines: list[str] = []
    in_summary = False
    for line in lines:
        stripped = line.strip()
        # Skip headers and empty lines until we find content
        if not stripped or stripped.startswith("#"):
            if in_summary and summary_lines:
                break
            continue
        # Skip YAML-like lines and table separators
        if stripped.startswith("|") or stripped.startswith("---"):
            if in_summary:
                break
            continue
        in_summary = True
        summary_lines.append(stripped)
        if len(" ".join(summary_lines)) > 300:
            break

    summary = " ".join(summary_lines)
    if len(summary) > 300:
        summary = summary[:297] + "..."
    return summary


# ─────────────────────────────────────────────────────────────
# MCP Server
# ─────────────────────────────────────────────────────────────


def create_server(wiki_dir: Path, raw_dir: Path, allow_ingest: bool = False) -> Server:
    """Create and configure the MCP server with wiki tools."""

    server = Server("irrbb-wiki-mcp")
    wiki_index = WikiIndex(wiki_dir)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        tools = [
            Tool(
                name="wiki_search",
                description=(
                    "Search the IRRBB wiki for pages matching a query. Returns ranked results "
                    "with page name, title, type, confidence, provenance, tags, and a summary snippet. "
                    "Use this to find relevant wiki pages before reading them in full. "
                    "Optionally filter by page_type (concept, regulation, model, entity, comparison, "
                    "open-question) and/or tags."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query — use IRRBB domain terms (e.g., 'NMD behavioral modeling', 'EVE outlier test', 'OSFI B-12 NII')",
                        },
                        "page_type": {
                            "type": "string",
                            "description": "Optional filter: concept, regulation, model, entity, comparison, open-question",
                            "enum": ["concept", "regulation", "model", "entity", "comparison", "open-question"],
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional tag filter — pages must have at least one matching tag",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum results to return (default: 10)",
                            "default": 10,
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="wiki_read",
                description=(
                    "Read a specific wiki page by name. Returns the full page content including "
                    "frontmatter, body, cross-references, and source list. Use this after wiki_search "
                    "to get the full content of a relevant page. Page names are kebab-case "
                    "(e.g., 'eve-sensitivity', 'bcbs-368', 'nmd-behavioral-modeling')."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page_name": {
                            "type": "string",
                            "description": "Page name (filename without .md extension, e.g., 'eve-sensitivity')",
                        },
                    },
                    "required": ["page_name"],
                },
            ),
            Tool(
                name="wiki_list",
                description=(
                    "List all wiki pages, optionally filtered by page_type or tag. Returns page name, "
                    "title, type, confidence, and provenance for each page. Use this for broad "
                    "exploration or to see what the wiki covers."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page_type": {
                            "type": "string",
                            "description": "Optional filter by page type",
                            "enum": ["concept", "regulation", "model", "entity", "comparison", "open-question"],
                        },
                        "tag": {
                            "type": "string",
                            "description": "Optional filter by tag (e.g., 'eve', 'nmd', 'osfi')",
                        },
                    },
                },
            ),
            Tool(
                name="wiki_index",
                description=(
                    "Return the full wiki index page. This is the primary navigation document — "
                    "a categorized catalog of every page in the wiki with one-line summaries. "
                    "Read this first to understand what the wiki contains and find relevant pages."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
        ]

        if allow_ingest:
            tools.append(
                Tool(
                    name="wiki_ingest",
                    description=(
                        "Signal that a new source has been added to raw/ and the wiki should be updated. "
                        "This tool refreshes the wiki index after filesystem changes. The actual ingest "
                        "workflow (reading the source, creating/updating wiki pages, updating index.md) "
                        "should be performed by the agent following the SKILL.md ingest workflow, then "
                        "call this tool to refresh the in-memory index."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "source_path": {
                                "type": "string",
                                "description": "Path to the newly ingested source in raw/",
                            },
                            "pages_affected": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of wiki page names that were created or updated",
                            },
                        },
                        "required": ["source_path"],
                    },
                )
            )

        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == "wiki_search":
            results = wiki_index.search(
                query=arguments["query"],
                page_type=arguments.get("page_type"),
                tags=arguments.get("tags"),
                max_results=arguments.get("max_results", 10),
            )
            if not results:
                return [TextContent(type="text", text="No matching wiki pages found for this query.")]
            return [TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "wiki_read":
            page = wiki_index.read_page(arguments["page_name"])
            if not page:
                available = ", ".join(sorted(wiki_index.pages.keys())[:20])
                return [
                    TextContent(
                        type="text",
                        text=f"Page '{arguments['page_name']}' not found. Available pages include: {available}",
                    )
                ]
            return [TextContent(type="text", text=json.dumps(page, indent=2))]

        elif name == "wiki_list":
            pages = wiki_index.list_pages(
                page_type=arguments.get("page_type"),
                tag=arguments.get("tag"),
            )
            if not pages:
                return [TextContent(type="text", text="No pages match the given filters.")]
            return [TextContent(type="text", text=json.dumps(pages, indent=2))]

        elif name == "wiki_index":
            index_page = wiki_index.read_page("index")
            if not index_page:
                return [TextContent(type="text", text="wiki/index.md not found.")]
            return [TextContent(type="text", text=index_page["content"])]

        elif name == "wiki_ingest":
            if not allow_ingest:
                return [
                    TextContent(
                        type="text",
                        text="Ingest is disabled. Start the server with --allow-ingest to enable write operations.",
                    )
                ]
            # Refresh the in-memory index after filesystem changes
            wiki_index.refresh()
            source = arguments.get("source_path", "unknown")
            affected = arguments.get("pages_affected", [])
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "status": "refreshed",
                            "source": source,
                            "pages_affected": affected,
                            "total_pages": len(wiki_index.pages),
                        },
                        indent=2,
                    ),
                )
            ]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return server


# ─────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────


def find_repo_root() -> Path:
    """Walk up from cwd looking for the wiki repo root."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / "AGENTS.md").exists() or (parent / "CLAUDE.md").exists():
            return parent
        if (parent / "wiki").is_dir() and (parent / "raw").is_dir():
            return parent
    return current


async def main() -> None:
    parser = argparse.ArgumentParser(description="MCP server for the IRRBB Risk Knowledge Wiki")
    parser.add_argument("--wiki-dir", type=Path, default=None, help="Path to wiki/ directory")
    parser.add_argument("--raw-dir", type=Path, default=None, help="Path to raw/ directory")
    parser.add_argument("--allow-ingest", action="store_true", help="Enable write operations (ingest)")
    args = parser.parse_args()

    repo_root = find_repo_root()
    wiki_dir = args.wiki_dir or (repo_root / "wiki")
    raw_dir = args.raw_dir or (repo_root / "raw")

    if not wiki_dir.exists():
        logger.error(f"Wiki directory not found: {wiki_dir}")
        logger.error("Run bootstrap.py first, or specify --wiki-dir")
        sys.exit(1)

    server = create_server(wiki_dir, raw_dir, allow_ingest=args.allow_ingest)

    logger.info(f"Starting IRRBB Wiki MCP server (wiki: {wiki_dir}, ingest: {args.allow_ingest})")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
