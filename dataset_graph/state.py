"""LangGraph state types for the interactive dataset generation pipeline.

Variable naming convention: all names describe behaviour, not a domain.
SEDAR/tariff-specific column names (filing_id, ticker, etc.) are handled
via CorpusConfig.identity_fields — they map to the generic names used here
(doc_id, entity_slug, entity_name, doc_date, context_category, context_tag).
"""
from __future__ import annotations

import logging
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema column definition
# ---------------------------------------------------------------------------

class SchemaColumn(TypedDict, total=False):
    name: str
    type: str           # "boolean", "string", "string|null", "integer", "number|null", …
    description: str
    extraction_instruction: str
    keywords: list[str] # first-class BM25 query source — set at schema approval time
    default: Any        # null, false, 0, or ""
    mode: str           # "direct" | "evidence" — see ExtractionMode below
    difficulty: str     # "trivial" | "standard" | "ambiguous" | "inferred" — drives temperature
    # How multiple mentions in one PDF map into this single cell (one row per PDF)
    value_cardinality: str  # "single_best" | "combine_all_occurrences"


# ---------------------------------------------------------------------------
# Cell-level evidence — one span per field per row
# ---------------------------------------------------------------------------

class EvidenceSpan(TypedDict, total=False):
    chunk_id: str
    quote: str          # verbatim excerpt (≤80 words) that supports the cell value
    page_start: int
    page_end: int
    section_path: str
    relevance: str      # "direct" | "adjacent" | "indirect"


class EvidenceEdge(TypedDict, total=False):
    """One provenance hop inside ``evidence_dag[field_name]``."""
    source_chunk: str
    target_chunk: str
    reasoning: str


class BeliefProposal(TypedDict, total=False):
    belief_id: str
    field_name: str
    hypothesis: str
    confidence: float
    evidence_chunk_id: str


class EpistemicBlackboard(TypedDict, total=False):
    """Serializable L1 backpack for one document (no graph objects)."""
    beliefs: list[BeliefProposal]
    field_pressure: dict[str, float]
    evidence_dag: dict[str, list[EvidenceEdge]]


class FieldEpistemicState(TypedDict, total=False):
    """Optional richer per-field epistemics (kept small for checkpoints)."""
    confidence: float
    frustration: float
    curiosity_signal: float


class EvidenceChainNode(TypedDict, total=False):
    chunk_id: str
    role: str
    summary: str


class EvidenceChain(TypedDict, total=False):
    """Ordered reasoning over chunks for one field (synthesis output)."""
    field_name: str
    nodes: list[EvidenceChainNode]
    reasoning_edges: list[dict[str, Any]]


class CellRecord(TypedDict, total=False):
    row_id: str         # == doc_id (canonical row anchor)
    field_name: str
    proposed_value: Any
    evidence: EvidenceSpan | None
    decision: str       # "proposed" | "approved" | "rejected" | "overridden"
    override_value: Any
    override_reason: str
    evidence_chain: EvidenceChain | None
    # Consistency flags set by consistency_check
    flag_all_default: bool      # True if every field is its default value
    flag_evidenceless: bool     # True if value != default but evidence_quote is null


# ---------------------------------------------------------------------------
# Extraction mode
# ---------------------------------------------------------------------------

ExtractionMode = Literal["direct", "evidence"]
# direct   — "find field value in likely source chunks, return it"
# evidence — "collect candidate quotes first, then decide value from evidence"
#            Used for ambiguous / hard-to-find fields where absence ≠ certainty.


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------

