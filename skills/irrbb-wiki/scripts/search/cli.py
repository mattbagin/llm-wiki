"""CLI entry point for the agentic search feature.

Usage:
    python tools/search/cli.py poll
    python tools/search/cli.py discover
    python tools/search/cli.py target --description "..." [--bank rbc] [--max-results 5]
    python tools/search/cli.py queue
    python tools/search/cli.py review <item_id>
    python tools/search/cli.py approve <item_id>
    python tools/search/cli.py reject <item_id> [--reason "..."]
    python tools/search/cli.py approve-all --min-score 9
    python tools/search/cli.py reject-all --max-score 5
    python tools/search/cli.py ingest-approved
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow both `python -m search.cli` and `python tools/search/cli.py` invocations.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "search"

import yaml

from .queue import ApprovalQueue
from .registry import load_registry


DEFAULT_REGISTRY_PATH = Path("tools/source_registry.yaml")
DEFAULT_INBOX_PATH = Path("inbox")
DEFAULT_WIKI_PATH = Path("wiki")


def cmd_poll(args: argparse.Namespace) -> int:
    from . import polling
    registry = load_registry(args.registry)
    summary = polling.run_polling(
        registry=registry,
        wiki_root=Path(args.wiki),
        inbox_root=Path(args.inbox),
        dry_run=args.dry_run,
    )
    print(yaml.safe_dump(summary, sort_keys=False))
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    from . import discovery
    registry = load_registry(args.registry)
    summary = discovery.run_discovery(
        registry=registry,
        wiki_root=Path(args.wiki),
        inbox_root=Path(args.inbox),
        dry_run=args.dry_run,
    )
    print(yaml.safe_dump(summary, sort_keys=False))
    return 0


def cmd_target(args: argparse.Namespace) -> int:
    from . import targeted
    registry = load_registry(args.registry)
    summary = targeted.run_targeted(
        description=args.description,
        registry=registry,
        wiki_root=Path(args.wiki),
        inbox_root=Path(args.inbox),
        bank_hint=args.bank,
        max_results=args.max_results,
        dry_run=args.dry_run,
    )
    print(yaml.safe_dump(summary, sort_keys=False))
    return 0


def cmd_queue(args: argparse.Namespace) -> int:
    queue = ApprovalQueue(Path(args.inbox))
    print(f"{'ID':<32} {'Score':<6} {'Source':<20} Title")
    for item in queue.iter_pending():
        eval_data = yaml.safe_load(item.evaluation_path.read_text(encoding="utf-8"))
        meta = eval_data.get("item", {})
        evaluation = eval_data.get("evaluation", {})
        title = meta.get("title", "?")[:60]
        source_id = meta.get("source_id", "?")[:18]
        score = evaluation.get("pass_1_score", "?")
        print(f"{item.item_id:<32} {score!s:<6} {source_id:<20} {title}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    queue = ApprovalQueue(Path(args.inbox))
    yaml_path = queue.pending_dir / f"{args.item_id}.yaml"
    md_path = queue.pending_dir / f"{args.item_id}.md"
    if not yaml_path.exists():
        print(f"item not found: {args.item_id}", file=sys.stderr)
        return 1
    print("─── EVALUATION ───")
    print(yaml_path.read_text(encoding="utf-8"))
    if md_path.exists():
        print("\n─── CONTENT (first 2000 chars) ───")
        print(md_path.read_text(encoding="utf-8")[:2000])
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    queue = ApprovalQueue(Path(args.inbox))
    queue.approve(args.item_id)
    print(f"approved: {args.item_id}")
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    queue = ApprovalQueue(Path(args.inbox))
    queue.reject(args.item_id, reason=args.reason)
    print(f"rejected: {args.item_id}")
    return 0


def cmd_approve_all(args: argparse.Namespace) -> int:
    queue = ApprovalQueue(Path(args.inbox))
    count = 0
    for item in list(queue.iter_pending()):
        eval_data = yaml.safe_load(item.evaluation_path.read_text(encoding="utf-8"))
        score = eval_data.get("evaluation", {}).get("pass_1_score", 0)
        if isinstance(score, int) and score >= args.min_score:
            queue.approve(item.item_id)
            count += 1
    print(f"approved {count} items (min_score={args.min_score})")
    return 0


def cmd_reject_all(args: argparse.Namespace) -> int:
    queue = ApprovalQueue(Path(args.inbox))
    count = 0
    for item in list(queue.iter_pending()):
        eval_data = yaml.safe_load(item.evaluation_path.read_text(encoding="utf-8"))
        score = eval_data.get("evaluation", {}).get("pass_1_score", 99)
        if isinstance(score, int) and score <= args.max_score:
            queue.reject(item.item_id, reason=f"bulk-reject max_score={args.max_score}")
            count += 1
    print(f"rejected {count} items (max_score={args.max_score})")
    return 0


def cmd_ingest_approved(args: argparse.Namespace) -> int:
    """Hand approved items off to the existing research.py ingest pipeline."""
    raise NotImplementedError(
        "Import research.run_file_ingest_pipeline and iterate queue.iter_approved()"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="search-cli", description="IRRBB wiki agentic search")
    p.add_argument("--registry", default=str(DEFAULT_REGISTRY_PATH))
    p.add_argument("--inbox", default=str(DEFAULT_INBOX_PATH))
    p.add_argument("--wiki", default=str(DEFAULT_WIKI_PATH))
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("poll", help="Run polling workflow")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_poll)

    s = sub.add_parser("discover", help="Run discovery workflow")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_discover)

    s = sub.add_parser("target", help="Run targeted search")
    s.add_argument("--description", required=True)
    s.add_argument("--bank")
    s.add_argument("--max-results", type=int, default=5)
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_target)

    s = sub.add_parser("queue", help="List pending items")
    s.set_defaults(func=cmd_queue)

    s = sub.add_parser("review", help="Show a pending item's evaluation + content")
    s.add_argument("item_id")
    s.set_defaults(func=cmd_review)

    s = sub.add_parser("approve", help="Approve a pending item")
    s.add_argument("item_id")
    s.set_defaults(func=cmd_approve)

    s = sub.add_parser("reject", help="Reject a pending item")
    s.add_argument("item_id")
    s.add_argument("--reason")
    s.set_defaults(func=cmd_reject)

    s = sub.add_parser("approve-all", help="Approve all pending items above a score threshold")
    s.add_argument("--min-score", type=int, required=True)
    s.set_defaults(func=cmd_approve_all)

    s = sub.add_parser("reject-all", help="Reject all pending items at or below a score threshold")
    s.add_argument("--max-score", type=int, required=True)
    s.set_defaults(func=cmd_reject_all)

    s = sub.add_parser("ingest-approved", help="Hand approved items to research.py pipeline")
    s.set_defaults(func=cmd_ingest_approved)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
