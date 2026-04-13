#!/usr/bin/env python3
"""
Lint tool for the IRRBB Risk Knowledge Wiki.

Checks wiki health across multiple dimensions:
  1. Broken wikilinks — [[links]] that don't resolve to existing pages
  2. Orphan pages — pages with no inbound links from other pages
  3. Missing/incomplete frontmatter — pages missing required YAML fields
  4. Confidence issues — high-confidence pages with few sources
  5. Stale sources — sources marked as superseded still cited by wiki pages
  6. Internal leakage — confidential source content synthesized into wiki pages
  7. Coverage gaps — [[stub]] markers indicating pages that should exist
  8. Index sync — pages on disk that aren't listed in index.md

Usage:
    python tools/lint_wiki.py                    # Run from repo root
    python tools/lint_wiki.py --wiki-dir ./wiki  # Explicit wiki directory
    python tools/lint_wiki.py --raw-dir ./raw    # Explicit raw directory
    python tools/lint_wiki.py --fix              # Auto-fix what's possible (index sync)
    python tools/lint_wiki.py --json             # Output results as JSON
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

REQUIRED_FRONTMATTER_FIELDS = [
    "page_type",
    "title",
    "created",
    "last_updated",
    "confidence",
    "provenance",
]

# Pages that don't need standard frontmatter
SPECIAL_PAGES = {"index.md", "log.md"}

# Wikilink pattern: [[some-page-name]]
WIKILINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")

# Stub marker pattern: topic name [stub]
STUB_PATTERN = re.compile(r"(\w[\w\s-]+)\s*\[stub\]")

# YAML frontmatter extraction (simple — between first two ---)
FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


# ─────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────


@dataclass
class LintIssue:
    """A single lint finding."""

    check: str  # e.g., "broken-link", "orphan", "frontmatter"
    severity: str  # "error", "warning", "info"
    file: str  # relative path
    message: str
    suggestion: Optional[str] = None


@dataclass
class LintReport:
    """Aggregated lint results."""

    issues: list[LintIssue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, issue: LintIssue) -> None:
        self.issues.append(issue)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "info")


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────


def parse_frontmatter(content: str) -> dict[str, str]:
    """Extract YAML frontmatter as a flat key-value dict.

    This is intentionally simple — no PyYAML dependency. Handles
    single-line key: value pairs and basic lists. Good enough for
    frontmatter validation.
    """
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


def find_wiki_pages(wiki_dir: Path) -> dict[str, Path]:
    """Build a map of page_name -> file_path for all .md files in wiki/.

    Page names are derived from the filename (without extension), which is
    what wikilinks reference: [[page-name]] -> page-name.md
    """
    pages: dict[str, Path] = {}
    for md_file in wiki_dir.rglob("*.md"):
        # Use stem (filename without extension) as the link target
        page_name = md_file.stem
        pages[page_name] = md_file
    return pages


def extract_wikilinks(content: str) -> list[str]:
    """Extract all [[wikilink]] targets from page content."""
    return WIKILINK_PATTERN.findall(content)


def extract_stubs(content: str) -> list[str]:
    """Extract all [stub] markers from page content."""
    return [m.strip() for m in STUB_PATTERN.findall(content)]


def relative_path(path: Path, base: Path) -> str:
    """Get a clean relative path string for display."""
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


# ─────────────────────────────────────────────────────────────
# Lint checks
# ─────────────────────────────────────────────────────────────


def check_broken_links(
    wiki_dir: Path, pages: dict[str, Path], base: Path
) -> list[LintIssue]:
    """Find [[wikilinks]] that don't resolve to any existing page."""
    issues: list[LintIssue] = []
    for page_name, page_path in pages.items():
        content = page_path.read_text(encoding="utf-8", errors="replace")
        for link_target in extract_wikilinks(content):
            if link_target not in pages:
                issues.append(
                    LintIssue(
                        check="broken-link",
                        severity="error",
                        file=relative_path(page_path, base),
                        message=f"Broken wikilink: [[{link_target}]]",
                        suggestion=f"Create wiki page '{link_target}.md' or replace with '{link_target} [stub]'",
                    )
                )
    return issues


