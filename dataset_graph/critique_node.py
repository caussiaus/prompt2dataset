"""Critique node: samples extraction rows and asks the LLM to assess quality.

Supports two call modes:
  critique_node(state)          — synchronous, returns updated state
  critique_node_stream(state)   — yields (token, final_state) for UI streaming
"""
from __future__ import annotations

import json
import logging
import random
import re
from typing import Any, Generator, List, Literal, Optional

import instructor
from openai import OpenAI
from pydantic import BaseModel, Field

from prompt2dataset.dataset_graph.critique_salvage import merge_critique_meta, salvage_critique_meta
from prompt2dataset.dataset_graph.state import DatasetState
from prompt2dataset.prompts.dataset_prompt import (
    CRITIQUE_SAMPLE_ROWS,
    CRITIQUE_SYSTEM_PROMPT,
    build_critique_user_prompt,
    context_budget,
)
from prompt2dataset.utils.config import get_settings
from prompt2dataset.utils.prompt2dataset_settings import load_prompt2dataset_config

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>|<redacted_thinking>.*?</redacted_thinking>", re.I | re.DOTALL)
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I | re.M)


def _robust_json(text: str) -> dict:
    """Parse the first JSON object in text using raw_decode — handles trailing content."""
    raw = _THINK_RE.sub("", text).strip()
    raw = _FENCE_RE.sub("", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(raw):
        if ch in ('{', '['):
            try:
                obj, _ = dec.raw_decode(raw, i)
                return obj if isinstance(obj, dict) else {}
            except json.JSONDecodeError:
                continue
    return {}


# ── Pydantic response model for instructor-structured critique output ─────────

class _FieldIssue(BaseModel):
    field: str
    issue: str = ""
    severity: Literal["high", "medium", "low"] = "medium"
    suggestion: str = ""
    suggested_call_config_delta: dict = Field(default_factory=dict)
    # e.g. {"retrieval_k": "+5", "temperature": 0.3, "include_adjacent_chunks": True}
    config_rationale: str = ""
    # e.g. "field had 68% evidenceless rate — wider retrieval and more temperature room needed"


class _CritiqueOut(BaseModel):
    overall_quality: Literal["good", "ok", "needs_work"] = "ok"
    field_issues: List[_FieldIssue] = Field(default_factory=list)
    overall_suggestion: str = ""

# Column prefixes to strip before sending rows to critique (keeps token count low)
_STRIP_SUFFIXES = ("_evidence_quote", "_evidence_pages", "_evidence_section", "_evidence")
_INTERNAL_COLS = frozenset({
    "filing_id", "ticker", "issuer_name", "profile_number",
    "doc_id", "entity_name", "entity_slug", "source_ref",
    "filing_date", "doc_date", "filing_type", "doc_type",
    "naics_sector", "context_category", "mechanism", "context_tag",
    "_extraction_error", "_all_chunks", "_keyword_hits",
    "_pass1_positive", "_evidence_blocks_used",
    "_flag_all_default", "_flag_evidenceless",
})


def _strip_row(row: dict) -> dict:
    """Remove identity + evidence columns before sending rows to critique LLM.

    Preserves a compact ``_row_note`` so the reviewer sees pipeline failures
    (e.g. vLLM connection errors), not just empty schema fields.
    """
    out = {}
    for k, v in row.items():
        if k in _INTERNAL_COLS:
            continue
        if any(k.endswith(suf) for suf in _STRIP_SUFFIXES):
            continue
        out[k] = v
    err = str(row.get("_extraction_error") or "").strip()
    if err:
        out["_row_note"] = f"extraction failed: {err[:220]}"
    elif row.get("_flag_all_default"):
        out["_row_note"] = (
            "all extracted fields still at schema default — often a failed or skipped LLM pass, "
            "not necessarily a bad schema definition"
        )
    return out


def _parse_json_block(text: str) -> dict[str, Any]:
    """Parse critique JSON from streamed text using robust raw_decode."""
    try:
        return _robust_json(text)
    except Exception:
        return {}


def _critique_meta_is_actionable(meta: dict[str, Any]) -> bool:
    """True only if the parsed object clearly follows the critique JSON schema.

    If the model returns a long prose gap analysis without ``overall_quality`` /
    ``field_issues``, :func:`_robust_json` may still return a random inner ``{}``
    or unrelated keys — we must not default quality to *ok* in those cases.
    """
    if not meta:
        return False
    if "overall_quality" in meta:
        return True
    fis = meta.get("field_issues")
    if isinstance(fis, list) and len(fis) > 0:
        return True
    return False


def _trim_raw_audit(text: str, limit: int = 80_000) -> str:
    t = text.strip()
    return t if len(t) <= limit else t[: limit - 20] + "\n… [truncated]"


def _build_critique_messages(state: DatasetState) -> list[dict]:
    rows = state.get("rows", [])
    columns = state.get("proposed_columns", [])
    dataset_name = state.get("dataset_name", "dataset")
    consistency_flags = state.get("consistency_flags") or {}

    sample = random.sample(rows, min(CRITIQUE_SAMPLE_ROWS, len(rows)))
    sample_clean = [_strip_row(r) for r in sample]

    user_prompt = build_critique_user_prompt(
        dataset_name,
        columns,
        sample_clean,
        consistency_flags=consistency_flags,
    )

    # Inject LiveState context block into system prompt
    context_prefix = _build_live_context(state)
    system_content = context_prefix + CRITIQUE_SYSTEM_PROMPT if context_prefix else CRITIQUE_SYSTEM_PROMPT
    system_content += (
        "\n\nFor fields with persistent failures, you may optionally set "
        "`suggested_call_config_delta` with keys like "
        "{\"retrieval_k\": \"+5\", \"temperature\": 0.2, \"include_adjacent_chunks\": true} "
        "and a brief `config_rationale`. These are shown to the user at Gate 3."
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_prompt},
    ]


