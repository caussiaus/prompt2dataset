"""Workspace router — selects which phase to render based on thread.step.

Layout:
  ┌───────────────────────────────────────────────────────────────┐
  │ [sidebar 220px — threads only]  │  [main: chat + table]       │
  └───────────────────────────────────────────────────────────────┘

Phases (thread.step):
  new         → landing / upload card
  designing   → parallel ingest + schema chat
  extracting  → trial extraction
  preview     → results + critique + approve/export
  full_run    → full-corpus extraction
  done        → download + start new

Old step names from prior versions are normalised in render().
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]

from app_pages.chat_render import (
    _handle_export_approve,
    _handle_full_run,
    render_chat_history,
    render_chat_input,
    render_extraction_progress,
    render_full_run_progress,
    render_ingest_progress,
    render_live_state_strip,
    render_sidebar_inspector,
    stream_critique_card,
    stream_schema_card,
)
from app_pages.pipeline_runner import (
    build_doc_queue,
    count_parsed_docs,
    eval_window_ready,
    launch_ingest,
)
from app_pages.table_render import render_field_strip, render_table
from app_pages.thread_store import (
    Thread,
    delete_thread,
    list_threads,
    load_context,
    load_thread,
    save_thread,
)
from prompt2dataset.corpus.config import CorpusConfig, new_run_id
from prompt2dataset.dataset_graph.state import DatasetState, SEDAR_IDENTITY_FIELDS

_CONFIG_DIR = ROOT / "output" / "corpus_configs"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _persist_docs_dir_to_corpus_yaml(t: Thread, docs_dir: str) -> None:
    """Keep corpus YAML in sync with the thread so ingest subprocesses see the latest PDF root."""
    cfg_path = _CONFIG_DIR / f"{t.corpus_id}.yaml"
    if not cfg_path.is_file():
        return
    cc = CorpusConfig.from_yaml(cfg_path)
    cc.docs_dir = docs_dir
    cc.to_yaml(cfg_path)

_SLUG_RE = re.compile(r"[^a-z0-9]+")

# Step names from the old codebase → new names
_STEP_NORMALISE = {
    "ingesting":        "designing",
    "schema":           "designing",
    "full_ingesting":   "full_run",
    "full_extracting":  "full_run",
    "approve":          "preview",
}


def _slugify(s: str) -> str:
    return _SLUG_RE.sub("_", s.lower().strip()).strip("_") or "corpus"


def _log_chat_correction(
    ws_state: DatasetState,
    user_text: str,
    assistant_text: str = "",
) -> None:
    """Append ``chat_correction`` to training_events for RL/DPO (best-effort)."""
    rid = (ws_state.get("run_id") or ws_state.get("feedback_run_id") or "").strip()
    if not rid or not (user_text or "").strip():
        return
    try:
        from prompt2dataset.training_events import (
            TrainingEventLogger,
            merge_training_event_state,
            trajectory_context_from_dataset_state,
        )

        st = merge_training_event_state(trajectory_context_from_dataset_state(dict(ws_state)))
        TrainingEventLogger(rid, state=st).log_chat_correction(
            (user_text or "").strip(),
            (assistant_text or "")[:8000],
        )
    except Exception:
        pass


def _clear_critique_state(ws_state: DatasetState) -> None:
    """Remove last critique so a new run is not confused with stale verdicts."""
    for k in (
        "critique_text",
        "critique_suggestions",
        "critique_config_deltas",
        "critique_quality",
        "critique_parse_ok",
        "critique_llm_raw",
        "critique_council_trace",
        "critique_consensus",
    ):
        ws_state.pop(k, None)


def _start_trial_reextract(t: Thread, ws_state: DatasetState) -> bool:
    """Clear sample rows and queue a fresh trial extraction with the same schema."""
    n = build_doc_queue(t, ws_state)
    if n <= 0:
        return False
    _clear_critique_state(ws_state)
    ws_state.pop("consistency_flags", None)
    ws_state["rows"] = []
    ws_state["cells"] = []
    st.session_state["ws_state"] = ws_state
    t.rows = []
    t.step = "extracting"
    t.status = "extracting"
    t.add_chat("assistant", f"Re-running trial extraction ({n} docs)…")
    save_thread(t)
    return True


def _build_workspace_data_chat_reply(ws_state: DatasetState) -> str:
    """Markdown assistant turn: tiny embedded table + how to run schema feedback."""
    rows = ws_state.get("rows") or []
    cols = ws_state.get("proposed_columns") or []
    if not rows:
        return (
            "No rows yet — run **trial extraction** first.\n\n"
            "To change field definitions, send **`/schema …`** (example: "
            "`/schema merge alt_name columns into one`)."
        )

    idf = [x for x in (ws_state.get("identity_fields") or []) if isinstance(x, str)]
    head_id = []
    for x in idf:
        if any(x in r for r in rows[:1]):
            head_id.append(x)
        if len(head_id) >= 2:
            break
    field_names: list[str] = []
    for c in cols[:12]:
        n = c.get("name") if isinstance(c, dict) else None
        if n and n not in head_id:
            field_names.append(str(n))
    headers = (head_id + field_names)[:9]
    if not headers:
        headers = [k for k in rows[0].keys() if not str(k).startswith("_")][:9]

    lines: list[str] = [
        f"**Sample table** — {min(3, len(rows))} of **{len(rows)}** rows. "
        "This message does not reset your schema or extracted rows.",
        "",
    ]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for r in rows[:3]:
        cells = []
        for h in headers:
            v = r.get(h, "")
            if v is None or str(v).strip() in ("", "None", "nan"):
                cells.append("—")
            else:
                cells.append(str(v).replace("|", "\\|").replace("\n", " ")[:72])
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(
        [
            "",
            "**Schema redesign** — only when you prefix with **`/schema`** (re-approve in the "
            "contract panel afterward). Otherwise chat here stays read-only for the pipeline.",
            "",
            "Buttons above: **Quality critique**, **Re-extract trial**, **Full corpus**, **Export CSV**.",
        ]
    )
    return "\n".join(lines)


def _render_review_action_bar(t: Thread, ws_state: DatasetState, *, ctx: str) -> None:
    """Persistent HITL actions: critique, re-extract, full run, export (preview or done)."""
    rows = ws_state.get("rows", [])
    if not rows:
        return

    has_critique = bool(ws_state.get("critique_text"))
    st.markdown("---")
    with st.chat_message("assistant"):
        st.markdown(
            "**Review & next steps** — chat below shows a **sample of the table** without "
            "re-running the schema designer. Use **`/schema …`** only when you want a schema "
            "revision. Buttons: critique, re-extract, full run, export."
        )
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            crit_label = "🔍 Re-run quality critique" if has_critique else "🔍 Quality critique"
            if st.button(crit_label, key=f"{ctx}_critique_btn", type="primary"):
                st.session_state["ws_run_critique"] = True
                st.rerun()
        with c2:
            if st.button("↻ Re-extract trial", key=f"{ctx}_reextract_btn"):
                if _start_trial_reextract(t, ws_state):
                    st.rerun()
                else:
                    st.error("No documents in queue — check your corpus index.")
        with c3:
            if st.button("▶ Full corpus run", key=f"{ctx}_fullcorpus_btn"):
                _handle_full_run(t, ws_state)
        with c4:
            if st.button("✓ Export CSV", key=f"{ctx}_export_btn"):
                if not ws_state.get("schema_approved"):
                    st.caption(
                        "Tip: mark **Approve schema** in the contract panel if you changed fields; "
                        "export still runs for this trial snapshot."
                    )
                _handle_export_approve(t, ws_state)


# ── Schema JSON import ─────────────────────────────────────────────────────────

_TYPE_MAP = {
    "string":  "string|null",
    "str":     "string|null",
    "text":    "string|null",
    "float":   "number|null",
    "number":  "number|null",
    "integer": "integer|null",
    "int":     "integer|null",
    "boolean": "boolean",
    "bool":    "boolean",
}

_DEFAULT_FOR_TYPE = {
    "boolean":    False,
    "bool":       False,
    "integer":    None,
    "int":        None,
    "float":      None,
    "number":     None,
    "string|null": None,
    "integer|null": None,
    "number|null": None,
}


def _detect_metadata_columns(
    columns: list[dict],
    identity_fields: list[str] | None = None,
) -> list[str]:
    """Return proposed schema fields that duplicate ``identity_fields`` (waste tokens).

    Only names that exactly match an identity column (case-insensitive) are flagged — avoids
    false positives like ``first_trade_date`` or ``ticker`` when those are not identity keys
    but still need to be extracted from the PDF.
    """
    id_l = {x.strip().lower() for x in (identity_fields or []) if x and str(x).strip()}
    out: list[str] = []
    for c in columns:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        if name.lower() in id_l:
            out.append(name)
    return out


def _parse_schema_json(raw: str) -> list[dict[str, Any]] | None:
    """Parse several JSON schema formats into a proposed_columns list.

    Supports:
      {"extraction_schema": [{name, type, description, required, enum, unit}, …]}
      {"columns": [{name, type, description, extraction_instruction, default}, …]}
      [{name, type, description}, …]   (bare list)
    Returns None if the text doesn't look like a schema.
    """
    raw = raw.strip()
    # Strip markdown fences
    raw = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw, flags=re.I | re.M).strip()
    try:
        obj = json.loads(raw)
    except Exception:
        return None

    # Normalise to a list of column dicts
    cols_raw: list[dict] = []
    if isinstance(obj, list):
        cols_raw = obj
    elif isinstance(obj, dict):
        for key in ("extraction_schema", "columns", "fields", "schema"):
            if isinstance(obj.get(key), list):
                cols_raw = obj[key]
                break
    if not cols_raw:
        return None

    # Validate: must have at least "name" in first item
    if not cols_raw or "name" not in cols_raw[0]:
        return None

    columns: list[dict[str, Any]] = []
    for c in cols_raw:
        name = str(c.get("name", "")).strip()
        if not name:
            continue
        raw_type = str(c.get("type", "string")).lower().strip()
        required = bool(c.get("required", False))

        # Map type
        if raw_type in ("string", "str", "text") and required:
            col_type = "string"
        else:
            col_type = _TYPE_MAP.get(raw_type, "string|null")

        description = str(c.get("description", "")).strip()
        unit = c.get("unit", "")
        enum_vals = c.get("enum", [])

        # Build extraction instruction
        instr_parts = [description] if description else []
        if unit:
            instr_parts.append(f"Unit: {unit}")
        if enum_vals:
            instr_parts.append(f"Must be one of: {', '.join(str(v) for v in enum_vals)}")
        extraction_instruction = " — ".join(instr_parts) or f"Find {name} in the document."

        default = _DEFAULT_FOR_TYPE.get(col_type, None)
        if col_type == "boolean":
            default = False

        columns.append({
            "name": name,
            "type": col_type,
            "description": description[:80] if description else name,
            "extraction_instruction": extraction_instruction,
            "default": default,
        })

    return columns if columns else None


def _msg_looks_like_schema(msg: str) -> bool:
    """Quick heuristic: does this chat message look like a pasted JSON schema?"""
    stripped = msg.strip()
    if not (stripped.startswith("{") or stripped.startswith("[") or stripped.startswith("```")):
        return False
    # Must contain "name" and "description" or "extraction_schema" or "columns"
    has_name = '"name"' in stripped or "'name'" in stripped
    has_schema_key = any(k in stripped for k in (
        '"extraction_schema"', '"columns"', '"fields"', '"schema"',
        '"description"', '"type"',
    ))
    return has_name and has_schema_key


def _ensure_enriched_proposed_columns(
    ws_state: DatasetState,
    t: Thread | None,
    *,
    persist: bool = True,
) -> None:
    """Normalize imported or restored schemas so extraction matches schema_node output.

    Fills ``keywords``, ``difficulty``, and ``value_cardinality`` when missing.
    Without these, BM25 retrieval is weak and wide JSON outputs can look empty.
    Idempotent for already-enriched columns. When the normalized list differs from
    what was loaded, updates ``t.schema_cols`` and saves the thread so resume
    picks up the same shape.
    """
    cols = ws_state.get("proposed_columns")
    if not cols:
        return
    from prompt2dataset.dataset_graph.mapping_contract import build_schema_mapping_summary
    from prompt2dataset.utils.call_config import enrich_proposed_columns_for_extraction

    topic = ws_state.get("corpus_topic") or (t.topic if t else "") or ""
    prior_sig = json.dumps(cols, sort_keys=True, default=str)
    enriched = enrich_proposed_columns_for_extraction(cols, corpus_topic=topic)
    new_sig = json.dumps(enriched, sort_keys=True, default=str)
    ws_state["proposed_columns"] = enriched
    if new_sig != prior_sig or not (ws_state.get("schema_mapping_summary") or "").strip():
        ws_state["schema_mapping_summary"] = build_schema_mapping_summary(
            enriched,
            ws_state.get("dataset_description") or "",
            row_granularity=ws_state.get("extraction_row_granularity")
            or "one_row_per_document",
        )
    if t is not None and persist and new_sig != prior_sig:
        t.schema_cols = enriched
        save_thread(t)


# ── Session helpers ────────────────────────────────────────────────────────────


def _reconcile_thread_step_status(t: Thread) -> None:
    """Keep ``t.step`` (routes the main UI) aligned with ``t.status`` (sidebar pill).

    If these diverge—e.g. ``status`` was set to ``extracting`` but ``step`` stayed
    ``designing``—the user stays on the designing page while the designing-phase gate
    runs every rerun, repeatedly calling ``build_doc_queue`` and resetting
    ``ws_doc_queue``. Extraction never runs and chat spams "starting trial extraction".
    """
    changed = False
    st_lc = (t.status or "").lower().strip()
    if st_lc == "extracting" and t.step == "designing":
        t.step = "extracting"
        changed = True
    elif st_lc in ("full_extracting",) and t.step == "designing":
        t.step = "full_run"
        changed = True
    if changed:
        save_thread(t)


def _load_thread_into_session(t: Thread) -> None:
    """Restore a thread's persisted state into ws_state session key."""
    ws_state: DatasetState = st.session_state.get("ws_state", {})

    if t.schema_cols and not ws_state.get("proposed_columns"):
        ws_state["proposed_columns"] = t.schema_cols

    if t.rows and not ws_state.get("rows"):
        ws_state["rows"] = t.rows

    if t.topic and not ws_state.get("corpus_topic"):
        ws_state["corpus_topic"] = t.topic

    if not ws_state.get("identity_fields"):
        cfg_path = _CONFIG_DIR / f"{t.corpus_id}.yaml"
        try:
            if cfg_path.exists():
                corpus_cfg = CorpusConfig.from_yaml(cfg_path)
                ws_state["identity_fields"] = corpus_cfg.identity_fields
                ws_state["corpus_topic"] = ws_state.get("corpus_topic") or corpus_cfg.topic
                ws_state["corpus_id"] = ws_state.get("corpus_id") or corpus_cfg.corpus_id
                ws_state["corpus_index_csv"] = corpus_cfg.index_csv
                ws_state["corpus_parse_index_csv"] = corpus_cfg.parse_index_csv
                ws_state["corpus_chunks_parquet"] = corpus_cfg.chunks_parquet
                ws_state["corpus_chunks_llm_parquet"] = corpus_cfg.chunks_llm_parquet
                ws_state["datasets_export_dir"] = corpus_cfg.datasets_dir
        except Exception:
            pass

    if not ws_state.get("identity_fields"):
        ws_state["identity_fields"] = SEDAR_IDENTITY_FIELDS

    if t.corpus_id and not ws_state.get("corpus_id"):
        ws_state["corpus_id"] = t.corpus_id

    if getattr(t, "run_id", ""):
        ws_state.setdefault("run_id", t.run_id)

    ws_state.setdefault("eval_window_min", 6)
    ws_state.setdefault("eval_window_max", 10)
    ws_state.setdefault("rework_count", 0)
    ws_state.setdefault("schema_iteration", 0)
    ws_state.setdefault("schema_approved", bool(t.schema_cols))
    ws_state.setdefault("use_sample", True)
    ws_state.setdefault("extraction_row_granularity", "one_row_per_document")

    if ws_state.get("proposed_columns") and not ws_state.get("schema_mapping_summary"):
        from prompt2dataset.dataset_graph.mapping_contract import build_schema_mapping_summary

        ws_state["schema_mapping_summary"] = build_schema_mapping_summary(
            ws_state["proposed_columns"],
            ws_state.get("dataset_description") or "",
            row_granularity=ws_state.get("extraction_row_granularity")
            or "one_row_per_document",
        )

    _ensure_enriched_proposed_columns(ws_state, t, persist=True)

    try:
        from prompt2dataset.utils.wonder_queue import merge_sidecars_into_ws_state

        merge_sidecars_into_ws_state(ws_state)
    except Exception:
        pass

    try:
        ctx = load_context(t.thread_id)
        if ctx is not None:
            eb = getattr(ctx, "epistemic_blackboard", None) or {}
            if isinstance(eb, dict) and eb:
                ws_state["epistemic_blackboard"] = eb
            wqp = getattr(ctx, "wonder_queue_preview", None) or []
            if isinstance(wqp, list) and wqp:
                ws_state["wonder_queue_preview"] = list(wqp)
            dd = (getattr(ctx, "datasets_export_dir", "") or "").strip()
            if dd:
                ws_state.setdefault("datasets_export_dir", dd)
    except Exception:
        pass

    st.session_state["ws_state"] = ws_state
    st.session_state["ws_thread"] = t