def check_orphan_pages(
    wiki_dir: Path, pages: dict[str, Path], base: Path
) -> list[LintIssue]:
    """Find pages with no inbound [[links]] from other pages."""
    # Build inbound link counts
    inbound: dict[str, int] = {name: 0 for name in pages}

    for page_name, page_path in pages.items():
        content = page_path.read_text(encoding="utf-8", errors="replace")
        for link_target in extract_wikilinks(content):
            if link_target in inbound:
                inbound[link_target] += 1

    issues: list[LintIssue] = []
    # Special pages and overview are allowed to be orphans
    exempt = {"index", "log", "overview"}
    for page_name, count in inbound.items():
        if count == 0 and page_name not in exempt:
            issues.append(
                LintIssue(
                    check="orphan",
                    severity="warning",
                    file=relative_path(pages[page_name], base),
                    message=f"Orphan page: no other page links to [[{page_name}]]",
                    suggestion="Add a [[link]] to this page from a related page, or add it to a Cross-References section",
                )
            )
    return issues


def check_frontmatter(
    wiki_dir: Path, pages: dict[str, Path], base: Path
) -> list[LintIssue]:
    """Check for missing or incomplete YAML frontmatter."""
    issues: list[LintIssue] = []
    for page_name, page_path in pages.items():
        if page_path.name in SPECIAL_PAGES:
            continue

        content = page_path.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(content)

        if not fm:
            issues.append(
                LintIssue(
                    check="frontmatter",
                    severity="error",
                    file=relative_path(page_path, base),
                    message="Missing YAML frontmatter",
                    suggestion="Add frontmatter block with required fields: "
                    + ", ".join(REQUIRED_FRONTMATTER_FIELDS),
                )
            )
            continue

        for required_field in REQUIRED_FRONTMATTER_FIELDS:
            if required_field not in fm or not fm[required_field]:
                issues.append(
                    LintIssue(
                        check="frontmatter",
                        severity="warning",
                        file=relative_path(page_path, base),
                        message=f"Missing frontmatter field: {required_field}",
                        suggestion=f"Add '{required_field}:' to the frontmatter block",
                    )
                )
    return issues


def check_confidence(
    wiki_dir: Path, pages: dict[str, Path], base: Path
) -> list[LintIssue]:
    """Flag pages with high confidence but few sources, or old sources."""
    issues: list[LintIssue] = []
    for page_name, page_path in pages.items():
        if page_path.name in SPECIAL_PAGES:
            continue

        content = page_path.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(content)

        confidence = fm.get("confidence", "").lower()
        source_count_str = fm.get("source_count", "0")

        try:
            source_count = int(source_count_str)
        except ValueError:
            source_count = 0

        if confidence == "high" and source_count <= 1:
            issues.append(
                LintIssue(
                    check="confidence",
                    severity="warning",
                    file=relative_path(page_path, base),
                    message=f"High confidence with only {source_count} source(s)",
                    suggestion="Downgrade confidence to 'medium' or add more supporting sources",
                )
            )
    return issues


def check_stubs(
    wiki_dir: Path, pages: dict[str, Path], base: Path
) -> list[LintIssue]:
    """Find [stub] markers indicating pages that should be created."""
    issues: list[LintIssue] = []
    for page_name, page_path in pages.items():
        content = page_path.read_text(encoding="utf-8", errors="replace")
        for stub_name in extract_stubs(content):
            issues.append(
                LintIssue(
                    check="stub",
                    severity="info",
                    file=relative_path(page_path, base),
                    message=f"Stub marker: '{stub_name}' — page should be created",
                    suggestion=f"Create a page for '{stub_name}' and replace the [stub] marker with a [[wikilink]]",
                )
            )
    return issues


