"""Per-document epistemic blackboard shape (JSON-serializable, checkpointer-safe).

``DatasetState["epistemic_blackboard"]`` is a mapping **doc_id → blackboard** with
``beliefs``, ``field_pressure`` (per-field floats), and ``evidence_dag`` (field → edges).
Legacy flat blobs (single top-level ``field_pressure`` with ``doc_id::field`` keys)
are normalized on read.
"""
from __future__ import annotations

from typing import Any


def empty_blackboard() -> dict[str, Any]:
    return {"beliefs": [], "field_pressure": {}, "evidence_dag": {}}


def _shape_bb(v: Any) -> dict[str, Any]:
    if not isinstance(v, dict):
        return empty_blackboard()
    out = empty_blackboard()
    if isinstance(v.get("beliefs"), list):
        out["beliefs"] = list(v["beliefs"])
    if isinstance(v.get("field_pressure"), dict):
        fp: dict[str, float] = {}
        for k, x in v["field_pressure"].items():
            if not str(k):
                continue
            try:
                fp[str(k)] = float(x)
            except (TypeError, ValueError):
                continue
        out["field_pressure"] = fp
    if isinstance(v.get("evidence_dag"), dict):
        out["evidence_dag"] = {str(k): list(x) if isinstance(x, list) else [] for k, x in v["evidence_dag"].items()}
    return out


def _split_legacy_flat(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fp_in = dict(raw.get("field_pressure") or {})
    beliefs = list(raw.get("beliefs") or [])
    dag = dict(raw.get("evidence_dag") or {})
    by_doc: dict[str, dict[str, Any]] = {}
    for k, v in fp_in.items():
        ks = str(k)
        if "::" in ks:
            did, fn = ks.split("::", 1)
        else:
            did, fn = "__global__", ks
        bb = by_doc.setdefault(did, empty_blackboard())
        try:
            bb["field_pressure"][fn] = float(v)
        except (TypeError, ValueError):
            bb["field_pressure"][fn] = 0.0
    if beliefs or dag:
        g = by_doc.setdefault("__global__", empty_blackboard())
        if beliefs:
            g["beliefs"] = beliefs
        if dag:
            g["evidence_dag"] = dag
    return by_doc


def normalize_epistemic_root(raw: Any) -> dict[str, dict[str, Any]]:
    """Return ``{doc_id: EpistemicBlackboard-shaped dict}``."""
    if not isinstance(raw, dict) or not raw:
        return {}
    known_top = {"beliefs", "field_pressure", "evidence_dag"}
    if set(raw.keys()) <= known_top:
        return _split_legacy_flat(raw)
    out: dict[str, dict[str, Any]] = {}
    for k, v in raw.items():
        if k in known_top:
            continue
        if isinstance(v, dict):
            out[str(k)] = _shape_bb(v)
    return out


def get_doc_blackboard(root: dict[str, dict[str, Any]], doc_id: str) -> dict[str, Any]:
    did = (doc_id or "").strip() or "__global__"
    if did not in root:
        root[did] = empty_blackboard()
    return root[did]
