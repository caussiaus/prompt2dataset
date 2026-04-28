"""Per-field LLM call configuration derived from schema difficulty.

Maps SchemaColumn.difficulty → temperature, max_tokens, and verbatim-quote
requirements. Fully deterministic — no LLM. Used by extraction_node and
PromptRouter to configure each field's extraction call independently.

Difficulty levels set by schema_node LLM:
  trivial   — field always appears explicitly (e.g. "company name")
  standard  — clear numeric or categorical field (e.g. "total assets")
  ambiguous — requires judgment (e.g. "risk level" — qualitative)
  inferred  — requires synthesis across multiple chunks (e.g. "ESG trend")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from prompt2dataset.dataset_graph.state import SchemaColumn


# ── Temperature map (deterministic, not learned) ──────────────────────────────

TEMPERATURE_MAP: dict[str, float] = {
    "trivial":   0.0,
    "standard":  0.05,
    "ambiguous": 0.2,
    "inferred":  0.35,
}

MAX_TOKENS_MAP: dict[str, int] = {
    "trivial":   150,
    "standard":  150,
    "ambiguous": 350,
    "inferred":  350,
}

REQUIRE_VERBATIM_MAP: dict[str, bool] = {
    "trivial":   True,
    "standard":  True,
    "ambiguous": True,
    "inferred":  False,   # synthesis fields may not have a single verbatim quote
}


@dataclass
class CallConfig:
    """LLM call parameters for a single extraction field."""
    temperature: float
    max_tokens: int
    require_verbatim_quote: bool
    field_name: str = ""
    difficulty: str = "standard"


def build_extraction_call_config(col: SchemaColumn) -> CallConfig:
    """Return per-field call config derived from SchemaColumn.difficulty.

    Falls back to "standard" if difficulty is missing or unrecognised.
    """
    diff = str(col.get("difficulty") or "standard").lower()
    if diff not in TEMPERATURE_MAP:
        diff = "standard"

    return CallConfig(
        field_name=col.get("name", ""),
        difficulty=diff,
        temperature=TEMPERATURE_MAP[diff],
        max_tokens=MAX_TOKENS_MAP[diff],
        require_verbatim_quote=REQUIRE_VERBATIM_MAP[diff],
    )


def default_call_config() -> CallConfig:
    """Return the standard-difficulty call config."""
    return build_extraction_call_config({"name": "", "difficulty": "standard"})


_DIFFICULTY_RANK = {"trivial": 0, "standard": 1, "ambiguous": 2, "inferred": 3}


def effective_temperature(columns: list) -> float:
    """Return the extraction temperature for a batch of columns.

    Uses the highest-difficulty column's temperature so that ambiguous / inferred
    fields get enough reasoning room. Pure trivial/standard batches stay tight.
    """
    if not columns:
        return TEMPERATURE_MAP["standard"]
    max_rank = max(
        _DIFFICULTY_RANK.get(str(col.get("difficulty") or "standard").lower(), 1)
        for col in columns
    )
    difficulty = ["trivial", "standard", "ambiguous", "inferred"][max_rank]
    return TEMPERATURE_MAP[difficulty]


# ── Keyword auto-population ────────────────────────────────────────────────────

def ensure_keywords(
    col: SchemaColumn,
    corpus_topic: str = "",
) -> list[str]:
    """Return populated keyword list for a SchemaColumn.

    If col already has keywords, returns them unchanged.
    Otherwise generates them from the extraction_instruction + description using
    NLP term extraction — no LLM call.
    """
    existing = col.get("keywords") or []
    if existing:
        return existing

    instruction = col.get("extraction_instruction") or ""
    description = col.get("description") or ""
    context_text = f"{instruction} {description}".strip()

    if not context_text:
        # Last resort: use field name words
        name = col.get("name", "")
        return [w for w in name.replace("_", " ").split() if len(w) > 2]

    try:
        from prompt2dataset.utils.nlp_utils import generate_field_keywords
        return generate_field_keywords(context_text, topic=corpus_topic, n=12)
    except Exception:
        # Fallback: split on whitespace, keep alpha tokens > 3 chars
        tokens = [
            t.strip(".,;:'\"()[]") for t in context_text.split()
            if len(t.strip(".,;:'\"()[]")) > 3
        ]
        return list(dict.fromkeys(tokens))[:12]  # deduplicate, preserve order


def enrich_proposed_columns_for_extraction(
    columns: list,
    corpus_topic: str = "",
) -> list[dict]:
    """Normalize imported / pasted schemas so extraction + retrieval behave like schema_node.

    Fills ``keywords``, ``difficulty``, ``value_cardinality`` when missing — imported
    JSON often skips these, which weakens BM25 and leaves defaults ambiguous.
    """
    try:
        from prompt2dataset.dataset_graph.mapping_contract import (
            default_value_cardinality_for_column,
        )
    except Exception:
        default_value_cardinality_for_column = None  # type: ignore

    out: list[dict] = []
    for c in columns:
        if not isinstance(c, dict):
            continue
        col = dict(c)
        col["keywords"] = ensure_keywords(col, corpus_topic)
        if not col.get("difficulty"):
            col["difficulty"] = "standard"
        if default_value_cardinality_for_column:
            if not col.get("value_cardinality"):
                col["value_cardinality"] = default_value_cardinality_for_column(col)
            elif col.get("value_cardinality") not in ("single_best", "combine_all_occurrences"):
                col["value_cardinality"] = default_value_cardinality_for_column(col)
        out.append(col)
    return out