def check_index_sync(
    wiki_dir: Path, pages: dict[str, Path], base: Path
) -> list[LintIssue]:
    """Check that all wiki pages on disk are listed in index.md."""
    index_path = wiki_dir / "index.md"
    if not index_path.exists():
        return [
            LintIssue(
                check="index-sync",
                severity="error",
                file="wiki/index.md",
                message="index.md does not exist",
                suggestion="Run bootstrap.py or create wiki/index.md manually",
            )
        ]

    index_content = index_path.read_text(encoding="utf-8", errors="replace")
    index_links = set(extract_wikilinks(index_content))

    issues: list[LintIssue] = []
    exempt = {"index", "log", "overview"}
    for page_name in pages:
        if page_name not in exempt and page_name not in index_links:
            issues.append(
                LintIssue(
                    check="index-sync",
                    severity="warning",
                    file=relative_path(pages[page_name], base),
                    message=f"Page '{page_name}' exists on disk but is not in index.md",
                    suggestion=f"Add [[{page_name}]] to the appropriate section in wiki/index.md",
                )
            )
    return issues


def check_source_staleness(raw_dir: Path, base: Path) -> list[LintIssue]:
    """Find sources in raw/ that are marked as superseded."""
    issues: list[LintIssue] = []
    if not raw_dir.exists():
        return issues

    for md_file in raw_dir.rglob("*.md"):
        content = md_file.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(content)

        if fm.get("status", "").lower() == "superseded":
            superseded_by = fm.get("superseded_by", "unknown")
            issues.append(
                LintIssue(
                    check="stale-source",
                    severity="warning",
                    file=relative_path(md_file, base),
                    message=f"Source is marked superseded (by: {superseded_by})",
                    suggestion="Check wiki pages citing this source — claims may need updating",
                )
            )
    return issues


def check_classification_leakage(
    wiki_dir: Path,
    raw_dir: Path,
    pages: dict[str, Path],
    base: Path,
) -> list[LintIssue]:
    """Check that wiki pages citing confidential sources only reference them by title.

    This is a heuristic check — it looks for wiki pages whose 'sources' frontmatter
    references files classified as confidential. The actual content check would require
    NLP, so this flags the relationship for human review.
    """
    issues: list[LintIssue] = []

    # Build a set of confidential source paths
    confidential_sources: set[str] = set()
    if raw_dir.exists():
        for md_file in raw_dir.rglob("*.md"):
            content = md_file.read_text(encoding="utf-8", errors="replace")
            fm = parse_frontmatter(content)
            if fm.get("classification", "").lower() == "confidential":
                confidential_sources.add(str(md_file.relative_to(base)))

    if not confidential_sources:
        return issues

    # Check each wiki page's sources list
    for page_name, page_path in pages.items():
        content = page_path.read_text(encoding="utf-8", errors="replace")
        for conf_source in confidential_sources:
            # Check if the confidential source path appears in the page content
            if conf_source in content:
                issues.append(
                    LintIssue(
                        check="classification-leakage",
                        severity="error",
                        file=relative_path(page_path, base),
                        message=f"References confidential source: {conf_source}",
                        suggestion="Ensure only the source title is referenced — no synthesized content from confidential sources",
                    )
                )
    return issues


# ─────────────────────────────────────────────────────────────
# Report formatting
# ─────────────────────────────────────────────────────────────

SEVERITY_ICONS = {
    "error": "\u2718",    # ✘
    "warning": "\u26a0",  # ⚠
    "info": "\u2139",     # ℹ
}

SEVERITY_COLORS = {
    "error": "\033[91m",    # red
    "warning": "\033[93m",  # yellow
    "info": "\033[94m",     # blue
}
RESET = "\033[0m"


def format_issue(issue: LintIssue, use_color: bool = True) -> str:
    """Format a single issue for terminal display."""
    icon = SEVERITY_ICONS.get(issue.severity, "?")
    if use_color:
        color = SEVERITY_COLORS.get(issue.severity, "")
        line = f"  {color}{icon} [{issue.check}]{RESET} {issue.file}"
    else:
        line = f"  {icon} [{issue.check}] {issue.file}"

    line += f"\n    {issue.message}"
    if issue.suggestion:
        line += f"\n    -> {issue.suggestion}"
    return line