def _build_live_context(state: DatasetState) -> str:
    """Produce a LiveState context block for the system prompt. Returns '' if empty."""
    try:
        from app_pages.thread_store import build_live_state, build_context_block
        live = build_live_state(dict(state))
        if live.fill_rates or live.active_flags or live.rework_count > 0:
            return build_context_block(live)
    except Exception:
        pass
    return ""


def _apply_critique_result(state: DatasetState, content: str) -> DatasetState:
    raw_audit = _trim_raw_audit(content)
    meta = _parse_json_block(content)
    salvage = salvage_critique_meta(content)
    if meta and salvage:
        meta = merge_critique_meta(meta, salvage)
    elif not _critique_meta_is_actionable(meta) and _critique_meta_is_actionable(salvage):
        meta = salvage

    if not raw_audit:
        return {
            **state,
            "critique_text": "Critique returned no content from the model.",
            "critique_suggestions": [],
            "critique_config_deltas": [],
            "critique_quality": "needs_work",
            "critique_parse_ok": False,
            "critique_llm_raw": "",
        }

    if not _critique_meta_is_actionable(meta):
        return {
            **state,
            "critique_text": raw_audit,
            "critique_suggestions": [],
            "critique_config_deltas": [],
            "critique_quality": "needs_work",
            "critique_parse_ok": False,
            "critique_llm_raw": raw_audit,
        }

    quality = str(meta.get("overall_quality", "ok")).lower()
    if quality not in ("good", "ok", "needs_work"):
        quality = "ok"

    # New structured field_issues list — each item: {field, issue, severity, suggestion}
    field_issues_raw = meta.get("field_issues", [])
    field_issues: list[dict] = []
    critique_config_deltas: list[dict] = []
    for item in (field_issues_raw if isinstance(field_issues_raw, list) else []):
        if isinstance(item, dict) and item.get("field"):
            field_issues.append({
                "field":      str(item.get("field", "")),
                "issue":      str(item.get("issue", "")),
                "severity":   str(item.get("severity", "medium")),
                "suggestion": str(item.get("suggestion", "")),
            })
            config_delta = item.get("suggested_call_config_delta") or {}
            if config_delta and isinstance(config_delta, dict):
                critique_config_deltas.append({
                    "field": str(item.get("field", "")),
                    "config_delta": config_delta,
                    "config_rationale": str(item.get("config_rationale", "")),
                })

    overall_suggestion = str(meta.get("overall_suggestion") or "").strip() or None

    # critique_text is the overall_suggestion + field count summary (no raw prose from LLM)
    if field_issues:
        summary_lines = [f"  [{i['severity'].upper()}] {i['field']}: {i['suggestion']}"
                         for i in field_issues]
        critique_text = (overall_suggestion or "") + "\n" + "\n".join(summary_lines)
    else:
        critique_text = overall_suggestion or "No issues detected."

    return {
        **state,
        "critique_text": critique_text,
        "critique_suggestions": field_issues,   # list[dict], not list[str]
        "critique_config_deltas": critique_config_deltas,
        "critique_quality": quality,
        "critique_parse_ok": True,
        "critique_llm_raw": raw_audit,
    }


