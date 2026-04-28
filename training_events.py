"""Append-only trajectory log for RLHF / PRM / DPO pipelines (see vault DOCUMENT_LIFECYCLE §4.7).

Canonical location: **ISF-PEECEE/prompt2dataset/training_events.py**.

Events are JSON lines. Path resolution prefers the corpus run root:

- When ``state["datasets_export_dir"]`` points at ``.../prompt2dataset/{corpus}/runs/{run_id}/datasets``,
  the log is **``.../runs/{run_id}/training_events.jsonl``** (sibling to ``datasets/``), matching
  ``library/pipeline-output/prompt2dataset/...`` layout from :class:`CorpusConfig`.
- Otherwise ``{feedback_base}/{run_id}/training_events.jsonl`` (or ``PROMPT2DATASET_FEEDBACK_DIR``).

Environment:

- ``TRAINING_EVENTS_DISABLE`` — if truthy (``1``, ``true``, ``yes``, ``on``), no file is written.
- ``PROMPT2DATASET_FEEDBACK_DIR`` — directory under which ``{run_id}/training_events.jsonl``
  is created when ``datasets_export_dir`` / custom path are unset. If unset, the host app may
  resolve via ``prompt2dataset.utils.config.get_settings()`` when importable; otherwise
  ``./output/feedback`` relative to the current working directory.
Host apps (``app.py``, ``scripts/*.py``) must put the ISF-PEECEE repo root on ``sys.path``
so ``import prompt2dataset`` resolves.

Multipass extraction (``extraction_multipass_blackboard``) appends additional ``llm_extract``
rows with ``state.extraction_phase`` set to ``"scout"`` or ``"synthesis"`` (see
:func:`log_llm_extract` ``extra_state``) so DPO/exports can filter by pass.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _disabled() -> bool:
    return os.environ.get("TRAINING_EVENTS_DISABLE", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _default_feedback_base() -> Path | None:
    override = (os.environ.get("PROMPT2DATASET_FEEDBACK_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    try:
        from prompt2dataset.utils.config import get_settings

        return get_settings().resolve("output/feedback")
    except Exception as exc:
        logger.debug("training_events: default feedback base fallback (no prompt2dataset): %s", exc)
    try:
        return (Path.cwd() / "output" / "feedback").resolve()
    except Exception:
        return None


def resolve_training_events_path(run_id: str, state: dict[str, Any] | None = None) -> Path | None:
    """Return the JSONL file path, or None if logging is disabled / no run_id."""
    if _disabled():
        return None
    rid = (run_id or "").strip()
    if not rid:
        return None
    st = state or {}
    custom = (st.get("training_events_path") or "").strip()
    if custom:
        return Path(custom).expanduser().resolve()

    dsd = (st.get("datasets_export_dir") or "").strip()
    if dsd:
        p = Path(dsd).expanduser().resolve()
        if p.name == "datasets":
            return p.parent / "training_events.jsonl"
        return p / "training_events.jsonl"

    base = _default_feedback_base()
    if base is None:
        return None
    return (base / rid / "training_events.jsonl").resolve()


def append_training_event(
    run_id: str,
    event: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
) -> None:
    """Append one event dict as a single JSON line. Never raises to callers."""
    try:
        path = resolve_training_events_path(run_id, state)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "run_id": run_id,
            "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            **event,
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("append_training_event failed: %s", exc)


def compute_schema_hash(proposed_columns: list[dict[str, Any]] | None) -> str:
    """MD5 of canonical JSON for ``proposed_columns`` — MDP scope key for DPO/RL joins."""
    cols = proposed_columns or []
    try:
        payload = json.dumps(cols, sort_keys=True, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        payload = "[]"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()[:12]


def trajectory_context_from_dataset_state(state: dict[str, Any] | None) -> dict[str, Any]:
    """Minimal snapshot for joining events (episode: run_id × doc_id × schema_hash)."""
    st = state or {}
    rid = (st.get("run_id") or st.get("feedback_run_id") or "").strip()
    cols = st.get("proposed_columns")
    sh = (st.get("schema_hash") or "").strip() if isinstance(st.get("schema_hash"), str) else ""
    if not sh:
        sh = compute_schema_hash(cols if isinstance(cols, list) else None)
    out = {
        "run_id": rid,
        "corpus_id": st.get("corpus_id", ""),
        "schema_iteration": int(st.get("schema_iteration", 0) or 0),
        "schema_hash": sh,
        "rework_count": int(st.get("rework_count", 0) or 0),
        "datasets_export_dir": st.get("datasets_export_dir", ""),
        "training_events_path": st.get("training_events_path", ""),
    }
    if isinstance(st.get("epistemic_blackboard"), dict):
        out["epistemic_blackboard"] = st["epistemic_blackboard"]
    return out


def merge_training_event_state(
    *parts: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge partial dicts for ``append_training_event(..., state=)``; later keys win."""
    out: dict[str, Any] = {}
    for p in parts:
        if not p:
            continue
        for k, v in p.items():
            if v is not None and v != "":
                out[k] = v
    if "proposed_columns" in out and "schema_hash" not in out:
        pc = out.get("proposed_columns")
        if isinstance(pc, list):
            out["schema_hash"] = compute_schema_hash(pc)
    return out


