"""Dynamic prompt builders for the interactive dataset generation pipeline.

The dataset pipeline lets a user describe in plain language what they want to
find across any corpus of documents, then designs and runs targeted extraction.

All prompts and variable names describe behavior, not a domain.
"""
from __future__ import annotations

import json
from typing import Any


# ---------------------------------------------------------------------------
# Context budget constants
# Approximate token counts at each node. Used to cap inputs so total context
# stays well inside the model's window (110k tokens default).
# ---------------------------------------------------------------------------

CONTEXT_BUDGET: dict[str, int] = {
    # Schema design node
    "schema_system":          600,   # system prompt tokens
    "schema_corpus_ctx":      400,   # doc count + sector/category summary
    "schema_chunk_samples":   800,   # ≤5 real chunk samples × ~160 chars each
    "schema_history":        2000,   # last 8 chat turns (sliding window)
    "schema_max_out":        1500,   # LLM response cap (field definitions JSON)

    # Extraction node (per document)
    "extraction_system":      500,   # system prompt tokens
    "extraction_fields":     1000,   # field definitions for all columns
    "extraction_evidence":   8400,   # ≤12 evidence blocks × 700 chars each
    "extraction_max_out":    2000,   # LLM response cap (one JSON object)

    # Critique node
    "critique_system":        400,   # system prompt tokens
    "critique_rows":         3000,   # ≤15 stripped rows (evidence cols removed)
    # Wide schemas need long field_issues arrays; 800 tokens truncates JSON → false "unstructured" parses
    "critique_max_out":      4096,   # default; overridden by config/prompt2dataset.yaml
}


def context_budget() -> dict[str, int]:
    """Node token caps. ``critique_max_out`` is read from ``config/prompt2dataset.yaml`` when present."""
    out = dict(CONTEXT_BUDGET)
    try:
        from prompt2dataset.utils.prompt2dataset_settings import load_prompt2dataset_config

        out["critique_max_out"] = load_prompt2dataset_config().critique_max_output_tokens
    except Exception:
        pass
    return out


def extraction_output_token_budget(num_schema_columns: int) -> int:
    """Completion budget for one-document JSON extraction (value + evidence per field).

    Wide schemas (20–40 fields) routinely exceed a flat 2k cap — the model truncates,
    JSON becomes invalid or incomplete, and validation falls back to defaults → empty rows.
    """
    base = CONTEXT_BUDGET["extraction_max_out"]
    n = max(0, int(num_schema_columns))
    if n <= 10:
        return base
    # Roughly 90–110 tokens per field (scalar + evidence object + braces)
    extra = (n - 10) * 100
    return min(16000, base + extra)

# Sliding window: only the last N chat turns are sent to schema_node.
# Earlier turns are summarised into a one-sentence prefix.
SCHEMA_HISTORY_WINDOW = 8

# Max evidence blocks per document sent to extraction_node.
EXTRACTION_MAX_EVIDENCE_BLOCKS = 12

# Max chars per evidence block (truncated to fit budget).
EXTRACTION_EVIDENCE_BLOCK_CHARS = 700

# Max rows sampled for critique.
CRITIQUE_SAMPLE_ROWS = 15

# Chars per chunk sample injected into schema design prompt.
SCHEMA_CHUNK_SAMPLE_CHARS = 200

# Max chunk samples to inject into schema design prompt.
SCHEMA_MAX_CHUNK_SAMPLES = 5


# ---------------------------------------------------------------------------
# Schema designer — converts a free-text user request into column definitions
# ---------------------------------------------------------------------------