# ── Sidebar ────────────────────────────────────────────────────────────────────


def _render_sidebar() -> Thread | None:
    STATUS_ICON = {
        "new": "○", "ingesting": "◑", "designing": "◑", "schema": "◈",
        "extracting": "◑", "preview": "◆", "approve": "◆",
        "full_ingesting": "◑", "full_extracting": "◑", "full_run": "◑",
        "done": "●", "failed": "✗",
    }
    STATUS_COLOR = {
        "ingesting": "#FCD34D", "designing": "#FCD34D",
        "extracting": "#FCD34D", "full_ingesting": "#FCD34D",
        "full_extracting": "#FCD34D", "full_run": "#FCD34D",
        "preview": "#34D399", "approve": "#34D399", "done": "#34D399",
        "failed": "#F87171", "schema": "#93C5FD",
    }

    with st.sidebar:
        st.markdown(
            "<div style='font-weight:700;font-size:0.95rem;padding:8px 0 12px;"
            "color:#F1F5F9'>Dataset Builder</div>",
            unsafe_allow_html=True,
        )

        if st.button("＋ New analysis", use_container_width=True, type="primary"):
            st.session_state.pop("ws_thread_id", None)
            st.session_state.pop("ws_state", None)
            st.session_state.pop("ws_doc_queue", None)
            st.session_state["ws_show_landing"] = True
            st.rerun()

        threads = list_threads()
        active_id: str = st.session_state.get("ws_thread_id", "")
        show_landing_flag = st.session_state.get("ws_show_landing", False)

        # Fresh session / new tab: sidebar lists runs but nothing is "open" — main area
        # stayed on the setup form. Open the newest thread unless user chose "+ New analysis".
        if not active_id and threads and not show_landing_flag:
            st.session_state["ws_thread_id"] = threads[0].thread_id
            active_id = threads[0].thread_id

        if not threads:
            st.markdown(
                "<div style='font-size:0.8rem;color:#475569;padding:6px 2px'>"
                "No analyses yet.</div>",
                unsafe_allow_html=True,
            )

        for t in threads:
            is_active = t.thread_id == active_id
            icon = STATUS_ICON.get(t.status, "○")
            dot_color = STATUS_COLOR.get(t.status, "#475569")
            label = t.title[:24] + ("…" if len(t.title) > 24 else "")

            c1, c2 = st.columns([8, 1])
            with c1:
                btn_type = "primary" if is_active else "secondary"
                if st.button(
                    label,
                    key=f"thread_btn_{t.thread_id}",
                    use_container_width=True,
                    type=btn_type,
                    help=f"{t.status} · {t.topic[:60]}",
                ):
                    st.session_state["ws_thread_id"] = t.thread_id
                    st.session_state.pop("ws_state", None)
                    st.session_state.pop("ws_doc_queue", None)
                    st.session_state.pop("ws_ingest_done", None)
                    st.session_state["ws_show_landing"] = False
                    st.rerun()
            with c2:
                if st.button("✕", key=f"del_{t.thread_id}", help="Delete"):
                    delete_thread(t.thread_id)
                    if active_id == t.thread_id:
                        st.session_state.pop("ws_thread_id", None)
                        st.session_state.pop("ws_state", None)
                    st.rerun()

            st.markdown(
                f"<div style='font-family:monospace;font-size:0.68rem;color:{dot_color};"
                f"margin:-6px 0 8px 4px'>{icon} {t.status}"
                f"<span style='color:#475569;margin-left:6px'>{t.age_label}</span></div>",
                unsafe_allow_html=True,
            )

        # Add PDFs to the active corpus (same folder ingest uses; then re-run ingest)
        if active_id:
            t_pdf = load_thread(active_id)
            if t_pdf and t_pdf.corpus_id:
                st.divider()
                with st.expander("Corpus PDFs", expanded=False):
                    st.caption(
                        "New analysis also supports upload on the landing page. "
                        "Here you can drop more files into the same corpus and re-ingest."
                    )
                    dest = (
                        Path(t_pdf.docs_dir).resolve()
                        if t_pdf.docs_dir
                        else ROOT / "output" / t_pdf.corpus_id / "uploads"
                    )
                    st.caption(f"**Save to:** `{dest}`")
                    more = st.file_uploader(
                        "Add PDFs",
                        type=["pdf"],
                        accept_multiple_files=True,
                        key=f"sidebar_pdf_{t_pdf.thread_id}",
                    )
                    if more:
                        dest.mkdir(parents=True, exist_ok=True)
                        _save_uploaded_pdfs(more, dest)
                        st.success(f"Saved {len(more)} file(s).")
                    if st.button("Re-run ingest (trial batch)", key="sidebar_reingest"):
                        launch_ingest(t_pdf, trial_n=t_pdf.trial_n)
                        t_pdf.status = "ingesting"
                        t_pdf.proc_done = False
                        save_thread(t_pdf)
                        st.rerun()

        # Field inspector
        focus = st.session_state.get("ws_focus_field", "")
        ws_state_sb: DatasetState = st.session_state.get("ws_state", {})
        if focus and ws_state_sb.get("proposed_columns"):
            st.divider()
            st.markdown("<div style='font-size:0.75rem;font-weight:700;color:#94A3B8;"
                        "text-transform:uppercase;letter-spacing:0.08em'>Field inspector</div>",
                        unsafe_allow_html=True)
            render_sidebar_inspector(ws_state_sb)

        active_id = st.session_state.get("ws_thread_id", "")
        if not active_id:
            return None
        t = load_thread(active_id)
        if not t and threads:
            st.session_state["ws_thread_id"] = threads[0].thread_id
            t = load_thread(threads[0].thread_id)
        if t:
            _load_thread_into_session(t)
        return t