def _state_from_structured(state: DatasetState, out: _CritiqueOut) -> DatasetState:
    """Build updated state from a validated instructor-parsed critique output."""
    field_issues = [
        {
            "field": fi.field,
            "issue": fi.issue,
            "severity": fi.severity,
            "suggestion": fi.suggestion,
        }
        for fi in out.field_issues
        if fi.field
    ]
    if field_issues:
        summary = (out.overall_suggestion or "") + "\n" + "\n".join(
            f"  [{i['severity'].upper()}] {i['field']}: {i['suggestion']}" for i in field_issues
        )
    else:
        summary = out.overall_suggestion or "No issues detected."

    # Extract per-field config deltas from field_issues
    critique_config_deltas = [
        {
            "field": fi.field,
            "config_delta": fi.suggested_call_config_delta,
            "config_rationale": fi.config_rationale,
        }
        for fi in out.field_issues
        if fi.suggested_call_config_delta
    ]

    return {
        **state,
        "critique_text": summary,
        "critique_suggestions": field_issues,
        "critique_config_deltas": critique_config_deltas,
        "critique_quality": out.overall_quality,
        "critique_parse_ok": True,
        "critique_llm_raw": _trim_raw_audit(out.model_dump_json()),
    }


def critique_node(state: DatasetState) -> DatasetState:
    """Sample up to CRITIQUE_SAMPLE_ROWS rows and ask the LLM for a quality critique.

    Synchronous version — uses instructor for structured Pydantic output with
    automatic retry. Falls back to streamed-text parsing on instructor error.

    When ``config/prompt2dataset.yaml`` sets ``critique.council_enabled: true``,
    runs parallel reviewers with distinct epistemic lenses plus a chairman merge
    (:mod:`prompt2dataset.dataset_graph.critique_council`).
    """
    rows = state.get("rows", [])
    if not rows:
        return {**state, "critique_text": "No rows extracted yet.", "critique_quality": "needs_work"}

    if load_prompt2dataset_config().critique_council_enabled:
        from prompt2dataset.dataset_graph import critique_council

        return critique_council.run_critique_with_council(state)

    cfg = get_settings()
    messages = _build_critique_messages(state)

    try:
        raw_client = OpenAI(
            base_url=cfg.vllm_base_url,
            api_key=cfg.vllm_api_key,
            timeout=float(cfg.vllm_timeout_sec),
        )
        client = instructor.from_openai(raw_client, mode=instructor.Mode.JSON)
        out: _CritiqueOut = client.chat.completions.create(
            model=cfg.vllm_model_name,
            messages=messages,
            response_model=_CritiqueOut,
            temperature=0.3,
            max_tokens=context_budget()["critique_max_out"],
            max_retries=3,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        return _state_from_structured(state, out)
    except Exception as exc:
        logger.error("critique_node LLM error: %s", exc)
        return {**state, "critique_text": f"Critique failed: {exc}", "critique_quality": "needs_work"}


def critique_node_stream(
    state: DatasetState,
) -> Generator[tuple[str, DatasetState | None], None, None]:
    """Streaming version of critique_node.

    Yields (token: str, None) for each streaming token, then finally
    yields ("", final_state) so the caller can update state.
    """
    rows = state.get("rows", [])
    if not rows:
        yield "", {**state, "critique_text": "No rows extracted yet.", "critique_quality": "needs_work"}
        return

    if load_prompt2dataset_config().critique_council_enabled:
        from prompt2dataset.dataset_graph import critique_council

        yield from critique_council.stream_critique_with_council(state)
        return

    cfg = get_settings()
    client = OpenAI(
        base_url=cfg.vllm_base_url,
        api_key=cfg.vllm_api_key,
        timeout=float(cfg.vllm_timeout_sec),
    )
    messages = _build_critique_messages(state)

    try:
        stream = client.chat.completions.create(
            model=cfg.vllm_model_name,
            messages=messages,
            temperature=0.3,
            max_tokens=context_budget()["critique_max_out"],
            stream=True,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        full_text = ""
        for chunk in stream:
            token = (chunk.choices[0].delta.content or "") if chunk.choices else ""
            if token:
                full_text += token
                yield token, None

        final_state = _apply_critique_result(state, full_text)
        yield "", final_state

    except Exception as exc:
        logger.error("critique_node_stream LLM error: %s", exc)
        yield "", {**state, "critique_text": f"Critique failed: {exc}", "critique_quality": "needs_work"}