SCHEMA_DESIGNER_SYSTEM_PROMPT = """\
You are a structured data extraction expert. The user describes what information \
they want to collect from a corpus of documents. You convert their request into \
a precise extraction schema that an LLM can fill in from each document.

RULES:
- Every column must be extractable from the document text alone — no inference beyond \
what is explicitly stated
- Prefer: boolean, string|null, integer (0-3 scale), or short string-enum fields
- ALWAYS include one "evidence_quote" column (type string|null) to capture verbatim \
text that directly supports the most important field
- ALWAYS include a "not_found_reason" column (type string|null) that the extractor fills \
when evidence is absent — this is the proof-of-absence record
- Use snake_case column names, ≤30 chars
- "description": ≤20 words, what the dashboard user sees
- "extraction_instruction": be VERY specific — list exact keywords, phrases, and section \
names the extractor should search for. Vague instructions produce empty results.
  Example (good): 'Look for "tariff", "trade restriction", "25% duty", "Section 301" in \
Management Discussion & Analysis, Risk Factors, or footnotes. Search for US-China, \
US-Canada trade war references.'
  Example (bad): 'Find tariff mentions.'
- "default": null, false, 0, or "" as appropriate if evidence is absent
- Field names must describe what you are capturing, not the domain they come from
- DO NOT include metadata or identity fields (company name, ticker, sector, date) — \
  these are automatically carried from the corpus index. Only include fields that require \
  reading the document text.

- Optional per column — "value_cardinality": "single_best" | "combine_all_occurrences"
  - single_best: one value per PDF (the strongest match to the instruction).
  - combine_all_occurrences: merge every relevant mention in the PDF into this one cell \
  (counts, sums, or values joined with "; "). Use for totals, citation counts, or \
  exhaustive lists in a single field.

Return ONLY a JSON object:
{
  "dataset_name": "snake_case_slug",
  "description": "one sentence about what this dataset captures",
  "columns": [
    {
      "name": "column_name",
      "type": "boolean|string|string|null|integer|number|number|null",
      "description": "dashboard-facing label",
      "extraction_instruction": "exact LLM instruction — specific keywords/phrases/sections to search for",
      "default": null
    }
  ]
}

Limit: 5-8 columns total. If document samples are provided, anchor your field \
instructions to actual language you see in those samples."""


def build_schema_design_user_prompt(
    user_query: str,
    naics_sectors: list[str],
    schema_feedback: str = "",
    *,
    doc_count: int = 0,
    doc_types: list[str] | None = None,
    corpus_name: str = "",
    corpus_topic: str = "",
    chunk_samples: list[dict[str, Any]] | None = None,
    chat_history: list[dict[str, str]] | None = None,
    nlp_hint: str | None = None,
) -> str:
    """Build the user-turn prompt for schema design.

    Args:
        user_query: What the user wants to extract.
        naics_sectors: Unique category values from the corpus index.
        schema_feedback: Prior feedback from user on a previous schema iteration.
        doc_count: Total documents in corpus.
        doc_types: Unique document types (e.g. "annual_report", "ESG_REPORT").
        corpus_name: Name of the corpus (e.g. "tsx_esg_2023").
        corpus_topic: From CorpusConfig.topic — the research focus of this corpus.
        chunk_samples: Real text chunks from partially-ingested docs (eval window).
        chat_history: Recent chat turns for continuity context.
    """
    # ── Corpus context block ──────────────────────────────────────────────
    ctx_lines: list[str] = []
    if doc_count:
        ctx_lines.append(f"- {doc_count} document{'s' if doc_count != 1 else ''} in corpus")
    if corpus_name:
        ctx_lines.append(f"- Corpus: {corpus_name}")
    if corpus_topic:
        ctx_lines.append(f"- Research focus: {corpus_topic}")
    if doc_types:
        ctx_lines.append(f"- Document types: {', '.join(doc_types[:5])}")
    sectors_str = ", ".join(sorted(set(naics_sectors)))[:300] if naics_sectors else ""
    if sectors_str:
        ctx_lines.append(f"- Categories / sectors present: {sectors_str}")
    if not ctx_lines:
        ctx_lines.append("- General document corpus")

    corpus_ctx = "\n".join(ctx_lines)

    # ── Real chunk samples (eval window grounding) ────────────────────────
    samples_block = ""
    if chunk_samples:
        lines = [f"\nSample document text ({len(chunk_samples)} docs parsed so far):"]
        for s in chunk_samples[:SCHEMA_MAX_CHUNK_SAMPLES]:
            doc_label = s.get("entity_name") or s.get("doc_id", "doc")
            page = s.get("page_start", "")
            section = s.get("section_path", "")
            text = str(s.get("text", ""))[:SCHEMA_CHUNK_SAMPLE_CHARS]
            label = f"{doc_label}" + (f" p.{page}" if page else "") + (f" [{section}]" if section else "")
            lines.append(f"  [{label}] {text}")
        samples_block = "\n".join(lines)

    # ── Recent chat history (sliding window) ──────────────────────────────
    history_block = ""
    if chat_history:
        window = chat_history[-SCHEMA_HISTORY_WINDOW:]
        if len(chat_history) > SCHEMA_HISTORY_WINDOW:
            prior_count = len(chat_history) - SCHEMA_HISTORY_WINDOW
            history_block = f"\n\nPrior refinements ({prior_count} earlier turns summarised above):\n"
        else:
            history_block = "\n\nRecent conversation:\n"
        for msg in window:
            role = msg.get("role", "user")
            content = msg.get("content", "")[:200]
            history_block += f"  {role}: {content}\n"

    # ── Feedback block ────────────────────────────────────────────────────
    feedback_block = ""
    if schema_feedback:
        feedback_block = f"\n\nUser feedback on previous schema:\n{schema_feedback}\n\nRevise accordingly."

    nlp_hint_block = nlp_hint or ""

    return (
        f"User request: {user_query}\n\n"
        f"Corpus context:\n{corpus_ctx}"
        f"{samples_block}"
        f"{nlp_hint_block}"
        f"{history_block}"
        f"{feedback_block}\n\n"
        "Design the extraction schema. Return JSON only."
    )


