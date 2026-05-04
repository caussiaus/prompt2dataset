"""Schema designer node: converts a user query into structured column definitions.

Supports two call modes:
  schema_node(state)          — standard: returns updated state (used by pipeline_runner)
  schema_node_stream(state)   — yields (token, final_state) tuples for UI streaming

The node reads partially-written chunks.parquet (if available) to inject real
document text samples into the schema design prompt. This grounds field suggestions
in actual document language rather than the user's description alone.
"""
from __future__ import annotations

import json
import logging
import random
import re
from pathlib import Path
from typing import Any, Generator, List, Optional

import instructor
import pandas as pd
from openai import OpenAI
from pydantic import BaseModel, Field

from prompt2dataset.dataset_graph.state import (
    DatasetState,
    SEDAR_IDENTITY_FIELDS,
)
from prompt2dataset.prompts.dataset_prompt import (
    CONTEXT_BUDGET,
    SCHEMA_MAX_CHUNK_SAMPLES,
    SCHEMA_CHUNK_SAMPLE_CHARS,
    SCHEMA_DESIGNER_SYSTEM_PROMPT,
    SCHEMA_HISTORY_WINDOW,
    build_schema_design_user_prompt,
)
from prompt2dataset.utils.config import get_settings

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I | re.M)
_THINK_RE = re.compile(r"<think>.*?</think>|<redacted_thinking>.*?</redacted_thinking>", re.I | re.DOTALL)


# ── Intent capture ────────────────────────────────────────────────────────────

def extract_intent_from_first_message(user_query: str) -> dict:
    """Extract domain label, output intent, and identity field hints from first message.

    Deterministic NLP extraction — no LLM call. Returns a dict with:
    - domain_label: str (e.g. "mining environmental disclosures")
    - output_intent: str (what uniquely identifies a row)
    - identity_field_hints: list[str] (likely identity columns)
    """
    if not user_query:
        return {"domain_label": "", "output_intent": "", "identity_field_hints": []}

    q_lower = user_query.lower()

    identity_hints = []
    for pattern, field_name in [
        (r"\bcompan(y|ies)\b", "company_name"),
        (r"\bticker\b|\bsymbol\b", "ticker"),
        (r"\byear\b|\bannual\b", "year"),
        (r"\bquarter\b|\bq[1-4]\b", "quarter"),
        (r"\bcountry\b|\bnation\b", "country"),
        (r"\bsector\b|\bindustry\b", "sector"),
        (r"\bfil(ing|ings)\b", "filing_type"),
    ]:
        if re.search(pattern, q_lower):
            identity_hints.append(field_name)

    if not identity_hints:
        identity_hints = ["doc_id", "entity_name"]

    sentences = user_query.split(".")
    output_intent = sentences[0].strip()[:100] if sentences else user_query[:100]

    words = [w.strip(".,;:\"'()[]") for w in user_query.split() if len(w) > 3]
    domain_label = " ".join(words[:6]) if words else user_query[:50]

    return {
        "domain_label": domain_label,
        "output_intent": output_intent,
        "identity_field_hints": identity_hints,
    }


# ── Homogeneity detection ─────────────────────────────────────────────────────

def detect_corpus_homogeneity(chunks_sample: list[dict]) -> dict:
    """Check if corpus documents share a consistent structure.

    Returns:
        {
            "is_homogeneous": bool,
            "common_sections": list[str],  # section headers found in >70% of docs
            "homogeneity_score": float,    # 0–1
        }
    """
    if not chunks_sample:
        return {"is_homogeneous": False, "common_sections": [], "homogeneity_score": 0.0}

    from collections import Counter
    section_counts: Counter = Counter()
    doc_ids = {c.get("doc_id", "") for c in chunks_sample}
    n_docs = max(len(doc_ids), 1)

    for chunk in chunks_sample:
        section = str(chunk.get("section_path", "") or "").strip()
        if section:
            section_counts[section] += 1

    MIN_RATE = 0.70
    common = [
        sec for sec, count in section_counts.most_common(20)
        if count / n_docs >= MIN_RATE
    ]

    score = len(common) / max(len(section_counts), 1)
    return {
        "is_homogeneous": len(common) >= 3,
        "common_sections": common[:10],
        "homogeneity_score": round(min(score, 1.0), 3),
    }


