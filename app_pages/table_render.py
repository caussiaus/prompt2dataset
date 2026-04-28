"""Table rendering — sticky results table + column inspector overlay.

Renders the extracted rows DataFrame below the chat thread. Clicking a
column header opens a slide-in inspector showing field definition, stats,
and evidence examples.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pandas as pd
import streamlit as st

from prompt2dataset.dataset_graph.state import DatasetState, SEDAR_IDENTITY_FIELDS

if TYPE_CHECKING:
    from app_pages.thread_store import DatasetContext


def dispatch_mutation(
    ctx: "DatasetContext",
    mutation_type: str,
    *,
    doc_id: str | None = None,
    field_name: str | None = None,
    value=None,
    reason: str | None = None,
) -> "DatasetContext":
    """Apply a typed user mutation to DatasetContext and persist it.

    Each mutation:
    1. Appends to ctx.user_annotations
    2. Applies the change to ctx.rows / ctx.proposed_columns as appropriate
    3. Saves ctx to disk immediately via save_context()

    Returns the updated ctx.
    """
    import datetime
    from app_pages.thread_store import TableMutation, save_context

    mutation = TableMutation(
        mutation_type=mutation_type,
        doc_id=doc_id,
        field_name=field_name,
        value=value,
        reason=reason,
        timestamp=datetime.datetime.utcnow().isoformat(),
    )
    ctx.user_annotations.append(mutation)

    if mutation_type == "override_value" and doc_id and field_name:
        proposed: Any = None
        for row in ctx.rows:
            rid = row.get("doc_id") or row.get("filing_id") or row.get("entity_slug", "")
            if rid == doc_id:
                proposed = row.get(field_name)
                row[field_name] = value
                break
        trid = (getattr(ctx, "run_id", "") or "").strip()
        if trid:
            from prompt2dataset.training_events import (
                append_training_event,
                merge_training_event_state,
                trajectory_context_from_dataset_state,
            )

            chunk_id = ""
            for row in ctx.rows:
                rid = row.get("doc_id") or row.get("filing_id") or row.get("entity_slug", "")
                if rid == doc_id:
                    chunk_id = str(
                        row.get(f"{field_name}_chunk_id")
                        or row.get("_evidence_chunk_id")
                        or ""
                    )
                    break
            evt_state = merge_training_event_state(
                trajectory_context_from_dataset_state(
                    {
                        "run_id": trid,
                        "feedback_run_id": trid,
                        "proposed_columns": ctx.proposed_columns,
                        "schema_iteration": ctx.schema_version,
                        "rework_count": ctx.rework_count,
                        "datasets_export_dir": getattr(ctx, "datasets_export_dir", "") or "",
                        "corpus_id": getattr(ctx, "corpus_id", "") or "",
                    }
                )
            )
            st_payload: dict = {
                "doc_id": doc_id,
                "field_name": field_name,
                "schema_iteration": ctx.schema_version,
                "rework_count": ctx.rework_count,
            }
            if chunk_id:
                st_payload["chunk_id"] = chunk_id
            if evt_state.get("schema_hash"):
                st_payload["schema_hash"] = evt_state["schema_hash"]
            append_training_event(
                trid,
                {
                    "event_type": "human_override",
                    "state": st_payload,
                    "action": {
                        "proposed_value": proposed,
                        "override_value": value,
                        "override_reason": (reason or "")[:4000],
                    },
                    "reward_signal": None,
                },
                state=evt_state,
            )

    elif mutation_type == "annotate_cell" and doc_id and field_name:
        pass  # stored in user_annotations only — value not overridden

    elif mutation_type in ("flag_row", "approve_row") and doc_id:
        for row in ctx.rows:
            rid = row.get("doc_id") or row.get("filing_id") or row.get("entity_slug", "")
            if rid == doc_id:
                row["_user_flag"] = mutation_type == "flag_row"
                break

    elif mutation_type == "adjust_instruction" and field_name:
        for col in ctx.proposed_columns:
            col_name = col.get("name") if isinstance(col, dict) else getattr(col, "name", "")
            if col_name == field_name:
                if isinstance(col, dict):
                    col["extraction_instruction"] = str(value or "")
                break

    save_context(ctx)
    return ctx


# Columns to always hide from the visible table (internal flags + evidence detail)
_HIDDEN_SUFFIXES = ("_evidence_quote", "_evidence_pages", "_evidence_section")
_HIDDEN_EXACT = frozenset({
    "_all_chunks", "_keyword_hits",
    "_pass1_positive", "_evidence_blocks_used",
    "_flag_all_default", "_flag_evidenceless",
    # _extraction_error is intentionally NOT hidden — it is surfaced as a badge
})


def value_counts_as_filled(v: Any, default: Any) -> bool:
    """True if ``v`` is a meaningful extracted value (matches table empty-cell rules).

    Keeps fill-rate badges aligned with displayed "—" cells: pandas ``NA`` / float nan /
    whitespace-only strings do not count as filled even when ``v != default`` by accident.
    """
    try:
        if v is None:
            return False
        if pd.isna(v):
            return False
    except (TypeError, ValueError):
        pass
    if isinstance(v, float) and pd.isna(v):
        return False
    if v == default:
        return False
    s = str(v).strip()
    if s in ("", "None", "nan", "NaN", "null", "<NA>", "—"):
        return False
    return True


def _visible_cols(df: pd.DataFrame, identity_fields: list[str]) -> list[str]:
    """Return ordered columns: identity first, then extracted fields, skip internals.

    _extraction_error is placed last so it is visible but not prominent.
    """
    id_in_df = [c for c in identity_fields if c in df.columns]
    has_errors = "_extraction_error" in df.columns and df["_extraction_error"].notna().any()
    rest = [
        c for c in df.columns
        if c not in id_in_df
        and c not in _HIDDEN_EXACT
        and c != "_extraction_error"
        and not any(c.endswith(s) for s in _HIDDEN_SUFFIXES)
    ]
    # Append _extraction_error at the end only when at least one row has an error
    if has_errors:
        rest.append("_extraction_error")
    return id_in_df + rest


def _style_row(row: pd.Series) -> list[str]:
    """Colour-code rows with consistency flags."""
    styles = [""] * len(row)
    if row.get("_flag_all_default"):
        styles = ["background-color: rgba(239,68,68,0.08)"] * len(row)
    elif row.get("_flag_evidenceless"):
        styles = ["background-color: rgba(234,179,8,0.1)"] * len(row)
    return styles


def _null_display(v: Any) -> Any:
    """Replace None / empty / nan with a styled dash placeholder."""
    if v is None:
        return "—"
    s = str(v)
    if s.strip() in ("", "None", "nan", "null"):
        return "—"
    return v


def _truncate(v: Any, max_len: int = 80) -> Any:
    """Truncate long strings for table display."""
    if isinstance(v, str) and len(v) > max_len:
        return v[:max_len] + "…"
    return v


def _style_cell(v: Any) -> str:
    """Return inline CSS for a single cell value."""
    if v == "—":
        return "color: #cbd5e1; font-style: italic; font-size: 0.82rem"
    return ""


def _fill_rate_bar(pct: float) -> str:
    """Tiny HTML fill-rate bar for column header."""
    color = "#22c55e" if pct > 0.7 else "#f59e0b" if pct > 0.3 else "#ef4444"
    bar_w = max(4, int(pct * 40))
    return (
        f"<div title='{pct:.0%} filled' style='display:inline-flex;align-items:center;"
        f"gap:4px;font-size:0.72rem;color:{color}'>"
        f"<div style='width:{bar_w}px;height:4px;border-radius:2px;background:{color}'></div>"
        f"{pct:.0%}</div>"
    )


def _max_field_pressure_by_column(
    ws_state: DatasetState,
    schema_cols: list[dict],
    rows: list[dict],
) -> dict[str, float]:
    from prompt2dataset.utils.epistemic_blackboard import normalize_epistemic_root

    root = normalize_epistemic_root(ws_state.get("epistemic_blackboard"))
    names = [str(c.get("name")) for c in schema_cols if c.get("name")]
    mx = {n: 0.0 for n in names}
    for r in rows:
        did = str(r.get("doc_id") or r.get("filing_id") or "")
        bb = root.get(did) if did else None
        if not isinstance(bb, dict):
            continue
        fp = bb.get("field_pressure") or {}
        if not isinstance(fp, dict):
            continue
        for k, v in fp.items():
            ks = str(k)
            if ks not in mx:
                continue
            try:
                mx[ks] = max(mx[ks], float(v))
            except (TypeError, ValueError):
                continue
    return mx


def render_table(ws_state: DatasetState, *, focus_field: str = "") -> None:
    """Render the full results table with fill-rate indicators and null styling.

    Args:
        ws_state: Current pipeline state containing rows + proposed_columns.
        focus_field: If set, highlight that column in the table.
    """
    rows = ws_state.get("rows", [])
    if not rows:
        return

    identity_fields = ws_state.get("identity_fields") or SEDAR_IDENTITY_FIELDS
    schema_cols = ws_state.get("proposed_columns", [])
    df = pd.DataFrame(rows)
    vis_cols = _visible_cols(df, identity_fields)
    df_vis = df[vis_cols].copy()

    # ── Extraction error badge ────────────────────────────────────────────
    error_rows = [r for r in rows if r.get("_extraction_error")]
    if error_rows:
        err_msgs = list({str(r["_extraction_error"])[:120] for r in error_rows[:3]})
        st.error(
            f"**{len(error_rows)}/{len(rows)} rows failed extraction.** "
            f"First error: `{err_msgs[0]}`  \n"
            "These rows contain identity fields only. Check vLLM is running and "
            "the chunks parquet has data for these documents."
        )

    # Warn badges
    flags = ws_state.get("consistency_flags") or {}
    n_all_def = flags.get("all_default_count", 0)
    n_ev_less = flags.get("evidenceless_count", 0)
    total = flags.get("total_rows", len(rows))

    if n_all_def or n_ev_less:
        badge_parts = []
        if n_all_def:
            badge_parts.append(f"⚠ {n_all_def}/{total} rows all-default (parse failure?)")
        if n_ev_less:
            badge_parts.append(f"⚠ {n_ev_less}/{total} rows with unsupported values (check evidence)")
        st.warning("  •  ".join(badge_parts))

    wq_prev = ws_state.get("wonder_queue_preview") or []
    if isinstance(wq_prev, list) and wq_prev:
        st.caption(
            f"Wonder queue preview: {len(wq_prev)} recent entries — see wonder_queue.jsonl beside training_events."
        )

    # Compute fill rates for extracted columns
    schema_col_names = {c.get("name") for c in schema_cols}
    fill_rates: dict[str, float] = {}
    for col in vis_cols:
        if col in schema_col_names:
            col_def = next((c for c in schema_cols if c.get("name") == col), {})
            default = col_def.get("default")
            non_default = df_vis[col].apply(lambda v: value_counts_as_filled(v, default))
            fill_rates[col] = non_default.sum() / max(len(df_vis), 1)

    # Render fill-rate bars above the table
    if fill_rates:
        bar_cols = st.columns(min(len(fill_rates), 8))
        for i, (col, pct) in enumerate(fill_rates.items()):
            with bar_cols[i % len(bar_cols)]:
                st.markdown(
                    f"<div style='font-size:0.72rem;font-family:monospace;color:#475569;"
                    f"overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:120px'"
                    f" title='{col}'>{col}</div>"
                    + _fill_rate_bar(pct),
                    unsafe_allow_html=True,
                )

    # Replace nulls with "—" and truncate long strings
    for col in df_vis.columns:
        df_vis[col] = df_vis[col].apply(_null_display).apply(_truncate)

    def _style_rows(row: pd.Series) -> list[str]:
        styles = []
        for v in row:
            if v == "—":
                styles.append("color: #cbd5e1; font-style: italic; font-size: 0.82rem")
            else:
                styles.append("")
        return styles

    styled = df_vis.style.apply(_style_rows, axis=1)

    if focus_field and focus_field in df_vis.columns:
        styled = styled.set_properties(
            **{"background-color": "rgba(99,102,241,0.07)"},
            subset=[focus_field],
        )

    press = _max_field_pressure_by_column(ws_state, schema_cols, rows)
    col_cfg: dict[str, Any] = {}
    for col in df_vis.columns:
        if col not in schema_col_names:
            continue
        p = float(press.get(col, 0.0))
        tip = f"Field pressure (max): {p:.2f}" if p > 0 else None
        if tip:
            col_cfg[col] = st.column_config.TextColumn(col, width="medium", help=tip)
        else:
            col_cfg[col] = st.column_config.TextColumn(col, width="medium")

    df_kwargs: dict[str, Any] = {
        "use_container_width": True,
        "height": min(520, 100 + 38 * len(df_vis)),
    }
    if col_cfg:
        df_kwargs["column_config"] = col_cfg
    st.dataframe(styled, **df_kwargs)


def render_column_inspector(ws_state: DatasetState, col_name: str) -> None:
    """Render the column inspector panel for a selected field.

    Shows: field definition, type, extraction instruction, default,
    fill-rate stats, and up to 3 evidence quote examples.
    """
    columns = ws_state.get("proposed_columns", [])
    rows = ws_state.get("rows", [])

    col_def = next((c for c in columns if c.get("name") == col_name), None)
    if not col_def:
        st.caption(f"No definition found for `{col_name}`")
        return

    st.markdown(f"#### `{col_name}`")
    st.markdown(
        f"**Type:** `{col_def.get('type', '?')}`  \n"
        f"**Description:** {col_def.get('description', '')}  \n"
        f"**Default:** `{json.dumps(col_def.get('default'))}`"
    )
    instr = col_def.get("extraction_instruction", "")
    if instr:
        with st.expander("Extraction instruction"):
            st.markdown(instr)

    from prompt2dataset.utils.epistemic_blackboard import normalize_epistemic_root

    root = normalize_epistemic_root(ws_state.get("epistemic_blackboard"))
    dag_edges: list[str] = []
    for did, bb in root.items():
        if not isinstance(bb, dict):
            continue
        dag = bb.get("evidence_dag") or {}
        if isinstance(dag, dict):
            evl = dag.get(col_name)
            if isinstance(evl, list) and evl:
                dag_edges.append(f"{did}: {len(evl)} edge(s)")
    if dag_edges:
        with st.expander("Evidence DAG (per doc)"):
            for line in dag_edges[:12]:
                st.caption(line)

    if rows:
        df = pd.DataFrame(rows)
        if col_name in df.columns:
            default = col_def.get("default")
            non_default = df[col_name].apply(lambda v: value_counts_as_filled(v, default))
            fill_rate = non_default.sum() / max(len(df), 1)
            filled_n = non_default.sum()
            total_n = len(df)

            color = "#22c55e" if fill_rate > 0.7 else "#f59e0b" if fill_rate > 0.3 else "#ef4444"
            bar_w = max(4, int(fill_rate * 100))
            st.markdown(
                f"<div style='margin:8px 0'>"
                f"<div style='font-size:0.75rem;color:#64748b;margin-bottom:4px'>"
                f"Fill rate: <strong style='color:{color}'>{fill_rate:.0%}</strong> "
                f"({filled_n}/{total_n} rows)</div>"
                f"<div style='background:#e2e8f0;border-radius:4px;height:6px'>"
                f"<div style='width:{bar_w}%;height:6px;border-radius:4px;background:{color}'></div>"
                f"</div></div>",
                unsafe_allow_html=True,
            )

            # Evidence examples
            ev_col = f"{col_name}_evidence_quote"
            if ev_col in df.columns:
                samples = (
                    df[df[ev_col].notna() & (df[ev_col] != "") & (df[ev_col] != "—")]
                    [ev_col].dropna().head(3).tolist()
                )
                if samples:
                    st.markdown("**Evidence quotes:**")
                    for q in samples:
                        st.markdown(
                            f"<blockquote style='border-left:3px solid #6366f1;padding:6px 12px;"
                            f"font-size:0.82rem;color:#475569;margin:6px 0;border-radius:0 6px 6px 0;"
                            f"background:rgba(99,102,241,0.04)'>{q}</blockquote>",
                            unsafe_allow_html=True,
                        )


def render_field_strip(ws_state: DatasetState) -> None:
    """Render horizontal pill buttons for each extracted field.

    Clicking a field sets ws_focus_field in session state, which
    causes the inspector to open in the sidebar.
    """
    columns = ws_state.get("proposed_columns", [])
    if not columns:
        return

    focus = st.session_state.get("ws_focus_field", "")
    rows = ws_state.get("rows", [])
    df = pd.DataFrame(rows) if rows else pd.DataFrame()

    cols = st.columns(min(len(columns), 6))
    for i, col_def in enumerate(columns):
        name = col_def.get("name", "")
        col_type = col_def.get("type", "")
        with cols[i % len(cols)]:
            active = name == focus
            # Fill-rate indicator dot
            pct = 0.0
            indicator = ""
            if not df.empty and name in df.columns:
                default = col_def.get("default")
                filled = df[name].apply(
                    lambda v: value_counts_as_filled(v, default)
                ).sum()
                pct = filled / max(len(df), 1)
                indicator = "●" if pct > 0.6 else "◑" if pct > 0.2 else "○"
            pct_label = f" {pct:.0%}" if not df.empty and name in df.columns else ""
            label = f"{indicator} {name}{pct_label}" if indicator else name
            if st.button(
                label,
                key=f"field_btn_{name}",
                use_container_width=True,
                type="primary" if active else "secondary",
                help=f"Type: {col_type}  •  Fill rate: {pct:.0%}" if pct else f"Type: {col_type}",
            ):
                st.session_state["ws_focus_field"] = "" if active else name
                st.rerun()