def print_report(report: LintReport, use_color: bool = True) -> None:
    """Print the full lint report to stdout."""
    print("\n" + "=" * 60)
    print("  IRRBB Wiki Lint Report")
    print("=" * 60)

    # Stats
    stats = report.stats
    print(f"\n  Wiki pages: {stats.get('page_count', 0)}")
    print(f"  Sources in raw/: {stats.get('source_count', 0)}")
    print()

    if not report.issues:
        print("  All checks passed. Wiki is healthy.\n")
        return

    # Group by check
    checks_seen: list[str] = []
    issues_by_check: dict[str, list[LintIssue]] = {}
    for issue in report.issues:
        if issue.check not in issues_by_check:
            checks_seen.append(issue.check)
            issues_by_check[issue.check] = []
        issues_by_check[issue.check].append(issue)

    for check_name in checks_seen:
        issues = issues_by_check[check_name]
        print(f"  --- {check_name} ({len(issues)} issue{'s' if len(issues) != 1 else ''}) ---\n")
        for issue in issues:
            print(format_issue(issue, use_color))
            print()

    # Summary
    print("-" * 60)
    parts = []
    if report.error_count:
        parts.append(f"{report.error_count} error{'s' if report.error_count != 1 else ''}")
    if report.warning_count:
        parts.append(f"{report.warning_count} warning{'s' if report.warning_count != 1 else ''}")
    if report.info_count:
        parts.append(f"{report.info_count} info")
    print(f"  Total: {', '.join(parts)}")
    print()


def report_to_json(report: LintReport) -> str:
    """Serialize the report to JSON."""
    return json.dumps(
        {
            "stats": report.stats,
            "summary": {
                "errors": report.error_count,
                "warnings": report.warning_count,
                "info": report.info_count,
            },
            "issues": [
                {
                    "check": i.check,
                    "severity": i.severity,
                    "file": i.file,
                    "message": i.message,
                    "suggestion": i.suggestion,
                }
                for i in report.issues
            ],
        },
        indent=2,
    )


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────


def find_repo_root() -> Path:
    """Walk up from cwd looking for AGENTS.md or CLAUDE.md."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / "AGENTS.md").exists() or (parent / "CLAUDE.md").exists():
            return parent
        if (parent / "wiki").is_dir() and (parent / "raw").is_dir():
            return parent
    return current


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lint the IRRBB Risk Knowledge Wiki"
    )
    parser.add_argument(
        "--wiki-dir",
        type=Path,
        default=None,
        help="Path to wiki/ directory (default: auto-detect from repo root)",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=None,
        help="Path to raw/ directory (default: auto-detect from repo root)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of formatted text",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output",
    )
    args = parser.parse_args()

    # Resolve paths
    repo_root = find_repo_root()
    wiki_dir = args.wiki_dir or (repo_root / "wiki")
    raw_dir = args.raw_dir or (repo_root / "raw")

    if not wiki_dir.exists():
        print(f"Error: wiki directory not found at {wiki_dir}")
        print("Run bootstrap.py first, or specify --wiki-dir")
        sys.exit(1)

    # Discover pages
    pages = find_wiki_pages(wiki_dir)
    base = repo_root

    # Count sources
    source_count = 0
    if raw_dir.exists():
        source_count = sum(1 for _ in raw_dir.rglob("*.md")) - sum(
            1 for f in raw_dir.rglob("*.md") if f.name == "README.md"
        )

    # Run all checks
    report = LintReport()
    report.stats = {
        "page_count": len(pages),
        "source_count": source_count,
        "wiki_dir": str(wiki_dir),
        "raw_dir": str(raw_dir),
    }

    report.issues.extend(check_broken_links(wiki_dir, pages, base))
    report.issues.extend(check_orphan_pages(wiki_dir, pages, base))
    report.issues.extend(check_frontmatter(wiki_dir, pages, base))
    report.issues.extend(check_confidence(wiki_dir, pages, base))
    report.issues.extend(check_stubs(wiki_dir, pages, base))
    report.issues.extend(check_index_sync(wiki_dir, pages, base))
    report.issues.extend(check_source_staleness(raw_dir, base))
    report.issues.extend(
        check_classification_leakage(wiki_dir, raw_dir, pages, base)
    )

    # Output
    if args.json:
        print(report_to_json(report))
    else:
        use_color = not args.no_color and sys.stdout.isatty()
        print_report(report, use_color)

    # Exit code: 1 if errors, 0 otherwise
    sys.exit(1 if report.error_count > 0 else 0)


if __name__ == "__main__":
    main()