# ── Landing (new thread) ───────────────────────────────────────────────────────


def _save_uploaded_pdfs(files, target_dir: Path) -> list[Path]:
    """Save Streamlit UploadedFile objects to target_dir. Returns saved paths."""
    target_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for f in files:
        dest = target_dir / f.name
        dest.write_bytes(f.getvalue())
        saved.append(dest)
    return saved


def _render_landing() -> None:
    """Conversational landing — single chat-style interface, no forms or tabs."""

    with st.chat_message("assistant"):
        st.markdown(
            "**What do you want to analyze?**\n\n"
            "Upload PDFs, paste a folder path, or import an existing schema. "
            "I'll start parsing in the background while you design the schema."
        )
        if list_threads():
            st.info(
                "**Runs in the sidebar** — click a thread (e.g. *ingesting*) to see the live "
                "progress bar, logs, and schema chat. This page is only for **starting** a new analysis."
            )

    # ── Source: uploaded files ────────────────────────────────────────────────
    uploaded_files = st.file_uploader(
        "Drop PDFs here (select multiple files; for large corpora use the folder path below)",
        type=["pdf"],
        accept_multiple_files=True,
    )
    if uploaded_files:
        names = [f.name for f in uploaded_files]
        st.caption(
            f"**{len(names)} file(s) ready:** {', '.join(names[:4])}"
            + ("…" if len(names) > 4 else "")
        )

    # ── Source: folder path ───────────────────────────────────────────────────
    folder_path = st.text_input(
        "Or paste a folder path",
        placeholder="/home/casey/reports    |    C:\\Users\\casey\\filings    (auto-translated for WSL)",
        key="landing_folder_path",
    )

    # ── Research prompt ───────────────────────────────────────────────────────
    topic = st.text_area(
        "What do you want to extract?",
        placeholder=(
            "e.g. tariff exposure and supply chain risk in annual MD&A\n"
            "e.g. ESG targets, emissions, net-zero commitments across portfolio\n"
            "e.g. revenue by segment and geographic region"
        ),
        height=90,
        key="landing_topic",
    )

    # ── Advanced: import schema + other params ────────────────────────────────
    with st.expander("⚙ Advanced — import schema / index CSV / batch settings"):
        c1a, c2a = st.columns(2)
        corpus_name_adv  = c1a.text_input("Corpus name (auto if blank)", key="landing_cname")
        trial_n_adv      = c2a.number_input("Trial batch size", 1, 50, 7, key="landing_trial")
        eval_min_adv     = c1a.number_input("Eval window min docs", 1, 20, 6, key="landing_eval")
        index_csv_adv    = c2a.text_input(
            "Existing index CSV (skip scanning)", key="landing_index_csv",
            placeholder="output/tariffs/index.csv",
        )
        schema_json_adv  = st.text_area(
            "Paste existing schema JSON (optional — skip LLM design)",
            height=120, key="landing_schema_json",
            placeholder='{"extraction_schema": [{"name": "...", "type": "string", "description": "..."}]}',
        )

    # ── Start ────────────────────────────────────────────────────────────────
    fp = folder_path.strip()
    ic = index_csv_adv.strip() if index_csv_adv else ""
    have_source = bool(uploaded_files) or bool(fp) or bool(ic)

    if st.button("▶ Start analysis", type="primary",
                 use_container_width=True, disabled=not have_source,
                 key="landing_start_btn"):
        if not topic.strip() and not schema_json_adv.strip():
            st.warning("Describe your research focus or paste a schema to continue.")
            return

        from prompt2dataset.corpus.paths import normalize_host_path

        # Resolve folder path
        docs_dir = ""
        if fp:
            docs_dir = str(normalize_host_path(fp))
            if not Path(docs_dir).exists():
                st.error(
                    f"Path not found: `{docs_dir}`\n\n"
                    "Windows paths (`C:\\...`) become `/mnt/c/...` in WSL. "
                    "Verify the drive is mounted with `ls /mnt/`."
                )
                return

        # Resolve index CSV
        resolved_index = ""
        if ic:
            p = Path(ic)
            if p.exists():
                resolved_index = str(p)
            else:
                st.error(f"Index CSV not found: `{ic}`")
                return

        # Parse imported schema
        imported_cols: list[dict] | None = None
        if schema_json_adv.strip():
            imported_cols = _parse_schema_json(schema_json_adv.strip())
            if imported_cols is None:
                st.error("Could not parse the schema JSON — make sure each entry has a `name` field.")
                return

        # Corpus name
        cname = corpus_name_adv.strip() if corpus_name_adv else ""
        if not cname:
            if uploaded_files:
                cname = _slugify(Path(uploaded_files[0].name).stem[:30]) or "corpus"
            elif fp:
                cname = _slugify(Path(fp).name[:30]) or "corpus"
            else:
                cname = "corpus"
        cid = _slugify(cname)
        trial_n_v  = int(trial_n_adv)
        eval_min_v = int(eval_min_adv)

        # Save uploaded PDFs
        if uploaded_files:
            upload_dir = ROOT / "output" / cid / "uploads"
            _save_uploaded_pdfs(uploaded_files, upload_dir)
            docs_dir = str(upload_dir)

        _rid = new_run_id()
        corpus_cfg = CorpusConfig(
            name=cname,
            corpus_id=cid,
            topic=topic.strip() or cname,
            docs_dir=docs_dir or str(ROOT / "output" / cid),
            file_pattern="auto",
            run_id=_rid,
        )
        if resolved_index:
            corpus_cfg.index_csv = resolved_index
        cfg_path = _CONFIG_DIR / f"{cid}.yaml"
        corpus_cfg.to_yaml(cfg_path)
        try:
            from prompt2dataset.utils.lakehouse import Lakehouse

            _src = (
                "upload"
                if uploaded_files
                else ("folder" if fp else ("index_import" if resolved_index else "new"))
            )
            Lakehouse().register_corpus(corpus_cfg, project_root=ROOT, source_kind=_src)
        except Exception:
            pass

        src_desc = (f"{len(uploaded_files)} uploaded PDF(s)" if uploaded_files
                    else fp or resolved_index)
        t = Thread.create(
            docs_dir=docs_dir or resolved_index,
            corpus_name=cname,
            topic=topic.strip() or cname,
            trial_n=trial_n_v,
        )
        t.corpus_id = cid
        t.run_id = _rid
        t.eval_window_min = eval_min_v

        ws_state: DatasetState = {
            "corpus_topic": topic.strip() or cname,
            "corpus_id": cid,
            "identity_fields": corpus_cfg.identity_fields,
            "corpus_index_csv": resolved_index or corpus_cfg.index_csv,
            "corpus_parse_index_csv": corpus_cfg.parse_index_csv,
            "corpus_chunks_parquet": corpus_cfg.chunks_parquet,
            "corpus_chunks_llm_parquet": corpus_cfg.chunks_llm_parquet,
            "datasets_export_dir": corpus_cfg.datasets_dir,
            "run_id": _rid,
            "eval_window_min": eval_min_v,
            "eval_window_max": eval_min_v + 4,
            "rework_count": 0,
            "schema_approved": False,
            "use_sample": True,
            "extraction_row_granularity": "one_row_per_document",
        }

        if imported_cols:
            ws_state["proposed_columns"] = imported_cols
            ws_state["schema_approved"] = True
            _ensure_enriched_proposed_columns(ws_state, t, persist=False)
            t.schema_cols = ws_state["proposed_columns"]

        skip_ingest = bool(resolved_index) and not docs_dir
        if skip_ingest:
            t.proc_done = True
            t.proc_rc = 0
            st.session_state["ws_ingest_done"] = True
            t.step = "extracting" if imported_cols else "designing"
            t.status = t.step
            step_msg = "Ready to extract." if imported_cols else "Describe what you want to extract."
            t.add_chat("user", f"{topic.strip() or '[schema import]'}\n\n_Source: {src_desc}_")
            t.add_chat("assistant",
                f"Loaded existing index `{Path(resolved_index).name}`. "
                + (f"Schema imported — {len(imported_cols)} fields. {step_msg}" if imported_cols
                   else step_msg))
        else:
            t.step = "designing"
            t.status = "designing"
            launch_ingest(t, trial_n=trial_n_v)
            t.add_chat("user", f"{topic.strip()}\n\n_Source: {src_desc}_")
            t.add_chat("assistant",
                f"Parsing `{cname}` in the background ({src_desc}). "
                f"{'Schema imported — ' + str(len(imported_cols)) + ' fields. ' if imported_cols else ''}"
                f"Extraction starts once {eval_min_v} docs are ready.")

        if resolved_index and imported_cols:
            n = build_doc_queue(t, ws_state)
            st.session_state["ws_doc_total"] = n

        save_thread(t)
        st.session_state.update({
            "ws_state": ws_state, "ws_thread": t,
            "ws_thread_id": t.thread_id, "ws_show_landing": False,
        })
        st.rerun()


