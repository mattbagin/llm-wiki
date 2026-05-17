"""Approval queue: filesystem-backed inbox with seen-URL state.

The queue is intentionally simple: YAML evaluation records and Markdown
content files live in `inbox/pending/`. Approval moves them to `approved/`;
rejection moves them to `rejected/`. State (seen URLs, last scan times) lives
in `inbox/state.json`.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import yaml

STATE_SCHEMA_VERSION = 1


@dataclass
class SourceState:
    last_scan: str | None = None
    last_successful_scan: str | None = None
    consecutive_failures: int = 0
    items_seen: int = 0


@dataclass
class QueueState:
    schema_version: int = STATE_SCHEMA_VERSION
    last_updated: str = ""
    sources: dict[str, SourceState] = field(default_factory=dict)
    seen_urls: list[str] = field(default_factory=list)
    content_hashes: dict[str, str] = field(default_factory=dict)


@dataclass
class QueueItem:
    item_id: str                     # e.g. "20260415-bcbs-d579"
    evaluation_path: Path
    content_path: Path


class ApprovalQueue:
    """Filesystem-backed approval queue rooted at `inbox/`."""

    def __init__(self, inbox_root: Path) -> None:
        self.root = Path(inbox_root)
        self.pending_dir = self.root / "pending"
        self.approved_dir = self.root / "approved"
        self.rejected_dir = self.root / "rejected"
        self.state_path = self.root / "state.json"

    # ── state ────────────────────────────────────────────────────────────

    def load_state(self) -> QueueState:
        if not self.state_path.exists():
            return QueueState(last_updated=_now_iso())
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        sources = {k: SourceState(**v) for k, v in data.get("sources", {}).items()}
        return QueueState(
            schema_version=data.get("schema_version", STATE_SCHEMA_VERSION),
            last_updated=data.get("last_updated", _now_iso()),
            sources=sources,
            seen_urls=data.get("seen_urls", []),
            content_hashes=data.get("content_hashes", {}),
        )

    def save_state(self, state: QueueState) -> None:
        state.last_updated = _now_iso()
        payload = {
            "schema_version": state.schema_version,
            "last_updated": state.last_updated,
            "sources": {k: asdict(v) for k, v in state.sources.items()},
            "seen_urls": state.seen_urls,
            "content_hashes": state.content_hashes,
        }
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ── pending / approved / rejected ────────────────────────────────────

    def iter_pending(self) -> Iterator[QueueItem]:
        yield from self._iter_dir(self.pending_dir)

    def iter_approved(self) -> Iterator[QueueItem]:
        yield from self._iter_dir(self.approved_dir)

    def iter_rejected(self) -> Iterator[QueueItem]:
        yield from self._iter_dir(self.rejected_dir)

    def approve(self, item_id: str) -> QueueItem:
        return self._move(item_id, self.pending_dir, self.approved_dir)

    def reject(self, item_id: str, reason: str | None = None) -> QueueItem:
        moved = self._move(item_id, self.pending_dir, self.rejected_dir)
        if reason:
            (self.rejected_dir / f"{item_id}.rejection-reason.txt").write_text(
                reason, encoding="utf-8"
            )
        return moved

    def write_pending(self, item_id: str, evaluation: dict, content: str) -> QueueItem:
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        eval_path = self.pending_dir / f"{item_id}.yaml"
        content_path = self.pending_dir / f"{item_id}.md"
        eval_path.write_text(yaml.safe_dump(evaluation, sort_keys=False), encoding="utf-8")
        content_path.write_text(content, encoding="utf-8")
        return QueueItem(item_id=item_id, evaluation_path=eval_path, content_path=content_path)

    # ── internals ────────────────────────────────────────────────────────

    def _iter_dir(self, directory: Path) -> Iterator[QueueItem]:
        if not directory.exists():
            return
        for yaml_path in sorted(directory.glob("*.yaml")):
            item_id = yaml_path.stem
            content_path = directory / f"{item_id}.md"
            yield QueueItem(item_id=item_id, evaluation_path=yaml_path, content_path=content_path)

    def _move(self, item_id: str, src: Path, dst: Path) -> QueueItem:
        dst.mkdir(parents=True, exist_ok=True)
        yaml_src = src / f"{item_id}.yaml"
        md_src = src / f"{item_id}.md"
        if not yaml_src.exists():
            raise FileNotFoundError(f"queue item not found in {src}: {item_id}")
        yaml_dst = dst / yaml_src.name
        md_dst = dst / md_src.name
        shutil.move(str(yaml_src), str(yaml_dst))
        if md_src.exists():
            shutil.move(str(md_src), str(md_dst))
        return QueueItem(item_id=item_id, evaluation_path=yaml_dst, content_path=md_dst)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
