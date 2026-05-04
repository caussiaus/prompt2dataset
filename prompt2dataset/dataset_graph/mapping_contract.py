"""Human- and LLM-facing contract: how schema columns map to one row per PDF.

The pipeline exports **one flat row per document** by default. Multiple facts inside
a PDF are handled either by picking a single best value per column or by combining
occurrences into one cell, depending on ``value_cardinality`` on each column.
"""
from __future__ import annotations

from typing import Any


def build_schema_mapping_summary(
    columns: list[dict[str, Any]],
    dataset_description: str = "",
    *,
    row_granularity: str = "one_row_per_document",
) -> str:
    """Short markdown-free text block for extraction prompts and the Streamlit UI."""
    lines: list[str] = []
    lines.append("DATASET ROW MODEL")
    lines.append(
        "Each CSV row = one PDF (one doc_id). Identity columns come from the corpus index; "
        "schema columns are filled only from evidence blocks."
    )
    lines.append(f"Row granularity option: {row_granularity} — see extraction policy in the UI.")
    if dataset_description.strip():
        lines.append(f"Dataset intent: {dataset_description.strip()[:400]}")
    lines.append("PER-COLUMN MAP (how many PDF mentions go into one cell)")
    for c in columns:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name", "")).strip()
        if not name:
            continue
        card = (c.get("value_cardinality") or default_value_cardinality_for_column(c)).strip()
        desc = (c.get("description") or "")[:160]
        instr = (c.get("extraction_instruction") or "")[:220]
        if card == "combine_all_occurrences":
            lines.append(
                f"- {name} [COMBINE ALL]: Merge every relevant occurrence in this doc into one "
                f"cell (counts, joined lists, or semicolon-separated values). {desc}"
            )
        else:
            lines.append(
                f"- {name} [SINGLE BEST]: One value per doc — choose the strongest match to the "
                f"instruction; do not average unrelated facts. {desc}"
            )
        if instr:
            lines.append(f"  Instruction: {instr}")
    lines.append(
        "EVIDENCE: For each field, return companion {field}_evidence with quote, chunk_id, "
        "page_start, page_end from the blocks."
    )
    return "\n".join(lines)


def default_value_cardinality_for_column(col: dict[str, Any]) -> str:
    """Infer a sensible default when the schema LLM omits value_cardinality."""
    name = str(col.get("name", "")).lower()
    typ = str(col.get("type", "")).lower()
    if any(x in name for x in ("count", "total", "number_of", "num_")):
        return "combine_all_occurrences"
    if "integer" in typ or typ == "number":
        return "combine_all_occurrences"
    return "single_best"