# ── Phase routers ──────────────────────────────────────────────────────────────


def _render_scoping(t: Thread, ws_state: DatasetState) -> None:
    """Phase 0 (optional): agent-guided scope definition.

    Guides the user through 3 questions:
      1. Which companies / tickers?
      2. Which document types?
      3. What date range?

    Each answer is parsed by scope_node (regex + lookup), the KG coverage is
    checked, missing docs trigger acquisition jobs, existing docs advance to
    'designing'.
    """
    from prompt2dataset.dataset_graph.scope_node import (
        parse_scope_from_prompt,
        resolve_scope,
        ScopeSpec,
    )

    render_chat_history(t)
    scope: ScopeSpec = t.scope_spec or {}

    # Determine which question to ask next
    has_entities = bool(scope.get("tickers") or scope.get("company_names") or scope.get("profile_numbers"))
    has_doc_types = bool(scope.get("doc_types"))
    has_dates = scope.get("date_from") is not None or scope.get("date_to") is not None

    with st.chat_message("assistant"):
        if not has_entities:
            st.markdown(
                "**Which companies should I include in this analysis?**\n\n"
                "You can provide:\n"
                "- Ticker symbols (e.g. `CNQ SU CVE`)\n"
                "- Company names (e.g. `Canadian Natural Resources, Suncor Energy`)\n"
                "- SEDAR profile numbers (6-digit)\n\n"
                "Or just describe them: *\"TSX energy companies exposed to US tariffs\"*"
            )
        elif not has_doc_types:
            st.markdown(
                "**What type of documents should I look for?**\n\n"
                "Examples: Annual MD&A, Annual Report, ESG/Sustainability Report, AIF, Management Circular\n\n"
                "Or just say *\"annual reports\"* or *\"sustainability reports\"*."
            )
        elif not has_dates:
            st.markdown(
                "**What time period should I cover?**\n\n"
                "Examples: `2022–2025`, `2023 and 2024`, `last 3 years`"
            )
        else:
            # All 3 questions answered — show coverage summary and let user proceed
            entities = scope.get("entities", [])
            unresolved = scope.get("unresolved", [])

            if entities:
                st.success(f"Scope defined: **{len(entities)} companies**, "
                           f"{scope.get('doc_types', [''])[0]}, "
                           f"{scope.get('date_from')}–{scope.get('date_to')}")
                for e in entities[:5]:
                    st.caption(f"  {e.get('sedar_name') or e.get('ticker')} — profile #{e.get('profile_number','?')}")

            if unresolved:
                st.warning(f"Could not resolve: {', '.join(unresolved)}\n"
                           "Please clarify these names or provide their SEDAR profile numbers.")

            c1, c2 = st.columns(2)
            with c1:
                if st.button("▶ Proceed to analysis", type="primary", key="scope_proceed_btn"):
                    t.step = "designing"
                    save_thread(t)
                    st.rerun()
            with c2:
                if st.button("↺ Change scope", key="scope_reset_btn"):
                    t.scope_spec = {}
                    save_thread(t)
                    st.rerun()

    # Chat input — parse answer with scope_node
    user_msg = render_chat_input(t, ws_state, step="scoping")
    if user_msg:
        t.add_chat("user", user_msg)
        _log_chat_correction(ws_state, user_msg, "")

        # Merge into existing scope
        parsed = parse_scope_from_prompt(user_msg)
        merged: ScopeSpec = {
            **scope,
            "tickers":       list(dict.fromkeys((scope.get("tickers") or []) + parsed.get("tickers", []))),
            "company_names": list(dict.fromkeys((scope.get("company_names") or []) + parsed.get("company_names", []))),
            "profile_numbers": list(dict.fromkeys((scope.get("profile_numbers") or []) + parsed.get("profile_numbers", []))),
            "doc_types":     parsed.get("doc_types") or scope.get("doc_types") or ["Annual MD&A"],
            "date_from":     parsed.get("date_from") or scope.get("date_from"),
            "date_to":       parsed.get("date_to") or scope.get("date_to"),
        }

        # Resolve entities once we have entity identifiers
        if merged.get("tickers") or merged.get("profile_numbers") or merged.get("company_names"):
            resolved = resolve_scope(
                merged,
                corpus_id=(t.corpus_id or None),
            )
            merged.update({
                "entities":   resolved.get("entities", []),
                "unresolved": resolved.get("unresolved", []),
            })

        t.scope_spec = merged
        ws_state["scope_spec"] = merged
        st.session_state["ws_state"] = ws_state
        save_thread(t)
        st.rerun()


