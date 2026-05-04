"""Append-only wonder_queue.jsonl beside training_events (same run root rules).

Unresolved / high-frustration fields are queued at export for human follow-up.
See :func:`prompt2dataset.training_events.resolve_training_events_path` for path layout.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _training_events_disabled() -> bool:
    return os.environ.get("TRAINING_EVENTS_DISABLE", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def resolve_wonder_queue_path(run_id: str, state: dict[str, Any] | None = None) -> Path | None:
    """Sibling of ``training_events.jsonl`` → ``wonder_queue.jsonl``."""
    try:
        from prompt2dataset.training_events import resolve_training_events_path

        if _training_events_disabled():
            return None
        te = resolve_training_events_path(run_id, state)
        if te is None:
            return None
        return te.parent / "wonder_queue.jsonl"
    except Exception as exc:
        logger.debug("resolve_wonder_queue_path: %s", exc)
        return None


def load_queue_entries(path: Path, *, limit: int = 5000) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        for ln in path.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
            if len(out) >= limit:
                break
    except OSError as exc:
        logger.debug("load_queue_entries: %s", exc)
    return out


def _entry_key(rec: dict[str, Any]) -> tuple[str, str, str, str]:
    st = rec.get("state") if isinstance(rec.get("state"), dict) else rec
    st = st or {}
    return (
        str(rec.get("run_id") or st.get("run_id") or ""),
        str(st.get("doc_id") or ""),
        str(st.get("field_name") or ""),
        str(st.get("schema_hash") or ""),
    )


def merge_queue_preview(existing: list[dict[str, Any]], loaded: list[dict[str, Any]], *, cap: int = 200) -> list[dict[str, Any]]:
    """Idempotent merge by (run_id, doc_id, field_name, schema_hash); newest-first scan wins."""
    combined = [x for x in loaded if isinstance(x, dict)] + [x for x in existing if isinstance(x, dict)]
    seen: set[tuple[str, str, str, str]] = set()
    picked: list[dict[str, Any]] = []
    for rec in reversed(combined):
        k = _entry_key(rec)
        if not k[1] or not k[2] or k in seen:
            continue
        seen.add(k)
        picked.append(rec)
        if len(picked) >= cap:
            break
    return list(reversed(picked))


def append_wonder_entries(
    run_id: str,
    entries: list[dict[str, Any]],
    *,
    state: dict[str, Any] | None = None,
) -> None:
    if not run_id or not entries:
        return
    try:
        path = resolve_wonder_queue_path(run_id, state)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for ent in entries:
                st_payload = ent if isinstance(ent, dict) else {}
                rec = {
                    "event_id": f"wonder_{uuid.uuid4().hex[:12]}",
                    "event_type": "wonder_queue",
                    "run_id": run_id,
                    "state": st_payload,
                }
                fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.debug("append_wonder_entries: %s", exc)


def build_wonder_state_entries(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Build ``state`` payloads for unresolved / evidenceless fields (respect pressure cap)."""
    from prompt2dataset.training_events import compute_schema_hash, trajectory_context_from_dataset_state
    from prompt2dataset.utils.epistemic_blackboard import get_doc_blackboard, normalize_epistemic_root
    from prompt2dataset.utils.prompt2dataset_settings import load_prompt2dataset_config

    cfg = load_prompt2dataset_config()
    rows = state.get("rows") or []
    cols = state.get("proposed_columns") or []
    if not rows or not cols:
        return []
    rid = str(state.get("run_id") or state.get("feedback_run_id") or "").strip()
    if not rid:
        return []
    root = dict(normalize_epistemic_root(state.get("epistemic_blackboard")))
    tr = trajectory_context_from_dataset_state(state)
    schema_hash = str(tr.get("schema_hash") or "").strip() or compute_schema_hash(
        cols if isinstance(cols, list) else None
    )
    max_p = float(cfg.wonder_queue_max_pressure_to_enqueue)
    max_n = int(cfg.wonder_queue_max_entries_per_export)
    out: list[dict[str, Any]] = []
    for row in rows:
        if len(out) >= max_n:
            break
        doc_id = str(row.get("doc_id") or row.get("filing_id") or "")
        doc_bb = get_doc_blackboard(root, doc_id or "__global__")
        fp = doc_bb.get("field_pressure") or {}
        for c in cols:
            if len(out) >= max_n:
                break
            name = str(c.get("name") or "")
            if not name:
                continue
            mode = str(c.get("mode") or "direct").lower()
            default_val = c.get("default")
            quote = str(row.get(f"{name}_evidence_quote") or "").strip()
            val = row.get(name)
            press = float(fp.get(name, 0.0))
            if press > max_p:
                continue
            evidenceless = val is not None and val != default_val and not quote
            unresolved_evidence_mode = mode == "evidence" and not quote and val == default_val
            if not (evidenceless or unresolved_evidence_mode):
                continue
            reason = "evidenceless" if evidenceless else "unresolved_evidence_mode"
            out.append(
                {
                    "doc_id": doc_id,
                    "field_name": name,
                    "schema_hash": schema_hash,
                    "reason": reason,
                    "field_pressure": press,
                    "cell_value_digest": str(val)[:400],
                }
            )
    return out


def merge_sidecars_into_ws_state(ws_state: dict[str, Any]) -> None:
    """Load wonder_queue.jsonl into ``wonder_queue_preview``; normalize epistemic root."""
    from prompt2dataset.utils.epistemic_blackboard import normalize_epistemic_root

    ws_state["epistemic_blackboard"] = normalize_epistemic_root(ws_state.get("epistemic_blackboard"))
    rid = str(ws_state.get("run_id") or ws_state.get("feedback_run_id") or "").strip()
    if not rid:
        return
    path = resolve_wonder_queue_path(rid, ws_state)
    if path is None:
        return
    loaded = load_queue_entries(path, limit=5000)
    if not loaded:
        return
    prev = ws_state.get("wonder_queue_preview") or []
    if not isinstance(prev, list):
        prev = []
    ws_state["wonder_queue_preview"] = merge_queue_preview(
        [x for x in prev if isinstance(x, dict)],
        loaded,
        cap=200,
    )
