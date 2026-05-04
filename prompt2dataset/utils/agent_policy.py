"""AgentPolicy and QuestionEngine — autonomy levels and interrupt logic.

AgentPolicy controls how much the pipeline does autonomously vs. interrupting
the user. QuestionEngine determines which single question to ask at each
interruption — fully deterministic, no LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from app_pages.thread_store import DatasetContext, LiveState


@dataclass
class AgentPolicy:
    """Controls pipeline autonomy and interruption thresholds."""
    autonomy_level: Literal["supervised", "semi", "researcher", "autonomous"] = "semi"
    # supervised: ask about schema, every flag batch, critique, export
    # semi: ask about schema approval, final export only
    # researcher: ask about schema approval only
    # autonomous: run to completion, send notification

    batch_interrupt_size: int = 10           # Gate 2 fires every N docs
    flag_rate_threshold: float = 0.40        # Gate 2 fires when all_default > this
    fill_rate_warn_threshold: float = 0.55   # targeted question when fill rate below
    max_rework_cycles: int = 3
    auto_upgrade_after_n_corpora: int = 3    # supervised → semi automatically

    def should_interrupt_at_gate1(self) -> bool:
        """Schema approval gate."""
        return self.autonomy_level in ("supervised", "semi", "researcher")

    def should_interrupt_at_gate2(self) -> bool:
        """Consistency flags gate."""
        return self.autonomy_level in ("supervised",)

    def should_interrupt_at_gate3(self) -> bool:
        """Critique and export gate."""
        return self.autonomy_level in ("supervised", "semi")


@dataclass
class Question:
    """A single interruption question for the user."""
    priority: int        # lower = higher priority (0 = blocking)
    condition: str       # machine-readable condition identifier
    text: str            # human-readable question text
    options: list[str]   # suggested responses (empty = free text)
    context: dict        # additional context for rendering


class QuestionEngine:
    """Determines the single highest-priority question to ask at each interruption.

    Reads AgentPolicy + DatasetContext + LiveState. No LLM.
    Returns at most one question per interruption call.
    """

    PRIORITY_STACK = [
        "topology_failure",           # 0 — broken pipeline edge
        "zero_docs_parsed",           # 1 — acquisition or parse failure
        "no_schema_columns",          # 2 — need domain context
        "fill_rate_below_threshold",  # 3 — extraction failing on 2+ columns
        "critique_flags_present",     # 4 — quality review needed
        "ambiguous_identity",         # 5 — rows may not be unique
        "doc_type_ambiguity",         # 6 — mixed results
    ]

    def should_interrupt(
        self,
        state: "DatasetContext",
        live: "LiveState",
        policy: AgentPolicy,
    ) -> Question | None:
        """Return the single most-blocking question, or None if pipeline can proceed."""
        for condition in self.PRIORITY_STACK:
            q = self._check(condition, state, live, policy)
            if q:
                return q
        return None

    def _check(
        self,
        condition: str,
        state: "DatasetContext",
        live: "LiveState",
        policy: AgentPolicy,
    ) -> Question | None:
        if condition == "topology_failure":
            if state.last_error and "topology" in (state.last_error or "").lower():
                return Question(
                    priority=0, condition=condition,
                    text=f"Pipeline topology error: {state.last_error[:200]}. How would you like to proceed?",
                    options=["Retry", "Skip this document", "Abort"],
                    context={"error": state.last_error},
                )

        elif condition == "zero_docs_parsed":
            n_rows = len(state.rows or [])
            if n_rows == 0 and state.extraction_done:
                return Question(
                    priority=1, condition=condition,
                    text="No documents were successfully parsed. Would you like to check the folder path or retry?",
                    options=["Check path", "Retry ingest", "Continue without data"],
                    context={},
                )

        elif condition == "no_schema_columns":
            if not state.proposed_columns:
                return Question(
                    priority=2, condition=condition,
                    text=f"What data would you like to extract from {state.domain_label or 'these documents'}?",
                    options=[],
                    context={},
                )

        elif condition == "fill_rate_below_threshold":
            if policy.should_interrupt_at_gate2():
                low_fields = [
                    f for f, rate in (live.fill_rates or {}).items()
                    if rate < policy.fill_rate_warn_threshold
                ]
                if len(low_fields) >= 2:
                    return Question(
                        priority=3, condition=condition,
                        text=f"{len(low_fields)} fields have low fill rates (<{policy.fill_rate_warn_threshold:.0%}): {', '.join(low_fields[:3])}. Would you like to refine the extraction instructions?",
                        options=["Refine instructions", "Accept and continue", "Skip these fields"],
                        context={"low_fields": low_fields},
                    )

        elif condition == "critique_flags_present":
            if policy.should_interrupt_at_gate3() and state.critique_config_deltas:
                n = len(state.critique_config_deltas)
                return Question(
                    priority=4, condition=condition,
                    text=f"The quality critique found issues with {n} fields. Review and accept/reject the suggested changes?",
                    options=["Review now", "Accept all", "Reject all and export"],
                    context={"n_fields": n},
                )

        return None