def _render_extraction_policy_expander(t: Thread, ws_state: DatasetState) -> None:
    """Row granularity + multi-item hint — stored on DatasetState for extraction."""
    from prompt2dataset.dataset_graph.mapping_contract import build_schema_mapping_summary

    with st.expander("Extraction policy", expanded=False):
        opts = ("one_row_per_document", "one_row_per_fact")
        cur = ws_state.get("extraction_row_granularity") or "one_row_per_document"
        if cur not in opts:
            cur = "one_row_per_document"
        ix = opts.index(cur)
        choice = st.selectbox(
            "Row granularity (per PDF)",
            options=opts,
            index=ix,
            format_func=lambda x: {
                "one_row_per_document": "One row per PDF (default)",
                "one_row_per_fact": "Primary fact + bullets in evidence_quote",
            }[x],
            key=f"extraction_row_granularity_select_{t.step}",
            help=(
                "When one PDF contains many similar line items, 'primary fact' tells the model "
                "to fill scalars for the best-supported item and mention others in evidence_quote."
            ),
        )
        prev = ws_state.get("extraction_row_granularity")
        ws_state["extraction_row_granularity"] = choice
        cols = ws_state.get("proposed_columns") or []
        if cols:
            ws_state["schema_mapping_summary"] = build_schema_mapping_summary(
                cols,
                ws_state.get("dataset_description") or "",
                row_granularity=choice,
            )
        st.session_state["ws_state"] = ws_state
        if choice != prev:
            save_thread(t)