class TrainingEventLogger:
    """Thin facade over :func:`append_training_event` with consistent event_type names.

    All methods are best-effort (never raise); paths follow ``state``/``trajectory_context``.
    """

    def __init__(
        self,
        run_id: str,
        *,
        state: dict[str, Any] | None = None,
    ) -> None:
        self.run_id = (run_id or "").strip()
        self._state = state or {}

    def set_state(self, state: dict[str, Any] | None) -> None:
        if state is not None:
            self._state = state

    @property
    def state(self) -> dict[str, Any]:
        return self._state

    def _emit(
        self,
        event_type: str,
        state_payload: dict[str, Any] | None = None,
        action: dict[str, Any] | None = None,
        reward_signal: Any = None,
    ) -> None:
        if not self.run_id:
            return
        base = {"event_type": event_type}
        if state_payload is not None:
            base["state"] = state_payload
        if action is not None:
            base["action"] = action
        base["reward_signal"] = reward_signal
        append_training_event(self.run_id, base, state=self._state)

    def log_llm_extract(
        self,
        doc_id: str,
        *,
        llm_raw_output: str,
        retrieved_chunk_ids: list[str],
        retrieved_chunk_hashes: list[str] | None = None,
        system_prompt: str = "",
        user_prompt: str = "",
        schema_json: str | None = None,
        extra_state: dict[str, Any] | None = None,
    ) -> None:
        """Log one model completion. Use ``extra_state['extraction_phase']`` (``scout`` / ``synthesis``) in multipass runs.

        When ``system_prompt`` / ``user_prompt`` / ``schema_json`` are provided, they are stored
        in the event action (truncated) so :mod:`scripts.export_dpo_pairs` can emit TRL-ready prompts.
        """
        st = {
            "doc_id": doc_id,
            "retrieved_chunks": (retrieved_chunk_ids or [])[:64],
        }
        if retrieved_chunk_hashes:
            st["retrieved_chunk_hashes"] = (retrieved_chunk_hashes or [])[:64]
        if extra_state:
            st.update(extra_state)
        if "schema_hash" not in st:
            st["schema_hash"] = trajectory_context_from_dataset_state(self._state).get("schema_hash", "")
        tr = self._state.get("schema_iteration")
        st.setdefault("schema_iteration", int(tr or 0))
        _max_ctx = 96_000
        act: dict[str, Any] = {
            "llm_raw_output": (llm_raw_output or "")[:32000],
            "reasoning_trace": _maybe_thinking((llm_raw_output or "")),
        }
        if system_prompt:
            act["system_prompt"] = (system_prompt or "")[:_max_ctx]
        if user_prompt:
            act["user_prompt"] = (user_prompt or "")[:_max_ctx]
        if schema_json:
            act["schema_json"] = (schema_json or "")[:_max_ctx]
        self._emit(
            "llm_extract",
            state_payload=st,
            action=act,
        )

    def log_extraction_failed(
        self,
        doc_id: str,
        *,
        error: str,
        retrieved_chunk_ids: list[str],
        extra_state: dict[str, Any] | None = None,
    ) -> None:
        st: dict[str, Any] = {
            "doc_id": doc_id,
            "retrieved_chunks": (retrieved_chunk_ids or [])[:64],
            "schema_hash": trajectory_context_from_dataset_state(self._state).get("schema_hash", ""),
        }
        if extra_state:
            st.update(extra_state)
        self._emit("extraction_failed", state_payload=st, action={"error": (error or "")[:2000]})

    def log_human_override(
        self,
        doc_id: str,
        field_name: str,
        *,
        proposed_value: Any,
        override_value: Any,
        chunk_id: str | None = None,
        **extra_action: Any,
    ) -> None:
        st = {
            "doc_id": doc_id,
            "field_name": field_name,
            "schema_hash": trajectory_context_from_dataset_state(self._state).get("schema_hash", ""),
        }
        if chunk_id:
            st["chunk_id"] = str(chunk_id)
        act: dict[str, Any] = {
            "proposed_value": proposed_value,
            "override_value": override_value,
        }
        act.update({k: v for k, v in extra_action.items() if v is not None})
        self._emit("human_override", state_payload=st, action=act, reward_signal=None)

    def log_schema_update(
        self,
        *,
        schema_hash: str,
        proposed_columns: list[dict[str, Any]] | None = None,
        approved: bool | None = None,
        user_feedback: str = "",
    ) -> None:
        st: dict[str, Any] = {"schema_hash": schema_hash or compute_schema_hash(proposed_columns)}
        if proposed_columns is not None:
            st["column_count"] = len(proposed_columns)
        act: dict[str, Any] = {"schema_hash": st["schema_hash"]}
        if approved is not None:
            act["approved"] = approved
        if user_feedback:
            act["user_feedback"] = user_feedback[:8000]
        self._emit("schema_update", state_payload=st, action=act, reward_signal=(1.0 if approved else None))

    def log_chat_correction(
        self,
        user_text: str,
        assistant_text: str = "",
    ) -> None:
        st = {
            "schema_hash": trajectory_context_from_dataset_state(self._state).get("schema_hash", ""),
        }
        self._emit(
            "chat_correction",
            state_payload=st,
            action={"user_text": (user_text or "")[:8000], "assistant_text": (assistant_text or "")[:8000]},
        )


def _maybe_thinking(raw: str) -> str:
    import re

    for pat in (
        r"<thinking>(?P<tr>[\s\S]*?)</thinking>",
        r"<think>(?P<tr>[\s\S]*?)</think>",
    ):
        m = re.search(pat, raw, re.I)
        if m:
            return m.group("tr").strip()[:16000]
    return ""
