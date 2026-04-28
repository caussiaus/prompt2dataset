"""PromptRouter — deterministic prompt variant and parameter selection.

Reads LiveState performance signals (fill_rates, active_flags, rework_count)
and selects the appropriate extraction prompt variant, few-shot examples,
and temperature for each field.

No LLM call is made anywhere in this module. It is a pure function over
measured pipeline state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app_pages.thread_store import LiveState
    from prompt2dataset.dataset_graph.state import SchemaColumn

from prompt2dataset.utils.call_config import TEMPERATURE_MAP


@dataclass
class ExtractionPrompt:
    """All parameters needed for one extraction LLM call."""
    instruction_variant: str   # "standard" | "exhaustive_search" | "numeric_with_units"
    examples: list[dict]       # few-shot evidence examples (may be empty)
    temperature: float
    system_prefix: str         # LiveState context block injected at top of system prompt


class PromptRouter:
    """Selects and assembles the extraction prompt based on LiveState signals.

    Usage:
        router = PromptRouter()
        prompt = router.get_extraction_prompt(field_col, live_state, doc_meta)
    """

    FILL_RATE_LOW_THRESHOLD = 0.40   # below this → use exhaustive_search variant
    EXAMPLES_POOL_LIMIT = 10         # max examples drawn from verified_extractions
    EXAMPLES_FOR_REWORK = 3          # examples when rework_count > 0
    EXAMPLES_DEFAULT = 1             # examples on first pass

    def get_extraction_prompt(
        self,
        field: "SchemaColumn",
        live_state: "LiveState",
        doc_meta: dict,
    ) -> ExtractionPrompt:
        """Select instruction variant, examples, and temperature from LiveState."""
        field_name = (
            field.get("name", "") if isinstance(field, dict) else getattr(field, "name", "")
        )
        difficulty = (
            (field.get("difficulty", "standard") if isinstance(field, dict)
             else getattr(field, "difficulty", "standard")) or "standard"
        )
        field_type = (
            (field.get("type", "string") if isinstance(field, dict)
             else getattr(field, "type", "string")) or "string"
        )

        # ── Instruction variant ──────────────────────────────────────────────
        fill_rate = live_state.fill_rates.get(field_name, 1.0)
        if fill_rate < self.FILL_RATE_LOW_THRESHOLD:
            instruction_variant = "exhaustive_search"
        elif "numeric" in field_type or "integer" in field_type or "number" in field_type:
            instruction_variant = "numeric_with_units"
        else:
            instruction_variant = "standard"

        # ── Few-shot examples ────────────────────────────────────────────────
        n_examples = (
            self.EXAMPLES_FOR_REWORK if live_state.rework_count > 0 else self.EXAMPLES_DEFAULT
        )
        examples = self._select_examples(
            field_name, live_state.verified_extractions, k=n_examples
        )

        # ── Temperature ──────────────────────────────────────────────────────
        temperature = TEMPERATURE_MAP.get(difficulty.lower(), TEMPERATURE_MAP["standard"])

        # ── System prefix from LiveState ─────────────────────────────────────
        try:
            from app_pages.thread_store import build_context_block  # noqa: PLC0415
            system_prefix = build_context_block(live_state)
        except Exception:
            system_prefix = ""

        return ExtractionPrompt(
            instruction_variant=instruction_variant,
            examples=examples,
            temperature=temperature,
            system_prefix=system_prefix,
        )

    def _select_examples(
        self,
        field_name: str,
        verified_extractions: list[dict],
        k: int = 1,
    ) -> list[dict]:
        """Select up to k verified extractions relevant to this field."""
        pool = [
            e for e in verified_extractions
            if field_name in e and e.get(field_name) is not None
        ]
        return pool[:k]
