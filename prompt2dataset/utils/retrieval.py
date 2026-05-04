"""Evidence retrieval for extraction — aligned with schema design.

Schema approval produces :pyattr:`keywords` and extraction instructions per column.
Those fields drive **one** query representation used consistently for:

- **LanceDB hybrid search** (dense vectors + BM25 on the chunk index), when
  ``corpus_id`` / ``doc_id`` are available
- **BM25Plus** over the per-document chunk parole (lexical view of the same intent)
- **Cross-encoder reranking** (same natural-language query string as hybrid search)

So semantic search is not a separate ad-hoc probe: it consumes the same
schema-authored signals the extraction prompt uses. Optional ``corpus_topic``
extends the hybrid / rerank query when the topic adds retrieval context not
already embedded in column text.
"""
from __future__ import annotations

import logging
import math
import os
import random
import re
from collections.abc import Sequence
from dataclasses import dataclass, field as dc_field
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from prompt2dataset.dataset_graph.state import SchemaColumn

logger = logging.getLogger(__name__)

# Match cap in ``build_extraction_user_prompt`` so sanitization aligns with prompt slicing.
try:
    from prompt2dataset.prompts.dataset_prompt import EXTRACTION_EVIDENCE_BLOCK_CHARS
except Exception:  # pragma: no cover
    EXTRACTION_EVIDENCE_BLOCK_CHARS = 700

# ── Constants ─────────────────────────────────────────────────────────────────

BM25_TOP_K = int(os.environ.get("RETRIEVAL_BM25_TOP_K", "20"))
# Align with EXTRACTION_MAX_EVIDENCE_BLOCKS (12): rerank pool feeds the extraction prompt.
RERANKER_TOP_N = int(os.environ.get("RETRIEVAL_RERANK_TOP_N", "12"))
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# ── Lazy singletons ───────────────────────────────────────────────────────────

_reranker = None
_reranker_attempted = False


def _get_reranker():
    global _reranker, _reranker_attempted
    if _reranker_attempted:
        return _reranker
    _reranker_attempted = True
    try:
        from sentence_transformers import CrossEncoder
        _reranker = CrossEncoder(RERANKER_MODEL)
        logger.info("retrieval: cross-encoder loaded (%s)", RERANKER_MODEL)
    except Exception as exc:
        logger.warning("retrieval: cross-encoder not available (%s) — using BM25 top-%d only", exc, BM25_TOP_K)
        _reranker = None
    return _reranker


# ── Tokeniser ─────────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenise(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


# ── BM25Plus index ────────────────────────────────────────────────────────────

def build_bm25_index(chunks_df: pd.DataFrame):
    """Build a BM25Plus index over the text column of a chunk DataFrame.

    Returns (bm25_index, chunk_rows) where chunk_rows is a list of row dicts
    in the same order as the BM25 corpus.  Returns (None, []) if the DataFrame
    is empty or rank_bm25 is not installed.
    """
    if chunks_df.empty:
        return None, []

    try:
        from rank_bm25 import BM25Plus
    except ImportError:
        logger.warning("retrieval: rank_bm25 not installed — falling back to sequential chunks")
        return None, []

    rows = chunks_df.to_dict("records")
    corpus = [_tokenise(str(r.get("text", ""))) for r in rows]
    try:
        bm25 = BM25Plus(corpus)
    except Exception as exc:
        logger.warning("retrieval: BM25Plus index build failed: %s", exc)
        return None, []

    return bm25, rows


# ── Query construction ────────────────────────────────────────────────────────

def _query_tokens_from_schema(schema_cols: list["SchemaColumn"]) -> list[str]:
    """Build a flat token list from all schema column keywords.

    Uses `col["keywords"]` (first-class field) if present, otherwise falls
    back to tokenising `col["extraction_instruction"]` — no LLM call is made.
    """
    tokens: list[str] = []
    for col in schema_cols:
        kws = col.get("keywords")
        if kws and isinstance(kws, list):
            for kw in kws:
                tokens.extend(_tokenise(str(kw)))
        else:
            instr = col.get("extraction_instruction") or col.get("description") or ""
            tokens.extend(_tokenise(instr)[:20])  # cap to avoid inflating low-signal prompts
    return list(set(tokens)) or ["document"]  # ensure non-empty query