def _robust_json(text: str) -> dict:
    """Parse the first JSON object in text using raw_decode — handles trailing content."""
    raw = _THINK_RE.sub("", text).strip()
    raw = _FENCE_RE.sub("", raw).strip()
    # Try full parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # raw_decode: finds and parses the first valid JSON object, ignoring trailing junk
    dec = json.JSONDecoder()
    for i, ch in enumerate(raw):
        if ch in ('{', '['):
            try:
                obj, _ = dec.raw_decode(raw, i)
                return obj if isinstance(obj, dict) else {}
            except json.JSONDecodeError:
                continue
    return {}


# ── Pydantic response model for instructor-structured output ──────────────────

class _SchemaColumnOut(BaseModel):
    name: str
    type: str = "string"
    description: str = ""
    extraction_instruction: str = ""
    keywords: List[str] = Field(default_factory=list)
    default: Optional[Any] = None
    mode: str = ""
    difficulty: str = "standard"
    # single_best: one value per PDF (strongest match). combine_all_occurrences: merge all (counts, lists).
    value_cardinality: str = "single_best"


class _SchemaDesignOut(BaseModel):
    dataset_name: str = "custom_extraction"
    description: str = ""
    columns: List[_SchemaColumnOut]
    config_rationale: str = ""   # why schema LLM recommends these extraction settings

_DEFAULT_CONTEXT_CATEGORIES = [
    "manufacturing", "mining_oil_gas", "financial_services",
    "utilities", "retail_trade", "transportation", "agriculture",
]


def _strip(s: str) -> str:
    s = _THINK_RE.sub("", s).strip()
    s = _FENCE_RE.sub("", s).strip()
    return s


def _collect_corpus_context(state: DatasetState, cfg) -> tuple[list[str], int, str, str]:
    """Return (context_categories, doc_count, corpus_name, corpus_topic) from index."""
    context_categories: list[str] = []
    doc_count = 0
    corpus_name = state.get("dataset_name", "")
    corpus_topic = state.get("corpus_topic", "")

    try:
        from prompt2dataset.corpus.paths import resolve_corpus_path

        idx_path = resolve_corpus_path(
            cfg.project_root,
            state.get("corpus_index_csv"),
            cfg.filings_index_path,
        )
        idx = pd.read_csv(idx_path, dtype=str)
        doc_count = len(idx)

        # Try several column names for context categories
        for col in ("context_category", "naics_sector", "category", "sector"):
            if col in idx.columns:
                context_categories = [s for s in idx[col].dropna().unique().tolist() if s]
                break

        if not corpus_name:
            corpus_name = Path(idx_path).stem.replace("_index", "").replace("_", " ")
    except Exception:
        context_categories = _DEFAULT_CONTEXT_CATEGORIES

    # Try to get corpus_topic from CorpusConfig
    if not corpus_topic:
        try:
            from prompt2dataset.corpus.config import CorpusConfig
            from pathlib import Path as _Path
            root = _Path(__file__).resolve().parents[1]
            config_dir = root / "output" / "corpus_configs"
            corpus_id = state.get("dataset_name", "").replace(" ", "_").lower()
            yaml = config_dir / f"{corpus_id}.yaml"
            if yaml.exists():
                cfg_obj = CorpusConfig.from_yaml(yaml)
                corpus_topic = getattr(cfg_obj, "topic", "") or ""
        except Exception:
            pass

    return context_categories, doc_count, corpus_name, corpus_topic