def _render_schema_contract_panel(ws_state: DatasetState) -> None:
    """Show how ideated schema maps to one row per PDF (and per-column cardinality)."""
    summary = (ws_state.get("schema_mapping_summary") or "").strip()
    if not summary:
        return
    with st.expander("How this schema maps to each PDF", expanded=False):
        st.markdown(
            "<div style='font-size:0.88rem;line-height:1.55;color:#334155;white-space:pre-wrap'>"
            + html.escape(summary)
            + "</div>",
            unsafe_allow_html=True,
        )


def _render_designing(t: Thread, ws_state: DatasetState) -> None:
    """Phase 1: parallel ingest + schema chat."""
    render_live_state_strip(ws_state, t)
    render_chat_history(t)
    _render_extraction_policy_expander(t, ws_state)
    _render_schema_contract_panel(ws_state)

    ingest_done = st.session_state.get("ws_ingest_done", t.proc_done)
    parsed_n = count_parsed_docs(ws_state)
    schema_approved = ws_state.get("schema_approved", False)

    # ── Onboarding window milestones ──────────────────────────────────────────
    GATE1_AVAILABLE_AT = 6
    FILL_PREVIEW_AT = 15
    GATE1_REQUIRED_AT = 30

    if ingest_done and parsed_n > 0:
        if FILL_PREVIEW_AT <= parsed_n < GATE1_REQUIRED_AT:
            rows = ws_state.get("rows", [])
            columns = ws_state.get("proposed_columns", [])
            if rows and columns:
                from app_pages.table_render import value_counts_as_filled

                fill_rates = {}
                for col in columns:
                    col_name = col.get("name", "")
                    if col_name:
                        default = col.get("default")
                        non_null = sum(
                            1 for r in rows
                            if value_counts_as_filled(r.get(col_name), default)
                        )
                        fill_rates[col_name] = round(non_null / max(len(rows), 1), 2)
                low_fields = [f for f, r in fill_rates.items() if r < 0.55]
                if low_fields:
                    st.info(
                        f"📊 **{parsed_n} docs parsed** — Fill rate preview: "
                        f"{len(low_fields)} fields below 55%: "
                        f"`{'`, `'.join(low_fields[:3])}`"
                    )
        elif parsed_n >= GATE1_REQUIRED_AT and not schema_approved:
            st.warning(
                f"📋 **{parsed_n} docs parsed.** Schema approval is required before extracting "
                f"the full corpus. Review and approve the schema below."
            )

    # ── Ingest status ─────────────────────────────────────────────────────────
    # ingest_done can flip True early via [EXTRACTION_READY] sentinel
    # (sample batch ready) while full corpus continues in background.
    with st.chat_message("assistant"):
        bg_still_running = (
            st.session_state.get("ws_proc") is not None
            and not st.session_state.get("ws_ingest_rc_final")
        )
        if not ingest_done:
            render_ingest_progress(t, ws_state)
        elif bg_still_running and parsed_n > 0:
            # Sample batch done via [EXTRACTION_READY] — full corpus still ingesting in bg
            bg_n = st.session_state.get("ws_background_docs", parsed_n)
            st.success(
                f"✓ **{parsed_n} docs ready** — extraction can start. "
                f"Full corpus is still ingesting in the background ({bg_n} so far)."
            )
        elif parsed_n == 0:
            st.warning(
                "**Ingest completed but 0 documents were parsed.**\n\n"
                "Possible causes:\n"
                "- The PDF folder path is not accessible from WSL (Windows paths become `/mnt/c/...`)\n"
                "- No `.pdf` files in the folder\n"
                "- Docling failed silently or the process was killed (RAM / OOM)\n\n"
                "Large trial batches or concurrent apps can exhaust RAM — try **Advanced** → lower "
                "trial size, close other browser tabs, or run ingest from a shell with a memory limit you control.\n\n"
                "You can still design a schema and import an index CSV, "
                "or fix the path below."
            )
            with st.expander("🔧 Fix path / retry ingest"):
                new_path = st.text_input(
                    "Corrected PDF folder path", key="fix_path_input",
                    placeholder="/mnt/c/Users/casey/reports  or  /home/casey/pdfs",
                )
                c1, c2 = st.columns(2)
                if c1.button("↺ Retry ingest", key="retry_ingest_btn", type="primary"):
                    if new_path:
                        from prompt2dataset.corpus.paths import normalize_host_path
                        fixed = str(normalize_host_path(new_path))
                        if Path(fixed).exists():
                            t.docs_dir = fixed
                            _persist_docs_dir_to_corpus_yaml(t, fixed)
                            t.proc_done = False
                            st.session_state["ws_ingest_done"] = False
                            launch_ingest(t, trial_n=t.trial_n)
                            save_thread(t)
                            st.rerun()
                        else:
                            st.error(f"Path still not found: `{fixed}`")
                    else:
                        st.warning("Enter a path first.")
                new_idx = st.text_input(
                    "Or import an existing index CSV", key="fix_index_input",
                    placeholder="output/tariffs/index.csv",
                )
                if c2.button("→ Use this index", key="use_index_btn"):
                    if new_idx and Path(new_idx).exists():
                        ws_state["corpus_index_csv"] = new_idx
                        st.session_state["ws_state"] = ws_state
                        t.proc_done = True
                        st.session_state["ws_ingest_done"] = True
                        t.add_chat("system", f"Loaded index from `{new_idx}`")
                        save_thread(t)
                        st.rerun()
                    else:
                        st.error("File not found.")
        else:
                eval_min = ws_state.get("eval_window_min", 6)
                if parsed_n >= eval_min:
                    st.success(f"✓ Ingest complete — {parsed_n} docs parsed")
                else:
                    st.info(f"Ingest complete — {parsed_n} docs parsed. Schema design is available.")

    # ── Gate: transition to extraction ───────────────────────────────────────
    # Require an on-disk index when parsed_n==0: corpus_index_csv is always a path *string*
    # from setup, which is truthy even before ingest creates the file — do not gate on that alone.
    _cidx = (ws_state.get("corpus_index_csv") or "").strip()
    _index_ready = bool(_cidx) and Path(_cidx).is_file()
    # Only transition from *designing* — avoids re-running when ``t.step`` already says
    # ``extracting`` (and prevents resetting ``ws_doc_queue`` every rerun).
    if (
        t.step == "designing"
        and ingest_done
        and schema_approved
        and (parsed_n > 0 or _index_ready)
    ):
        n = build_doc_queue(t, ws_state)
        if n > 0:
            t.step = "extracting"
            t.status = "extracting"
            t.add_chat("assistant", f"Schema approved — starting trial extraction ({n} documents)…")
            save_thread(t)
            st.rerun()
            return

    # ── Auto-generate schema once docs are ready and no schema exists yet ───────
    # The corpus topic the user entered at creation is the initial user_query.
    # We fire it automatically so the agent proposes a schema without needing
    # an explicit follow-up message.
    existing_cols = ws_state.get("proposed_columns", [])
    if (ingest_done and not existing_cols and not schema_approved
            and not st.session_state.get("ws_run_schema")
            and not st.session_state.get("ws_schema_auto_fired")):
        topic = ws_state.get("corpus_topic") or ws_state.get("user_query") or t.topic or ""
        if topic:
            ws_state["user_query"] = topic
            st.session_state["ws_state"] = ws_state
            st.session_state["ws_run_schema"] = True
            st.session_state["ws_schema_auto_fired"] = True
            st.rerun()

    # ── Show existing schema if present ──────────────────────────────────────
    existing_cols = ws_state.get("proposed_columns", [])
    if existing_cols and not schema_approved:
        with st.chat_message("assistant"):
            _render_schema_inline(t, ws_state, existing_cols)

    # ── Schema streaming ──────────────────────────────────────────────────────
    if st.session_state.pop("ws_run_schema", False):
        updated = stream_schema_card(t, ws_state)
        st.session_state["ws_state"] = updated
        st.session_state["ws_schema_auto_fired"] = True

    # ── Chat input ────────────────────────────────────────────────────────────
    user_msg = render_chat_input(t, ws_state, step="designing")
    if user_msg:
        # Check if pasted JSON schema
        if _msg_looks_like_schema(user_msg):
            columns = _parse_schema_json(user_msg)
            if columns:
                ws_state["proposed_columns"] = columns
                ws_state["schema_approved"] = False
                ws_state["schema_iteration"] = ws_state.get("schema_iteration", 0) + 1
                _ensure_enriched_proposed_columns(ws_state, t, persist=False)
                st.session_state["ws_state"] = ws_state
                t.add_chat("user", f"[Pasted JSON schema — {len(columns)} fields]")
                t.schema_cols = ws_state["proposed_columns"]
                t.add_chat("assistant",
                    f"Loaded your schema — {len(columns)} fields: "
                    + ", ".join(f"`{c['name']}`" for c in columns[:5])
                    + ("…" if len(columns) > 5 else "")
                    + "\n\nReview and click **Approve** to start extraction."
                )
                save_thread(t)
                st.rerun()
                return

        t.add_chat("user", user_msg)
        _log_chat_correction(ws_state, user_msg, "")
        ws_state["user_query"] = user_msg
        ws_state["schema_feedback"] = ""
        st.session_state["ws_state"] = ws_state
        save_thread(t)
        st.session_state["ws_run_schema"] = True
        st.rerun()