class DatasetState(TypedDict, total=False):
    # ── User intent ──────────────────────────────────────────────────────
    user_query: str
    corpus_topic: str           # from CorpusConfig.topic; anchors schema design

    # ── Corpus scope ─────────────────────────────────────────────────────
    sample_doc_ids: list[str]   # if set, restrict trial extraction to these doc_ids
    use_sample: bool            # True during interactive design, False for full-corpus run

    # ── Document identity ─────────────────────────────────────────────────
    # Generic column names used in extracted rows. Populated from CorpusConfig.identity_fields.
    # SEDAR aliases: doc_id=filing_id, entity_name=issuer_name, entity_slug=ticker,
    #                doc_date=filing_date, context_category=naics_sector, context_tag=mechanism
    identity_fields: list[str]  # ordered list of columns that go in every output row

    # ── Schema design loop ───────────────────────────────────────────────
    schema_iteration: int
    dataset_name: str
    dataset_description: str
    proposed_columns: list[SchemaColumn]
    schema_mapping_summary: str   # auto-built: row model + per-column map for extraction/UI
    schema_approved: bool
    schema_feedback: str

    # ── Extraction policy (UI + graph) ─────────────────────────────────────
    # one_row_per_document: one output row per PDF (default).
    # one_row_per_fact: prompt guides model to prioritize the best-supported fact;
    #   additional items go in evidence_quote bullets until true multi-row is implemented.
    extraction_row_granularity: Literal["one_row_per_document", "one_row_per_fact"]

    # ── Extraction call configuration (set by schema_node, read by extraction_node) ──
    extraction_call_config: dict            # serialized ExtractionCallConfig per field
                                            # {field_name: {temperature, max_tokens, require_verbatim_quote, difficulty}}
    extraction_call_config_rationale: str   # why schema LLM recommends these extraction settings

    # ── Evaluation window (grounding schema in real document content) ─────
    eval_window_min: int        # min docs chunked before injecting samples (default 6)
    eval_window_max: int        # max docs to sample for schema grounding (default 10)

    # ── Extraction ───────────────────────────────────────────────────────
    extraction_mode: ExtractionMode     # "direct" or "evidence"
    extraction_done: bool
    rows: list[dict[str, Any]]          # flat dicts: identity + field values + evidence cols
    cells: list[CellRecord]             # structured cell records (parallel to rows)
    dataset_path: str
    cells_dataset_path: str             # JSONL written beside CSV on export (optional)

    # ── Consistency flags (set after each extraction batch) ───────────────
    consistency_flags: dict[str, Any]   # {"all_default_count": N, "evidenceless_count": M, ...}

    # ── Critique loop ────────────────────────────────────────────────────
    critique_text: str
    critique_suggestions: list[dict]    # list[{field, issue, severity, suggestion}]
    critique_quality: str               # "good" | "ok" | "needs_work"
    critique_config_deltas: list[dict]  # list[{field, config_delta, config_rationale}]
    critique_parse_ok: bool             # False when streamed output was not structured JSON
    critique_llm_raw: str              # verbatim model output (trimmed) for audit / replay
    # Validation council (when critique.council_enabled): per-reviewer traces + chairman epistemics
    critique_council_trace: list[dict]  # [{lens, overall_quality, field_issues, parse_ok, ...}, ...]
    critique_consensus: dict            # {reviewer_agreement_score, dissent_summary, consensus_rationale, ...}
    export_approved: bool

    # ── Rework loop ───────────────────────────────────────────────────────
    rework_count: int                   # number of rework cycles completed (max 3)

    # ── Feedback / versioning ────────────────────────────────────────────
    feedback_run_id: str                # UUID written to feedback store per session

    # ── Active corpus (Streamlit / multi-corpus) ──────────────────────────
    corpus_id: str                      # slug for LanceDB chunks_{corpus_id} + settings
    corpus_index_csv: str               # override for index; default = Settings.filings_index_path
    corpus_parse_index_csv: str         # docling_parse_index.csv for this run (parse OK vs chunk parity)
    corpus_chunks_parquet: str
    corpus_chunks_llm_parquet: str
    datasets_export_dir: str            # where custom dataset CSVs are written
    run_id: str                         # artifact isolation (Thread.run_id, corpus runs/{run_id})
    training_events_path: str           # optional override for trajectory JSONL path

    # ── Stigmergic epistemics (L1 backpack + wonder backlog) ──────────────
    # Keys are doc_id (or "__global__" for legacy merges). Values are JSON-serializable only.
    epistemic_blackboard: dict[str, EpistemicBlackboard]
    wonder_queue_preview: list[dict[str, Any]]  # recent wonder_queue.jsonl rows for UI

    # ── Internal ─────────────────────────────────────────────────────────
    error: str


# ---------------------------------------------------------------------------
# Generic identity field defaults (SEDAR backward-compat)
# ---------------------------------------------------------------------------

# These are the column names in the SEDAR corpus CSVs. Other corpora override
# via CorpusConfig.identity_fields. Code uses state["identity_fields"] to know
# which columns to carry as identity in every output row.
SEDAR_IDENTITY_FIELDS: list[str] = [
    "filing_id",        # doc_id for SEDAR
    "entity_id",        # canonical DuckDB / registry join key
    "ticker",           # entity_slug for SEDAR
    "issuer_name",      # entity_name for SEDAR
    "profile_number",   # source_ref for SEDAR
    "filing_date",      # doc_date for SEDAR
    "filing_type",      # doc_type for SEDAR
    "naics_sector",     # context_category for SEDAR
    "mechanism",        # context_tag for SEDAR
]