def _sample_chunks_from_parquet(chunks_parquet: str, n: int = SCHEMA_MAX_CHUNK_SAMPLES) -> list[dict[str, Any]]:
    """Read partially-written chunks parquet, return n random chunks across different docs.

    This is the evaluation window: as Docling finishes each PDF, chunks appear
    in the parquet. We sample across documents to give the schema LLM grounded examples.
    """
    try:
        p = Path(chunks_parquet)
        if not p.exists() or p.stat().st_size < 1024:
            return []
        df = pd.read_parquet(p)
        if df.empty:
            return []

        # Normalise column names to generic form
        col_map = {
            "filing_id": "doc_id", "issuer_name": "entity_name",
            "ticker": "entity_slug", "filing_date": "doc_date",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        # One chunk per doc, prefer keyword-hit chunks
        id_col = next((c for c in ("doc_id", "filing_id") if c in df.columns), None)
        if not id_col:
            sample = df.sample(min(n, len(df)))
        else:
            # Prioritise keyword hits within each doc group, then pick one per doc
            if "keyword_hit" in df.columns:
                kw_mask = df["keyword_hit"].astype(str).str.lower().isin(["true", "1"])
                df_prio = pd.concat([df[kw_mask], df[~kw_mask]])
            else:
                df_prio = df
            sample = df_prio.groupby(id_col).first().reset_index().sample(min(n, len(df_prio)))

        result = []
        for _, row in sample.iterrows():
            text = str(row.get("text", ""))[:SCHEMA_CHUNK_SAMPLE_CHARS]
            if not text.strip():
                continue
            result.append({
                "doc_id": str(row.get("doc_id", row.get("filing_id", ""))),
                "entity_name": str(row.get("entity_name", row.get("issuer_name", ""))),
                "page_start": row.get("page_start", ""),
                "section_path": str(row.get("section_path", ""))[:60],
                "text": text,
            })
        return result
    except Exception as e:
        logger.debug("_sample_chunks_from_parquet: %s", e)
        return []


def _get_chunk_samples(state: DatasetState, cfg) -> list[dict[str, Any]]:
    """Get real document samples if the eval window is satisfied."""
    eval_min = state.get("eval_window_min", 6)
    eval_max = state.get("eval_window_max", 10)

    from prompt2dataset.corpus.paths import resolve_corpus_path

    chunks_path = resolve_corpus_path(
        cfg.project_root,
        state.get("corpus_chunks_parquet"),
        cfg.chunks_parquet,
    )
    samples = _sample_chunks_from_parquet(str(chunks_path), n=eval_max)

    if len(samples) < eval_min:
        return []  # eval window not yet satisfied — don't inject partial samples

    return samples[:eval_max]


def _nlp_draft_for_prompt(topic: str, existing_cols: list[dict] | None) -> str:
    """Generate an NLP-based schema draft to seed the LLM prompt.

    Runs in milliseconds — no LLM call. Returns an empty string if no
    draft can be generated (topic too short, no matching intent, etc.).

    The draft is injected into the user prompt so the LLM refines rather
    than generates from scratch. This dramatically reduces schema iteration
    tokens.
    """
    if not topic or len(topic) < 10:
        return ""
    if existing_cols:
        # Already have a schema — NLP draft would confuse the refinement
        return ""
    try:
        from prompt2dataset.utils.nlp_utils import draft_schema_from_prompt, classify_topic
        tags = classify_topic(topic)
        if not tags:
            return ""  # no domain matched — let LLM design freely
        fields = draft_schema_from_prompt(topic, max_fields=6)
        if not fields:
            return ""
        import json as _json
        draft_str = _json.dumps({"columns": fields}, indent=2)
        return (
            "\n\n## NLP Pre-draft (refine, don't replace)\n"
            "The following field candidates were generated from your topic using intent classification. "
            "Use them as a starting point — improve names, fix types, add missing fields, remove irrelevant ones:\n"
            f"```json\n{draft_str}\n```\n"
        )
    except Exception as exc:
        logger.debug("_nlp_draft_for_prompt: %s", exc)
        return ""


def _build_messages(state: DatasetState, cfg) -> tuple[list[dict], str]:
    """Build the message list and user prompt for the schema LLM call."""
    context_categories, doc_count, corpus_name, corpus_topic = _collect_corpus_context(state, cfg)
    chunk_samples = _get_chunk_samples(state, cfg)
    chat_history: list[dict] = state.get("chat_history", []) if hasattr(state, "get") else []  # type: ignore[assignment]

    # ── NLP pre-draft (first iteration only, before any schema feedback) ────
    existing_cols = state.get("proposed_columns") if state.get("schema_iteration", 0) > 0 else None
    nlp_hint = _nlp_draft_for_prompt(
        corpus_topic or state.get("user_query", ""),
        existing_cols,
    )

    user_prompt = build_schema_design_user_prompt(
        user_query=state.get("user_query", ""),
        naics_sectors=context_categories,
        schema_feedback=state.get("schema_feedback", ""),
        doc_count=doc_count,
        corpus_name=corpus_name,
        corpus_topic=corpus_topic,
        chunk_samples=chunk_samples if chunk_samples else None,
        chat_history=chat_history if chat_history else None,
        nlp_hint=nlp_hint or None,
    )

    # Inject LiveState context block into system prompt
    context_prefix = _build_live_context(state)
    system_content = context_prefix + SCHEMA_DESIGNER_SYSTEM_PROMPT if context_prefix else SCHEMA_DESIGNER_SYSTEM_PROMPT

    # Append intent capture context if present
    intent = state.get("_intent_capture")
    if intent and isinstance(intent, dict) and intent.get("domain_label"):
        intent_block = (
            f"\n\n## Detected Intent\n"
            f"Domain: {intent['domain_label']}\n"
            f"Output intent: {intent.get('output_intent', '')}\n"
            f"Suggested identity fields: {', '.join(intent.get('identity_field_hints', []))}\n"
        )
        system_content = system_content + intent_block

    # Append vault schema library context (optional — never blocks)
    try:
        from prompt2dataset.connectors.obsidian_bridge import get_vault_client
        vc = get_vault_client()
        all_schemas = vc.list_schemas()
        if all_schemas:
            schema_contexts = []
            for sname in all_schemas[:2]:
                sdata = vc.get_schema(sname)
                cols = sdata.get("columns", [])
                if cols:
                    schema_contexts.append(
                        f"Existing schema '{sname}': {[c.get('name', '') for c in cols[:8]]}"
                    )
            if schema_contexts:
                vault_block = "\n\n## Available Schemas in Vault\n" + "\n".join(schema_contexts)
                system_content = system_content + vault_block
    except Exception:
        pass

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_prompt},
    ]
    return messages, user_prompt