def _render_schema_inline(t: Thread, ws_state: DatasetState, columns: list[dict]) -> None:
    """Render the current schema with Approve/Edit/Regenerate buttons inline."""
    from app_pages.chat_render import _render_schema_fields_html
    meta_cols = _detect_metadata_columns(columns, ws_state.get("identity_fields"))
    if meta_cols:
        st.warning(
            f"**Overlap with identity fields:** `{'`, `'.join(meta_cols)}` match "
            f"``identity_fields`` and are copied from the doc index into each row — "
            f"keeping them in the extraction schema wastes tokens. Remove them unless you "
            f"intentionally want the model to *re-derive* them from PDF text.",
            icon="⚠️",
        )
    _render_schema_fields_html(columns)

    # ── ExtractionCallConfig preview (Gate 1 config surface) ──────────────────
    extraction_call_config = ws_state.get("extraction_call_config", {})
    config_rationale = ws_state.get("extraction_call_config_rationale", "")
    if extraction_call_config:
        with st.expander("⚙ Extraction settings (recommended by schema LLM)", expanded=False):
            if config_rationale:
                st.caption(config_rationale)
            cols_data = []
            for field_name, cfg in extraction_call_config.items():
                cols_data.append({
                    "Field": field_name,
                    "Difficulty": cfg.get("difficulty", "standard"),
                    "Temperature": cfg.get("temperature", 0.05),
                    "Max tokens": cfg.get("max_tokens", 150),
                    "Verbatim quote": "✓" if cfg.get("require_verbatim_quote") else "—",
                })
            if cols_data:
                import pandas as _pd
                st.dataframe(
                    _pd.DataFrame(cols_data),
                    use_container_width=True,
                    hide_index=True,
                )
            st.caption("These settings are applied automatically. Adjust field difficulty in chat to change them.")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("✓ Approve schema", key="schema_approve_inline", type="primary"):
            ws_state["schema_approved"] = True
            st.session_state["ws_state"] = ws_state
            t.add_chat("user", "✓ Schema approved.")
            save_thread(t)
            # Persist schema to Obsidian vault
            try:
                from connectors.obsidian_bridge import get_obsidian_bridge
                _bridge = get_obsidian_bridge()
                _bridge.write_schema(
                    schema_name=ws_state.get("dataset_name", t.thread_id[:8]),
                    corpus_id=t.corpus_id or "unknown",
                    columns=ws_state.get("proposed_columns", []),
                    quality="pending",
                )
            except Exception:
                pass
            st.rerun()
    with c2:
        if st.button("✏ Edit in chat", key="schema_edit_inline"):
            st.session_state["ws_chat_input"] = "Modify the schema: "
            st.rerun()
    with c3:
        if st.button("↺ Regenerate", key="schema_regen_inline"):
            ws_state["schema_feedback"] = "Regenerate with a fresh approach."
            st.session_state["ws_state"] = ws_state
            st.session_state["ws_run_schema"] = True
            st.rerun()


def _render_extracting(t: Thread, ws_state: DatasetState) -> None:
    """Phase 2: trial extraction — one doc per Streamlit rerun."""
    render_live_state_strip(ws_state, t)
    render_chat_history(t)
    _render_extraction_policy_expander(t, ws_state)
    _render_schema_contract_panel(ws_state)
    # Rows append after each doc (`pop_and_extract_one`); show partial table live.
    if ws_state.get("rows") and ws_state.get("proposed_columns"):
        _render_inline_table(ws_state)
    with st.chat_message("assistant"):
        render_extraction_progress(t, ws_state)

    if st.session_state.pop("ws_run_critique", False):
        updated = stream_critique_card(t, ws_state)
        st.session_state["ws_state"] = updated
        t.step = "preview"
        save_thread(t)
        st.rerun()


def _render_preview(t: Thread, ws_state: DatasetState) -> None:
    """Phase 3: inline results + critique + chat."""
    render_live_state_strip(ws_state, t)
    render_chat_history(t)

    rows    = ws_state.get("rows", [])
    columns = ws_state.get("proposed_columns", [])

    _render_extraction_policy_expander(t, ws_state)
    _render_schema_contract_panel(ws_state)

    # Table shown inline
    if rows or columns:
        _render_inline_table(ws_state)

    if columns and not rows:
        with st.chat_message("assistant"):
            st.markdown(f"Schema ready ({len(columns)} fields) — run extraction to fill the table.")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("▶ Trial extraction", key="preview_run_trial_btn", type="primary"):
                    n = build_doc_queue(t, ws_state)
                    if n > 0:
                        t.step = "extracting"
                        t.status = "extracting"
                        t.add_chat("assistant", f"Starting trial extraction ({n} docs)…")
                        save_thread(t)
                        st.rerun()
                    else:
                        st.error("No documents in queue — check your corpus index.")
            with c2:
                if st.button("▶ Full corpus run", key="preview_full_run_btn"):
                    ws_state["use_sample"] = False
                    n = build_doc_queue(t, ws_state)
                    t.step = "full_run"
                    t.status = "full_extracting"
                    t.add_chat("assistant", f"Starting full corpus extraction ({n} docs)…")
                    save_thread(t)
                    st.rerun()

    if st.session_state.pop("ws_run_critique", False):
        updated = stream_critique_card(t, ws_state)
        st.session_state["ws_state"] = updated
        save_thread(t)
        return

    if rows:
        _render_review_action_bar(t, ws_state, ctx="preview")

    user_msg = render_chat_input(t, ws_state, step="preview")
    if user_msg:
        if _msg_looks_like_schema(user_msg):
            cols_imp = _parse_schema_json(user_msg)
            if cols_imp:
                ws_state["proposed_columns"] = cols_imp
                ws_state["schema_approved"] = False
                ws_state["rows"] = []
                _ensure_enriched_proposed_columns(ws_state, t, persist=False)
                st.session_state["ws_state"] = ws_state
                t.schema_cols = ws_state["proposed_columns"]
                t.rows = []
                t.add_chat("user", f"[Updated schema — {len(cols_imp)} fields]")
                save_thread(t)
                st.rerun()
                return

        msg_stripped = user_msg.strip()
        low = msg_stripped.lower()
        if low.startswith("/schema"):
            body = msg_stripped[7:].strip() or "Improve the schema using the current extraction sample."
            t.add_chat("user", f"[schema feedback] {body}")
            _log_chat_correction(ws_state, f"[schema feedback] {body}", "")
            ws_state["user_query"] = body
            ws_state["schema_feedback"] = body
            ws_state["schema_approved"] = False
            st.session_state["ws_state"] = ws_state
            save_thread(t)
            st.session_state["ws_run_schema"] = True
            st.rerun()
            return

        _reply = _build_workspace_data_chat_reply(ws_state)
        t.add_chat("user", user_msg)
        t.add_chat("assistant", _reply)
        _log_chat_correction(ws_state, user_msg, _reply)
        save_thread(t)
        st.rerun()
        return

    if st.session_state.pop("ws_run_schema", False):
        updated = stream_schema_card(t, ws_state)
        st.session_state["ws_state"] = updated