def _query_string_from_schema(schema_cols: list["SchemaColumn"]) -> str:
    """Human-readable query string for the cross-encoder."""
    parts: list[str] = []
    for col in schema_cols:
        kws = col.get("keywords")
        if kws and isinstance(kws, list):
            parts.append(" ".join(str(k) for k in kws[:5]))
        else:
            parts.append(str(col.get("extraction_instruction") or col.get("name") or "")[:80])
    return " | ".join(p for p in parts if p)[:400]


REFINEMENT_QUERY_MAX_CHARS = 520


def effective_retrieval_query_string(
    schema_cols: list["SchemaColumn"],
    corpus_topic: str | None = None,
    query_override: str | None = None,
) -> str:
    """Schema-aligned query, or ``query_override`` when the scout provides a hop query."""
    q = (query_override or "").strip()
    if q:
        return q[:REFINEMENT_QUERY_MAX_CHARS]
    return semantic_query_string(schema_cols, corpus_topic)


def semantic_query_string(
    schema_cols: list["SchemaColumn"],
    corpus_topic: str | None = None,
) -> str:
    """Single query text for Lance hybrid + cross-encoder (schema-first, topic augments).

    Matches what schema design encodes in ``keywords`` and instructions; corpus_topic
    is appended only when it adds non-redundant retrieval context.
    """
    base = _query_string_from_schema(schema_cols)
    ct = (corpus_topic or "").strip()
    if not ct:
        return base
    if len(ct) > 12 and ct.lower()[: min(80, len(ct))] in base.lower():
        return base
    combined = f"{base} | {ct}"
    return combined[:520]


def _finalize_evidence_blocks(blocks: list[dict]) -> list[dict]:
    """Strip parser garbage and cap block length before prompts / rerankers see text."""
    from prompt2dataset.utils.context_sanitize import sanitize_evidence_text

    cap = int(EXTRACTION_EVIDENCE_BLOCK_CHARS)
    out: list[dict] = []
    for b in blocks:
        bb = dict(b)
        bb["text"] = sanitize_evidence_text(str(bb.get("text", "")), max_len=cap)
        out.append(bb)
    return out