def _build_live_context(state: DatasetState) -> str:
    """Produce a LiveState context block for the system prompt. Returns '' if empty."""
    try:
        from app_pages.thread_store import build_live_state, build_context_block
        live = build_live_state(dict(state))
        # Only inject if there's meaningful state (not first-ever call)
        if live.fill_rates or live.active_flags or live.rework_count > 0:
            return build_context_block(live)
    except Exception:
        pass
    return ""


def _apply_result(state: DatasetState, raw_content: str) -> DatasetState:
    """Parse streamed LLM text response and return updated state.

    Used by schema_node_stream only — the sync schema_node uses instructor directly.
    Also auto-populates keywords for columns where the LLM omitted them.
    """
    try:
        data = _robust_json(raw_content)
    except Exception as exc:
        logger.error("schema_node: failed to parse LLM response: %s\nRaw: %s", exc, raw_content[:500])
        return {**state, "error": f"Schema LLM parse error: {exc}"}

    raw_columns = data.get("columns", [])
    if not raw_columns:
        return {**state, "error": "LLM returned empty columns list"}

    from prompt2dataset.dataset_graph.mapping_contract import (
        build_schema_mapping_summary,
        default_value_cardinality_for_column,
    )
    from prompt2dataset.utils.call_config import ensure_keywords, build_extraction_call_config
    corpus_topic = state.get("corpus_topic", "")
    columns = []
    for col in raw_columns:
        if isinstance(col, dict):
            col["keywords"] = ensure_keywords(col, corpus_topic)
            if not col.get("difficulty"):
                col["difficulty"] = "standard"
            if not col.get("value_cardinality"):
                col["value_cardinality"] = default_value_cardinality_for_column(col)
            elif col["value_cardinality"] not in ("single_best", "combine_all_occurrences"):
                col["value_cardinality"] = default_value_cardinality_for_column(col)
        columns.append(col)

    identity_fields = state.get("identity_fields") or SEDAR_IDENTITY_FIELDS

    # Build per-field extraction call config from difficulty
    extraction_call_config = {}
    for col in columns:
        if isinstance(col, dict) and col.get("name"):
            cfg = build_extraction_call_config(col)
            extraction_call_config[col["name"]] = {
                "temperature": cfg.temperature,
                "max_tokens": cfg.max_tokens,
                "require_verbatim_quote": cfg.require_verbatim_quote,
                "difficulty": cfg.difficulty,
            }

    schema_mapping_summary = build_schema_mapping_summary(
        columns,
        data.get("description", ""),
        row_granularity=state.get("extraction_row_granularity") or "one_row_per_document",
    )

    return {
        **state,
        "dataset_name": data.get("dataset_name", "custom_extraction"),
        "dataset_description": data.get("description", ""),
        "proposed_columns": columns,
        "schema_mapping_summary": schema_mapping_summary,
        "extraction_call_config": extraction_call_config,
        "extraction_call_config_rationale": data.get("config_rationale", ""),
        "schema_approved": False,
        "schema_feedback": "",
        "schema_iteration": state.get("schema_iteration", 0) + 1,
        "identity_fields": identity_fields,
        "error": "",
    }