def _render_full_run(t: Thread, ws_state: DatasetState) -> None:
    """Phase 4: full corpus extraction."""
    render_live_state_strip(ws_state, t)
    render_chat_history(t)
    _render_extraction_policy_expander(t, ws_state)
    _render_schema_contract_panel(ws_state)
    if ws_state.get("rows") and ws_state.get("proposed_columns"):
        _render_inline_table(ws_state)
    with st.chat_message("assistant"):
        render_full_run_progress(t, ws_state)

    if st.session_state.pop("ws_run_critique", False):
        updated = stream_critique_card(t, ws_state)
        st.session_state["ws_state"] = updated
        t.step = "done"
        save_thread(t)
        st.rerun()


def _render_done(t: Thread, ws_state: DatasetState) -> None:
    """Phase 5: done — inline table + chat."""
    render_live_state_strip(ws_state, t)
    render_chat_history(t)
    _render_inline_table(ws_state)

    if st.session_state.pop("ws_run_critique", False):
        updated = stream_critique_card(t, ws_state)
        st.session_state["ws_state"] = updated
        save_thread(t)
        return

    if ws_state.get("rows"):
        _render_review_action_bar(t, ws_state, ctx="done")

    user_msg = render_chat_input(t, ws_state, step="done")
    if user_msg:
        _dr = _build_workspace_data_chat_reply(ws_state)
        t.add_chat("user", user_msg)
        t.add_chat("assistant", _dr)
        _log_chat_correction(ws_state, user_msg, _dr)
        save_thread(t)
        st.rerun()


# ── Status bar (always visible at top of every active session) ────────────────


def _render_status_bar(t: Thread, ws_state: DatasetState, step: str) -> None:
    """Thin bar at the top: corpus name · phase pill · Stop button if running."""
    _PHASE_LABELS = {
        "designing":  ("🔵", "Parsing"),
        "extracting": ("🟡", "Extracting"),
        "preview":    ("🟢", "Review"),
        "full_run":   ("🟡", "Full run"),
        "done":       ("✅", "Done"),
        "scoping":    ("🔵", "Scoping"),
    }
    dot, label = _PHASE_LABELS.get(step, ("⚪", step.title()))
    corpus = t.corpus_name or t.corpus_id or "Corpus"
    parsed = st.session_state.get("ws_parsed_docs", 0)
    ingest_done = st.session_state.get("ws_ingest_done", t.proc_done)

    # Build detail string
    if step == "designing" and not ingest_done:
        detail = f"· {parsed} docs parsed" if parsed else "· parsing…"
    elif step in ("extracting", "full_run"):
        q = st.session_state.get("ws_doc_queue", [])
        tot = st.session_state.get("ws_doc_total", 1)
        done_n = tot - len(q)
        detail = f"· {done_n}/{tot} docs"
    else:
        rows = ws_state.get("rows", [])
        detail = f"· {len(rows)} rows" if rows else ""

    running = (
        step in ("designing", "extracting", "full_run")
        and (not ingest_done or step in ("extracting", "full_run"))
    )

    left, right = st.columns([6, 1])
    with left:
        st.markdown(
            f"<div style='font-size:0.82rem;color:var(--text-muted);padding:4px 0 8px'>"
            f"<strong style='color:var(--text)'>{corpus}</strong>"
            f"&nbsp;&nbsp;{dot}&nbsp;<span style='color:var(--text2)'>{label}</span>"
            f"&nbsp;&nbsp;<span style='opacity:0.6'>{detail}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with right:
        if running:
            st.markdown("<div class='stop-bar'>", unsafe_allow_html=True)
            if st.button("⏹ Stop", key="topbar_stop_btn"):
                from app_pages.pipeline_runner import kill_ingest, clear_extraction_state
                kill_ingest()
                clear_extraction_state()
                t.add_log("Stopped by user.")
                t.step = "preview" if ws_state.get("rows") else "designing"
                save_thread(t)
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
        elif step == "done":
            path = t.dataset_path or ws_state.get("dataset_path", "")
            if path and Path(path).exists():
                with open(path, "rb") as fh:
                    st.download_button(
                        "⬇ CSV",
                        data=fh.read(),
                        file_name=Path(path).name,
                        mime="text/csv",
                        type="secondary",
                        key="topbar_dl_btn",
                    )

    st.markdown("<hr style='margin:0 0 10px'>", unsafe_allow_html=True)


# ── Inline table helper (used by preview + done phases) ───────────────────────


def _render_inline_table(ws_state: DatasetState) -> None:
    """Show field strip + table inline in the chat flow."""
    rows    = ws_state.get("rows", [])
    columns = ws_state.get("proposed_columns", [])
    if rows and columns:
        render_field_strip(ws_state)
        render_table(ws_state, focus_field=st.session_state.get("ws_focus_field", ""))
    elif columns:
        render_field_strip(ws_state)


# ── Main entry point ───────────────────────────────────────────────────────────


def render() -> None:
    """Main workspace render — called by app.py."""
    t = _render_sidebar()

    show_landing = st.session_state.get("ws_show_landing", False)
    if t is None or show_landing:
        _render_landing()
        return

    ws_state: DatasetState = st.session_state.get("ws_state", {})
    if ws_state.get("proposed_columns"):
        _ensure_enriched_proposed_columns(ws_state, t, persist=True)

    _reconcile_thread_step_status(t)

    step = _STEP_NORMALISE.get(t.step, t.step) or "new"

    if t.proc_done and not st.session_state.get("ws_ingest_done"):
        st.session_state["ws_ingest_done"] = True

    # Reset auto-fire flag when thread changes so each new corpus gets its schema
    last_tid = st.session_state.get("_last_thread_id")
    if last_tid != t.thread_id:
        st.session_state["_last_thread_id"] = t.thread_id
        st.session_state.pop("ws_schema_auto_fired", None)

    if step in ("new", "designing") and ws_state.get("proposed_columns") and ws_state.get("rows"):
        step = "preview"
        t.step = "preview"
        save_thread(t)

    if step == "new":
        _render_landing()
        return

    # ── Top status bar — always-visible Stop + phase label ───────────────────
    _render_status_bar(t, ws_state, step)

    # ── Single-column chat (full width, max-width controlled by CSS) ──────────
    if step == "scoping":
        _render_scoping(t, ws_state)
    elif step == "designing":
        _render_designing(t, ws_state)
    elif step == "extracting":
        _render_extracting(t, ws_state)
    elif step == "preview":
        _render_preview(t, ws_state)
    elif step == "full_run":
        _render_full_run(t, ws_state)
    elif step == "done":
        _render_done(t, ws_state)
    else:
        _render_landing()