# ---------------------------------------------------------------------------
# Extraction prompt — runs per-document against the approved schema
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """\
You extract specific information from a document.

You ONLY see structured evidence blocks — NOT the full document. Evidence blocks \
include the chunk text, page numbers, and section path from the original document.

Rules:
- READ EVERY evidence block carefully before concluding that a field is absent
- If information IS present — even tangentially — extract it; use null/false only when \
  the evidence blocks contain absolutely nothing relevant after thorough reading
- DO NOT invent or hallucinate; only extract what is explicitly stated in the blocks
- For each field, populate BOTH the value AND its companion _evidence object:
    - _evidence.quote: exact verbatim excerpt from one block (≤80 words) that most
      directly supports your answer; null only if truly absent
    - _evidence.chunk_id: the chunk_id header from the relevant block; null if absent
    - _evidence.page_start / page_end: page numbers from that block's header
    - _evidence.section_path: section from that block's header
- For not_found_reason: if all fields are defaults, explain specifically which \
  keywords you searched for and why they were absent (e.g. "Searched blocks for \
  'tariff', 'duty', 'Section 301', 'trade restriction' — none found. Document covers \
  domestic real estate operations only.")
- If several independent facts match the SAME scalar fields (e.g. multiple revenue \
  segments), populate those fields from the ONE fact best supported by the evidence \
  blocks (clearest quote + number). Use additional bullets inside the \
  ``evidence_quote`` field's supporting quote text to list other candidates \
  verbatim — still ONE JSON object, one row.
- Respect each field's cardinality hint in the user prompt: [SINGLE BEST] vs \
[COMBINE ALL]. For COMBINE ALL, aggregate every matching instance in the doc into \
that one cell (and cite representative spans in evidence).
- Return ONE JSON object with exactly the specified keys. No markdown, no explanation."""

_EXTRACTION_COT_ADDENDUM = """

OUTPUT FORMAT (strict):
- First, write your reasoning inside a single <thinking>...</thinking> block. For each \
schema field, briefly cite which block(s) you used or why the value is default/absent, \
with short verbatim quotes where relevant.
- After the closing </thinking> tag, output ONLY a single JSON object (no other prose) \
with exactly the field keys and companion [each field's]_evidence objects the user message lists."""


def extraction_system_prompt(*, use_chain_of_thought: bool) -> str:
    """Base extraction system prompt, optionally with a mandatory <thinking> block for RL/audit."""
    if use_chain_of_thought:
        return EXTRACTION_SYSTEM_PROMPT + _EXTRACTION_COT_ADDENDUM
    return EXTRACTION_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Multipass extraction — Scout (pass 1) and synthesis user prompt
# ---------------------------------------------------------------------------

SCOUT_SYSTEM_PROMPT = """\
You are a scout for structured data extraction from document evidence. You will \
receive a list of target fields and ranked evidence blocks for ONE document.

PHASE: hypothesis pass — do NOT produce final per-field evidence objects for every \
column, and do NOT output the full extraction JSON schema used for the final pass.

Return ONE JSON object with exactly these top-level keys:
- resolved_fields: an object whose keys are a SUBSET of the given field names. \
Only include fields you can answer with high confidence from the blocks alone \
(self-contained, e.g. identity metadata or an explicit literal in the text).
- hypotheses: an array of objects, each with:
  - target_fields: string[] — which schema field(s) the hint relates to
  - summary: string — the clue in your own words (short)
  - anchor_chunk_ids: string[] — chunk_id values from the evidence headers that support the hint
  - needs: string — what to search for in a follow-up (terms, table names, concepts)
- unresolved_fields: string[] — field names you could not address yet; include any \
field not in resolved_fields that still needs more context.

Rules: prefer leaving hard / multi-hop / ambiguous fields in hypotheses or \
unresolved_fields rather than guessing. Use exact field names from the schema."""