GENERIC_IDENTITY_FIELDS: list[str] = [
    "doc_id",
    "entity_id",
    "entity_name",
    "doc_date",
    "doc_type",
]


def resolve_identity_fields(
    state: "DatasetState",
    available_columns: list[str] | None = None,
) -> list[str]:
    """Return the best identity field list for this dataset.

    Priority:
      1. state["identity_fields"] (set by CorpusConfig or user)
      2. SEDAR_IDENTITY_FIELDS if the corpus has SEDAR-style columns
      3. GENERIC_IDENTITY_FIELDS as universal fallback
    """
    if state.get("identity_fields"):
        return state["identity_fields"]

    cols = set(available_columns or [])
    # If the dataset has SEDAR-style columns, use SEDAR fields
    sedar_signals = {"filing_id", "issuer_name", "profile_number", "naics_sector"}
    if cols & sedar_signals:
        return SEDAR_IDENTITY_FIELDS

    return GENERIC_IDENTITY_FIELDS


# ---------------------------------------------------------------------------
# Pydantic extraction gate
# ---------------------------------------------------------------------------

# Map schema type strings → Python annotation strings used in dynamic model
_SCHEMA_TYPE_TO_PY: dict[str, str] = {
    "boolean":      "bool",
    "bool":         "bool",
    "string":       "str",
    "string|null":  "str | None",
    "integer":      "int | None",
    "integer|null": "int | None",
    "number":       "float | None",
    "number|null":  "float | None",
    "float":        "float | None",
    "float|null":   "float | None",
}


def build_extraction_row_model(schema_cols: list[SchemaColumn]) -> type[BaseModel]:
    """Dynamically build a Pydantic model for one extraction row.

    Each column in schema_cols maps to a typed field with a sensible default.
    The model uses model_config(extra="ignore") so evidence companion keys
    returned by the LLM do not raise validation errors.

    Usage:
        RowModel = build_extraction_row_model(columns)
        try:
            validated = RowModel.model_validate(llm_json_dict)
            row_values = validated.model_dump()
        except ValidationError as exc:
            # flag parse errors but keep defaults
    """
    from pydantic import create_model
    from pydantic.config import ConfigDict

    field_defs: dict[str, Any] = {}
    for col in schema_cols:
        name = col.get("name", "")
        if not name:
            continue
        raw_type = str(col.get("type", "string|null")).lower().strip()
        default_val = col.get("default")

        # Resolve Python type
        py_type_str = _SCHEMA_TYPE_TO_PY.get(raw_type, "str | None")

        # Build the actual Python type object
        if py_type_str == "bool":
            py_type: Any = bool
            if default_val is None:
                default_val = False
        elif py_type_str == "str":
            py_type = str
            if default_val is None:
                default_val = ""
        elif py_type_str == "str | None":
            from typing import Optional
            py_type = Optional[str]
        elif py_type_str == "int | None":
            from typing import Optional
            py_type = Optional[int]
        elif py_type_str == "float | None":
            from typing import Optional
            py_type = Optional[float]
        else:
            from typing import Optional
            py_type = Optional[str]

        field_defs[name] = (py_type, default_val)

    model = create_model(
        "ExtractionRow",
        __config__=ConfigDict(extra="ignore", coerce_numbers_to_str=False),
        **field_defs,
    )
    return model


def validate_extraction_row(
    raw_data: dict[str, Any],
    schema_cols: list[SchemaColumn],
) -> tuple[dict[str, Any], bool]:
    """Validate LLM extraction output against schema types.

    Returns (validated_values, had_parse_error).
    On partial validation failure, returns the model's defaults for bad fields
    and sets had_parse_error=True.  The row is never discarded.
    """
    RowModel = build_extraction_row_model(schema_cols)
    had_error = False
    try:
        validated = RowModel.model_validate(raw_data)
        return validated.model_dump(), False
    except ValidationError as exc:
        logger.debug("validate_extraction_row: validation errors: %s", exc)
        had_error = True
        # Build a best-effort dict: use validated value where possible, default elsewhere
        result: dict[str, Any] = {}
        defaults = {col["name"]: col.get("default") for col in schema_cols if col.get("name")}
        for col in schema_cols:
            name = col.get("name", "")
            if not name:
                continue
            val = raw_data.get(name, defaults.get(name))
            # Attempt individual coercion; fall back to default on failure
            try:
                single = RowModel.model_validate({name: val})
                result[name] = getattr(single, name)
            except Exception:
                result[name] = defaults.get(name)
        return result, had_error
