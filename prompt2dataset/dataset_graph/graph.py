"""LangGraph definition for the interactive dataset generation pipeline.

Flow (canonical LangGraph; Streamlit mirrors the same state keys):
  schema_design → (approved?) → extraction → grounding_gate → critique
      ├── export_approved OR cap / not needs_work → export → END
      └── needs_work + rework_count < 3 → prepare_rework → schema_design

Worker model (vs. “agent swarm”)
--------------------------------
Nodes are **phase workers**, not persistent multi-agent negotiators. **Extraction** fans out **one asyncio task per PDF** (single-pass: system + user; or
multipass: scout + synthesis when ``extraction_multipass_blackboard`` is enabled) scoped
to that filing’s chunks — analogous to **one group chat per document**, initialized
for every row in the dataset. **LiveState** is only for schema/critique
prompts (dataset-level), not injected into per-PDF extraction (see
:mod:`prompt2dataset.dataset_graph.extraction_contract`).

**Critique** may optionally run a **validation council** (``critique.council_enabled`` in
``config/prompt2dataset.yaml``): independent reviewers with different epistemic lenses,
then a chairman model that merges verdicts and emits an explicit agreement score
(:mod:`prompt2dataset.dataset_graph.critique_council`) before export/rework routing.

``prepare_rework`` applies :func:`_increment_rework` so headless runs advance
``rework_count`` and reset ``schema_approved`` (the UI also calls this on "Rework schema").

Note: ``schema_design`` → ``schema_design`` self-loops when the schema is not yet
approved (same as re-entering the designer). Interactive deployments should use
checkpointer + thread_id and pause for human approval where needed.

``scope_node`` (deterministic ticker/profile resolution) runs in the UI *before*
this graph; it is intentionally not a LangGraph node.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Literal

import pandas as pd
from langgraph.graph import END, StateGraph
from langgraph.checkpoint.sqlite import SqliteSaver

from prompt2dataset.dataset_graph.critique_node import critique_node
from prompt2dataset.dataset_graph.extraction_node import extraction_node, resolve_extraction_schema_columns
from prompt2dataset.dataset_graph.grounding_gate import grounding_node
from prompt2dataset.dataset_graph.schema_node import schema_node
from prompt2dataset.dataset_graph.state import (
    DatasetState,
    SEDAR_IDENTITY_FIELDS,
    resolve_identity_fields,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------

def _route_after_schema(state: DatasetState) -> Literal["extraction", "schema_design"]:
    if state.get("schema_approved"):
        return "extraction"
    return "schema_design"


def _route_after_critique(state: DatasetState) -> Literal["export", "prepare_rework"]:
    if state.get("export_approved"):
        return "export"
    # Rework loop: bump rework_count + clear approval, then redesign schema
    if (state.get("critique_quality") == "needs_work"
            and state.get("rework_count", 0) < 3):
        return "prepare_rework"
    return "export"


def prepare_rework_node(state: DatasetState) -> DatasetState:
    """Increment rework counter and reset schema approval before schema_design."""
    return _increment_rework(state)


# ---------------------------------------------------------------------------
# Export node (saves the CSV and returns the path in state)
# ---------------------------------------------------------------------------

def export_node(state: DatasetState) -> DatasetState:
    """Persist the extracted rows to a timestamped CSV file.

    Identity columns are determined by state['identity_fields'] so this
    works for any corpus — not just SEDAR.
    """
    rows = state.get("rows", [])
    if not rows:
        return {**state, "error": "No rows to export"}

    from prompt2dataset.dataset_graph.export_normalize import normalize_rows_for_export
    from prompt2dataset.utils.config import get_settings
    cfg = get_settings()

    if state.get("datasets_export_dir"):
        datasets_dir = Path(state["datasets_export_dir"])
    else:
        datasets_dir = cfg.resolve(getattr(cfg, "datasets_dir", "output/datasets"))
    datasets_dir.mkdir(parents=True, exist_ok=True)

    name = state.get("dataset_name", "custom_extraction")
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = datasets_dir / f"{name}_{ts}.csv"

    schema_cols = resolve_extraction_schema_columns(state)
    rows = normalize_rows_for_export(rows, schema_cols)
    df = pd.DataFrame(rows)

    # ── KG metadata enrichment ────────────────────────────────────────────────
    # Fuzzy-match company names against vault Entities and add metadata columns
    # (profile_number, ticker, naics, exchange, etc.) for any domain.
    try:
        from prompt2dataset.utils.metadata_constructor import get_metadata_constructor
        mc = get_metadata_constructor()
        company_col = next(
            (c for c in ("company_name", "entity_name", "sedar_name") if c in df.columns),
            None,
        )
        if company_col:
            df = mc.enrich_dataframe(df, company_col=company_col)
            logger.info("export_node: KG enrichment applied on column %r", company_col)
    except Exception as _enrich_e:
        logger.debug("export_node: KG enrichment skipped: %s", _enrich_e)

    # Move identity columns to front — auto-detect the right identity schema
    id_cols = resolve_identity_fields(state, available_columns=df.columns.tolist())

    # Domain-agnostic column ordering:
    # 1. identity fields (configured per corpus via state["identity_fields"])
    # 2. extracted schema fields
    # 3. evidence/quality/flag/meta columns (sorted by suffix for readability)
    schema_names = [c.get("name", "") for c in schema_cols if c.get("name")]
    evidence_cols = [c for c in df.columns if any(
        c.endswith(suf) for suf in (
            "_evidence_quote", "_evidence_pages", "_evidence_section",
            "_chunk_id", "_verified", "_entailment_score"
        )
    )]
    flag_cols = [c for c in df.columns if c.startswith("_flag_") or c.startswith("_user_")]
    meta_cols = [c for c in df.columns if c in (
        "schema_version", "extracted_at", "rework_count",
        "source_url", "acquisition_job_id", "doc_hash",
    )]
    ordered_names = (
        [c for c in id_cols if c in df.columns]
        + [c for c in schema_names if c in df.columns and c not in id_cols]
        + sorted(evidence_cols)
        + sorted(flag_cols)
        + sorted(meta_cols)
    )
    rest = [c for c in df.columns if c not in set(ordered_names)]
    df = df[ordered_names + rest]

    if logger.isEnabledFor(logging.DEBUG) and rows:
        preview_n = min(3, len(rows))
        try:
            preview = json.dumps(rows[:preview_n], ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            preview = str(rows[:preview_n])
        if len(preview) > 16_000:
            preview = preview[:16_000] + "…(truncated)"
        logger.debug(
            "export_node: pre-CSV row preview (showing %d of %d rows): %s",
            preview_n,
            len(rows),
            preview,
        )

    df.to_csv(path, index=False)
    logger.info("export_node: saved %d rows to %s", len(df), path)

    cells_path_str = ""
    cells = state.get("cells") or []
    if cells:
        cells_path = path.with_suffix(".cells.jsonl")
        with open(cells_path, "w", encoding="utf-8") as fh:
            for cell in cells:
                fh.write(json.dumps(cell, ensure_ascii=False, default=str) + "\n")
        cells_path_str = str(cells_path)
        logger.info("export_node: saved %d cell records to %s", len(cells), cells_path_str)

    # ── Write run note to Obsidian vault ─────────────────────────────────
    try:
        from prompt2dataset.connectors.obsidian_bridge import get_obsidian_bridge
        bridge = get_obsidian_bridge()
        run_id = state.get("run_id") or f"run_{ts}"
        corpus_id = state.get("corpus_id", "unknown")
        schema_name = state.get("dataset_name", "unknown")
        quality = state.get("critique_quality", "ok")
        flags = {
            "all_default_count": sum(
                1 for r in rows if all(not v for k, v in r.items() if k not in (id_cols or []))
            ),
            "evidenceless_count": sum(1 for r in rows if not r.get("evidence_quote")),
            "parse_error_count": state.get("parse_error_count", 0),
        }
        bridge.write_run_note(
            run_id=run_id,
            corpus_id=corpus_id,
            schema_name=schema_name,
            quality=quality,
            row_count=len(rows),
            doc_count=len({r.get("filing_id") or r.get("doc_id", "") for r in rows}),
            consistency_flags=flags,
            dataset_path=str(path),
        )
    except Exception as _e:
        logger.warning("export_node: failed to write obsidian run note: %s", _e)

    rid = str(state.get("run_id") or state.get("feedback_run_id") or "").strip()
    if rid:
        try:
            from prompt2dataset.utils.wonder_queue import append_wonder_entries, build_wonder_state_entries

            wq = build_wonder_state_entries(dict(state))
            if wq:
                append_wonder_entries(rid, wq, state=dict(state))
                if os.environ.get("GLOBAL_WONDER_QUEUE_SYNC", "").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                    "on",
                ):
                    from prompt2dataset.utils.global_wonder_queue import mirror_export_wonders

                    mirror_export_wonders(
                        run_id=rid,
                        run_wonder_states=wq,
                        corpus_id=str(state.get("corpus_id") or ""),
                    )
        except Exception as _wq:
            logger.debug("export_node: wonder_queue append skipped: %s", _wq)

    out = {**state, "dataset_path": str(path), "error": ""}
    if cells_path_str:
        out["cells_dataset_path"] = cells_path_str
    return out


# ---------------------------------------------------------------------------
# Schema rework node (increments rework_count before looping back)
# ---------------------------------------------------------------------------

def _increment_rework(state: DatasetState, selected_suggestions: list[dict] | None = None) -> DatasetState:
    """Increment the rework counter and reset schema approval for another pass.

    selected_suggestions: human-selected field_issue dicts from the critique UI.
    If None, all critique suggestions are used.  Each item is a structured dict:
      {field, issue, severity, suggestion}
    This is converted to a typed delta spec string for schema_node (not raw LLM prose).
    """
    suggestions = selected_suggestions
    if suggestions is None:
        raw = state.get("critique_suggestions", [])
        # Handle both old list[str] format and new list[dict] format
        suggestions = raw if raw and isinstance(raw[0], dict) else []

    if suggestions:
        lines = []
        for s in suggestions:
            field = s.get("field", "")
            sug = s.get("suggestion", "")
            if field and sug:
                lines.append(f"[{field}] {sug}")
        schema_feedback = "\n".join(lines)
    else:
        schema_feedback = ""

    return {
        **state,
        "rework_count": state.get("rework_count", 0) + 1,
        "schema_approved": False,
        "schema_feedback": schema_feedback,
    }


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

_CHECKPOINT_DB = Path("state/checkpoints.db")


def _backup_checkpoints() -> None:
    """Copy checkpoints.db to a timestamped backup on app start.

    Called once per process start to preserve the previous checkpoint state.
    Keeps at most 7 daily backups; older ones are silently removed.
    """
    if not _CHECKPOINT_DB.exists():
        return
    backup_dir = _CHECKPOINT_DB.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"checkpoints_{stamp}.db"
    try:
        shutil.copy2(_CHECKPOINT_DB, dest)
        # Prune: keep newest 7 backups
        existing = sorted(backup_dir.glob("checkpoints_*.db"), reverse=True)
        for old in existing[7:]:
            old.unlink(missing_ok=True)
    except Exception as exc:
        logging.getLogger(__name__).warning("checkpoint backup failed: %s", exc)


def build_dataset_graph(*, checkpoint_db: str | Path | None = None):
    """Build and compile the dataset graph with persistent SqliteSaver checkpointing.

    Args:
        checkpoint_db: Path to the SQLite checkpoint file.
            Defaults to state/checkpoints.db or the CHECKPOINT_SQLITE_PATH env var.

    Returns:
        Compiled LangGraph (CompiledStateGraph) with SqliteSaver checkpointer.
    """
    db_path = (
        Path(checkpoint_db)
        if checkpoint_db
        else Path(os.environ.get("CHECKPOINT_SQLITE_PATH", str(_CHECKPOINT_DB)))
    )
    db_path.parent.mkdir(parents=True, exist_ok=True)

    g = StateGraph(DatasetState)

    g.add_node("schema_design", schema_node)
    g.add_node("extraction", extraction_node)
    g.add_node("grounding_gate", grounding_node)
    g.add_node("critique", critique_node)
    g.add_node("prepare_rework", prepare_rework_node)
    g.add_node("export", export_node)

    g.set_entry_point("schema_design")

    g.add_conditional_edges(
        "schema_design",
        _route_after_schema,
        {"extraction": "extraction", "schema_design": "schema_design"},
    )

    g.add_edge("extraction", "grounding_gate")
    g.add_edge("grounding_gate", "critique")

    g.add_conditional_edges(
        "critique",
        _route_after_critique,
        {"export": "export", "prepare_rework": "prepare_rework"},
    )
    g.add_edge("prepare_rework", "schema_design")

    g.add_edge("export", END)

    # SqliteSaver.from_conn_string is a context manager; compile needs a real saver instance.
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    return g.compile(checkpointer=checkpointer)