def _apply_structured(state: DatasetState, out: _SchemaDesignOut) -> DatasetState:
    """Build updated state from a validated instructor-parsed schema output.

    Also auto-populates keywords for any column where the LLM didn't provide them,
    using NLP term extraction from the extraction_instruction + description.
    """
    from prompt2dataset.dataset_graph.mapping_contract import (
        build_schema_mapping_summary,
        default_value_cardinality_for_column,
    )
    from prompt2dataset.utils.call_config import ensure_keywords
    corpus_topic = state.get("corpus_topic", "")

    columns = []
    for col in out.columns:
        col_dict = col.model_dump()
        # Auto-populate keywords from extraction_instruction if LLM skipped them
        col_dict["keywords"] = ensure_keywords(col_dict, corpus_topic)
        # Normalize difficulty
        if not col_dict.get("difficulty"):
            col_dict["difficulty"] = "standard"
        if not col_dict.get("value_cardinality"):
            col_dict["value_cardinality"] = default_value_cardinality_for_column(col_dict)
        elif col_dict["value_cardinality"] not in ("single_best", "combine_all_occurrences"):
            col_dict["value_cardinality"] = default_value_cardinality_for_column(col_dict)
        columns.append(col_dict)

    if not columns:
        return {**state, "error": "LLM returned empty columns list"}

    identity_fields = state.get("identity_fields") or SEDAR_IDENTITY_FIELDS

    # Build per-field extraction call config from difficulty
    from prompt2dataset.utils.call_config import build_extraction_call_config
    extraction_call_config = {}
    for col in columns:
        cfg = build_extraction_call_config(col)
        extraction_call_config[col["name"]] = {
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "require_verbatim_quote": cfg.require_verbatim_quote,
            "difficulty": cfg.difficulty,
        }

    schema_mapping_summary = build_schema_mapping_summary(
        columns,
        out.description or "",
        row_granularity=state.get("extraction_row_granularity") or "one_row_per_document",
    )

    return {
        **state,
        "dataset_name": out.dataset_name or "custom_extraction",
        "dataset_description": out.description,
        "proposed_columns": columns,
        "schema_mapping_summary": schema_mapping_summary,
        "extraction_call_config": extraction_call_config,
        "extraction_call_config_rationale": out.config_rationale,
        "schema_approved": False,
        "schema_feedback": "",
        "schema_iteration": state.get("schema_iteration", 0) + 1,
        "identity_fields": identity_fields,
        "error": "",
    }


