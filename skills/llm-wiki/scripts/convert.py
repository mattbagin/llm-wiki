#!/usr/bin/env python3
"""
Convert web pages, .docx, .pdf (and other office formats) into Markdown for the
LLM wiki's ingest pipeline.

Strategy: prefer Microsoft's `markitdown` (one library covers docx/pdf/pptx/xlsx/
html/images). If it isn't installed, fall back to focused per-format libraries so
the tool still works on locked-down machines:

    .docx        → mammoth, else python-docx
    .pdf         → pdfplumber, else pypdf
    .html/.htm   → research.py's HTML→text extractor
    URL          → research.py fetch + extract (or markitdown if available)
    .md/.txt     → passthrough

Usage:
    python tools/convert.py path/to/file.docx
    python tools/convert.py https://example.com/article -o out.md
    python tools/convert.py report.pdf --out report.md

Install (optional, as needed):
    pip install markitdown          # preferred, covers everything
    pip install mammoth pdfplumber  # fallbacks
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("convert")

PASSTHROUGH_SUFFIXES = {".md", ".markdown", ".txt"}


def is_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


def convert(source: str) -> str:
    """Convert a file path or URL to Markdown text. Raises RuntimeError with an
    actionable message if no converter is available for the input."""
    if is_url(source):
        return _convert_url(source)

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"file not found: {source}")

    suffix = path.suffix.lower()
    if suffix in PASSTHROUGH_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")

    # Preferred: markitdown handles all office/pdf/html formats.
    md = _try_markitdown(str(path))
    if md is not None:
        return md

    if suffix == ".docx":
        return _docx_fallback(path)
    if suffix == ".pdf":
        return _pdf_fallback(path)
    if suffix in (".html", ".htm"):
        return _html_fallback(path.read_text(encoding="utf-8", errors="replace"))

    raise RuntimeError(
        f"no converter available for {suffix or 'this file'}. "
        "Install markitdown (`pip install markitdown`) for broad format support."
    )


# ── Converters ───────────────────────────────────────────────────────────────


def _try_markitdown(source: str) -> str | None:
    """Return markdown via markitdown, or None if markitdown isn't installed."""
    try:
        from markitdown import MarkItDown
    except ImportError:
        return None
    try:
        result = MarkItDown().convert(source)
        return result.text_content
    except Exception as e:  # noqa: BLE001 — fall back on any markitdown failure
        logger.warning("markitdown failed on %s (%s) — trying fallback", source, e)
        return None


def _convert_url(url: str) -> str:
    md = _try_markitdown(url)
    if md is not None:
        return md
    # Fallback: reuse research.py's fetcher + HTML→text extractor.
    research = _import_research()
    if research is not None:
        res = research.fetch_url(url)
        if res.success:
            return f"# {res.title}\n\nSource: {url}\n\n{res.content}"
        raise RuntimeError(f"failed to fetch {url}: {res.error}")
    # Last resort: raw httpx + local HTML extractor.
    import httpx

    resp = httpx.get(url, follow_redirects=True, timeout=30, headers={"User-Agent": "LLM-Wiki-Research/1.0"})
    resp.raise_for_status()
    return _html_fallback(resp.text)


def _docx_fallback(path: Path) -> str:
    try:
        import mammoth

        with path.open("rb") as fh:
            return mammoth.convert_to_markdown(fh).value
    except ImportError:
        pass
    try:
        import docx  # python-docx

        document = docx.Document(str(path))
        return "\n\n".join(p.text for p in document.paragraphs if p.text.strip())
    except ImportError as e:
        raise RuntimeError(
            "no .docx converter installed. `pip install markitdown` (preferred) "
            "or `pip install mammoth` / `pip install python-docx`."
        ) from e


def _pdf_fallback(path: Path) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n\n".join(pages).strip()
    except ImportError:
        pass
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except ImportError as e:
        raise RuntimeError(
            "no .pdf converter installed. `pip install markitdown` (preferred) "
            "or `pip install pdfplumber` / `pip install pypdf`."
        ) from e


def _html_fallback(html: str) -> str:
    """Use research.py's HTML→text extractor if importable, else a minimal strip."""
    research = _import_research()
    if research is not None and hasattr(research, "_extract_text_from_html"):
        title = research._extract_title_from_html(html)
        text = research._extract_text_from_html(html)
        return (f"# {title}\n\n{text}" if title else text)
    import re

    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+\n", "\n", text).strip()


def _import_research():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import research  # type: ignore
        return research
    except ImportError:
        return None


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a file or URL to Markdown")
    parser.add_argument("source", help="Path to a file (.docx/.pdf/.html/...) or a URL")
    parser.add_argument("-o", "--out", type=Path, help="Write markdown here (default: stdout)")
    args = parser.parse_args()

    try:
        markdown = convert(args.source)
    except (FileNotFoundError, RuntimeError) as e:
        logger.error("%s", e)
        sys.exit(1)

    if args.out:
        args.out.write_text(markdown, encoding="utf-8")
        logger.info("wrote %d chars to %s", len(markdown), args.out)
    else:
        sys.stdout.write(markdown)


if __name__ == "__main__":
    main()