def build_scout_json_schema() -> dict[str, Any]:
    """Tight OpenAI/vLLM JSON schema for the scout (multipass pass 1)."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "resolved_fields": {
                "type": "object",
                "additionalProperties": True,
            },
            "hypotheses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "target_fields": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "summary": {"type": "string"},
                        "anchor_chunk_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "needs": {"type": "string"},
                    },
                    "required": ["target_fields", "summary", "anchor_chunk_ids", "needs"],
                },
            },
            "unresolved_fields": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["resolved_fields", "hypotheses", "unresolved_fields"],
    }


def build_scout_user_prompt(
    columns: list[dict[str, Any]],
    doc_meta: dict[str, Any],
    evidence_blocks: list[dict[str, Any]],
    *,
    all_chunks_count: int,
    keyword_hit_count: int,
    pass1_positive_count: int,
    extraction_mode: str = "direct",
    corpus_topic: str = "",
    row_granularity: str = "one_row_per_document",
    schema_mapping_summary: str = "",
    evidence_max_blocks: int | None = None,
    evidence_block_chars: int | None = None,
) -> str:
    """User prompt for pass 1 (scout): same context as extraction, different output contract."""
    mode_note = (
        "\nEXTRACTION MODE — evidence-first: note which fields need multi-step reasoning.\n"
        if extraction_mode == "evidence"
        else ""
    )

    def _card_label(c: dict) -> str:
        card = (c.get("value_cardinality") or "single_best").strip()
        if card == "combine_all_occurrences":
            return " [COMBINE ALL occurrences in this doc into this cell]"
        return " [SINGLE BEST value per doc]"

    col_lines = "\n".join(
        f'  "{c["name"]}" ({c["type"]}){_card_label(c)}: {c.get("description","")}\n'
        f'    Look for: {c.get("extraction_instruction") or c.get("description","")}\n'
        f'    Default if absent: {json.dumps(c.get("default"))}'
        for c in columns
    )

    n_blk = int(evidence_max_blocks) if evidence_max_blocks is not None else EXTRACTION_MAX_EVIDENCE_BLOCKS
    n_blk = max(1, min(n_blk, EXTRACTION_MAX_EVIDENCE_BLOCKS))
    n_ch = int(evidence_block_chars) if evidence_block_chars is not None else EXTRACTION_EVIDENCE_BLOCK_CHARS
    n_ch = max(120, n_ch)

    if evidence_blocks:
        capped = evidence_blocks[:n_blk]
        blocks_text = "\n\n".join(
            (
                f"[Block {i + 1} | chunk_id={b.get('chunk_id', '')} "
                f"| pages {b.get('page_start', '?')}-{b.get('page_end', '?')} "
                f"| section: {b.get('section_path', '')}]\n"
                f"{str(b.get('text', b.get('quote', '')))[:n_ch]}"
            )
            for i, b in enumerate(capped)
        )
    else:
        blocks_text = (
            "NO RELEVANT EVIDENCE BLOCKS FOUND IN THIS DOCUMENT.\n"
            "Put all fields in unresolved_fields; resolved_fields and hypotheses can be empty."
        )

    doc_parts: list[str] = []
    for field in ("company_name", "entity_name", "issuer_name", "entity_slug", "ticker",
                  "doc_type", "filing_type", "doc_date", "filing_date",
                  "context_category", "naics_sector", "profile_number", "entity_id"):
        val = doc_meta.get(field, "")
        if val and str(val) not in ("", "nan", "None"):
            doc_parts.append(str(val))
    doc_header = " | ".join(doc_parts) if doc_parts else "Document"

    coverage_parts = [f"{all_chunks_count} total chunks"]
    if keyword_hit_count:
        coverage_parts.append(f"{keyword_hit_count} keyword hits")
    if pass1_positive_count:
        coverage_parts.append(f"{pass1_positive_count} topic-relevant")
    coverage = " | ".join(coverage_parts)
    topic_note = f"\nResearch focus: {corpus_topic}" if corpus_topic else ""
    contract_block = ""
    if (schema_mapping_summary or "").strip():
        contract_block = f"\n--- Schema mapping contract (from ideation) ---\n{schema_mapping_summary.strip()}\n---\n"

    return (
        f"Document: {doc_header}{topic_note}\n"
        f"Coverage: {coverage}{contract_block}"
        f"{mode_note}\n\n"
        f"Evidence blocks:\n{blocks_text}\n\n"
        f"Target fields (schema):\n{col_lines}\n\n"
        f"Output ONLY the JSON object with keys: resolved_fields, hypotheses, unresolved_fields. "
        f"Field names in resolved_fields and unresolved_fields must come from the names above."
    )


def build_extraction_user_prompt(
    columns: list[dict[str, Any]],
    doc_meta: dict[str, Any],
    evidence_blocks: list[dict[str, Any]],
    *,
    all_chunks_count: int,
    keyword_hit_count: int,
    pass1_positive_count: int,
    extraction_mode: str = "direct",
    corpus_topic: str = "",
    row_granularity: str = "one_row_per_document",
    schema_mapping_summary: str = "",
    extra_sections: str = "",
    evidence_max_blocks: int | None = None,
    evidence_block_chars: int | None = None,
) -> str:
    """Build the user-turn prompt for single-document extraction.

    Args:
        columns: Approved schema columns.
        doc_meta: Identity fields for this document (any corpus column names).
        evidence_blocks: Ranked text chunks for this document.
        all_chunks_count: Total chunks for this doc (for coverage context).
        keyword_hit_count: Chunks matching keyword filter (if run).
        pass1_positive_count: Chunks flagged as topic-relevant by LLM pre-filter (if run).
        extraction_mode: "direct" or "evidence".
        corpus_topic: Research focus string from CorpusConfig.topic.
        row_granularity: ``one_row_per_document`` (default) or ``one_row_per_fact``
            (emphasize choosing one primary fact; see system prompt).
        schema_mapping_summary: Row/column contract from schema ideation (injected verbatim).
        extra_sections: Optional markdown/text inserted after the schema contract (e.g. multipass blackboard).
    """
    mode_note = (
        "\nEXTRACTION MODE — evidence-first: collect all candidate quotes first, "
        "then decide the field value based on the weight of evidence.\n"
        if extraction_mode == "evidence"
        else ""
    )

    def _card_label(c: dict) -> str:
        card = (c.get("value_cardinality") or "single_best").strip()
        if card == "combine_all_occurrences":
            return " [COMBINE ALL occurrences in this doc into this cell]"
        return " [SINGLE BEST value per doc]"

    col_lines = "\n".join(
        f'  "{c["name"]}" ({c["type"]}){_card_label(c)}: {c.get("description","")}\n'
        f'    Look for: {c.get("extraction_instruction") or c.get("description","")}\n'
        f'    Default if absent: {json.dumps(c.get("default"))}'
        for c in columns
    )

    # Build field list including evidence companions
    field_names_with_evidence: list[str] = []
    for c in columns:
        field_names_with_evidence.append(c["name"])
        field_names_with_evidence.append(f"{c['name']}_evidence")

    n_blk = int(evidence_max_blocks) if evidence_max_blocks is not None else EXTRACTION_MAX_EVIDENCE_BLOCKS
    n_blk = max(1, min(n_blk, EXTRACTION_MAX_EVIDENCE_BLOCKS))
    n_ch = int(evidence_block_chars) if evidence_block_chars is not None else EXTRACTION_EVIDENCE_BLOCK_CHARS
    n_ch = max(120, n_ch)

    if evidence_blocks:
        capped = evidence_blocks[:n_blk]
        blocks_text = "\n\n".join(
            (
                f"[Block {i + 1} | chunk_id={b.get('chunk_id', '')} "
                f"| pages {b.get('page_start', '?')}-{b.get('page_end', '?')} "
                f"| section: {b.get('section_path', '')}]\n"
                f"{str(b.get('text', b.get('quote', '')))[:n_ch]}"
            )
            for i, b in enumerate(capped)
        )
    else:
        blocks_text = (
            "NO RELEVANT EVIDENCE BLOCKS FOUND IN THIS DOCUMENT.\n"
            "The document did not contain passages matching the topic keywords. "
            "Use all field defaults and explain why in not_found_reason."
        )

    # Build document header from whatever identity fields are available
    doc_parts: list[str] = []
    for field in ("company_name", "entity_name", "issuer_name", "entity_slug", "ticker",
                  "doc_type", "filing_type", "doc_date", "filing_date",
                  "context_category", "naics_sector", "profile_number", "entity_id"):
        val = doc_meta.get(field, "")
        if val and str(val) not in ("", "nan", "None"):
            doc_parts.append(str(val))
    doc_header = " | ".join(doc_parts) if doc_parts else "Document"

    # Coverage summary
    coverage_parts = [f"{all_chunks_count} total chunks"]
    if keyword_hit_count:
        coverage_parts.append(f"{keyword_hit_count} keyword hits")
    if pass1_positive_count:
        coverage_parts.append(f"{pass1_positive_count} topic-relevant")
    coverage = " | ".join(coverage_parts)

    topic_note = f"\nResearch focus: {corpus_topic}" if corpus_topic else ""

    granularity_note = ""
    if row_granularity == "one_row_per_fact":
        granularity_note = (
            "\nROW POLICY — one primary fact per document row:\n"
            "If evidence contains multiple similar items (e.g. several segments), "
            "fill scalar fields for the single best-supported item only; add verbatim "
            "snippets for the others as extra bullet lines inside the `evidence_quote` "
            "supporting quote (same field, still one JSON object).\n"
        )

    # Build a compact keyword reminder from extraction_instruction fields so the
    # model knows what it is hunting for before it reads the blocks.
    keyword_hints: list[str] = []
    for c in columns:
        instr = c.get("extraction_instruction", "")
        if instr:
            keyword_hints.append(f'  "{c["name"]}": {instr[:120]}')
    keyword_reminder = ""
    if keyword_hints and len(columns) <= 22:
        keyword_reminder = (
            "\nKeywords / concepts to search for in the blocks:\n" + "\n".join(keyword_hints) + "\n"
        )

    contract_block = ""
    if (schema_mapping_summary or "").strip():
        contract_block = f"\n--- Schema mapping contract (from ideation) ---\n{schema_mapping_summary.strip()}\n---\n"

    if len(field_names_with_evidence) <= 24:
        keys_clause = (
            f"Return JSON with keys: {json.dumps(field_names_with_evidence)}"
        )
    else:
        keys_clause = (
            "Return one JSON object: for every name under **Fields to extract**, include that "
            "key plus `{name}_evidence` with quote, chunk_id, page_start, page_end, section_path."
        )

    return (
        f"Document: {doc_header}{topic_note}{granularity_note}\n"
        f"Coverage: {coverage}"
        f"{contract_block}"
        f"{extra_sections}"
        f"{keyword_reminder}"
        f"{mode_note}\n\n"
        f"Evidence blocks:\n{blocks_text}\n\n"
        f"Fields to extract:\n{col_lines}\n\n"
        f"For EACH field also return a companion {{field}}_evidence object with: "
        f"quote, chunk_id, page_start, page_end, section_path (all null if absent).\n\n"
        f"{keys_clause}"
    )


def format_blackboard_extraction_preamble(
    *, resolved_fields: dict[str, Any], hypotheses: list[dict[str, Any]], unresolved_fields: list[str]
) -> str:
    """Text block injected into the synthesis user prompt (multipass)."""
    payload = {
        "resolved_fields": resolved_fields,
        "hypotheses": hypotheses,
        "unresolved_fields": unresolved_fields,
    }
    raw = json.dumps(payload, ensure_ascii=False, indent=2)[:12_000]
    return f"\n--- Blackboard (scout pass) ---\n{raw}\n---\n"


def build_multipass_synthesis_user_prompt(
    columns: list[dict[str, Any]],
    doc_meta: dict[str, Any],
    evidence_blocks: list[dict[str, Any]],
    *,
    all_chunks_count: int,
    keyword_hit_count: int,
    pass1_positive_count: int,
    blackboard: dict[str, Any],
    extraction_mode: str = "direct",
    corpus_topic: str = "",
    row_granularity: str = "one_row_per_document",
    schema_mapping_summary: str = "",
    second_pass: bool = False,
    evidence_max_blocks: int | None = None,
    evidence_block_chars: int | None = None,
) -> str:
    """User prompt for multipass final extraction; includes merged evidence + scout blackboard."""
    rf = blackboard.get("resolved_fields")
    if not isinstance(rf, dict):
        rf = {}
    hy = blackboard.get("hypotheses")
    if not isinstance(hy, list):
        hy = []
    uf = blackboard.get("unresolved_fields")
    if not isinstance(uf, list):
        uf = []
    pre = format_blackboard_extraction_preamble(
        resolved_fields=rf,
        hypotheses=hy,  # type: ignore[arg-type]
        unresolved_fields=[str(x) for x in uf],
    )
    if second_pass:
        pre = (
            pre
            + "\nThe evidence blocks below may include a second targeted retrieval pass. "
            "Use them together with the first pass; deduplicate mentally by chunk_id.\n"
        )
    return build_extraction_user_prompt(
        columns,
        doc_meta,
        evidence_blocks,
        all_chunks_count=all_chunks_count,
        keyword_hit_count=keyword_hit_count,
        pass1_positive_count=pass1_positive_count,
        extraction_mode=extraction_mode,
        corpus_topic=corpus_topic,
        row_granularity=row_granularity,
        schema_mapping_summary=schema_mapping_summary,
        extra_sections=pre,
        evidence_max_blocks=evidence_max_blocks,
        evidence_block_chars=evidence_block_chars,
    )


def build_dynamic_json_schema(
    columns: list[dict[str, Any]],
    *,
    with_evidence: bool = True,
    with_evidence_chains: bool = False,
) -> dict[str, Any]:
    """Build an OpenAI/vLLM guided-decoding JSON schema from column definitions.

    When ``with_evidence=True`` (default), each field gets a companion
    ``{name}_evidence`` object containing chunk provenance.

    When ``with_evidence_chains=True``, an optional top-level ``evidence_chains`` array
    is allowed for ordered provenance graphs (not required).
    """
    _type_map: dict[str, Any] = {
        "boolean": {"type": "boolean"},
        "string": {"type": "string"},
        "string|null": {"type": ["string", "null"]},
        "integer": {"type": "integer"},
        "integer|null": {"type": ["integer", "null"]},
        "number": {"type": "number"},
        "number|null": {"type": ["number", "null"]},
    }

    _evidence_schema = {
        "type": ["object", "null"],
        "properties": {
            "quote": {"type": ["string", "null"]},
            "chunk_id": {"type": ["string", "null"]},
            "page_start": {"type": ["integer", "null"]},
            "page_end": {"type": ["integer", "null"]},
            "section_path": {"type": ["string", "null"]},
        },
    }

    properties: dict[str, Any] = {}
    required: list[str] = []
    for col in columns:
        t = col.get("type", "string|null").strip()
        properties[col["name"]] = _type_map.get(t, {"type": ["string", "null"]})
        required.append(col["name"])
        if with_evidence:
            ev_key = f"{col['name']}_evidence"
            properties[ev_key] = _evidence_schema
            required.append(ev_key)

    if with_evidence_chains:
        properties["evidence_chains"] = {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "field_name": {"type": "string"},
                    "nodes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": True,
                            "properties": {
                                "chunk_id": {"type": ["string", "null"]},
                                "role": {"type": "string"},
                                "summary": {"type": "string"},
                            },
                        },
                    },
                    "reasoning_edges": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["field_name", "nodes"],
            },
        }

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


# ---------------------------------------------------------------------------
# Critique prompt — samples rows and asks if extraction looks correct
# ---------------------------------------------------------------------------

CRITIQUE_SYSTEM_PROMPT = """\
You are a data quality reviewer for an LLM extraction pipeline. You receive a \
sample of extracted rows from a document corpus and assess whether the \
extraction schema and LLM outputs are working correctly.

