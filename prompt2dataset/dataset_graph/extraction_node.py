"""Targeted extraction node.

Supports two modes of operation:

  design (sample) mode  — run on a small subset of documents chosen by the user
                          so they can validate field definitions before committing
                          to a full-corpus run. Uses the interactive vLLM profile.

  full-corpus mode      — run on all documents. Uses the batch vLLM profile.

Each extracted row carries per-field evidence spans (quote + chunk_id + page) so
every cell can answer: which row is this, what evidence supports it, who overrode it.

Per PDF, extraction is **one or more isolated LLM requests** (single-pass, or
when ``extraction_multipass_blackboard`` is enabled: Scout → optional targeted
retrieval → Synthesis). No cross-PDF context or chat transcript. A full dataset
run is N such document pipelines in parallel (asyncio), one “conversation” per filing.

Variable naming: all names are generic (doc_id, doc_meta, entity_name, etc.).
SEDAR-specific column names (filing_id, ticker, issuer_name, ...) are handled
via CorpusConfig.identity_fields — they pass through unchanged from the index CSV.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import os
import hashlib
import json
import logging
import re
from typing import Any

import orjson
import pandas as pd

from prompt2dataset.dataset_graph.state import (
    CellRecord,
    DatasetState,
    EvidenceSpan,
    SchemaColumn,
    SEDAR_IDENTITY_FIELDS,
    validate_extraction_row,
)
from prompt2dataset.prompts.dataset_prompt import (
    CONTEXT_BUDGET,
    EXTRACTION_MAX_EVIDENCE_BLOCKS,
    EXTRACTION_EVIDENCE_BLOCK_CHARS,
    SCOUT_SYSTEM_PROMPT,
    build_dynamic_json_schema,
    build_extraction_user_prompt,
    build_multipass_synthesis_user_prompt,
    build_scout_json_schema,
    build_scout_user_prompt,
    extraction_output_token_budget,
    extraction_system_prompt,
)
from prompt2dataset.utils.call_config import effective_temperature
from prompt2dataset.utils.config import get_settings
from prompt2dataset.utils.retrieval import (
    merge_evidence_block_lists,
    retrieve_evidence_blocks,
    retrieve_refinement_blocks,
    semantic_query_string,
)
from prompt2dataset.utils.vllm_router import get_profile, make_async_client, profile_for_workload
from prompt2dataset.utils.prompt2dataset_settings import load_prompt2dataset_config
from prompt2dataset.dataset_graph.training_events import (
    TrainingEventLogger,
    trajectory_context_from_dataset_state,
)

logger = logging.getLogger(__name__)


def _default_for_schema_type(typ: str, *, required: bool) -> Any:
    t = (typ or "string").lower()
    if t == "boolean":
        return False
    if t in ("integer", "int", "float", "number", "double"):
        return None if not required else 0
    return "" if required else None


def _extraction_schema_list_to_columns(items: list[Any]) -> list[SchemaColumn]:
    """Shape ``extraction_schema`` entries like :func:`schema_to_proposed_columns` in run scripts."""
    cols: list[SchemaColumn] = []
    for c in items:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name", "")).strip()
        if not name:
            continue
        typ = str(c.get("type", "string")).strip()
        desc = str(c.get("description", "")).strip()
        if c.get("unit"):
            desc = f"{desc} (unit: {c['unit']})".strip()
        if c.get("enum"):
            desc = f"{desc} Allowed values: {c['enum']}".strip()
        req = bool(c.get("required"))
        ins = str(c.get("extraction_instruction") or "").strip()
        if not ins:
            ins = desc or f"Extract {name} from the document."
        default_val = c.get("default") if "default" in c else _default_for_schema_type(typ, required=req)
        cols.append(
            {
                "name": name,
                "type": typ,
                "description": desc,
                "extraction_instruction": ins,
                "keywords": [w for w in (name.replace("_", " "),) if w],
                "default": default_val,
                "mode": str(c.get("mode") or "direct"),
            }
        )
    return cols


def resolve_extraction_schema_columns(state: DatasetState) -> list[SchemaColumn]:
    """Use ``proposed_columns`` when present; otherwise build columns from ``extraction_schema``."""
    pc = state.get("proposed_columns")
    if isinstance(pc, list) and len(pc) > 0:
        return list(pc)
    ext = state.get("extraction_schema")
    if isinstance(ext, list) and ext:
        return _extraction_schema_list_to_columns(ext)
    return []


def _log_debug_parsed_extraction(doc_key: str, data: dict[str, Any], *, phase: str) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return
    try:
        blob = json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        blob = str(data)
    maxlen = 12_000
    if len(blob) > maxlen:
        blob = blob[:maxlen] + "…(truncated)"
    logger.debug("extraction parsed JSON (%s) doc=%s: %s", phase, doc_key, blob)


def _cap_requested_max_tokens(
    requested: int,
    *,
    profile: Any,
    cfg: Any,
    phase: str = "extraction",
    n_cols: int = 0,
) -> int:
    """Clamp completion ``max_tokens`` to profile and :class:`Settings` limits.

    Schema-driven budgets can exceed a small model's completion ceiling; vLLM
    then returns 400. Keep ``VLLM_MAX_TOKENS`` and ``VLLM_INTERACTIVE_MAX_TOKENS``
    at or below the served model's maximum completion tokens.
    """
    _ = phase, n_cols
    try:
        r = max(1, int(requested))
    except (TypeError, ValueError):
        r = 1
    try:
        p_cap = int(getattr(profile, "max_tokens", r))
    except (TypeError, ValueError):
        p_cap = r
    try:
        c_cap = int(getattr(cfg, "vllm_max_tokens", r))
    except (TypeError, ValueError):
        c_cap = r
    return max(1, min(r, p_cap, c_cap))


def _prompt_token_estimate(text: str) -> int:
    """Conservative token estimate vs. BPE tokenizers (English + numeric PDF text)."""
    from prompt2dataset.utils.chunking import estimate_tokens

    # ``len//3`` tracks byte-pair-ish density better than word-count for ESG tables.
    return max(estimate_tokens(text), (len(text) + 2) // 3)


def _compact_columns_for_prompt(
    columns: list[SchemaColumn], *, max_desc_chars: int, max_instr_chars: int
) -> list[SchemaColumn]:
    """Shorten schema narrative so tiny-context models can still see all field names."""
    out: list[SchemaColumn] = []
    for c in columns:
        d = str(c.get("description", "")).strip()
        ins = str(c.get("extraction_instruction", "") or d).strip()
        if len(d) > max_desc_chars:
            d = d[: max_desc_chars - 3] + "..."
        if len(ins) > max_instr_chars:
            ins = ins[: max_instr_chars - 3] + "..."
        nc = dict(c)
        nc["description"] = d
        nc["extraction_instruction"] = ins
        out.append(nc)  # type: ignore[arg-type]
    return out


def _guided_schema_token_budget(schema: dict[str, Any] | None) -> int:
    if not schema:
        return 0
    try:
        return _prompt_token_estimate(json.dumps(schema, ensure_ascii=False, default=str))
    except Exception:
        return 1536


def build_extraction_guided_schema(
    columns: list[SchemaColumn],
    cfg: Any,
    *,
    with_evidence_chains: bool,
) -> dict[str, Any]:
    """Build vLLM ``guided_json`` that fits beside chat text in the configured context window.

    Full schemas with companion ``*_evidence`` objects can exceed a 4k/8k **served**
    ``--max-model-len`` by themselves (tokens counted differently from chat text alone).
    When that happens, shrink to value-only guided JSON — the user prompt contract still asks
    for per-field provenance keys.
    """
    ctx = max(512, int(getattr(cfg, "vllm_model_max_context_tokens", 8192)))
    full = build_dynamic_json_schema(
        columns,
        with_evidence=True,
        with_evidence_chains=with_evidence_chains,
    )
    full_est = _guided_schema_token_budget(full)
    allowance = max(640, int(ctx * 0.38))
    if full_est <= allowance:
        return full
    thin = build_dynamic_json_schema(
        columns,
        with_evidence=False,
        with_evidence_chains=False,
    )
    thin_est = _guided_schema_token_budget(thin)
    logger.warning(
        "extraction: compact guided_json (value fields only): context_window=%s est_full_guided≈%s tok "
        "est_compact≈%s tok — still emit per-field *_evidence objects when instructed.",
        ctx,
        full_est,
        thin_est,
    )
    if thin_est > max(384, ctx // 5):
        logger.warning(
            "extraction: compact guided_json still large (~%s tok) vs context=%s — widen "
            "vLLM ``--max-model-len`` and Settings.VLLM_MODEL_MAX_CONTEXT_TOKENS for best fidelity.",
            thin_est,
            ctx,
        )
    return thin


def _extraction_user_prompt_budget_tokens(
    cfg: Any,
    system_prompt: str,
    max_out: int,
    *,
    extra_reserved_tokens: int = 0,
) -> int:
    """Tokens available for the extraction user message (rough lower bound)."""
    ctx = int(cfg.vllm_model_max_context_tokens)
    # Assume a completion budget when sizing the user message; actual max_out is reclamped
    # after the user text is fixed. On narrow served windows, do not starve the evidence+
    # schema copy: reserve a smaller completion slice here and expand max_out only if room remains.
    completion_assumed = min(int(max_out), max(384, ctx // 3))
    if ctx <= 6144:
        tight_cap = max(256, ctx // 5)
        completion_assumed = min(completion_assumed, tight_cap)
    overhead = _prompt_token_estimate(system_prompt) + completion_assumed + 512
    slack = max(512, int(ctx * 0.10))
    xr = max(0, int(extra_reserved_tokens))
    return max(128, ctx - overhead - slack - xr)


def _fit_extraction_user_prompt_for_context(
    *,
    columns: list[SchemaColumn],
    doc_meta: dict[str, Any],
    evidence_blocks: list[dict[str, Any]],
    all_chunks: int,
    keyword_hits: int,
    pass1_pos: int,
    extraction_mode: str,
    corpus_topic: str,
    row_granularity: str,
    schema_mapping_summary: str,
    extra_sections: str,
    prompt_tail: str,
    cfg: Any,
    system_prompt: str,
    max_out: int,
    extra_reserved_tokens: int = 0,
) -> str:
    """Shrink ranked evidence until user + system + completion fits model context."""
    from prompt2dataset.prompts.dataset_prompt import (
        EXTRACTION_EVIDENCE_BLOCK_CHARS,
        EXTRACTION_MAX_EVIDENCE_BLOCKS,
        build_extraction_user_prompt,
    )

    budget = _extraction_user_prompt_budget_tokens(
        cfg,
        system_prompt,
        max_out,
        extra_reserved_tokens=extra_reserved_tokens,
    )
    char_tiers = (
        EXTRACTION_EVIDENCE_BLOCK_CHARS,
        500,
        400,
        300,
        250,
        200,
        160,
        120,
    )
    # Widen schema text last: trim per-field instructions before dropping evidence further.
    ctx_cap = int(cfg.vllm_model_max_context_tokens)
    wide_schema = len(columns) >= 22
    if ctx_cap <= 8192 or wide_schema:
        # Full-width field cards blow the user budget on 4k–8k contexts; start from tight copy.
        desc_loop: tuple[tuple[Any, Any], ...] = (
            (160, 190),
            (120, 150),
            (80, 100),
            (50, 70),
            (40, 55),
        )
    else:
        desc_loop = (
            (None, None),
            (220, 280),
            (160, 200),
            (120, 150),
            (80, 100),
            (50, 70),
        )

    for max_desc, max_instr in desc_loop:
        cols_use: list[SchemaColumn] = columns
        if max_desc is not None:
            cols_use = _compact_columns_for_prompt(
                columns, max_desc_chars=max_desc, max_instr_chars=max_instr or max_desc
            )
        for nb in range(EXTRACTION_MAX_EVIDENCE_BLOCKS, 0, -1):
            for ch in char_tiers:
                ch_use = max(120, min(int(ch), EXTRACTION_EVIDENCE_BLOCK_CHARS))
                up = build_extraction_user_prompt(
                    columns=cols_use,
                    doc_meta=doc_meta,
                    evidence_blocks=evidence_blocks,
                    all_chunks_count=all_chunks,
                    keyword_hit_count=keyword_hits,
                    pass1_positive_count=pass1_pos,
                    extraction_mode=extraction_mode,
                    corpus_topic=corpus_topic,
                    row_granularity=row_granularity,
                    schema_mapping_summary=schema_mapping_summary,
                    extra_sections=extra_sections,
                    evidence_max_blocks=nb,
                    evidence_block_chars=ch_use,
                )
                composite = up + prompt_tail
                if _prompt_token_estimate(composite) <= budget:
                    if (
                        nb < EXTRACTION_MAX_EVIDENCE_BLOCKS
                        or ch_use < EXTRACTION_EVIDENCE_BLOCK_CHARS
                        or max_desc is not None
                    ):
                        logger.warning(
                            "extraction: tightened packing (schema_max_desc=%s) %d blocks × %d chars "
                            "(~%d tok user+tail vs budget %d; context=%d)",
                            max_desc,
                            nb,
                            ch_use,
                            _prompt_token_estimate(composite),
                            budget,
                            cfg.vllm_model_max_context_tokens,
                        )
                    return composite
    logger.warning(
        "extraction: user prompt may exceed context (budget=%d context=%d); using minimal slice",
        budget,
        cfg.vllm_model_max_context_tokens,
    )
    up = build_extraction_user_prompt(
        columns=_compact_columns_for_prompt(columns, max_desc_chars=50, max_instr_chars=70),
        doc_meta=doc_meta,
        evidence_blocks=evidence_blocks,
        all_chunks_count=all_chunks,
        keyword_hit_count=keyword_hits,
        pass1_positive_count=pass1_pos,
        extraction_mode=extraction_mode,
        corpus_topic=corpus_topic,
        row_granularity=row_granularity,
        schema_mapping_summary=schema_mapping_summary,
        extra_sections=extra_sections,
        evidence_max_blocks=1,
        evidence_block_chars=120,
    )
    return up + prompt_tail


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I | re.M)
# Strip <thinking> / <think> before JSON (CoT prompts; model variants)
_THINK_RE = re.compile(
    r"\x3Cthink\x3E[\s\S]*?\x3C/think\x3E"
    r"|\x3Cthink\x3E[\s\S]*?\x3C/think\x3E"
    r"|\x3Credacted_thinking\x3E[\s\S]*?\x3C/redacted_thinking\x3E",
    re.I,
)


def _strip(s: str) -> str:
    s = _THINK_RE.sub("", s).strip()
    return _FENCE_RE.sub("", s).strip()


def _parse_json(content: str) -> dict[str, Any]:
    """Robust JSON extraction from LLM output.

    Uses raw_decode to find and parse the first valid JSON object regardless
    of surrounding text or trailing content. Falls back to orjson for the
    full-string case (handles BOM, whitespace differences).
    """
    raw = _strip(content)
    # Fast path: try the whole string first
    try:
        return orjson.loads(raw)
    except Exception:
        pass
    # raw_decode: walks forward to find the first '{' or '[' and parses from there
    dec = json.JSONDecoder()
    for i, ch in enumerate(raw):
        if ch in ('{', '['):
            try:
                obj, _ = dec.raw_decode(raw, i)
                return obj if isinstance(obj, dict) else {}
            except json.JSONDecodeError:
                continue
    raise ValueError(f"No JSON object found in LLM output (first 200 chars): {raw[:200]!r}")


def _null_evidence() -> dict[str, Any]:
    return {"quote": None, "chunk_id": None, "page_start": None, "page_end": None, "section_path": None}


def _normalize_extraction_payload(
    data: dict[str, Any],
    columns: list[SchemaColumn],
) -> dict[str, Any]:
    """Merge flat *_evidence_* keys into nested ``{field}_evidence`` objects.

    Some models emit ``field_evidence_quote`` at the top level instead of
    ``field_evidence: {quote: ...}``, which previously dropped evidence and
    could confuse validation.
    """
    if not data or not isinstance(data, dict):
        return data
    out = dict(data)
    for col in columns:
        name = col.get("name")
        if not name:
            continue
        ev_key = f"{name}_evidence"
        existing = out.get(ev_key)
        if isinstance(existing, dict) and existing:
            continue
        q = out.get(f"{name}_evidence_quote")
        cid = out.get(f"{name}_chunk_id")
        sec = out.get(f"{name}_evidence_section")
        pages_raw = out.get(f"{name}_evidence_pages")
        p0 = out.get(f"{name}_page_start")
        p1 = out.get(f"{name}_page_end")
        if p0 is None and isinstance(pages_raw, str) and "-" in pages_raw:
            parts = pages_raw.split("-")
            try:
                p0 = int(parts[0].strip())
                p1 = int(parts[1].strip()) if len(parts) > 1 else p0
            except (ValueError, IndexError):
                pass
        if any(x is not None for x in (q, cid, sec, p0, p1, pages_raw)):
            out[ev_key] = {
                "quote": q,
                "chunk_id": str(cid) if cid is not None else None,
                "page_start": p0 if p0 is not None else None,
                "page_end": p1 if p1 is not None else None,
                "section_path": sec,
            }
    return out


def _default_row(
    doc_meta: dict[str, Any],
    columns: list[SchemaColumn],
    identity_fields: list[str] | None = None,
    *,
    error: str = "",
) -> dict[str, Any]:
    """Build a default row carrying all identity fields from doc_meta.

    identity_fields is the ordered list of column names to carry through
    (from CorpusConfig.identity_fields or SEDAR_IDENTITY_FIELDS fallback).
    Any column not present in doc_meta gets an empty string.
    """
    fields = identity_fields or SEDAR_IDENTITY_FIELDS
    row: dict[str, Any] = {f: doc_meta.get(f, "") for f in fields}
    row["_extraction_error"] = error

    for col in columns:
        row[col["name"]] = col.get("default")
        row[f"{col['name']}_evidence_quote"] = None
        row[f"{col['name']}_evidence_pages"] = None
        row[f"{col['name']}_evidence_section"] = None
    return row


def _cells_from_row(
    row: dict[str, Any],
    columns: list[SchemaColumn],
    identity_fields: list[str] | None = None,
) -> list[CellRecord]:
    """Convert a flat row dict into structured CellRecord objects."""
    cells: list[CellRecord] = []
    # Use first identity field as the row anchor
    fields = identity_fields or SEDAR_IDENTITY_FIELDS
    row_id = str(row.get(fields[0], "")) if fields else ""

    by_field_chain: dict[str, Any] = {}
    chains_raw = row.get("_evidence_chains")
    if isinstance(chains_raw, str) and chains_raw.strip():
        try:
            arr = json.loads(chains_raw)
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, dict) and item.get("field_name"):
                        by_field_chain[str(item["field_name"])] = item
        except json.JSONDecodeError:
            pass

    for col in columns:
        ev_q = row.get(f"{col['name']}_evidence_quote")
        ev_p = row.get(f"{col['name']}_evidence_pages", "")
        ev_s = row.get(f"{col['name']}_evidence_section")
        p0, p1 = 0, 0
        if ev_p and ev_p != "None":
            parts = str(ev_p).split("-")
            try:
                p0 = int(parts[0])
                p1 = int(parts[1]) if len(parts) > 1 else p0
            except (ValueError, IndexError):
                pass

        field_val = row.get(col["name"])
        default_val = col.get("default")
        # Consistency flags
        flag_evidenceless = bool(
            field_val is not None and field_val != default_val and not ev_q
        )

        cid_cell = row.get(f"{col['name']}_chunk_id")
        evidence: EvidenceSpan = {
            "quote": ev_q,
            "chunk_id": str(cid_cell).strip() if cid_cell else None,
            "page_start": p0 or None,
            "page_end": p1 or None,
            "section_path": ev_s,
            "relevance": "direct" if ev_q else "indirect",
        }
        cr: CellRecord = CellRecord(
            row_id=row_id,
            field_name=col["name"],
            proposed_value=field_val,
            evidence=evidence if ev_q else None,
            decision="proposed",
            flag_all_default=False,  # set by run_consistency_check
            flag_evidenceless=flag_evidenceless,
        )
        ec = by_field_chain.get(col["name"])
        if ec:
            cr["evidence_chain"] = ec  # type: ignore[typeddict-item]
        cells.append(cr)
    return cells


def rebuild_cells_from_rows(
    rows: list[dict[str, Any]],
    columns: list[SchemaColumn],
    identity_fields: list[str] | None = None,
) -> list[CellRecord]:
    """Flatten ``rows`` into ``CellRecord`` list (same shape as ``extraction_node`` output)."""
    fields = identity_fields or SEDAR_IDENTITY_FIELDS
    cells: list[CellRecord] = []
    for row in rows:
        cells.extend(_cells_from_row(row, columns, fields))
    return cells


# ── NLI cell verification ─────────────────────────────────────────────────────

_nli_model = None
_nli_attempted = False
_NLI_MODEL_NAME = "cross-encoder/nli-MiniLM2-L6-H768"
_NLI_THRESHOLD = 0.65   # entailment score threshold for verification


def _get_nli_model():
    """Lazy-load the NLI cross-encoder. Returns None if unavailable."""
    global _nli_model, _nli_attempted
    if _nli_attempted:
        return _nli_model
    _nli_attempted = True
    try:
        from sentence_transformers import CrossEncoder
        _nli_model = CrossEncoder(_NLI_MODEL_NAME)
        logger.info("NLI model loaded: %s", _NLI_MODEL_NAME)
    except Exception as exc:
        logger.warning("NLI model not available (%s) — skipping cell verification", exc)
        _nli_model = None
    return _nli_model


def verify_quote_in_chunk(
    quote: str,
    chunk_text: str,
) -> tuple[bool, float]:
    """Verify that ``quote`` is entailed by ``chunk_text`` using NLI.

    Uses cross-encoder/nli-MiniLM2-L6-H768. Returns (is_verified, entailment_score).

    - is_verified: True if entailment_score >= _NLI_THRESHOLD
    - entailment_score: float [0, 1]; 0.0 if model unavailable or empty inputs

    Falls back gracefully: if the model is not available or inference fails,
    returns (False, 0.0) and logs a debug message.
    """
    if not quote or not chunk_text:
        return False, 0.0

    model = _get_nli_model()
    if model is None:
        return False, 0.0

    try:
        # NLI: premise=chunk_text, hypothesis=quote
        score = model.predict([(chunk_text[:1024], quote[:256])])
        if hasattr(score, "__iter__"):
            score = float(list(score)[0])
        else:
            score = float(score)
        score = max(0.0, min(1.0, score))
        return score >= _NLI_THRESHOLD, score
    except Exception as exc:
        logger.debug("verify_quote_in_chunk failed: %s", exc)
        return False, 0.0


def run_consistency_check(
    rows: list[dict[str, Any]],
    columns: list[SchemaColumn],
    identity_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Scan extracted rows for quality issues.

    Returns a flags dict with counts used by critique_node and the UI.
    Adds _flag_all_default and _flag_evidenceless keys to each row in-place.
    """
    fields = identity_fields or SEDAR_IDENTITY_FIELDS
    col_names = [c["name"] for c in columns]
    defaults = {c["name"]: c.get("default") for c in columns}

    all_default_count = 0
    evidenceless_count = 0

    for row in rows:
        # Check if all extracted fields are their default value
        all_def = all(row.get(n) == defaults[n] for n in col_names if n in row)
        row["_flag_all_default"] = all_def
        if all_def:
            all_default_count += 1

        # Check for non-null values without evidence
        ev_less = 0
        for n in col_names:
            val = row.get(n)
            quote = row.get(f"{n}_evidence_quote")
            if val is not None and val != defaults[n] and not quote:
                ev_less += 1
        row["_flag_evidenceless"] = ev_less > 0
        if ev_less > 0:
            evidenceless_count += 1

        # NLI cell verification
        for col in columns:
            col_name = col.get("name", "")
            if not col_name:
                continue
            quote = str(row.get(f"{col_name}_evidence_quote") or "")
            if quote:
                chunk_text = str(row.get(f"{col_name}_chunk_text") or "")
                if chunk_text:
                    verified, score = verify_quote_in_chunk(quote, chunk_text)
                else:
                    # No chunk text stored — length heuristic fallback
                    verified = len(quote) >= 10
                    score = 0.75 if verified else 0.0
            else:
                verified = False
                score = 0.0
            row[f"{col_name}_verified"] = verified
            row[f"{col_name}_entailment_score"] = round(score, 3)

    parse_error_count = sum(1 for r in rows if r.get("_flag_parse_error"))
    extraction_error_count = sum(
        1 for r in rows if str(r.get("_extraction_error") or "").strip()
    )

    from prompt2dataset.dataset_graph.extraction_contract import summarize_evidence_closure

    closure = summarize_evidence_closure(rows, columns)

    return {
        "all_default_count": all_default_count,
        "evidenceless_count": evidenceless_count,
        "parse_error_count": parse_error_count,
        "extraction_error_count": extraction_error_count,
        **closure,
        "total_rows": len(rows),
        "nli_verified_count": sum(
            1 for row in rows
            for col in columns
            if row.get(f"{col.get('name', '')}_verified", False)
        ),
        "nli_checked_count": sum(
            1 for row in rows
            for col in columns
            if f"{col.get('name', '')}_entailment_score" in row
        ),
    }


