"""Thread persistence — each analysis run is a "thread" stored as JSON.

Threads live in output/threads/<thread_id>.json and hold all state needed
to resume a pipeline session: corpus info, chat history, schema, rows, log.

Also provides LiveState — a compact, read-only performance trace derived from
DatasetState that is injected into every LLM prompt as group-chat context.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_THREADS_DIR = _ROOT / "output" / "threads"

STATUS_COLORS = {
    "new":              "#7A6652",
    "ingesting":        "#E6C97A",
    "schema":           "#9DC8A0",
    "extracting":       "#E6C97A",
    "preview":          "#9DC8A0",
    "full_ingesting":   "#E6C97A",
    "full_extracting":  "#E6C97A",
    "done":             "#9DC8A0",
    "failed":           "#E88080",
}


@dataclass
class Thread:
    thread_id: str
    title: str
    created_at: str
    status: str       # new | ingesting | schema | extracting | preview | full_ingesting | full_extracting | done | failed
    docs_dir: str
    corpus_id: str
    corpus_name: str
    topic: str
    run_id: str = ""  # pipeline artifact isolation — see library DOCUMENT_LIFECYCLE.md
    trial_n: int = 7
    step: str = "new"
    schema_cols: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    chat: list = field(default_factory=list)
    log: list = field(default_factory=list)
    field_notes: dict = field(default_factory=dict)   # field_name → free-text note
    proc_done: bool = True
    proc_rc: int = 0
    dataset_path: str = ""
    error_msg: str = ""
    rework_count: int = 0
    eval_window_min: int = 6
    eval_window_max: int = 10
    max_rework_iterations: int = 3
    # Scope / acquisition tracking
    scope_spec: dict = field(default_factory=dict)        # ScopeSpec from scope_node
    acquisition_jobs: list = field(default_factory=list)  # list of acquisition job dicts

    @classmethod
    def create(cls, docs_dir: str, corpus_name: str, topic: str, trial_n: int = 7) -> "Thread":
        from prompt2dataset.corpus.config import _slugify
        tid = uuid.uuid4().hex[:10]
        cid = _slugify(corpus_name) or "corpus"
        title = (corpus_name or topic)[:42]
        return cls(
            thread_id=tid,
            title=title,
            created_at=datetime.now(timezone.utc).isoformat(),
            status="new",
            docs_dir=docs_dir,
            corpus_id=cid,
            corpus_name=corpus_name,
            topic=topic,
            trial_n=trial_n,
        )

    def add_log(self, line: str) -> None:
        self.log.append(line)

    def add_chat(self, role: str, content: str, **kwargs) -> None:
        """Append a chat message. Extra kwargs (card, columns, etc.) are stored alongside."""
        msg: dict = {"role": role, "content": content}
        msg.update(kwargs)
        self.chat.append(msg)

    def save(self) -> None:
        save_thread(self)

    @property
    def status_color(self) -> str:
        return STATUS_COLORS.get(self.status, "#7A6652")

    @property
    def age_label(self) -> str:
        try:
            dt = datetime.fromisoformat(self.created_at)
            delta = datetime.now(timezone.utc) - dt
            s = int(delta.total_seconds())
            if s < 60:
                return "just now"
            if s < 3600:
                return f"{s//60}m ago"
            if s < 86400:
                return f"{s//3600}h ago"
            return f"{s//86400}d ago"
        except Exception:
            return ""


def _dir() -> Path:
    _THREADS_DIR.mkdir(parents=True, exist_ok=True)
    return _THREADS_DIR


def save_thread(t: Thread) -> None:
    (_dir() / f"{t.thread_id}.json").write_text(
        json.dumps(asdict(t), indent=2, default=str), encoding="utf-8"
    )


def load_thread(thread_id: str) -> Thread | None:
    path = _dir() / f"{thread_id}.json"
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return Thread(**{k: d[k] for k in Thread.__dataclass_fields__ if k in d})
    except Exception:
        return None


def list_threads() -> list[Thread]:
    threads: list[Thread] = []
    for p in sorted(_dir().glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            threads.append(Thread(**{k: d[k] for k in Thread.__dataclass_fields__ if k in d}))
        except Exception:
            pass
    return threads


def delete_thread(thread_id: str) -> None:
    p = _dir() / f"{thread_id}.json"
    if p.exists():
        p.unlink()


# ---------------------------------------------------------------------------
# LiveState — compact read-only performance trace for LLM context injection
# ---------------------------------------------------------------------------

@dataclass
class LiveState:
    """Compact read-only snapshot of the pipeline's current performance.

    Derived from DatasetState + Thread. Never persisted independently —
    rebuilt on every mutation from the canonical sources.
    Injected at the top of every LLM prompt via build_context_block().
    """
    corpus_summary: str          # domain label, doc count, parsed count
    schema_snapshot: str         # column names + types
    fill_rates: dict             # {field: float} — per-field fill rate
    active_flags: dict           # {flag_name: count} e.g. evidenceless_count
    pending_action: str          # single string: what system recommends next
    rework_count: int = 0
    verified_extractions: list = field(default_factory=list)  # few-shot pool
    acquisition_jobs: list = field(default_factory=list)      # job statuses


def build_live_state(ws_state: dict, t: "Thread | None" = None) -> LiveState:
    """Derive LiveState from the current DatasetState and Thread.

    Called before every LLM node invocation.  Fast and deterministic.
    """
    # Corpus summary
    corpus_name = ws_state.get("dataset_name") or (t.corpus_name if t else "") or "corpus"
    corpus_topic = ws_state.get("corpus_topic", "")
    n_rows = len(ws_state.get("rows") or [])
    corpus_summary = f"Corpus: {corpus_name}"
    if corpus_topic:
        corpus_summary += f" | Topic: {corpus_topic[:80]}"
    if n_rows:
        corpus_summary += f" | {n_rows} rows extracted"

    # Schema snapshot
    columns = ws_state.get("proposed_columns") or []
    if columns:
        schema_snapshot = "Schema: " + ", ".join(
            f"{c.get('name')}({c.get('type','?')})" for c in columns[:10]
        )
        if len(columns) > 10:
            schema_snapshot += f" … +{len(columns)-10} more"
    else:
        schema_snapshot = "Schema: not yet defined"

    # Fill rates
    fill_rates: dict = {}
    if columns and (ws_state.get("rows") or []):
        from app_pages.table_render import value_counts_as_filled

        rows = ws_state["rows"]
        for col in columns:
            name = col.get("name", "")
            if not name:
                continue
            default = col.get("default")
            filled = sum(1 for r in rows if value_counts_as_filled(r.get(name), default))
            fill_rates[name] = round(filled / max(len(rows), 1), 3)

    # Active flags from consistency_flags
    flags = ws_state.get("consistency_flags") or {}
    active_flags: dict = {
        k: v for k, v in flags.items()
        if isinstance(v, int) and v > 0 and k != "total_rows"
    }

    # Pending action
    pending_action = _derive_pending_action(ws_state, n_rows)

    # Few-shot pool: extractions with evidence
    verified: list = []
    if columns and n_rows > 0:
        rows = ws_state.get("rows", [])
        for row in rows[:50]:  # scan first 50 rows only
            if not row.get("_extraction_error") and not row.get("_flag_all_default"):
                ev_count = sum(
                    1 for col in columns
                    if row.get(f"{col.get('name')}_evidence_quote")
                )
                if ev_count > 0:
                    verified.append(row)
            if len(verified) >= 5:
                break

    return LiveState(
        corpus_summary=corpus_summary,
        schema_snapshot=schema_snapshot,
        fill_rates=fill_rates,
        active_flags=active_flags,
        pending_action=pending_action,
        rework_count=ws_state.get("rework_count", 0),
        verified_extractions=verified,
        acquisition_jobs=(t.acquisition_jobs if t else []),
    )


def _derive_pending_action(ws_state: dict, n_rows: int) -> str:
    """Deterministic single-sentence description of what the pipeline should do next."""
    if not ws_state.get("proposed_columns"):
        return "Design the extraction schema based on the corpus topic."
    if not ws_state.get("schema_approved"):
        return "Review and approve the proposed schema before extraction begins."
    if n_rows == 0:
        return "Start extraction — schema is approved and documents are ready."
    flags = ws_state.get("consistency_flags") or {}
    ex_err = int(flags.get("extraction_error_count", 0))
    if n_rows and ex_err / n_rows >= 0.5:
        return (
            "Most rows failed extraction (see table `_extraction_error` / `_row_note` in critique). "
            "Fix vLLM connectivity, chunks, and parsing — your schema is unlikely the root cause."
        )
    flag_rate = (flags.get("all_default_count", 0) + flags.get("evidenceless_count", 0)) / max(n_rows, 1)
    if flag_rate > 0.4:
        if n_rows and ex_err / n_rows >= 0.25:
            return (
                f"Many rows have consistency flags ({flag_rate:.0%}), often alongside extraction errors — "
                "stabilize the LLM pass first, then reconsider schema tuning if fields stay empty."
            )
        return f"Quality issue: {flag_rate:.0%} of rows have consistency flags — consider schema refinement."
    if ws_state.get("critique_quality") == "needs_work":
        return "Critique found issues — review field verdicts, chat to refine schema, or re-run critique."
    if ws_state.get("schema_approved") and n_rows > 0 and not ws_state.get("critique_text"):
        return "Trial extract ready — quality critique runs automatically after extraction (or use Review actions)."
    if ws_state.get("critique_text") and ws_state.get("schema_approved") and n_rows > 0:
        return "Sample reviewed — iterate in chat, re-run critique, re-extract trial, full corpus, or export."
    return "Pipeline running — no immediate action required."


# ── DatasetContext ─────────────────────────────────────────────────────────────

import logging
from dataclasses import dataclass as _dataclass, field as dc_field
from typing import Literal

_ctx_logger = logging.getLogger(__name__)


@_dataclass
class TableMutation:
    """A typed user action on the dataset table."""
    mutation_type: Literal[
        "annotate_cell",
        "override_value",
        "flag_row",
        "approve_row",
        "add_column",
        "adjust_instruction",
    ]
    doc_id: str | None
    field_name: str | None
    value: Any
    reason: str | None
    timestamp: str  # ISO 8601


@_dataclass
class DatasetContext:
    """Full serializable corpus state — written to disk on every mutation.

    This is the authoritative source of truth for resuming after a crash
    or session end. Never stored in LangGraph state directly — too large.
    `LiveState` is derived from this on every render.
    """
    thread_id: str
    corpus_id: str
    domain_label: str
    identity_fields: list[str] = dc_field(default_factory=list)
    proposed_columns: list[dict] = dc_field(default_factory=list)
    schema_version: int = 1
    rows: list[dict] = dc_field(default_factory=list)
    cells: list[dict] = dc_field(default_factory=list)
    user_annotations: list[TableMutation] = dc_field(default_factory=list)
    chat_history: list[dict] = dc_field(default_factory=list)
    schema_approved: bool = False
    extraction_done: bool = False
    export_path: str | None = None
    rework_count: int = 0
    last_error: str | None = None
    extraction_call_config: dict = dc_field(default_factory=dict)
    critique_config_deltas: list[dict] = dc_field(default_factory=list)
    run_id: str = ""
    # For training_events path + MDP joins (with proposed_columns, run_id)
    datasets_export_dir: str = ""
    epistemic_blackboard: dict = dc_field(default_factory=dict)
    wonder_queue_preview: list = dc_field(default_factory=list)
    created_at: str = dc_field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = dc_field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


_CONTEXT_DIR = Path(__file__).resolve().parents[1] / "output" / "threads"


def context_path(thread_id: str) -> Path:
    """Return the path for a DatasetContext JSON file."""
    _CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    return _CONTEXT_DIR / f"{thread_id}_context.json"


def save_context(ctx: DatasetContext) -> None:
    """Write DatasetContext to disk as JSON. Never raises — logs on failure."""
    ctx.updated_at = datetime.now(timezone.utc).isoformat()
    try:
        p = context_path(ctx.thread_id)
        raw = {
            k: (
                [vars(m) for m in v] if k == "user_annotations" else v
            )
            for k, v in vars(ctx).items()
        }
        p.write_text(json.dumps(raw, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        _ctx_logger.error("save_context failed: %s", exc)


def load_context(thread_id: str) -> DatasetContext | None:
    """Load DatasetContext from disk. Returns None if not found."""
    p = context_path(thread_id)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        mutations = [TableMutation(**m) for m in raw.pop("user_annotations", [])]
        ctx = DatasetContext(**raw)
        ctx.user_annotations = mutations
        return ctx
    except Exception:
        return None


def context_from_state(thread_id: str, ws_state: dict, corpus_id: str = "") -> DatasetContext:
    """Build a DatasetContext from a DatasetState dict (ws_state).

    Used to create/refresh the context from the current pipeline state.
    """
    return DatasetContext(
        thread_id=thread_id,
        corpus_id=corpus_id or ws_state.get("corpus_topic", ""),
        domain_label=ws_state.get("corpus_topic", ws_state.get("dataset_name", "")),
        identity_fields=ws_state.get("identity_fields", []),
        proposed_columns=ws_state.get("proposed_columns", []),
        schema_version=int(ws_state.get("schema_iteration") or 1),
        rows=ws_state.get("rows", []),
        schema_approved=ws_state.get("schema_approved", False),
        extraction_done=ws_state.get("extraction_done", False),
        rework_count=ws_state.get("rework_count", 0),
        extraction_call_config=ws_state.get("extraction_call_config", {}),
        critique_config_deltas=ws_state.get("critique_config_deltas", []),
        last_error=ws_state.get("error"),
        run_id=str(ws_state.get("run_id") or ws_state.get("feedback_run_id") or ""),
        datasets_export_dir=str(ws_state.get("datasets_export_dir") or ""),
        epistemic_blackboard=ws_state.get("epistemic_blackboard") or {},
        wonder_queue_preview=list(ws_state.get("wonder_queue_preview") or []),
    )


def build_context_block(live_state: LiveState) -> str:
    """Produce a compact context header for LLM prompt injection.

    This string is prepended to every LLM system prompt so the model
    always knows the current pipeline state without needing chat history.
    Keep it under 400 tokens.
    """
    lines = [
        "## Current Dataset State",
        live_state.corpus_summary,
        live_state.schema_snapshot,
    ]

    if live_state.fill_rates:
        low = {k: v for k, v in live_state.fill_rates.items() if v < 0.55}
        if low:
            low_str = ", ".join(f"{k}={v:.0%}" for k, v in sorted(low.items(), key=lambda x: x[1])[:5])
            lines.append(f"Low fill rates: {low_str}")
        else:
            avg = sum(live_state.fill_rates.values()) / len(live_state.fill_rates)
            lines.append(f"Avg fill rate: {avg:.0%} across {len(live_state.fill_rates)} fields")

    if live_state.active_flags:
        flag_str = ", ".join(f"{k}={v}" for k, v in live_state.active_flags.items())
        lines.append(f"Quality flags: {flag_str}")

    if live_state.rework_count > 0:
        lines.append(f"Rework cycle: {live_state.rework_count} of 3")

    lines.append(f"Next action: {live_state.pending_action}")
    lines.append("---")

    return "\n".join(lines) + "\n"


# ── Session context management ─────────────────────────────────────────────────

MAX_CONTEXT_MESSAGES = 50
CONTEXT_SUMMARY_TRIGGER = 40
ALWAYS_KEEP_LAST_N = 10


def summarize_chat_history(
    messages: list[dict],
    *,
    max_messages: int = MAX_CONTEXT_MESSAGES,
    summary_trigger: int = CONTEXT_SUMMARY_TRIGGER,
    keep_last_n: int = ALWAYS_KEEP_LAST_N,
) -> list[dict]:
    """Trim chat history when it exceeds summary_trigger messages.

    Strategy:
    1. Keep the most recent `keep_last_n` messages intact.
    2. Summarize older messages into a single [system] summary message.
    3. LiveState is always injected fresh — it does NOT need to be in chat history.

    Returns the trimmed message list (never raises).
    """
    if len(messages) <= summary_trigger:
        return messages

    older = messages[:-keep_last_n]
    recent = messages[-keep_last_n:]

    turns = []
    for m in older:
        role = m.get("role", "?")
        content = str(m.get("content", ""))[:100]
        turns.append(f"{role}: {content}")

    summary_text = (
        f"[Session summary — {len(older)} earlier messages]\n"
        + "\n".join(turns[:20])
        + (f"\n... ({len(older) - 20} more)" if len(older) > 20 else "")
    )

    summary_msg = {"role": "system", "content": summary_text}
    return [summary_msg] + recent


def restore_checkpoint_state(thread_id: str) -> dict | None:
    """Attempt to restore DatasetState from SqliteSaver checkpoint.

    Returns the latest checkpoint state dict for `thread_id`, or None
    if no checkpoint exists or restoration fails.
    """
    logger = logging.getLogger(__name__)
    try:
        from prompt2dataset.dataset_graph.graph import build_dataset_graph
        graph = build_dataset_graph()
        config = {"configurable": {"thread_id": thread_id}}
        state = graph.get_state(config)
        if state and state.values:
            logger.info("restore_checkpoint_state: restored state for thread %s", thread_id)
            return dict(state.values)
    except Exception as exc:
        logger.debug("restore_checkpoint_state failed: %s", exc)
    return None
