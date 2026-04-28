"""Extraction worker model + acceptance clause (evidence closure).

Architecture (what runs today)
------------------------------
- **LangGraph** orchestrates *phases*: ``schema_design → extraction → critique → export``.
  Each phase is a *node* (single LLM or deterministic step), not a persistent agent with
  private memory.

**One PDF ≈ one isolated “group chat” from the model’s perspective**

  For extraction, each filing is a **fresh, stateless two-message turn**: the same
  system prompt plus a **user message built only from that PDF** — identity header
  (company / doc metadata from the index) and **retrieval-ranked evidence blocks for
  that ``doc_id`` only**. No other PDF’s chunks, no prior extraction replies, and no
  Streamlit chat history are injected. Running the dataset means **initializing one
  such conversation per PDF** (often one company / one report per row), in parallel
  via ``asyncio.gather``, all sharing the **same approved schema**.

  The **dataset-level** thread (schema design, critique, LiveState) is separate: that is
  where “group chat” context spans turns. It does **not** mix documents; it only shapes
  the shared field definitions and post-batch quality review.

- **LiveState** / ``build_context_block`` prepends a compact summary to **schema** and
  **critique** prompts — corpus health, fill rates — not to per-PDF extraction calls.

There is **no** multi-agent “swarm” that negotiates fields on the wire. Distribution is:
**many concurrent one-shot extractors** over a **shared chunk index**, with **shared schema**.

**RL / DPO / “verifiable” training hooks:** schema approvals, cell edits, and extraction
turns can append to ``training_events.jsonl`` (see :mod:`prompt2dataset.training_events`
and :mod:`prompt2dataset.dataset_graph.feedback_store`) with ``run_id`` and
``schema_hash`` — the pipeline for reward models or DPO is **downstream** of this app,
not a separate on-wire agent fleet.

Acceptance clause — when we treat a row as structurally credible
-----------------------------------------------------------------
**Evidence closure (circularity):** for every schema field, either the value equals the
column default *or* there is a non-empty ``{field}_evidence_quote`` drawn from the evidence
blocks. Values without quotes are *not* closed — they fail congruency with the retrieval
contract (“only say what the blocks support”).

**Operational failures** (non-empty ``_extraction_error``) are **out of scope** for schema
critique: the row did not complete extraction; closure is not evaluated.

This module exposes small counters so the UI / critique / supervisors can distinguish
“bad schema” from “bad pass” from “empty retrieval”.
"""
from __future__ import annotations

from typing import Any

from prompt2dataset.dataset_graph.state import SchemaColumn


def row_is_evidence_closed(row: dict[str, Any], columns: list[SchemaColumn]) -> bool:
    """True iff no non-default value lacks a supporting evidence quote."""
    defaults = {c["name"]: c.get("default") for c in columns}
    for c in columns:
        name = c.get("name", "")
        if not name:
            continue
        val = row.get(name)
        default = defaults.get(name)
        quote = row.get(f"{name}_evidence_quote")
        if val is not None and val != default and not (quote and str(quote).strip()):
            return False
    return True


def row_operational_failure(row: dict[str, Any]) -> bool:
    return bool(str(row.get("_extraction_error") or "").strip())


def summarize_evidence_closure(
    rows: list[dict[str, Any]],
    columns: list[SchemaColumn],
) -> dict[str, int]:
    """Aggregate closure stats for consistency_flags / telemetry."""
    ok = 0
    violated = 0
    skipped = 0
    for row in rows:
        if row_operational_failure(row):
            skipped += 1
            continue
        if row_is_evidence_closed(row, columns):
            ok += 1
        else:
            violated += 1
    return {
        "evidence_closure_ok_count": ok,
        "evidence_closure_violation_count": violated,
        "evidence_closure_skipped_count": skipped,
    }