Important — distinguish **pipeline failure** from **bad schema**:
- If many rows include `_row_note` mentioning connection errors, timeouts, or empty chunks, \
or the consistency pre-flags say most rows never completed extraction, treat that as an \
**operational / retrieval / vLLM** problem. Say so in `overall_suggestion` and use \
`field_issues: []` unless you see evidence of a real schema mismatch. \
**Do not** tell the user to "reassess" or redesign a schema they already defined when the \
data is empty because extraction never ran successfully.
- Only recommend schema changes when extracted values exist (or proof-of-absence with evidence) \
but are systematically wrong, too sparse despite successful passes, too broad, or contradictory.

Identify (when extraction actually produced values):
1. Columns that are almost always null/false/empty — might be too specific or poorly worded
2. Columns that are almost always filled — might be too broad (catching boilerplate)
3. Cells where a non-null value has no evidence quote — potential hallucination
4. Schema improvements: renamed columns, split/merged fields, better extraction instructions

You MUST respond with a single valid JSON object — no prose before or after. The schema is:
{
  "overall_quality": "good" | "ok" | "needs_work",
  "field_issues": [
    {
      "field": "<column name or '__schema__' for schema-level issues>",
      "issue": "<concise description of the problem>",
      "severity": "high" | "medium" | "low",
      "suggestion": "<actionable fix — max 30 words>"
    }
  ],
  "overall_suggestion": "<one sentence max — the single most important change>"
}