def _dedupe_blocks(blocks: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for b in blocks:
        cid = str(b.get("chunk_id", ""))
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append(b)
    return out


def merge_evidence_block_lists(
    *lists: list[dict],
    max_total: int = 12,
) -> list[dict]:
    """Merge evidence block lists in order; dedupe by ``chunk_id``; cap to ``max_total``."""
    merged: list[dict] = []
    for lst in lists:
        for b in lst or []:
            merged.append(b)
    return _dedupe_blocks(merged)[: max(0, int(max_total))]


# ── Stigmergic retrieval: hunger, optional anneal, substrate placeholder ───────


def field_pressure_for_doc(dataset_state: dict[str, Any] | None, doc_id: str) -> dict[str, float]:
    """Per-document ``field_pressure`` from ``epistemic_blackboard`` (normalized root)."""
    from prompt2dataset.utils.epistemic_blackboard import normalize_epistemic_root

    if not dataset_state:
        return {}
    root = normalize_epistemic_root(dataset_state.get("epistemic_blackboard"))
    inner = root.get(str(doc_id)) or {}
    if not isinstance(inner, dict):
        return {}
    fp = inner.get("field_pressure") or {}
    out: dict[str, float] = {}
    if isinstance(fp, dict):
        for k, v in fp.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
    return out


def hunger_boost_top_k(
    schema_cols: list["SchemaColumn"],
    field_pressure: dict[str, float] | None,
    *,
    bonus: int,
) -> int:
    """Extra BM25 pool depth from normalized max pressure (cap ``bonus``)."""
    if not field_pressure or bonus <= 0 or not schema_cols:
        return 0
    vals = [
        float(field_pressure.get(str(c.get("name", "")), 0.0))
        for c in schema_cols
        if c.get("name")
    ]
    if not vals:
        return 0
    frac = min(1.0, max(vals) / 10.0)
    return int(round(bonus * frac))


def _block_energy_anneal(block: dict[str, Any]) -> float:
    t = len(str(block.get("text", "")))
    return abs(t - 400) / 400.0


def annealed_reorder_blocks(
    blocks: Sequence[dict[str, Any]],
    *,
    scores: Sequence[float] | None = None,
    steps: int = 40,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Permute chunk order with a short simulated-annealing walk (keeps multiset)."""
    if not blocks or steps <= 0:
        return list(blocks)
    rng = random.Random(seed)
    order = list(range(len(blocks)))

    def energy(perm: list[int]) -> float:
        e = 0.0
        for pos, i in enumerate(perm):
            e += _block_energy_anneal(blocks[i]) * (1.0 + 0.02 * pos)
            if scores is not None and 0 <= i < len(scores):
                e -= 0.15 * float(scores[i])
        return e

    e_cur = energy(order)
    temp = 1.0
    for _ in range(steps):
        if len(order) < 2:
            break
        i, j = rng.randrange(len(order)), rng.randrange(len(order))
        if i == j:
            continue
        order[i], order[j] = order[j], order[i]
        e_new = energy(order)
        de = e_new - e_cur
        if de < 0 or rng.random() < math.exp(-de / max(1e-6, temp)):
            e_cur = e_new
        else:
            order[i], order[j] = order[j], order[i]
        temp = max(0.05, temp * 0.97)
    return [blocks[idx] for idx in order]


def augment_evidence_with_substrate(
    doc_id: str,
    blocks: list[dict[str, Any]],
    *,
    dataset_state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Placeholder: return ``blocks`` unchanged (no cross-repo substrate dependency)."""
    _ = (doc_id, dataset_state)
    return list(blocks or [])


# ── Cross-encoder reranker ────────────────────────────────────────────────────

def rerank_with_cross_encoder(
    query_str: str,
    blocks: list[dict],
    top_n: int = RERANKER_TOP_N,
) -> list[dict]:
    """Rerank blocks using the cross-encoder; returns top_n or all if fewer."""
    reranker = _get_reranker()
    if reranker is None or not blocks:
        return blocks[:top_n]

    try:
        pairs = [(query_str, str(b.get("text", ""))) for b in blocks]
        scores = reranker.predict(pairs)
        ranked = sorted(zip(scores, blocks), key=lambda x: x[0], reverse=True)
        return [b for _, b in ranked[:top_n]]
    except Exception as exc:
        logger.warning("retrieval: cross-encoder inference failed (%s) — using BM25 order", exc)
        return blocks[:top_n]


# ── Main retrieval entry point ────────────────────────────────────────────────

def _hunger_adjust_top(
    top_k: int,
    top_n: int,
    schema_cols: list["SchemaColumn"],
    dataset_state: dict[str, Any] | None,
    doc_id: str | None,
) -> tuple[int, int]:
    try:
        from prompt2dataset.utils.prompt2dataset_settings import load_prompt2dataset_config

        cfg = load_prompt2dataset_config()
        if not cfg.retrieval_hunger_weight_retrieval or not dataset_state or not doc_id:
            return top_k, top_n
        fp = field_pressure_for_doc(dataset_state, str(doc_id))
        b = hunger_boost_top_k(schema_cols, fp, bonus=cfg.retrieval_hunger_top_k_bonus)
        return min(top_k + b, 96), min(top_n + max(0, b // 2), 24)
    except Exception:
        return top_k, top_n


def _finalize_blocks_pipeline(
    blocks: list[dict],
    *,
    dataset_state: dict[str, Any] | None,
    doc_id: str | None,
) -> list[dict]:
    out = augment_evidence_with_substrate(str(doc_id or ""), list(blocks or []), dataset_state=dataset_state)
    try:
        from prompt2dataset.utils.prompt2dataset_settings import load_prompt2dataset_config

        n = int(load_prompt2dataset_config().retrieval_anneal_walk_steps)
    except Exception:
        n = 0
    if n > 0 and out:
        out = annealed_reorder_blocks(out, steps=n)
    return _finalize_evidence_blocks(out)


def retrieve_evidence_blocks(
    schema_cols: list["SchemaColumn"],
    doc_chunks_df: pd.DataFrame,
    top_k: int = BM25_TOP_K,
    top_n: int = RERANKER_TOP_N,
    *,
    doc_id: str | None = None,
    corpus_id: str | None = None,
    corpus_topic: str | None = None,
    use_lance: bool = True,
    query_override: str | None = None,
    dataset_state: dict[str, Any] | None = None,
) -> tuple[list[dict], int, int]:
    """Retrieve the best evidence blocks for one document.

    ``corpus_id`` selects the LanceDB table ``chunks_<corpus_id>`` (see DuckDB
    ``corpus_registry`` in :mod:`prompt2dataset.utils.document_catalog`).

    **Semantic / hybrid (LanceDB):** uses :func:`semantic_query_string` — the same
    schema ``keywords`` + instructions (and optional ``corpus_topic``) that shape
    the extraction prompt — unless ``query_override`` is set (e.g. hypothesis-driven
    second pass). Hybrid hits are then **cross-encoder reranked** with that string.

    **Fallback:** BM25Plus on parquet chunks for this doc, then the same reranker.

    Returns:
        blocks      — top_n evidence block dicts (text, chunk_id, page_start, page_end, section_path)
        total       — total chunks in doc_chunks_df
        keyword_hits— number of pre-tagged keyword_hit=True chunks
    """
    q_semantic = effective_retrieval_query_string(
        schema_cols, corpus_topic, query_override=query_override
    )
    top_k, top_n = _hunger_adjust_top(top_k, top_n, schema_cols, dataset_state, doc_id)

    # ── LanceDB hybrid search (schema-aligned query) ──────────────────────────
    if use_lance and doc_id and corpus_id:
        try:
            from prompt2dataset.utils.lance_store import (  # noqa: PLC0415
                LanceStoreUnavailable,
                corpus_table_exists,
                lance_hybrid_search,
            )
            if corpus_table_exists(corpus_id):
                lance_results = lance_hybrid_search(q_semantic, corpus_id, doc_id, k=top_k)
                if lance_results:
                    blocks = [
                        {
                            "chunk_id": r.get("chunk_id", ""),
                            "text": r.get("text", ""),
                            "section_path": r.get("section_path", ""),
                            "page_start": r.get("page_start", 0),
                            "page_end": r.get("page_end", 0),
                        }
                        for r in lance_results
                    ]
                    total = len(doc_chunks_df) if doc_chunks_df is not None and len(doc_chunks_df) else len(lance_results)
                    kw_hits = sum(1 for r in lance_results if r.get("keyword_hit"))
                    blocks = rerank_with_cross_encoder(q_semantic, blocks, top_n=top_n)
                    return _finalize_blocks_pipeline(blocks, dataset_state=dataset_state, doc_id=doc_id), total, kw_hits
        except (LanceStoreUnavailable, Exception) as exc:
            logger.debug(
                "retrieve_evidence_blocks: LanceDB not available (%s), falling back to BM25", exc
            )

    total = len(doc_chunks_df)
    if total == 0:
        return [], 0, 0

    # ── Step 1: count and separate keyword-hit chunks ──────────────────────────
    kw_col = "keyword_hit" if "keyword_hit" in doc_chunks_df.columns else None
    if kw_col:
        kw_df = doc_chunks_df[doc_chunks_df[kw_col].astype(bool)]
        keyword_hits = len(kw_df)
    else:
        kw_df = pd.DataFrame()
        keyword_hits = 0

    # ── Step 2: choose the BM25 pool ──────────────────────────────────────────
    MIN_KW_POOL = 3
    use_kw_only = bool(kw_col and len(kw_df) >= MIN_KW_POOL)
    bm25_pool = kw_df if use_kw_only else doc_chunks_df  # else full doc

    bm25, rows = build_bm25_index(bm25_pool)

    if bm25 is None:
        # rank_bm25 not available — prefer keyword chunks, pad with sequential
        if kw_col and not kw_df.empty:
            kw_rows = kw_df.to_dict("records")
            rest = doc_chunks_df[~doc_chunks_df[kw_col].astype(bool)].head(max(0, top_n - len(kw_rows))).to_dict("records")
            fallback_rows = (kw_rows + rest)[:top_n]
        else:
            fallback_rows = doc_chunks_df.head(top_n).to_dict("records")
        return (
            _finalize_blocks_pipeline(
                _rows_to_blocks(fallback_rows),
                dataset_state=dataset_state,
                doc_id=doc_id,
            ),
            total,
            keyword_hits,
        )

    # ── Step 3: BM25 ranking within the pool ──────────────────────────────────
    qo = (query_override or "").strip()
    if qo:
        query_tokens = _tokenise(qo) or _query_tokens_from_schema(schema_cols)
    else:
        query_tokens = _query_tokens_from_schema(schema_cols)
    scores = bm25.get_scores(query_tokens)
    max_s = float(max(scores)) if len(scores) else 0.0

    # Keyword-hit chunks follow *corpus* topic rules at chunk time; the extraction
    # *schema* may ask for narrower terms than chunk-time tagging. If BM25 finds
    # almost nothing in the keyword-only pool, search the full document.
    if use_kw_only and max_s < 1e-6:
        bm25_full, rows_full = build_bm25_index(doc_chunks_df)
        if bm25_full is not None:
            alt = bm25_full.get_scores(query_tokens)
            if alt is not None and len(alt) and float(max(alt)) > max_s:
                bm25, rows = bm25_full, rows_full
                scores = alt
                logger.debug(
                    "retrieve_evidence_blocks: expanded pool full-doc (kw-only BM25 too weak: %.2e)",
                    max_s,
                )

    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    top_rows = [rows[i] for i, _s in indexed[:top_k]]
    if not top_rows:
        top_rows = rows[:top_k]

    blocks = _rows_to_blocks(top_rows)

    # ── Step 4: rerank (same schema-aligned string as hybrid path) ───────────
    blocks = rerank_with_cross_encoder(q_semantic, blocks, top_n=top_n)

    return _finalize_blocks_pipeline(blocks, dataset_state=dataset_state, doc_id=doc_id), total, keyword_hits


def retrieve_refinement_blocks(
    query: str,
    schema_cols: list["SchemaColumn"],
    doc_chunks_df: pd.DataFrame,
    top_k: int = BM25_TOP_K,
    top_n: int = 8,
    *,
    doc_id: str | None = None,
    corpus_id: str | None = None,
    corpus_topic: str | None = None,
    use_lance: bool = True,
    dataset_state: dict[str, Any] | None = None,
) -> tuple[list[dict], int, int]:
    """Second-pass retrieval for multipass extraction (hypothesis-driven query text)."""
    return retrieve_evidence_blocks(
        schema_cols,
        doc_chunks_df,
        top_k=top_k,
        top_n=top_n,
        doc_id=doc_id,
        corpus_id=corpus_id,
        corpus_topic=corpus_topic,
        use_lance=use_lance,
        query_override=query,
        dataset_state=dataset_state,
    )


def _rows_to_blocks(rows: list[dict]) -> list[dict]:
    return [
        {
            "chunk_id": str(r.get("chunk_id", "")),
            "text": str(r.get("text", "")),
            "section_path": str(r.get("section_path", "")),
            "page_start": r.get("page_start", 0),
            "page_end": r.get("page_end", 0),
        }
        for r in rows
    ]


# ── Adaptive retrieval config ──────────────────────────────────────────────────

@dataclass
class RetrievalConfig:
    """Parameters for one retrieval call."""
    k: int = 20
    score_threshold: float = 0.0
    include_adjacent_chunks: bool = False
    expand_query: bool = False
    note: str = ""


def adaptive_retrieval_config(
    field_col: "SchemaColumn",
    previous_attempt: dict | None,
    *,
    base_k: int = BM25_TOP_K,
    base_threshold: float = 0.0,
) -> RetrievalConfig:
    """Derive the next retrieval config from the prior extraction outcome.

    Called after a failed or flagged extraction attempt. Uses the prior
    LLM output's `not_found_reason` and `_flag_evidenceless` signals to
    escalate retrieval depth — fully deterministic, no LLM.

    Args:
        field_col: the SchemaColumn being retrieved for
        previous_attempt: a row dict or CellRecord dict from the prior attempt,
                          or None for the first attempt
        base_k: baseline retrieval k from the schema-recommended config
        base_threshold: baseline score threshold

    Returns:
        RetrievalConfig with adjusted parameters
    """
    if previous_attempt is None:
        return RetrievalConfig(k=base_k, score_threshold=base_threshold)

    not_found = bool(previous_attempt.get("not_found_reason"))
    evidenceless = bool(previous_attempt.get("_flag_evidenceless"))

    if not_found:
        return RetrievalConfig(
            k=min(base_k * 2, 60),
            score_threshold=max(0.0, base_threshold * 0.8),
            include_adjacent_chunks=True,
            note="escalated: not_found_reason in prior attempt",
        )
    if evidenceless:
        return RetrievalConfig(
            k=base_k,
            score_threshold=max(0.0, base_threshold * 0.6),
            expand_query=True,
            note="escalated: _flag_evidenceless in prior attempt",
        )

    return RetrievalConfig(k=base_k, score_threshold=base_threshold)