def _apply_meta_cols(row: dict[str, Any], doc_meta: dict[str, Any]) -> None:
    """Stamp every extracted row with provenance and deduplication meta columns."""
    row["extracted_at"] = _dt.datetime.utcnow().isoformat()
    row["schema_version"] = 1  # overridden by graph if rework_count > 0
    row["source_url"] = str(doc_meta.get("source_url", "") or "")
    row["acquisition_job_id"] = str(doc_meta.get("acquisition_job_id", "") or "")
    try:
        _doc_id_str = str(doc_meta.get("doc_id") or doc_meta.get("filing_id", ""))
        row["doc_hash"] = hashlib.md5(_doc_id_str.encode()).hexdigest()[:12]
    except Exception:
        row["doc_hash"] = ""
    row["_flag_parse_error"] = bool(row.get("_flag_parse_error") or row.get("_extraction_error"))


def _chunk_hashes_for_training(blocks: list[dict[str, Any]], *, limit: int = 24) -> list[str]:
    """Short MD5 digests of retrieved chunk text for training_events joins."""
    out: list[str] = []
    for b in (blocks or [])[:limit]:
        t = str(b.get("text", ""))[:8192]
        out.append(hashlib.md5(t.encode("utf-8", errors="ignore")).hexdigest()[:16])
    return out