Rules:
- field_issues may be an empty list if quality is good **or** if the sample shows only \
pipeline failures (see above).
- Do NOT include prose outside the JSON object.
- overall_suggestion should be null if overall_quality is "good".
- If overall_quality is "needs_work" solely due to failed extraction connectivity, \
overall_suggestion must name that root cause (e.g. verify vLLM, chunks parquet, PDF parse) \
— not "revisit schema" or "reassess column definitions".
- Keep each "issue" and "suggestion" string concise (≤ 200 chars). Prioritize the top 12 \
highest-severity field_issues; omit redundant low-severity duplicates."""


def build_critique_user_prompt(
    dataset_name: str,
    columns: list[dict[str, Any]],
    sample_rows: list[dict[str, Any]],
    *,
    consistency_flags: dict[str, Any] | None = None,
) -> str:
    """Build the user-turn prompt for critique.

    Args:
        dataset_name: Name of the dataset being critiqued.
        columns: Schema column definitions.
        sample_rows: Up to CRITIQUE_SAMPLE_ROWS rows (evidence cols already stripped).
        consistency_flags: Summary from consistency_check (all_default_count, evidenceless_count).
    """
    col_summary = json.dumps(
        [{"name": c["name"], "type": c["type"], "description": c["description"]} for c in columns],
        indent=2,
    )
    rows_text = json.dumps(sample_rows[:CRITIQUE_SAMPLE_ROWS], indent=2, default=str)

    flags_note = ""
    if consistency_flags:
        parts = []
        n_all_def = consistency_flags.get("all_default_count", 0)
        n_ev_less = consistency_flags.get("evidenceless_count", 0)
        n_parse_err = consistency_flags.get("parse_error_count", 0)
        if n_all_def:
            parts.append(f"{n_all_def} rows have ALL fields at default value (possible parse failures)")
        if n_ev_less:
            parts.append(f"{n_ev_less} cells have a non-null value but no evidence quote (potential hallucination)")
        if n_parse_err:
            parts.append(f"{n_parse_err} rows had Pydantic type-validation errors (LLM returned wrong types)")
        n_ex_err = consistency_flags.get("extraction_error_count", 0)
        n_tot = max(int(consistency_flags.get("total_rows", 0)), 1)
        if n_ex_err:
            parts.append(
                f"{n_ex_err} rows recorded a non-empty `_extraction_error` "
                f"({100 * n_ex_err / n_tot:.0f}% of rows) — likely LLM/HTTP/chunk issues, not schema design"
            )
        if parts:
            flags_note = "\n\nConsistency check pre-flags:\n" + "\n".join(f"- {p}" for p in parts)

    return (
        f"Dataset: {dataset_name}\n\n"
        f"Schema columns:\n{col_summary}\n"
        f"{flags_note}\n\n"
        f"Sample extracted rows (up to {CRITIQUE_SAMPLE_ROWS}):\n{rows_text}\n\n"
        "Assess extraction quality. If `_row_note` or pre-flags show failed LLM/HTTP passes, "
        "say so and avoid blaming the user's schema. "
        "When extraction succeeded, evaluate whether columns are well-defined, values are plausible, "
        "and evidence supports non-default cells — flag hallucinations or fields that are too broad/narrow."
    )


# ---------------------------------------------------------------------------
# Chairman — merges independent reviewer JSON into one consensus verdict
# ---------------------------------------------------------------------------

CHAIRMAN_CONSENSUS_SYSTEM_PROMPT = """\
You are the **chairman** of a validation council for an LLM extraction pipeline.