def schema_node(state: DatasetState) -> DatasetState:
    """Call the LLM to design (or refine) an extraction schema from the user query.

    Synchronous version — uses instructor for structured Pydantic output with
    automatic retry on JSON parse failure. Falls back to raw parsing on error.
    """
    cfg = get_settings()

    # Intent capture on first schema iteration
    if not state.get("schema_iteration") or state.get("schema_iteration", 0) == 0:
        user_query = state.get("user_query", "")
        intent = extract_intent_from_first_message(user_query)
        state = {**state, "_intent_capture": intent}

    # Homogeneity detection from available chunks
    chunk_samples = _get_chunk_samples(state, cfg)
    if chunk_samples:
        homogeneity = detect_corpus_homogeneity(chunk_samples)
        state = {**state, "corpus_homogeneity": homogeneity}

    messages, _ = _build_messages(state, cfg)

    logger.info(
        "schema_node: calling LLM (iteration %d, eval_window_min=%d)",
        state.get("schema_iteration", 0) + 1,
        state.get("eval_window_min", 6),
    )
    try:
        raw_client = OpenAI(
            base_url=cfg.vllm_base_url,
            api_key=cfg.vllm_api_key,
            timeout=float(cfg.vllm_timeout_sec),
        )
        client = instructor.from_openai(raw_client, mode=instructor.Mode.JSON)
        out: _SchemaDesignOut = client.chat.completions.create(
            model=cfg.vllm_model_name,
            messages=messages,
            response_model=_SchemaDesignOut,
            temperature=0.2,
            max_tokens=CONTEXT_BUDGET["schema_max_out"],
            max_retries=3,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        return _apply_structured(state, out)
    except Exception as exc:
        logger.error("schema_node: LLM call failed: %s", exc)
        return {**state, "error": f"vLLM unreachable or schema parse failed: {exc}"}


def schema_node_stream(
    state: DatasetState,
) -> Generator[tuple[str, DatasetState | None], None, None]:
    """Streaming version of schema_node.

    Yields (token: str, None) for each streaming token, then finally
    yields ("", final_state) so the caller can update state.

    Usage in Streamlit:
        full_text = ""
        final_state = state
        for token, new_state in schema_node_stream(state):
            if new_state is not None:
                final_state = new_state
            else:
                full_text += token
                # render token into chat bubble
    """
    cfg = get_settings()
    client = OpenAI(
        base_url=cfg.vllm_base_url,
        api_key=cfg.vllm_api_key,
        timeout=float(cfg.vllm_timeout_sec),
    )

    # Intent capture on first schema iteration
    if not state.get("schema_iteration") or state.get("schema_iteration", 0) == 0:
        user_query = state.get("user_query", "")
        intent = extract_intent_from_first_message(user_query)
        state = {**state, "_intent_capture": intent}

    # Homogeneity detection from available chunks
    chunk_samples = _get_chunk_samples(state, cfg)
    if chunk_samples:
        homogeneity = detect_corpus_homogeneity(chunk_samples)
        state = {**state, "corpus_homogeneity": homogeneity}

    messages, _ = _build_messages(state, cfg)

    logger.info("schema_node_stream: streaming response (iteration %d)", state.get("schema_iteration", 0) + 1)

    try:
        stream = client.chat.completions.create(
            model=cfg.vllm_model_name,
            messages=messages,
            temperature=0.2,
            max_tokens=CONTEXT_BUDGET["schema_max_out"],
            stream=True,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        full_text = ""
        for chunk in stream:
            token = (chunk.choices[0].delta.content or "") if chunk.choices else ""
            if token:
                full_text += token
                yield token, None

        final_state = _apply_result(state, full_text)
        yield "", final_state

    except Exception as exc:
        logger.error("schema_node_stream: LLM call failed: %s", exc)
        yield "", {**state, "error": f"vLLM unreachable: {exc}"}
