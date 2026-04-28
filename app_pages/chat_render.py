"""Chat renderer — all chat bubbles, inline pipeline cards, and control buttons.

Renders:
  - Past chat messages (user + assistant + system/log)
  - Schema card (streamed inline, with Approve / Edit / Regenerate)
  - Ingest progress card (with Stop button)
  - Extraction progress card (with Stop button)
  - Critique card (streamed inline, with Accept / Ignore / Export)
  - Approve / Export card
  - Chat input box (bottom of page)

Session state keys consumed (generic names):
  ws_thread         Thread — current active thread
  ws_state          DatasetState — current pipeline state
  ws_ingest_done    bool
  ws_doc_queue      list
  ws_doc_total      int
  ws_focus_field    str
  ws_chat_input     str — prefilled chat input value
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Generator

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]

from app_pages.thread_store import Thread, save_thread
from app_pages.table_render import render_column_inspector, render_field_strip, render_table
from prompt2dataset.dataset_graph.state import DatasetState


# ── LiveState context strip ───────────────────────────────────────────────────


def render_live_state_strip(ws_state: DatasetState, t: "Thread | None" = None) -> None:
    """Persistent thin status strip above the chat showing current pipeline state.

    Shows: pending action, fill rate summary, active flags, rework count.
    Always stays in view — never scrolls off screen. Compact (one line).
    """
    try:
        from app_pages.thread_store import build_live_state
        live = build_live_state(dict(ws_state) if ws_state else {}, t)
    except Exception:
        return

    has_content = (
        live.fill_rates or live.active_flags
        or live.rework_count > 0
        or (live.pending_action and "no immediate" not in live.pending_action.lower())
    )
    if not has_content:
        return

    parts = []
    if live.pending_action and "no immediate" not in live.pending_action.lower():
        parts.append(f"<strong>→</strong> {live.pending_action}")
    if live.fill_rates:
        low = {k: v for k, v in live.fill_rates.items() if v < 0.55}
        if low:
            worst = min(low.items(), key=lambda x: x[1])
            parts.append(f"⚠ Low fill: <code>{worst[0]}</code> {worst[1]:.0%}")
        else:
            avg = sum(live.fill_rates.values()) / len(live.fill_rates)
            parts.append(f"Fill rate: <strong>{avg:.0%}</strong>")
    if live.active_flags:
        flag_str = " ".join(f"{k.replace('_count','')}: {v}" for k, v in live.active_flags.items())
        parts.append(f"Flags: {flag_str}")
    if live.rework_count:
        parts.append(f"Rework: {live.rework_count}/3")

    if parts:
        st.markdown(
            "<div style='background:#F0F7FF;border:1px solid #BFDBFE;border-radius:6px;"
            "padding:5px 12px;font-size:0.79rem;color:#1E40AF;margin-bottom:8px;"
            "display:flex;gap:16px;flex-wrap:wrap'>"
            + "  &nbsp;·&nbsp;  ".join(parts)
            + "</div>",
            unsafe_allow_html=True,
        )


# ── Message rendering ──────────────────────────────────────────────────────────


def render_chat_history(t: Thread) -> None:
    """Render all messages from thread.chat as Streamlit chat messages."""
    for msg_index, msg in enumerate(t.chat):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        card = msg.get("card")  # optional structured card type

        if role == "system":
            # System / log messages: dimmed, smaller
            st.markdown(
                f"<div class='log-msg'>{content}</div>",
                unsafe_allow_html=True,
            )
            continue

        with st.chat_message(role):
            st.markdown(content)
            if card == "schema":
                _render_schema_card_static(msg, msg_index=msg_index)
            elif card == "critique":
                _render_critique_card_static(msg, msg_index=msg_index)


_TYPE_COLORS = {
    "str":   ("#3b82f6", "#dbeafe"),   # blue
    "string": ("#3b82f6", "#dbeafe"),
    "float": ("#f59e0b", "#fef3c7"),   # amber
    "int":   ("#10b981", "#d1fae5"),   # green
    "bool":  ("#8b5cf6", "#ede9fe"),   # purple
    "date":  ("#06b6d4", "#cffafe"),   # cyan
    "string|null": ("#3b82f6", "#dbeafe"),
}
_DEFAULT_TYPE_COLOR = ("#6b7280", "#f3f4f6")


def _type_badge(type_str: str) -> str:
    fg, bg = _TYPE_COLORS.get(type_str, _DEFAULT_TYPE_COLOR)
    short = type_str.replace("|null", "?")
    return (
        f"<span style='display:inline-block;padding:1px 7px;border-radius:99px;"
        f"font-size:0.72rem;font-weight:600;letter-spacing:.02em;"
        f"background:{bg};color:{fg};font-family:monospace'>{short}</span>"
    )


def _render_schema_fields_html(columns: list[dict]) -> None:
    rows_html = ""
    for col in columns:
        name = col.get("name", "")
        ctype = col.get("type", "str")
        desc = col.get("description", "")
        badge = _type_badge(ctype)
        rows_html += (
            f"<div style='display:flex;align-items:baseline;gap:10px;padding:6px 0;"
            f"border-bottom:1px solid rgba(0,0,0,0.05)'>"
            f"<span style='font-family:monospace;font-size:0.85rem;font-weight:600;"
            f"min-width:170px;flex-shrink:0;color:var(--text1,#1e293b)'>{name}</span>"
            f"{badge}"
            f"<span style='font-size:0.82rem;color:var(--text2,#64748b);flex:1'>{desc}</span>"
            f"</div>"
        )
    st.markdown(
        f"<div style='background:rgba(99,102,241,0.04);border:1px solid rgba(99,102,241,0.12);"
        f"border-radius:10px;padding:10px 16px;margin:6px 0'>"
        f"<div style='font-size:0.78rem;font-weight:700;color:#6366f1;letter-spacing:.05em;"
        f"text-transform:uppercase;margin-bottom:8px'>📋 {len(columns)} fields</div>"
        f"{rows_html}</div>",
        unsafe_allow_html=True,
    )


def _render_schema_card_static(msg: dict, *, msg_index: int = 0) -> None:
    """Render a schema card from a stored chat message (non-streaming)."""
    ws_state: DatasetState = st.session_state.get("ws_state", {})
    _mid = f"h{msg_index}"
    columns = msg.get("columns") or ws_state.get("proposed_columns", [])
    approved = ws_state.get("schema_approved", False)

    if columns:
        _render_schema_fields_html(columns)

    if not approved:
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("✓ Approve schema", key=f"schema_approve_btn_{_mid}", type="primary"):
                _handle_approve_schema()
        with c2:
            if st.button("✏ Edit in chat", key=f"schema_edit_btn_{_mid}"):
                st.session_state["ws_chat_input"] = "Modify the schema: "
                st.rerun()
        with c3:
            if st.button("↺ Regenerate", key=f"schema_regen_btn_{_mid}"):
                _handle_regenerate_schema()


def _render_critique_suggestions_checkboxes(suggestions: list, key_prefix: str) -> list[dict]:
    """Render field_issues as checkboxes. Returns the selected subset."""
    selected: list[dict] = []
    if not suggestions:
        return selected

    with st.expander("Suggested changes — select to apply", expanded=True):
        for i, s in enumerate(suggestions):
            if isinstance(s, dict):
                label = f"[{s.get('severity','').upper()}] **{s.get('field','')}** — {s.get('suggestion','')}"
                issue_note = s.get("issue", "")
                checked = st.checkbox(label, value=True, key=f"{key_prefix}_sug_{i}",
                                      help=issue_note)
                if checked:
                    selected.append(s)
            else:
                # Backward-compat: plain string suggestions
                if st.checkbox(str(s), value=True, key=f"{key_prefix}_sug_{i}"):
                    selected.append({"field": "__schema__", "issue": str(s),
                                     "severity": "medium", "suggestion": str(s)})
    return selected


def _render_critique_config_deltas(ws_state: DatasetState, key_prefix: str) -> list[str]:
    """Render per-field parameter delta suggestions at Gate 3.

    Shows each field's suggested config delta (e.g. retrieval_k +5, temperature 0.3).
    User can accept or reject each independently.
    Returns list of field names whose config delta was accepted.
    """
    deltas = ws_state.get("critique_config_deltas", [])
    if not deltas:
        return []

    accepted = []
    st.markdown("**Parameter adjustments suggested by critique:**")
    for di, item in enumerate(deltas):
        field = item.get("field", "")
        delta = item.get("config_delta", {})
        rationale = item.get("config_rationale", "")
        if not delta:
            continue
        delta_str = ", ".join(f"{k}: {v}" for k, v in delta.items())
        col_a, col_b = st.columns([6, 1])
        with col_a:
            st.markdown(
                f"<span style='font-family:monospace;font-size:0.85rem'>"
                f"<strong>{field}</strong></span> — `{delta_str}`",
                unsafe_allow_html=True,
            )
            if rationale:
                st.caption(rationale)
        with col_b:
            safe_field = "".join(c if c.isalnum() else "_" for c in str(field))[:40]
            if st.checkbox("Accept", key=f"{key_prefix}_delta_{di}_{safe_field}", value=True):
                accepted.append(field)
    return accepted


def _render_critique_consensus_block(ws_state: DatasetState, *, key_prefix: str) -> None:
    """Show validation-council epistemics when ``critique_consensus`` is present."""
    cons = ws_state.get("critique_consensus")
    if not cons or not isinstance(cons, dict):
        return
    if cons.get("error"):
        st.caption(f"Council error: {cons.get('error')}")
        return
    score = cons.get("reviewer_agreement_score")
    qualities = cons.get("reviewer_qualities") or []
    lenses = cons.get("lenses") or []
    with st.expander(
        "Validation council — how consensus was reached",
        expanded=False,
        key=f"{key_prefix}_val_council",
    ):
        if score is not None:
            st.markdown(f"**Reviewer agreement (modal alignment):** {float(score):.0%}")
        if qualities:
            pairs = [
                f"`{l or '?'}` → **{q}**"
                for l, q in zip(lenses, qualities)
            ]
            if len(pairs) < len(qualities):
                pairs.extend(f"— → **{q}**" for q in qualities[len(pairs) :])
            st.markdown("Independent verdicts: " + " · ".join(pairs))
        if cons.get("dissent_summary"):
            st.markdown("**Dissent / tension:** " + str(cons["dissent_summary"]))
        if cons.get("consensus_rationale"):
            st.caption(str(cons["consensus_rationale"]))


def _render_critique_card_static(msg: dict, *, msg_index: int = 0) -> None:
    """Render a critique card from stored message."""
    ws_state: DatasetState = st.session_state.get("ws_state", {})
    quality = ws_state.get("critique_quality", "ok")
    suggestions = ws_state.get("critique_suggestions", [])
    export_approved = ws_state.get("export_approved", False)
    key_prefix = f"critique_hist_{msg_index}"

    color = {"good": "#22c55e", "ok": "#f59e0b", "needs_work": "#ef4444"}.get(quality, "#94a3b8")
    st.markdown(
        f"<span style='color:{color};font-weight:600;font-size:0.85rem'>"
        f"Quality: {quality.replace('_', ' ').upper()}</span>",
        unsafe_allow_html=True,
    )
    _render_critique_consensus_block(ws_state, key_prefix=key_prefix)

    selected = _render_critique_suggestions_checkboxes(suggestions, key_prefix=key_prefix)
    accepted_deltas = _render_critique_config_deltas(ws_state, key_prefix=key_prefix)
    if accepted_deltas:
        ws_state["_accepted_config_delta_fields"] = accepted_deltas
        st.session_state["ws_state"] = ws_state

    if not export_approved:
        t: Thread = st.session_state.get("ws_thread")
        _mid = f"h{msg_index}"
        if quality == "needs_work":
            c0, c1, c2, c3 = st.columns(4)
            with c0:
                if st.button("↺ Rework schema", key=f"critique_rework_btn_{_mid}", type="primary"):
                    _handle_rework(t, ws_state, selected or suggestions)
            with c1:
                if st.button("✓ Approve & export", key=f"critique_approve_btn_{_mid}", type="primary"):
                    _handle_export_approve(t, ws_state)
            with c2:
                if st.button("→ Export anyway", key=f"critique_export_btn_{_mid}"):
                    _handle_export_approve(t, ws_state)
            with c3:
                if st.button("▶ Full corpus run", key=f"critique_fullrun_btn_{_mid}"):
                    _handle_full_run(t, ws_state)
        else:
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("✓ Approve & export", key=f"critique_approve_btn_{_mid}", type="primary"):
                    _handle_export_approve(t, ws_state)
            with c2:
                if st.button("→ Export anyway", key=f"critique_export_btn_{_mid}"):
                    _handle_export_approve(t, ws_state)
            with c3:
                if st.button("▶ Full corpus run", key=f"critique_fullrun_btn_{_mid}"):
                    _handle_full_run(t, ws_state)


# ── Live streaming cards ────────────────────────────────────────────────────────


def stream_schema_card(t: Thread, ws_state: DatasetState) -> DatasetState:
    """Stream schema_node output into the chat thread.

    During streaming, shows a clean thinking indicator (not raw JSON).
    After parsing, stores a human-readable summary + the structured schema card.
    """
    from prompt2dataset.dataset_graph.schema_node import schema_node_stream

    with st.chat_message("assistant"):
        thinking_placeholder = st.empty()
        thinking_placeholder.markdown("_Designing schema…_ ▌")

        full_text = ""
        final_state = ws_state

        for token, new_state in schema_node_stream(ws_state):
            if new_state is not None:
                final_state = new_state
            else:
                full_text += token
                # Show a compact status during streaming, not raw JSON
                token_count = len(full_text)
                if token_count < 80:
                    thinking_placeholder.markdown(f"_Designing schema…_ ▌")
                else:
                    thinking_placeholder.markdown(f"_Designing schema ({token_count} chars)…_ ▌")

        thinking_placeholder.empty()

        error = final_state.get("error", "")
        if error:
            st.error(f"Schema design failed: {error}")
            t.add_chat("assistant", f"Schema design failed: {error}")
            t.add_log(f"schema_node error: {error}")
            save_thread(t)
            return final_state

        columns = final_state.get("proposed_columns", [])
        dataset_name = final_state.get("dataset_name", "")
        dataset_desc = final_state.get("dataset_description", "")

        # Clean summary line — what the user reads in the chat
        summary = f"Here's a **{len(columns)}-field schema**"
        if dataset_name:
            summary += f" for **{dataset_name.replace('_', ' ')}**"
        if dataset_desc:
            summary += f" — {dataset_desc[:120]}"
        st.markdown(summary)

        if columns:
            _render_schema_fields_html(columns)

        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("✓ Approve schema", key="schema_approve_stream_btn", type="primary"):
                _handle_approve_schema()
        with c2:
            if st.button("✏ Edit in chat", key="schema_edit_stream_btn"):
                st.session_state["ws_chat_input"] = "Modify the schema: "
                st.rerun()
        with c3:
            if st.button("↺ Regenerate", key="schema_regen_stream_btn"):
                _handle_regenerate_schema()

    # Store a human-readable summary in chat history (not raw JSON)
    t.add_chat("assistant", summary, card="schema", columns=columns)
    t.schema_cols = columns
    save_thread(t)

    return final_state


def stream_critique_card(t: Thread, ws_state: DatasetState) -> DatasetState:
    """Stream critique_node output into the chat thread."""
    from prompt2dataset.dataset_graph.critique_node import critique_node_stream

    full_text = ""
    final_state = ws_state
    with st.chat_message("assistant"):
        placeholder = st.empty()

        for token, new_state in critique_node_stream(ws_state):
            if new_state is not None:
                final_state = new_state
            else:
                full_text += token
                placeholder.markdown(full_text + "▌")

        # Keep the streamed text on screen — do not wipe the placeholder.
        quality = final_state.get("critique_quality", "ok")
        suggestions = final_state.get("critique_suggestions", [])
        critique_text = (final_state.get("critique_text") or "").strip()
        if final_state.get("critique_council_trace"):
            body = full_text.strip() or critique_text
        else:
            body = critique_text or full_text.strip()
        parse_ok = final_state.get("critique_parse_ok", True)
        if not parse_ok and not body:
            body = full_text.strip()

        color = {"good": "#22c55e", "ok": "#f59e0b", "needs_work": "#ef4444"}.get(quality, "#94a3b8")
        badge = (
            f"<span style='color:{color};font-weight:600;font-size:0.85rem'>"
            f"Quality: {quality.replace('_', ' ').upper()}"
            f"{'' if parse_ok else ' · unstructured response'}</span>"
        )
        placeholder.markdown(
            f"{badge}\n\n{body}" if body else badge,
            unsafe_allow_html=True,
        )
        _render_critique_consensus_block(final_state, key_prefix="stream")

        selected = _render_critique_suggestions_checkboxes(suggestions, key_prefix="stream")
        accepted_deltas = _render_critique_config_deltas(final_state, key_prefix="stream")
        if accepted_deltas:
            final_state["_accepted_config_delta_fields"] = accepted_deltas
            st.session_state["ws_state"] = final_state

        if quality == "needs_work":
            c0, c1, c2, c3 = st.columns(4)
            with c0:
                if st.button("↺ Rework schema", key="critique_rework_stream_btn", type="primary"):
                    _handle_rework(t, final_state, selected or suggestions)
            with c1:
                if st.button("✓ Approve & export", key="critique_approve_stream_btn", type="primary"):
                    _handle_export_approve(t, final_state)
            with c2:
                if st.button("→ Export anyway", key="critique_export_stream_btn"):
                    _handle_export_approve(t, final_state)
            with c3:
                if st.button("▶ Full corpus run", key="critique_fullrun_stream_btn"):
                    _handle_full_run(t, final_state)
        else:
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("✓ Approve & export", key="critique_approve_stream_btn", type="primary"):
                    _handle_export_approve(t, final_state)
            with c2:
                if st.button("→ Export anyway", key="critique_export_stream_btn"):
                    _handle_export_approve(t, final_state)
            with c3:
                if st.button("▶ Full corpus run", key="critique_fullrun_stream_btn"):
                    _handle_full_run(t, final_state)

    if final_state.get("critique_council_trace"):
        display_text = full_text.strip() or (final_state.get("critique_text") or "").strip()
    else:
        display_text = (final_state.get("critique_text") or "").strip() or full_text.strip()
    if not final_state.get("critique_parse_ok", True) and not display_text:
        display_text = full_text.strip()
    t.add_chat(
        "assistant",
        display_text or "Critique complete.",
        card="critique",
        quality=final_state.get("critique_quality", "ok"),
        critique_parse_ok=final_state.get("critique_parse_ok", True),
    )
    save_thread(t)
    return final_state


# ── Extraction progress ────────────────────────────────────────────────────────


def render_ingest_progress(t: Thread, ws_state: DatasetState) -> None:
    """Live ingest progress.  Polls the subprocess queue and shows per-doc status.

    When the [EXTRACTION_READY] sentinel arrives, it sets ws_ingest_done=True
    so the schema-approval flow unlocks automatically — the full corpus can keep
    parsing in the background while the user works on the sample.
    """
    from app_pages.pipeline_runner import count_parsed_docs, poll_ingest

    done = poll_ingest(t)
    parsed = count_parsed_docs(ws_state)

    # Live counters from incremental signals
    live_parsed = st.session_state.get("ws_parsed_docs", parsed)
    live_chunks = st.session_state.get("ws_parsed_chunks", 0)
    eval_min = ws_state.get("eval_window_min", 6)

    # Progress bar based on live signal or parquet count
    display_n = max(parsed, live_parsed)
    bar_val = min(0.95, max(0.02, display_n / max(eval_min * 2, 10)))

    if done:
        st.progress(1.0, text=f"✓ Parsed {display_n} docs ({live_chunks or '?'} chunks)")
    else:
        label = f"Parsing… {display_n} docs ready"
        if live_chunks:
            label += f" · {live_chunks} chunks"
        bg_docs = st.session_state.get("ws_background_docs", 0)
        if bg_docs > eval_min:
            label += f" · {bg_docs - eval_min} more incoming"
        st.progress(bar_val, text=label)

    # Surface parse errors prominently
    parse_error = st.session_state.get("ws_parse_error", "")
    if parse_error:
        if parse_error.startswith("[PARSE_ZERO_CHUNKS]"):
            st.warning(
                f"**Docling ran, but no chunks were written for the UI.**\n\n{parse_error}\n\n"
                "CPU/GPU can still spike during layout/OCR even when the chunk step fails. "
                "Check the log for `[CHUNK_ZERO]` lines; re-run chunk from a shell if needed."
            )
        else:
            st.error(
                f"**Parse failed — 0 documents ingested.**\n\n{parse_error}\n\n"
                "Check that the PDF folder path is accessible, contains `.pdf` files, "
                "and that Docling can read them."
            )

    if display_n >= eval_min and not done:
        st.caption(
            f"💡 **{display_n} docs ready** — approve the schema to start extraction "
            "while the rest continues ingesting."
        )
    elif display_n == 0 and not done and not parse_error:
        st.caption("Loading Docling GPU model — first doc takes ~60–90 s…")
    elif done and display_n == 0 and not parse_error:
        st.error(
            "**Ingest completed but 0 documents were parsed.**\n\n"
            "Possible causes: PDF folder path not accessible from WSL (Windows paths become `/mnt/c/…`), "
            "no `.pdf` files in the folder, or Docling failed silently. "
            "Check the log above for details."
        )

    if not done:
        st.rerun()


def render_extraction_progress(t: Thread, ws_state: DatasetState) -> None:
    """Show extraction progress.

    By default pops **several** docs per rerun and runs them in parallel (asyncio + shared
    vLLM endpoint) so GPU utilization is not stuck at a single serial request — unlike the
    old one-doc-per-rerun loop. Tune batch size in ``config/prompt2dataset.yaml`` (``streamlit.extraction_batch``).

    The Stop button is also in the top status bar — this just shows the progress bar.
    """
    from app_pages.pipeline_runner import (
        pop_and_extract_batch,
        pop_and_extract_one,
        run_consistency_after_extraction,
    )
    from prompt2dataset.utils.prompt2dataset_settings import load_prompt2dataset_config

    p2d = load_prompt2dataset_config()

    queue: list = st.session_state.get("ws_doc_queue", [])
    total: int  = st.session_state.get("ws_doc_total", 1)
    done_count  = total - len(queue)

    pct = done_count / max(total, 1)
    st.progress(pct, text=f"Extracting… {done_count} / {total} docs")

    batch = max(1, p2d.streamlit_extraction_batch)
    conc = max(1, p2d.streamlit_extraction_concurrency)

    if queue:
        if batch > 1:
            pop_and_extract_batch(t, ws_state, batch_size=batch, concurrency=min(conc, batch))
        else:
            pop_and_extract_one(t, ws_state)
        st.rerun()
    else:
        # Trial extraction ends at t.step == "extracting"; full corpus ends at "full_run".
        trial_just_finished = t.step == "extracting"
        ws_state = run_consistency_after_extraction(t, ws_state)
        rows = ws_state.get("rows", [])
        if rows:
            st.success(f"✓ {len(rows)} rows extracted")
        t.step = "preview"
        save_thread(t)
        if trial_just_finished and p2d.streamlit_auto_critique_after_trial and rows:
            st.session_state["ws_run_critique"] = True
        st.rerun()


# ── Full corpus run ────────────────────────────────────────────────────────────


def render_full_run_progress(t: Thread, ws_state: DatasetState) -> None:
    """Show full-corpus extraction progress (same as trial but with use_sample=False)."""
    ws_state["use_sample"] = False
    render_extraction_progress(t, ws_state)


# ── Action handlers ────────────────────────────────────────────────────────────


def _handle_approve_schema() -> None:
    ws_state: DatasetState = st.session_state.get("ws_state", {})
    ws_state["schema_approved"] = True
    st.session_state["ws_state"] = ws_state
    t: Thread = st.session_state.get("ws_thread")
    if t:
        t.add_chat("user", "✓ Schema approved.")
        t.add_log("Schema approved — queuing extraction.")
        save_thread(t)
    st.rerun()


def _handle_regenerate_schema() -> None:
    ws_state: DatasetState = st.session_state.get("ws_state", {})
    ws_state["schema_approved"] = False
    ws_state["schema_feedback"] = "Regenerate — produce a fresh schema design."
    st.session_state["ws_state"] = ws_state
    st.session_state["ws_run_schema"] = True
    st.rerun()


def _handle_rework(t: Thread, ws_state: DatasetState, suggestions: list) -> None:
    """Handle rework loop. suggestions is list[dict] (structured) or list[str] (compat)."""
    from prompt2dataset.dataset_graph.graph import _increment_rework

    # Build structured delta using _increment_rework
    updated = _increment_rework(ws_state, selected_suggestions=suggestions if isinstance(suggestions[0] if suggestions else None, dict) else None)
    ws_state.update({
        "rework_count": updated["rework_count"],
        "schema_approved": False,
        "schema_feedback": updated.get("schema_feedback", ""),
        "rows": [],
        "cells": [],
    })
    st.session_state["ws_state"] = ws_state

    # Build a clean human-readable prefill from structured suggestions
    if suggestions and isinstance(suggestions[0], dict):
        lines = [f"- [{s.get('field','')}] {s.get('suggestion','')}" for s in suggestions[:5]]
        prefill = "Please update the schema:\n" + "\n".join(lines)
    elif suggestions:
        prefill = "Rework the schema based on these suggestions: " + "; ".join(str(s) for s in suggestions[:3])
    else:
        prefill = "Rework the schema."

    st.session_state["ws_chat_input"] = prefill
    t.add_chat("system", f"Rework cycle {ws_state['rework_count']}/3 started.")
    t.add_log(f"rework_loop: cycle {ws_state['rework_count']}")
    t.step = "designing"
    t.rows = []
    save_thread(t)
    st.rerun()


def _handle_export_approve(t: Thread, ws_state: DatasetState) -> None:
    from prompt2dataset.dataset_graph.graph import export_node

    ws_state["export_approved"] = True
    result = export_node(ws_state)
    err = (result.get("error") or "").strip()
    if err:
        result = {**result, "export_approved": False}
        st.session_state["ws_state"] = result
        save_thread(t)
        st.error(f"Export failed: {err}")
        st.rerun()
        return

    path = result.get("dataset_path", "")
    cells_path = result.get("cells_dataset_path", "")
    st.session_state["ws_state"] = result
    t.dataset_path = path
    t.status = "done"
    t.step = "done"
    msg = f"✓ Dataset exported to `{path}`"
    if cells_path:
        msg += f"\n\nCell-level JSONL: `{cells_path}`"
    t.add_chat("assistant", msg)
    save_thread(t)
    st.rerun()


def _handle_full_run(t: Thread, ws_state: DatasetState) -> None:
    from app_pages.pipeline_runner import build_doc_queue
    ws_state["use_sample"] = False
    ws_state["rows"] = []
    ws_state["cells"] = []
    st.session_state["ws_state"] = ws_state
    n = build_doc_queue(t, ws_state)
    t.step = "full_run"
    t.status = "full_extracting"
    t.add_chat("assistant", f"Running full corpus extraction ({n} docs)…")
    t.add_log(f"full_run: queued {n} docs")
    save_thread(t)
    st.rerun()


# ── Chat input ─────────────────────────────────────────────────────────────────


def render_chat_input(t: Thread, ws_state: DatasetState, step: str) -> str | None:
    """Render the bottom chat input and return the submitted message (or None)."""
    prefill = st.session_state.pop("ws_chat_input", "")

    # Contextual placeholder
    placeholders = {
        "new": "Describe your corpus or paste a schema JSON…",
        "designing": "Describe what to extract  •  or paste a JSON schema directly…",
        "extracting": "Extraction running — you can refine when done.",
        "preview": "Chat: sample table reply. For schema redesign use /schema … or paste JSON.",
        "full_run": "Full run in progress…",
        "done": "Ask about the dataset, export again, or start a new analysis…",
    }
    ph = placeholders.get(step, "Message…")
    disabled = step in ("extracting", "full_run")

    msg = st.chat_input(ph, disabled=disabled, key="chat_input_box")
    if msg:
        return msg

    # Handle prefill (shows in input on next render — only submit if non-empty default)
    if prefill and not disabled:
        st.session_state["ws_chat_input_pending"] = prefill

    return None


# ── Sidebar helper: field inspector ───────────────────────────────────────────


def render_sidebar_inspector(ws_state: DatasetState) -> None:
    """Show field inspector in sidebar when a field is focused."""
    focus = st.session_state.get("ws_focus_field", "")
    if not focus:
        st.caption("Click a field button above to inspect it.")
        return
    render_column_inspector(ws_state, focus)
