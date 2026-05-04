"""Deterministic grounding gate: verify evidence quotes against source chunk text.

Runs as a LangGraph node **after** extraction and **before** critique. Does not load
the heavy multi-layer substrate — only substring / optional NLI checks.

See ``critique_council`` for optional multi-LLM critique (different concern).
"""
from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd

from prompt2dataset.dataset_graph.state import DatasetState, SEDAR_IDENTITY_FIELDS, SchemaColumn
from prompt2dataset.utils.epistemic_blackboard import get_doc_blackboard, normalize_epistemic_root
from prompt2dataset.utils.prompt2dataset_settings import load_prompt2dataset_config

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")


def collapse_ws(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip()).lower()


def quote_substring_verified(quote: str, source: str) -> bool:
    """True if normalized ``quote`` appears as substring of normalized ``source``."""
    if not quote or not source:
        return False
    cq, cs = collapse_ws(quote), collapse_ws(source)
    return len(cq) >= 8 and cq in cs


def _chunk_text_map_for_doc(doc_id: str, chunks: pd.DataFrame) -> dict[str, str]:
    """Map chunk_id -> text for rows belonging to ``doc_id``."""
    if chunks is None or chunks.empty or not doc_id:
        return {}
    out: dict[str, str] = {}
    for col in ("doc_id", "filing_id"):
        if col not in chunks.columns:
            continue
        sub = chunks[chunks[col].astype(str) == str(doc_id)]
        if sub.empty:
            continue
        if "chunk_id" not in sub.columns or "text" not in sub.columns:
            return {}
        for _, r in sub.iterrows():
            cid = str(r.get("chunk_id") or "").strip()
            if cid:
                out[cid] = str(r.get("text") or "")
        return out
    return {}


def apply_grounding_to_state(state: DatasetState) -> DatasetState:
    """Verify each evidence quote; clear failing quotes and bump ``field_pressure``."""
    p2d = load_prompt2dataset_config()
    if not p2d.grounding_enabled:
        return state

    rows: list[dict[str, Any]] = list(state.get("rows") or [])
    columns: list[SchemaColumn] = state.get("proposed_columns") or []
    if not rows or not columns:
        return state

    from prompt2dataset.dataset_graph.extraction_node import (
        _load_corpus_data,
        run_consistency_check,
        verify_quote_in_chunk,
    )
    from prompt2dataset.utils.config import get_settings

    cfg = get_settings()
    try:
        _, chunks, _ = _load_corpus_data(cfg, state)
    except Exception as exc:
        logger.warning("grounding_gate: could not load chunks (%s) — substring checks only", exc)
        chunks = pd.DataFrame()

    root_bb: dict[str, Any] = dict(normalize_epistemic_root(state.get("epistemic_blackboard")))

    identity_fields = state.get("identity_fields")
    if not isinstance(identity_fields, list):
        identity_fields = SEDAR_IDENTITY_FIELDS
    col_names = [c.get("name", "") for c in columns if c.get("name")]

    for row in rows:
        doc_id = str(row.get("doc_id") or row.get("filing_id") or "")
        doc_bb = get_doc_blackboard(root_bb, doc_id or "__global__")
        fp = doc_bb["field_pressure"]
        cmap = _chunk_text_map_for_doc(doc_id, chunks) if not chunks.empty else {}
        row["_flag_grounding_failed"] = False
        for name in col_names:
            quote = str(row.get(f"{name}_evidence_quote") or "").strip()
            if not quote:
                continue
            cid = str(row.get(f"{name}_chunk_id") or "").strip()
            chunk_text = str(row.get(f"{name}_chunk_text") or "")
            if not chunk_text and cid and cid in cmap:
                chunk_text = cmap[cid]
            source = chunk_text
            if not source.strip():
                ok = False
            elif p2d.grounding_require_substring:
                ok = quote_substring_verified(quote, source)
                if not ok and p2d.grounding_use_nli:
                    ok_nli, _ = verify_quote_in_chunk(quote, source)
                    ok = ok_nli
            elif p2d.grounding_use_nli:
                ok, _ = verify_quote_in_chunk(quote, source)
            else:
                ok = True
            if not ok:
                fp[name] = float(fp.get(name, 0.0)) + 1.0
                row[f"{name}_evidence_quote"] = None
                row[f"{name}_evidence_pages"] = None
                row[f"{name}_evidence_section"] = None
                row[f"{name}_chunk_id"] = ""
                row[f"{name}_verified"] = False
                row[f"{name}_entailment_score"] = 0.0
                row["_flag_grounding_failed"] = True
                logger.debug(
                    "grounding_gate: cleared evidence for doc=%s field=%s",
                    doc_id,
                    name,
                )

    consistency_flags = run_consistency_check(rows, columns, identity_fields)

    from prompt2dataset.dataset_graph.extraction_node import rebuild_cells_from_rows

    cells = rebuild_cells_from_rows(rows, columns, identity_fields)
    return {
        **state,
        "rows": rows,
        "cells": cells,
        "consistency_flags": consistency_flags,
        "epistemic_blackboard": root_bb,
    }


def grounding_node(state: DatasetState) -> DatasetState:
    """LangGraph node wrapper."""
    return apply_grounding_to_state(state)