You receive **anonymized JSON outputs** from 1–3 independent reviewers. Each reviewer saw the \
same schema and the same sampled rows but was given a different **epistemic lens** (evidence \
literalism, schema coherence, or cross-sample skepticism).

Your job:
1. Synthesize **one** final verdict: `overall_quality`, `field_issues`, and `overall_suggestion` \
using the same JSON shape as a single reviewer (field_issues entries use field / issue / severity / \
suggestion; optional suggested_call_config_delta + config_rationale when useful).
2. Report **epistemic consensus**: `reviewer_agreement_score` (0–1) must be **≤** the provided \
`vote_agreement` when reviewers disagree materially — use the supplied number as an upper bound \
when in doubt.
3. `dissent_summary`: one short paragraph on where reviewers disagreed or tension remained.
4. `consensus_rationale`: one short paragraph explaining how you reconciled views (majority vs \
strong minority, evidence vs schema framing).

Rules:
- If reviewers mostly flag **pipeline / vLLM / empty extraction**, the final verdict should say \
so — do not blame the user's schema.
- Do **not** upgrade to `overall_quality: "good"` unless reviewers largely agree extraction is \
sound and issues are minor.
- Respond with **one valid JSON object only** — keys:
  overall_quality, field_issues, overall_suggestion,
  reviewer_agreement_score, dissent_summary, consensus_rationale
- overall_suggestion may be an empty string if overall_quality is good."""


def build_chairman_user_prompt(
    reviewer_traces: list[dict[str, Any]],
    *,
    vote_agreement: float,
) -> str:
    """Build user message for chairman from reviewer trace dicts (lens, qualities, issues)."""
    slim: list[dict[str, Any]] = []
    for i, tr in enumerate(reviewer_traces):
        slim.append(
            {
                "reviewer_index": i + 1,
                "lens": tr.get("lens"),
                "overall_quality": tr.get("overall_quality"),
                "overall_suggestion": tr.get("overall_suggestion"),
                "field_issues": tr.get("field_issues") or [],
                "parse_ok": tr.get("parse_ok", True),
            }
        )
    return (
        f"Modal-label agreement across reviewers (fraction aligned with the most common "
        f"overall_quality): **{vote_agreement:.3f}**. "
        f"Your `reviewer_agreement_score` must not exceed this unless you justify a higher "
        f"numeric consensus on *specific sub-issues* in `consensus_rationale`.\n\n"
        f"Reviewer JSON (independent runs):\n{json.dumps(slim, indent=2, default=str)}\n\n"
        "Produce the single merged JSON object described in your system instructions."
    )
