"""Repo-root stigmergic queue for Claw / cron (separate from per-run ``wonder_queue.jsonl``).

Append-only JSONL at ``<ISF-PEECEE>/state/wonder_queue.jsonl`` (override with
``ISF_GLOBAL_WONDER_QUEUE_PATH``). Records are small dicts so Tier-1 (Claw) can
grep/tail the file and Tier-2 (vLLM) runs heavy work when the controller allows.

Event types:
- ``global_wonder`` — work item (default ``status``: ``pending``).
- ``wonder_resolved`` — optional closure row with ``ref_event_id`` pointing at a prior ``event_id``.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def isf_repo_root() -> Path:
    """``prompt2dataset/utils/`` → ISF-PEECEE repo root."""
    return Path(__file__).resolve().parents[2]


def global_wonder_queue_path() -> Path:
    override = (os.environ.get("ISF_GLOBAL_WONDER_QUEUE_PATH") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (isf_repo_root() / "state" / "wonder_queue.jsonl").resolve()


def append_global_wonder(
    task: dict[str, Any],
    *,
    priority: str = "normal",
    run_id: str | None = None,
    source: str = "manual",
) -> str:
    """Append one ``global_wonder`` line. ``task`` should be JSON-serializable."""
    path = global_wonder_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    eid = f"gw_{uuid.uuid4().hex[:16]}"
    rec: dict[str, Any] = {
        "event_id": eid,
        "event_type": "global_wonder",
        "status": "pending",
        "priority": str(priority or "normal"),
        "source": str(source),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": (run_id or "").strip() or None,
        "task": dict(task) if isinstance(task, dict) else {"payload": task},
    }
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("append_global_wonder: %s", exc)
        raise
    return eid


def append_wonder_resolved(ref_event_id: str, *, summary: str = "", ok: bool = True) -> str:
    path = global_wonder_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    eid = f"gr_{uuid.uuid4().hex[:16]}"
    rec = {
        "event_id": eid,
        "event_type": "wonder_resolved",
        "ref_event_id": ref_event_id,
        "ok": bool(ok),
        "summary": (summary or "")[:4000],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
    return eid


def load_all_events(path: Path | None = None, *, limit: int = 20_000) -> list[dict[str, Any]]:
    p = path or global_wonder_queue_path()
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not ln.strip():
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
            if len(out) >= limit:
                break
    except OSError as exc:
        logger.debug("load_all_events: %s", exc)
    return out


def pending_global_wonders(*, limit: int = 200) -> list[dict[str, Any]]:
    """Return ``global_wonder`` rows that are not superseded by a ``wonder_resolved`` for the same ``event_id``."""
    events = load_all_events(limit=50_000)
    resolved: set[str] = set()
    for ev in events:
        if ev.get("event_type") == "wonder_resolved" and ev.get("ref_event_id"):
            resolved.add(str(ev["ref_event_id"]))
    pending: list[dict[str, Any]] = []
    for ev in events:
        if ev.get("event_type") != "global_wonder":
            continue
        eid = str(ev.get("event_id") or "")
        if not eid or eid in resolved:
            continue
        if str(ev.get("status", "pending")).lower() in ("done", "cancelled", "skipped"):
            continue
        pending.append(ev)
    return pending[-limit:]


def mirror_export_wonders(*, run_id: str, run_wonder_states: list[dict[str, Any]], corpus_id: str = "") -> int:
    """Mirror per-field export wonders into the global queue (dedupe by run_id+doc+field+schema)."""
    if not run_id or not run_wonder_states:
        return 0
    existing = pending_global_wonders(limit=5000)
    seen: set[tuple[str, str, str, str]] = set()
    for ev in existing:
        t = ev.get("task") if isinstance(ev.get("task"), dict) else {}
        seen.add(
            (
                str(ev.get("run_id") or ""),
                str(t.get("doc_id") or ""),
                str(t.get("field_name") or ""),
                str(t.get("schema_hash") or ""),
            )
        )
    n = 0
    for st in run_wonder_states:
        if not isinstance(st, dict):
            continue
        doc_id = str(st.get("doc_id") or "")
        field_name = str(st.get("field_name") or "")
        schema_hash = str(st.get("schema_hash") or "")
        key = (run_id, doc_id, field_name, schema_hash)
        if key in seen:
            continue
        seen.add(key)
        append_global_wonder(
            {
                "kind": "export_gap",
                "corpus_id": corpus_id or None,
                "doc_id": doc_id,
                "field_name": field_name,
                "schema_hash": schema_hash,
                "reason": st.get("reason"),
                "field_pressure": st.get("field_pressure"),
            },
            priority="high" if str(st.get("reason") or "") == "evidenceless" else "normal",
            run_id=run_id,
            source="export_mirror",
        )
        n += 1
    if n:
        logger.info("mirrored %s global wonder(s) from run %s corpus=%s", n, run_id, corpus_id or "-")
    return n