def _schema_blob_for_training(obj: Any, limit: int = 96_000) -> str | None:
    """Serialize schema / guided-json dict for training_events (truncated)."""
    if obj is None:
        return None
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None
    if not s:
        return None
    return s[:limit]


async def _extract_one(
    client,
    sem: asyncio.Semaphore,
    cfg,
    profile,
    doc_meta: dict[str, Any],
    evidence_blocks: list[dict[str, Any]],
    columns: list[SchemaColumn],
    json_schema: dict,
    identity_fields: list[str],
    *,
    all_chunks: int,
    keyword_hits: int,
    pass1_pos: int,
    extraction_mode: str,
    corpus_topic: str = "",
    row_granularity: str = "one_row_per_document",
    schema_mapping_summary: str = "",
    trajectory_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from prompt2dataset.utils.prompt2dataset_settings import load_prompt2dataset_config

    p2d = load_prompt2dataset_config()
    use_cot = getattr(p2d, "extraction_chain_of_thought", True)
    if os.environ.get("PROMPT2DATASET_EXTRACTION_COT", "").strip().lower() in ("0", "false", "no", "off"):
        use_cot = False
    if os.environ.get("PROMPT2DATASET_EXTRACTION_COT", "").strip().lower() in ("1", "true", "yes", "on"):
        use_cot = True
    ctx_lim = int(cfg.vllm_model_max_context_tokens)
    cot_explicit_on = os.environ.get("PROMPT2DATASET_EXTRACTION_COT", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if ctx_lim <= 8192 and len(columns) >= 12 and not cot_explicit_on:
        use_cot = False
        logger.info(
            "extraction: CoT off for narrow context (%s tok) × wide schema (%s cols)",
            ctx_lim,
            len(columns),
        )
    system_prompt = extraction_system_prompt(use_chain_of_thought=use_cot)

    prompt_tail = ""
    if p2d.extraction_evidence_chain_in_schema:
        prompt_tail = (
            "\n\n--- Optional evidence chains ---\n"
            "You may include top-level JSON key \"evidence_chains\": an array of "
            "{'field_name', 'nodes': [{chunk_id, role, summary}], 'reasoning_edges': [...]} "
            "linking chunks for provenance."
        )

    # Use max-difficulty temperature across all columns in this batch
    batch_temperature = effective_temperature(columns) or profile.temperature
    max_out = extraction_output_token_budget(len(columns))
    if use_cot:
        max_out = min(24_000, max_out + 2200)
    raw_max_out = max_out
    max_out = _cap_requested_max_tokens(
        max_out, profile=profile, cfg=cfg, phase="extraction", n_cols=len(columns)
    )
    if raw_max_out > max_out:
        logger.info(
            "extraction: capping max_tokens %d → %d (profile=%s profile_cap=%s settings_cap=%s)",
            raw_max_out,
            max_out,
            getattr(profile, "name", "?"),
            getattr(profile, "max_tokens", "?"),
            getattr(cfg, "vllm_max_tokens", "?"),
        )
    if max_out > CONTEXT_BUDGET["extraction_max_out"]:
        logger.info(
            "extraction: %d schema columns → max_tokens=%d (wide schema%s)",
            len(columns),
            max_out,
            " + CoT" if use_cot else "",
        )

    use_guided = bool(cfg.use_guided_decoding and not use_cot)
    guided_overhead = _guided_schema_token_budget(json_schema) if use_guided else 0

    if (
        use_guided
        and ctx_lim <= 8192
        and len(columns) >= 20
    ):
        use_guided = False
        guided_overhead = 0
        logger.warning(
            "extraction: guided_json off for wide schemas (≥20 fields) with context_window≤8192 — "
            "use ``json_object`` + prompt; widen vLLM --max-model-len for full guided fidelity.",
            # (message is intentionally one line for log scanners)
        )

    _budget_probe = _extraction_user_prompt_budget_tokens(
        cfg,
        system_prompt,
        max_out,
        extra_reserved_tokens=guided_overhead,
    )
    _min_doc_prompt = 700 if ctx_lim <= 6144 else 512
    if use_guided and _budget_probe < _min_doc_prompt:
        use_guided = False
        guided_overhead = 0
        logger.warning(
            "extraction: guided_json disabled — user message budget would be %d tok "
            "(need ≥%d for doc+schema text; context=%d). Using json_object + prompt contract.",
            _budget_probe,
            _min_doc_prompt,
            ctx_lim,
        )

    user_prompt = _fit_extraction_user_prompt_for_context(
        columns=columns,
        doc_meta=doc_meta,
        evidence_blocks=evidence_blocks,
        all_chunks=all_chunks,
        keyword_hits=keyword_hits,
        pass1_pos=pass1_pos,
        extraction_mode=extraction_mode,
        corpus_topic=corpus_topic,
        row_granularity=row_granularity,
        schema_mapping_summary=schema_mapping_summary,
        extra_sections="",
        prompt_tail=prompt_tail,
        cfg=cfg,
        system_prompt=system_prompt,
        max_out=max_out,
        extra_reserved_tokens=guided_overhead,
    )
    inp_est = (
        _prompt_token_estimate(system_prompt)
        + _prompt_token_estimate(user_prompt)
        + guided_overhead
    )
    max_room = max(64, int(cfg.vllm_model_max_context_tokens) - inp_est - 96)
    if max_out > max_room:
        logger.info(
            "extraction: reducing completion budget %d → %d (est. input %d tok, context=%d)",
            max_out,
            max_room,
            inp_est,
            cfg.vllm_model_max_context_tokens,
        )
        max_out = max_room

    extra: dict[str, Any] = profile.extra_body(guided_json=json_schema if use_guided else None)
    if use_cot:
        # Allow freeform thinking + JSON; json_object / guided would truncate or break.
        resp_fmt = None
    else:
        resp_fmt = ({"type": "json_object"} if not cfg.use_guided_decoding else None)

    rid = (trajectory_ctx or {}).get("run_id") or ""
    doc_key = str(doc_meta.get("doc_id") or doc_meta.get("filing_id") or "")
    last_raw = ""
    ch_ids = [str(b.get("chunk_id", "")) for b in evidence_blocks[:24]]
    ch_hashes = _chunk_hashes_for_training(evidence_blocks, limit=24)
    evt = TrainingEventLogger(rid, state=trajectory_ctx) if rid else None
    chain_blob: Any = None
    for attempt in range(3):
        try:
            async with sem:
                resp = await client.chat.completions.create(
                    model=cfg.vllm_model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=batch_temperature,
                    max_tokens=max_out,
                    top_p=profile.top_p,
                    extra_body=extra if extra else None,
                    response_format=resp_fmt,
                )
            raw = resp.choices[0].message.content or ""
            last_raw = raw
            data = _normalize_extraction_payload(_parse_json(raw), columns)
            _log_debug_parsed_extraction(doc_key, data, phase="extract")
            chain_blob = data.pop("evidence_chains", None)
        except Exception as exc:
            if attempt == 2:
                logger.warning("extraction failed for %s: %s",
                               doc_meta.get("doc_id", doc_meta.get("filing_id")), exc)
                row = _default_row(doc_meta, columns, identity_fields, error=str(exc))
                row.update({"_all_chunks": all_chunks, "_keyword_hits": keyword_hits,
                            "_pass1_positive": pass1_pos, "_evidence_blocks_used": 0,
                            "_flag_parse_error": True})
                _apply_meta_cols(row, doc_meta)
                if evt:
                    evt.log_extraction_failed(
                        doc_key,
                        error=str(exc)[:2000],
                        retrieved_chunk_ids=ch_ids,
                        extra_state={"attempt": attempt + 1, "chain_of_thought": use_cot},
                    )
                return row
            await asyncio.sleep(2 ** attempt)
            continue

        # Pydantic validation gate — coerce types, flag on failure
        validated_values, had_parse_error = validate_extraction_row(data, columns)

        row = _default_row(doc_meta, columns, identity_fields)
        for col in columns:
            name = col["name"]
            if name in validated_values:
                row[name] = validated_values[name]
            # Evidence companion keys are passed through raw (not validated)
            ev_key = f"{name}_evidence"
            ev = data.get(ev_key) or {}
            if isinstance(ev, dict):
                row[f"{name}_evidence_quote"] = ev.get("quote")
                p0, p1 = ev.get("page_start"), ev.get("page_end")
                row[f"{name}_evidence_pages"] = f"{p0}-{p1}" if p0 is not None else None
                row[f"{name}_evidence_section"] = ev.get("section_path")
                row[f"{name}_chunk_id"] = str(ev.get("chunk_id") or "")

        row["_all_chunks"] = all_chunks
        row["_keyword_hits"] = keyword_hits
        row["_pass1_positive"] = pass1_pos
        row["_evidence_blocks_used"] = len(evidence_blocks)
        row["_flag_parse_error"] = had_parse_error
        if chain_blob is not None:
            try:
                row["_evidence_chains"] = json.dumps(chain_blob, ensure_ascii=False, default=str)[:20000]
            except (TypeError, ValueError):
                pass
        _apply_meta_cols(row, doc_meta)
        if evt:
            ev_sh = (trajectory_ctx or {}).get("schema_hash", "")
            evt.log_llm_extract(
                doc_key,
                llm_raw_output=last_raw,
                retrieved_chunk_ids=ch_ids,
                retrieved_chunk_hashes=ch_hashes,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_json=_schema_blob_for_training(json_schema),
                extra_state={
                    "rework_count": (trajectory_ctx or {}).get("rework_count", 0),
                    "evidence_block_count": len(evidence_blocks),
                    "keyword_hits": keyword_hits,
                    "extraction_mode": extraction_mode,
                    "parse_error": had_parse_error,
                    "schema_hash": ev_sh,
                    "chain_of_thought": use_cot,
                },
            )
        return row

    fallback = _default_row(doc_meta, columns, identity_fields, error="max retries")
    _apply_meta_cols(fallback, doc_meta)
    if evt:
        evt.log_extraction_failed(
            doc_key, error="max retries", retrieved_chunk_ids=ch_ids, extra_state={}
        )
    return fallback


def _normalize_scout_payload(data: dict[str, Any]) -> dict[str, Any]:
    rf = data.get("resolved_fields")
    if not isinstance(rf, dict):
        rf = {}
    hy_raw = data.get("hypotheses")
    hy: list[dict[str, Any]] = []
    if isinstance(hy_raw, list):
        for h in hy_raw[:20]:
            if isinstance(h, dict):
                hy.append(h)
    uf_raw = data.get("unresolved_fields")
    uf: list[str] = []
    if isinstance(uf_raw, list):
        seen_u: set[str] = set()
        for x in uf_raw:
            if not x:
                continue
            s = str(x)
            if s in seen_u:
                continue
            seen_u.add(s)
            uf.append(s)
            if len(uf) >= 200:
                break
    return {"resolved_fields": rf, "hypotheses": hy, "unresolved_fields": uf}


def _refinement_query_from_scout(
    columns: list[SchemaColumn],
    blackboard: dict[str, Any],
    corpus_topic: str,
) -> str:
    """Build a single query string for hypothesis-driven retrieval (truncated)."""
    names = {c.get("name") for c in columns if c.get("name")}
    unresolved = [x for x in (blackboard.get("unresolved_fields") or []) if x in names]
    parts: list[str] = []
    for field_name in unresolved[:16]:
        col = next((c for c in columns if c.get("name") == field_name), None)
        if not col:
            continue
        kws = col.get("keywords") or []
        for k in kws[:4]:
            parts.append(str(k))
        instr = str(col.get("extraction_instruction") or col.get("description") or "").strip()[:200]
        if instr:
            parts.append(instr)
    for h in (blackboard.get("hypotheses") or [])[:4]:
        if not isinstance(h, dict):
            continue
        for k in ("needs", "summary"):
            t = str(h.get(k) or "").strip()
            if t:
                parts.append(t[:300])
    seen: set[str] = set()
    unique: list[str] = []
    for p in parts:
        p = p.strip()
        if not p or p in seen:
            continue
        seen.add(p)
        unique.append(p)
    q = " | ".join(unique)
    if len(q.strip()) < 12:
        return semantic_query_string(columns, corpus_topic)[:520]
    return q[:520]


async def _extract_one_multipass(
    client,
    sem: asyncio.Semaphore,
    cfg,
    profile,
    doc_meta: dict[str, Any],
    initial_blocks: list[dict[str, Any]],
    doc_chunks_df: pd.DataFrame,
    columns: list[SchemaColumn],
    json_schema: dict,
    identity_fields: list[str],
    *,
    all_chunks: int,
    keyword_hits: int,
    pass1_pos: int,
    extraction_mode: str,
    corpus_id: str | None = None,
    corpus_topic: str = "",
    row_granularity: str = "one_row_per_document",
    schema_mapping_summary: str = "",
    trajectory_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Scout → optional refinement retrieve → full extraction (synthesis)."""
    p2d = load_prompt2dataset_config()
    use_cot = getattr(p2d, "extraction_chain_of_thought", True)
    if os.environ.get("PROMPT2DATASET_EXTRACTION_COT", "").strip().lower() in ("0", "false", "no", "off"):
        use_cot = False
    if os.environ.get("PROMPT2DATASET_EXTRACTION_COT", "").strip().lower() in ("1", "true", "yes", "on"):
        use_cot = True

    doc_id = str(doc_meta.get("doc_id") or doc_meta.get("filing_id") or "")
    lance_corpus_id = corpus_id
    if isinstance(lance_corpus_id, str) and not lance_corpus_id.strip():
        lance_corpus_id = None
    ctopic = corpus_topic or None

    scout_user = build_scout_user_prompt(
        columns,
        doc_meta,
        initial_blocks,
        all_chunks_count=all_chunks,
        keyword_hit_count=keyword_hits,
        pass1_positive_count=pass1_pos,
        extraction_mode=extraction_mode,
        corpus_topic=corpus_topic,
        row_granularity=row_granularity,
        schema_mapping_summary=schema_mapping_summary,
    )
    scout_json_schema = build_scout_json_schema()
    scout_extra = profile.extra_body(
        guided_json=scout_json_schema if cfg.use_guided_decoding else None
    )
    ncols = max(1, len(columns))
    scout_raw = min(12_000, 1200 + 45 * ncols)
    scout_max = _cap_requested_max_tokens(
        scout_raw, profile=profile, cfg=cfg, phase="scout", n_cols=ncols
    )
    if scout_raw > scout_max:
        logger.info(
            "multipass scout: capping max_tokens %d → %d",
            scout_raw,
            scout_max,
        )
    doc_key = str(doc_meta.get("doc_id") or doc_meta.get("filing_id") or "")
    ch_ids = [str(b.get("chunk_id", "")) for b in (initial_blocks or [])[:24]]
    rid = (trajectory_ctx or {}).get("run_id") or ""
    evt = TrainingEventLogger(rid, state=trajectory_ctx) if rid else None

    blackboard: dict[str, Any] | None = None
    for attempt in range(2):
        try:
            async with sem:
                sresp = await client.chat.completions.create(
                    model=cfg.vllm_model_name,
                    messages=[
                        {"role": "system", "content": SCOUT_SYSTEM_PROMPT},
                        {"role": "user", "content": scout_user},
                    ],
                    temperature=min(0.3, (effective_temperature(columns) or profile.temperature)),
                    max_tokens=scout_max,
                    top_p=profile.top_p,
                    extra_body=scout_extra if scout_extra else None,
                    response_format={"type": "json_object"},
                )
            sraw = sresp.choices[0].message.content or ""
            sdata = _parse_json(sraw)
            blackboard = _normalize_scout_payload(sdata)
            if evt:
                ev_sh = (trajectory_ctx or {}).get("schema_hash", "")
                evt.log_llm_extract(
                    doc_key,
                    llm_raw_output=sraw,
                    retrieved_chunk_ids=ch_ids,
                    retrieved_chunk_hashes=_chunk_hashes_for_training(initial_blocks or [], limit=24),
                    system_prompt=SCOUT_SYSTEM_PROMPT,
                    user_prompt=scout_user,
                    schema_json=_schema_blob_for_training(scout_json_schema),
                    extra_state={
                        "extraction_phase": "scout",
                        "rework_count": (trajectory_ctx or {}).get("rework_count", 0),
                        "evidence_block_count": len(initial_blocks or []),
                        "schema_hash": ev_sh,
                        "chain_of_thought": False,
                    },
                )
            break
        except Exception as exc:
            if attempt == 1:
                logger.warning("multipass scout failed for %s, falling back to single-pass: %s", doc_id, exc)
                return await _extract_one(
                    client,
                    sem,
                    cfg,
                    profile,
                    doc_meta,
                    initial_blocks,
                    columns,
                    json_schema,
                    identity_fields,
                    all_chunks=all_chunks,
                    keyword_hits=keyword_hits,
                    pass1_pos=pass1_pos,
                    extraction_mode=extraction_mode,
                    corpus_topic=corpus_topic,
                    row_granularity=row_granularity,
                    schema_mapping_summary=schema_mapping_summary,
                    trajectory_ctx=trajectory_ctx,
                )
            await asyncio.sleep(1.5)
    if not blackboard:
        blackboard = {"resolved_fields": {}, "hypotheses": [], "unresolved_fields": [c.get("name", "") for c in columns if c.get("name")]}

    refine_blocks: list[dict[str, Any]] = []
    refinement_query = ""
    hops = 0
    need_hop = bool(
        p2d.extraction_max_refinement_hops > 0
        and (blackboard.get("hypotheses") or blackboard.get("unresolved_fields"))
    )
    if need_hop and not doc_chunks_df.empty:
        refinement_query = _refinement_query_from_scout(
            columns, blackboard, corpus_topic
        )
        if refinement_query.strip():
            try:
                refine_blocks, _t, _k = retrieve_refinement_blocks(
                    refinement_query,
                    columns,
                    doc_chunks_df,
                    top_n=p2d.extraction_refinement_evidence_blocks,
                    doc_id=doc_id or None,
                    corpus_id=lance_corpus_id,
                    corpus_topic=ctopic,
                    dataset_state=trajectory_ctx,
                )
            except Exception as exc:
                logger.debug("refinement retrieve failed: %s", exc)
                refine_blocks = []
            if refine_blocks:
                hops = 1

    merged = merge_evidence_block_lists(
        initial_blocks or [],
        refine_blocks,
        max_total=int(EXTRACTION_MAX_EVIDENCE_BLOCKS),
    )

    syn_user = build_multipass_synthesis_user_prompt(
        columns,
        doc_meta,
        merged,
        all_chunks_count=all_chunks,
        keyword_hit_count=keyword_hits,
        pass1_positive_count=pass1_pos,
        blackboard=blackboard,
        extraction_mode=extraction_mode,
        corpus_topic=corpus_topic,
        row_granularity=row_granularity,
        schema_mapping_summary=schema_mapping_summary,
        second_pass=bool(refine_blocks),
    )
    if p2d.extraction_evidence_chain_in_schema:
        syn_user += (
            "\n\n--- Optional evidence chains ---\n"
            "You may include top-level JSON key \"evidence_chains\": an array of "
            "{'field_name', 'nodes': [{chunk_id, role, summary}], 'reasoning_edges': [...]}."
        )

    system_prompt = extraction_system_prompt(use_chain_of_thought=use_cot)
    use_guided = bool(cfg.use_guided_decoding and not use_cot)
    extra: dict[str, Any] = profile.extra_body(
        guided_json=json_schema if use_guided else None
    )
    batch_temperature = effective_temperature(columns) or profile.temperature
    max_out = extraction_output_token_budget(len(columns))
    if use_cot:
        max_out = min(24_000, max_out + 2200)
    syn_raw = max_out
    max_out = _cap_requested_max_tokens(
        max_out, profile=profile, cfg=cfg, phase="synthesis", n_cols=len(columns)
    )
    if syn_raw > max_out:
        logger.info(
            "extraction (synthesis): capping max_tokens %d → %d",
            syn_raw,
            max_out,
        )
    if max_out > CONTEXT_BUDGET["extraction_max_out"]:
        logger.info(
            "extraction (synthesis): %d schema columns → max_tokens=%d (multipass%s)",
            len(columns),
            max_out,
            " + CoT" if use_cot else "",
        )
    if use_cot:
        resp_fmt = None
    else:
        resp_fmt = ({"type": "json_object"} if not cfg.use_guided_decoding else None)
    ch_ids_syn = [str(b.get("chunk_id", "")) for b in merged[:24]]
    ch_hashes_syn = _chunk_hashes_for_training(merged, limit=24)

    last_raw = ""
    chain_blob: Any = None
    for attempt in range(3):
        try:
            async with sem:
                resp = await client.chat.completions.create(
                    model=cfg.vllm_model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": syn_user},
                    ],
                    temperature=batch_temperature,
                    max_tokens=max_out,
                    top_p=profile.top_p,
                    extra_body=extra if extra else None,
                    response_format=resp_fmt,
                )
            raw = resp.choices[0].message.content or ""
            last_raw = raw
            data = _normalize_extraction_payload(_parse_json(raw), columns)
            _log_debug_parsed_extraction(doc_key, data, phase="synthesis")
            chain_blob = data.pop("evidence_chains", None)
        except Exception as exc:
            if attempt == 2:
                logger.warning("multipass synthesis failed for %s: %s", doc_id, exc)
                row = _default_row(doc_meta, columns, identity_fields, error=str(exc))
                row.update(
                    {
                        "_all_chunks": all_chunks,
                        "_keyword_hits": keyword_hits,
                        "_pass1_positive": pass1_pos,
                        "_evidence_blocks_used": len(merged),
                        "_flag_parse_error": True,
                    }
                )
                _apply_meta_cols(row, doc_meta)
                return row
            await asyncio.sleep(2 ** attempt)
            continue

        validated_values, had_parse_error = validate_extraction_row(data, columns)
        row = _default_row(doc_meta, columns, identity_fields)
        for col in columns:
            name = col["name"]
            if name in validated_values:
                row[name] = validated_values[name]
            ev_key = f"{name}_evidence"
            ev = data.get(ev_key) or {}
            if isinstance(ev, dict):
                row[f"{name}_evidence_quote"] = ev.get("quote")
                p0, p1 = ev.get("page_start"), ev.get("page_end")
                row[f"{name}_evidence_pages"] = f"{p0}-{p1}" if p0 is not None else None
                row[f"{name}_evidence_section"] = ev.get("section_path")
                row[f"{name}_chunk_id"] = str(ev.get("chunk_id") or "")

        row["_all_chunks"] = all_chunks
        row["_keyword_hits"] = keyword_hits
        row["_pass1_positive"] = pass1_pos
        row["_evidence_blocks_used"] = len(merged)
        row["_flag_parse_error"] = had_parse_error
        if chain_blob is not None:
            try:
                row["_evidence_chains"] = json.dumps(chain_blob, ensure_ascii=False, default=str)[:20000]
            except (TypeError, ValueError):
                pass
        try:
            row["_extraction_multipass_meta"] = json.dumps(
                {
                    "hops": hops,
                    "hypotheses_n": len(blackboard.get("hypotheses") or []),
                    "refinement_query": (refinement_query or "")[:400],
                    "refinement_block_count": len(refine_blocks),
                },
                ensure_ascii=False,
            )
        except Exception:
            pass
        _apply_meta_cols(row, doc_meta)
        if evt:
            ev_sh = (trajectory_ctx or {}).get("schema_hash", "")
            evt.log_llm_extract(
                doc_key,
                llm_raw_output=last_raw,
                retrieved_chunk_ids=ch_ids_syn,
                retrieved_chunk_hashes=ch_hashes_syn,
                system_prompt=system_prompt,
                user_prompt=syn_user,
                schema_json=_schema_blob_for_training(json_schema),
                extra_state={
                    "extraction_phase": "synthesis",
                    "rework_count": (trajectory_ctx or {}).get("rework_count", 0),
                    "evidence_block_count": len(merged),
                    "keyword_hits": keyword_hits,
                    "extraction_mode": extraction_mode,
                    "parse_error": had_parse_error,
                    "schema_hash": ev_sh,
                    "chain_of_thought": use_cot,
                },
            )
        return row

    fallback = _default_row(doc_meta, columns, identity_fields, error="max retries")
    _apply_meta_cols(fallback, doc_meta)
    if evt:
        evt.log_extraction_failed(
            doc_key, error="max retries (synthesis)", retrieved_chunk_ids=ch_ids_syn, extra_state={}
        )
    return fallback


def _filter_chunks_by_doc(chunks: pd.DataFrame, doc_id: str) -> pd.DataFrame:
    """Return the subset of chunks belonging to doc_id (tries doc_id and filing_id columns)."""
    for col in ("doc_id", "filing_id"):
        if col in chunks.columns:
            result = chunks[chunks[col] == doc_id]
            if not result.empty:
                return result
    return pd.DataFrame()


def _build_evidence_blocks(
    doc_id: str,
    chunks: pd.DataFrame,
    chunks_llm: pd.DataFrame,
    schema_cols: list[SchemaColumn] | None = None,
    *,
    corpus_id: str | None = None,
    corpus_topic: str | None = None,
    dataset_state: dict[str, Any] | None = None,
) -> tuple[list[dict], int, int, int]:
    """Return (evidence_blocks, total_chunks, keyword_hits, pass1_pos=0).

    Retrieval uses the same schema ``keywords`` + instructions as the extraction
    prompt: LanceDB hybrid when ``corpus_id`` is set and the table exists, else
    BM25Plus on parquet chunks; cross-encoder reranking applies in both paths.
    chunks_llm is accepted for backward-compat but unused. pass1_pos is always 0.
    """
    cid = (corpus_id or "").strip() or None
    ctopic = (corpus_topic or "").strip() or None
    doc_chunks = _filter_chunks_by_doc(chunks, doc_id) if not chunks.empty else pd.DataFrame()
    blocks, total, keyword_hits = retrieve_evidence_blocks(
        schema_cols or [],
        doc_chunks,
        doc_id=doc_id or None,
        corpus_id=cid,
        corpus_topic=ctopic,
        dataset_state=dataset_state,
    )
    logger.debug(
        "_build_evidence_blocks: doc=%s corpus_id=%s blocks=%d/%d kw_hits=%d",
        doc_id, cid or "-", len(blocks), total, keyword_hits,
    )
    return blocks, total, keyword_hits, 0


def _load_corpus_data(
    settings,
    state: DatasetState | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    from prompt2dataset.corpus.paths import resolve_corpus_path

    st = state or {}
    root = settings.project_root
    idx_path = resolve_corpus_path(
        root, st.get("corpus_index_csv"), settings.filings_index_path
    )
    chunks_path = resolve_corpus_path(
        root, st.get("corpus_chunks_parquet"), settings.chunks_parquet
    )
    llm_path = resolve_corpus_path(
        root, st.get("corpus_chunks_llm_parquet"), settings.chunks_llm_parquet
    )

    idx = pd.read_csv(idx_path, dtype=str)
    try:
        chunks = pd.read_parquet(str(chunks_path))
    except Exception:
        chunks = pd.DataFrame(
            columns=["doc_id", "filing_id", "chunk_id", "text",
                     "section_path", "page_start", "page_end", "keyword_hit"]
        )
    try:
        chunks_llm = pd.read_parquet(str(llm_path))
    except Exception:
        chunks_llm = pd.DataFrame(columns=["doc_id", "filing_id", "chunk_id",
                                            "topic_relevant", "mentions_tariffs"])
    return idx, chunks, chunks_llm


async def _run_extraction(
    cfg,
    idx: pd.DataFrame,
    chunks: pd.DataFrame,
    chunks_llm: pd.DataFrame,
    columns: list[SchemaColumn],
    extraction_mode: str,
    profile_name: str,
    identity_fields: list[str],
    corpus_topic: str = "",
    corpus_id: str | None = None,
    row_granularity: str = "one_row_per_document",
    schema_mapping_summary: str = "",
    trajectory_ctx: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    profile = get_profile(profile_name, cfg)
    client = make_async_client(profile, cfg)
    sem = asyncio.Semaphore(profile.max_concurrent_requests)
    p2d = load_prompt2dataset_config()
    json_schema = build_extraction_guided_schema(
        columns,
        cfg,
        with_evidence_chains=p2d.extraction_evidence_chain_in_schema,
    )

    tasks = []
    for _, row in idx.iterrows():
        doc_meta = row.to_dict()
        # Normalise doc_id: try both generic and SEDAR column names
        doc_id = str(doc_meta.get("doc_id") or doc_meta.get("filing_id", ""))
        blocks, total, kw, pos = _build_evidence_blocks(
            doc_id,
            chunks,
            chunks_llm,
            columns,
            corpus_id=corpus_id,
            corpus_topic=corpus_topic or None,
            dataset_state=trajectory_ctx,
        )
        doc_chunks = _filter_chunks_by_doc(chunks, doc_id) if not chunks.empty else pd.DataFrame()
        if p2d.extraction_multipass_blackboard:
            tasks.append(
                _extract_one_multipass(
                    client,
                    sem,
                    cfg,
                    profile,
                    doc_meta,
                    blocks,
                    doc_chunks,
                    columns,
                    json_schema,
                    identity_fields,
                    all_chunks=total,
                    keyword_hits=kw,
                    pass1_pos=pos,
                    extraction_mode=extraction_mode,
                    corpus_id=corpus_id,
                    corpus_topic=corpus_topic,
                    row_granularity=row_granularity,
                    schema_mapping_summary=schema_mapping_summary,
                    trajectory_ctx=trajectory_ctx,
                )
            )
        else:
            tasks.append(
                _extract_one(
                    client, sem, cfg, profile, doc_meta, blocks, columns, json_schema,
                    identity_fields,
                    all_chunks=total, keyword_hits=kw, pass1_pos=pos,
                    extraction_mode=extraction_mode,
                    corpus_topic=corpus_topic,
                    row_granularity=row_granularity,
                    schema_mapping_summary=schema_mapping_summary,
                    trajectory_ctx=trajectory_ctx,
                )
            )

    mode = "multipass" if p2d.extraction_multipass_blackboard else "single"
    logger.info("extraction_node: %d async extractions [profile=%s, mode=%s]", len(tasks), profile_name, mode)
    return list(await asyncio.gather(*tasks, return_exceptions=False))


def extract_one_filing(
    state: DatasetState,
    doc_meta: dict,
) -> dict:
    """Extract a single document and return its flat row dict.

    Uses concurrency=1 and the interactive profile so it is friendly
    to the Streamlit UI loop (called once per rerun, result shown immediately).

    Backward-compat: also accepts `filing_meta` as kwarg name in caller code.
    """
    cfg = get_settings()
    columns: list[SchemaColumn] = resolve_extraction_schema_columns(state)
    if not columns:
        return {}

    identity_fields = state.get("identity_fields") or SEDAR_IDENTITY_FIELDS
    corpus_topic = state.get("corpus_topic", "")
    corpus_id = state.get("corpus_id")
    row_granularity = state.get("extraction_row_granularity") or "one_row_per_document"
    schema_mapping_summary = state.get("schema_mapping_summary") or ""

    _, chunks, chunks_llm = _load_corpus_data(cfg, state)
    tr = trajectory_context_from_dataset_state(dict(state))
    p2d = load_prompt2dataset_config()
    json_schema = build_extraction_guided_schema(
        columns,
        cfg,
        with_evidence_chains=p2d.extraction_evidence_chain_in_schema,
    )
    profile = get_profile("interactive", cfg)
    extraction_mode = state.get("extraction_mode") or "direct"
    doc_id = str(doc_meta.get("doc_id") or doc_meta.get("filing_id", ""))
    blocks, total, kw, pos = _build_evidence_blocks(
        doc_id,
        chunks,
        chunks_llm,
        columns,
        corpus_id=corpus_id if isinstance(corpus_id, str) else None,
        corpus_topic=corpus_topic or None,
        dataset_state=tr,
    )

    doc_chunks = _filter_chunks_by_doc(chunks, doc_id) if not chunks.empty else pd.DataFrame()

    async def _run() -> dict:
        sem = asyncio.Semaphore(1)
        client = make_async_client(profile, cfg)
        tctx = tr if tr.get("run_id") else None
        cid = corpus_id if isinstance(corpus_id, str) else None
        if p2d.extraction_multipass_blackboard:
            return await _extract_one_multipass(
                client, sem, cfg, profile, doc_meta, blocks, doc_chunks, columns, json_schema,
                identity_fields,
                all_chunks=total, keyword_hits=kw, pass1_pos=pos,
                extraction_mode=extraction_mode,
                corpus_id=cid,
                corpus_topic=corpus_topic,
                row_granularity=row_granularity,
                schema_mapping_summary=schema_mapping_summary,
                trajectory_ctx=tctx,
            )
        return await _extract_one(
            client, sem, cfg, profile, doc_meta, blocks, columns, json_schema,
            identity_fields,
            all_chunks=total, keyword_hits=kw, pass1_pos=pos,
            extraction_mode=extraction_mode,
            corpus_topic=corpus_topic,
            row_granularity=row_granularity,
            schema_mapping_summary=schema_mapping_summary,
            trajectory_ctx=tctx,
        )

    return asyncio.run(_run())


# Alias for external scripts / notebooks that expect this name.
extract_pdf = extract_one_filing


def extract_batch_filings(
    state: DatasetState,
    doc_metas: list[dict],
    *,
    concurrency: int = 4,
) -> list[dict]:
    """Extract a batch of documents in parallel and return their row dicts.

    Runs up to `concurrency` extractions simultaneously using a shared
    asyncio Semaphore and a single async HTTP client.  This is the drop-in
    replacement for calling ``extract_one_filing`` in a serial loop.

    Args:
        state: current DatasetState (schema, corpus paths, identity fields…)
        doc_metas: list of document metadata dicts (one per doc to extract)
        concurrency: max simultaneous vLLM calls (default 4)

    Returns:
        list of row dicts in the same order as ``doc_metas``.
        Failed rows contain an ``_extraction_error`` key with the exception message.
    """
    if not doc_metas:
        return []

    cfg = get_settings()
    columns: list[SchemaColumn] = resolve_extraction_schema_columns(state)
    if not columns:
        identity_fields = state.get("identity_fields") or SEDAR_IDENTITY_FIELDS
        return [{f: m.get(f, "") for f in identity_fields} for m in doc_metas]

    identity_fields = state.get("identity_fields") or SEDAR_IDENTITY_FIELDS
    corpus_topic = state.get("corpus_topic", "")
    corpus_id = state.get("corpus_id")
    extraction_mode = state.get("extraction_mode") or "direct"
    row_granularity = state.get("extraction_row_granularity") or "one_row_per_document"
    schema_mapping_summary = state.get("schema_mapping_summary") or ""

    _, chunks, chunks_llm = _load_corpus_data(cfg, state)
    tr = trajectory_context_from_dataset_state(dict(state))
    p2d = load_prompt2dataset_config()
    json_schema = build_extraction_guided_schema(
        columns,
        cfg,
        with_evidence_chains=p2d.extraction_evidence_chain_in_schema,
    )
    profile = get_profile("interactive", cfg)

    async def _run_batch() -> list[dict]:
        sem = asyncio.Semaphore(concurrency)
        client = make_async_client(profile, cfg)

        async def _safe_extract(doc_meta: dict) -> dict:
            doc_id = str(doc_meta.get("doc_id") or doc_meta.get("filing_id", ""))
            blocks, total, kw, pos = _build_evidence_blocks(
                doc_id,
                chunks,
                chunks_llm,
                columns,
                corpus_id=corpus_id if isinstance(corpus_id, str) else None,
                corpus_topic=corpus_topic or None,
                dataset_state=tr,
            )
            doc_chunks = _filter_chunks_by_doc(chunks, doc_id) if not chunks.empty else pd.DataFrame()
            tctx = tr if tr.get("run_id") else None
            cid = corpus_id if isinstance(corpus_id, str) else None
            try:
                if p2d.extraction_multipass_blackboard:
                    return await _extract_one_multipass(
                        client, sem, cfg, profile, doc_meta, blocks, doc_chunks, columns,
                        json_schema, identity_fields,
                        all_chunks=total, keyword_hits=kw, pass1_pos=pos,
                        extraction_mode=extraction_mode,
                        corpus_id=cid,
                        corpus_topic=corpus_topic,
                        row_granularity=row_granularity,
                        schema_mapping_summary=schema_mapping_summary,
                        trajectory_ctx=tctx,
                    )
                return await _extract_one(
                    client, sem, cfg, profile, doc_meta, blocks, columns,
                    json_schema, identity_fields,
                    all_chunks=total, keyword_hits=kw, pass1_pos=pos,
                    extraction_mode=extraction_mode,
                    corpus_topic=corpus_topic,
                    row_granularity=row_granularity,
                    schema_mapping_summary=schema_mapping_summary,
                    trajectory_ctx=tctx,
                )
            except Exception as exc:
                row = {f: doc_meta.get(f, "") for f in identity_fields}
                row["_extraction_error"] = str(exc)
                return row

        return list(await asyncio.gather(*(_safe_extract(m) for m in doc_metas)))

    return asyncio.run(_run_batch())


def extraction_node(state: DatasetState) -> DatasetState:
    """Run targeted extraction.

    If state['use_sample'] is True, restrict to state['sample_doc_ids'] and
    use the interactive vLLM profile (lower concurrency, tunable temperature).
    Otherwise run on the full corpus with the batch profile.
    """
    cfg = get_settings()
    columns = resolve_extraction_schema_columns(state)
    if not columns:
        return {**state, "error": "No columns defined — run schema_node or set extraction_schema"}

    identity_fields = state.get("identity_fields") or SEDAR_IDENTITY_FIELDS
    corpus_topic = state.get("corpus_topic", "")
    corpus_id_raw = state.get("corpus_id")
    corpus_id = corpus_id_raw if isinstance(corpus_id_raw, str) else None
    row_granularity = state.get("extraction_row_granularity") or "one_row_per_document"
    schema_mapping_summary = state.get("schema_mapping_summary") or ""

    idx, chunks, chunks_llm = _load_corpus_data(cfg, state)

    use_sample = state.get("use_sample", False)
    sample_doc_ids = state.get("sample_doc_ids") or state.get("sample_tickers") or []
    full_idx = idx

    if use_sample and sample_doc_ids:
        # Try matching by doc_id, filing_id, ticker, or entity_slug
        for col in ("doc_id", "filing_id", "ticker", "entity_slug"):
            if col in full_idx.columns:
                idx = full_idx[full_idx[col].isin(sample_doc_ids)].copy()
                if not idx.empty:
                    break
        else:
            # Fuzzy name match fallback
            def _name_match(row: dict) -> bool:
                name = str(row.get("issuer_name", row.get("entity_name", ""))).lower()
                return any(
                    frag.lower().replace("tsx:", "").strip("_") in name
                    for frag in sample_doc_ids
                    if frag
                )
            idx = full_idx[full_idx.apply(_name_match, axis=1)].copy()

        logger.info("extraction_node: sample mode — %d docs for filter %s", len(idx), sample_doc_ids)
        if idx.empty:
            if len(full_idx) <= 50:
                idx = full_idx.copy()
            else:
                return {**state, "error": f"No rows matched sample filter: {sample_doc_ids}"}

    n_rows = len(idx)
    profile_name = "interactive" if use_sample else profile_for_workload(n_rows)
    extraction_mode = state.get("extraction_mode") or "direct"

    logger.info("extraction_node: %d docs | profile=%s | mode=%s", n_rows, profile_name, extraction_mode)

    tr = trajectory_context_from_dataset_state(dict(state))
    rows = asyncio.run(
        _run_extraction(
            cfg,
            idx,
            chunks,
            chunks_llm,
            columns,
            extraction_mode,
            profile_name,
            identity_fields,
            corpus_topic,
            corpus_id=corpus_id,
            row_granularity=row_granularity,
            schema_mapping_summary=schema_mapping_summary,
            trajectory_ctx=tr if tr.get("run_id") else None,
        )
    )

    # Run consistency check
    consistency_flags = run_consistency_check(rows, columns, identity_fields)

    cells = rebuild_cells_from_rows(rows, columns, identity_fields)

    return {
        **state,
        "rows": rows,
        "cells": cells,
        "extraction_done": True,
        "consistency_flags": consistency_flags,
        "error": "",
    }
