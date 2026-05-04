"""Load ``config/prompt2dataset.yaml`` for the Streamlit prompt-to-dataset workspace.

Secrets and machine paths stay in ``.env`` / :class:`Settings`; tuning for this module lives
in the YAML file so it is versioned and editable without touching ``.env.example``.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Prompt2DatasetConfig:
    critique_max_output_tokens: int
    # Multi-reviewer + chairman consensus (informational epistemics at critique gate)
    critique_council_enabled: bool
    critique_council_reviewer_count: int
    critique_council_chairman_temperature: float
    critique_council_reviewer_temperatures: tuple[float, ...]
    export_quote_max_chars: int
    extraction_chain_of_thought: bool
    extraction_multipass_blackboard: bool
    extraction_max_refinement_hops: int
    extraction_refinement_evidence_blocks: int
    streamlit_auto_critique_after_trial: bool
    streamlit_extraction_batch: int
    streamlit_extraction_concurrency: int
    # Deterministic grounding gate (post-extraction, pre-critique)
    grounding_enabled: bool
    grounding_require_substring: bool
    grounding_use_nli: bool
    # Wonder queue (export-time backlog)
    wonder_queue_max_pressure_to_enqueue: float
    wonder_queue_max_entries_per_export: int
    # Optional guided JSON: evidence_chains array on extraction output
    extraction_evidence_chain_in_schema: bool
    # Hunger-weighted retrieval + optional annealed reorder
    retrieval_hunger_weight_retrieval: bool
    retrieval_hunger_top_k_bonus: int
    retrieval_anneal_walk_steps: int

    def critique_council_reviewer_temperatures_list(self) -> list[float]:
        """Sampling temperatures per reviewer; padded if YAML list is short."""
        n = max(1, min(int(self.critique_council_reviewer_count), 3))
        if self.critique_council_reviewer_temperatures:
            t = [float(x) for x in self.critique_council_reviewer_temperatures]
            i = 0
            while len(t) < n:
                t.append(round(0.30 + 0.06 * i, 3))
                i += 1
            return t[:n]
        return [round(0.28 + 0.09 * i, 3) for i in range(n)]

    @staticmethod
    def defaults() -> Prompt2DatasetConfig:
        return Prompt2DatasetConfig(
            critique_max_output_tokens=4096,
            critique_council_enabled=False,
            critique_council_reviewer_count=2,
            critique_council_chairman_temperature=0.15,
            critique_council_reviewer_temperatures=(),
            export_quote_max_chars=1200,
            extraction_chain_of_thought=True,
            extraction_multipass_blackboard=True,
            extraction_max_refinement_hops=1,
            extraction_refinement_evidence_blocks=8,
            streamlit_auto_critique_after_trial=True,
            streamlit_extraction_batch=3,
            streamlit_extraction_concurrency=3,
            grounding_enabled=True,
            grounding_require_substring=True,
            grounding_use_nli=True,
            wonder_queue_max_pressure_to_enqueue=5.0,
            wonder_queue_max_entries_per_export=200,
            extraction_evidence_chain_in_schema=False,
            retrieval_hunger_weight_retrieval=True,
            retrieval_hunger_top_k_bonus=8,
            retrieval_anneal_walk_steps=0,
        )


def _as_bool(v: Any, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("0", "false", "no", "off"):
        return False
    if s in ("1", "true", "yes", "on"):
        return True
    return default


def _as_int(v: Any, default: int, *, min_v: int = 1, max_v: int | None = None) -> int:
    try:
        n = int(v)
        n = max(min_v, n)
        if max_v is not None:
            n = min(max_v, n)
        return n
    except (TypeError, ValueError):
        return default


def _as_float(v: Any, default: float, *, min_v: float = 0.0, max_v: float = 2.0) -> float:
    try:
        x = float(v)
        return max(min_v, min(max_v, x))
    except (TypeError, ValueError):
        return default


def _parse_reviewer_temperatures(v: Any) -> tuple[float, ...]:
    if not isinstance(v, (list, tuple)):
        return ()
    out: list[float] = []
    for item in v:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            continue
    return tuple(out)


def load_prompt2dataset_config(project_root: Path | None = None) -> Prompt2DatasetConfig:
    """Read ``config/prompt2dataset.yaml`` under the pipeline repo; missing file → defaults."""
    from prompt2dataset.utils.config import get_settings

    root = Path(project_root).resolve() if project_root is not None else get_settings().project_root
    path = root / "config" / "prompt2dataset.yaml"
    dflt = Prompt2DatasetConfig.defaults()
    if not path.is_file():
        return _apply_extraction_multipass_env(dflt)
    try:
        from ruamel.yaml import YAML

        y = YAML(typ="safe")
        with path.open(encoding="utf-8") as fh:
            raw = y.load(fh)
    except Exception as exc:
        logger.warning("prompt2dataset config: failed to read %s (%s) — using defaults", path, exc)
        return _apply_extraction_multipass_env(dflt)
    if not isinstance(raw, dict):
        return _apply_extraction_multipass_env(dflt)

    crit = raw.get("critique") or {}
    exp = raw.get("export") or {}
    ext = raw.get("extraction") or {}
    st = raw.get("streamlit") or {}
    gr = raw.get("grounding") or {}
    wq = raw.get("wonder_queue") or {}
    ret = raw.get("retrieval") or {}

    out = Prompt2DatasetConfig(
        critique_max_output_tokens=_as_int(
            crit.get("max_output_tokens"),
            dflt.critique_max_output_tokens,
            min_v=256,
            max_v=128_000,
        ),
        critique_council_enabled=_as_bool(
            crit.get("council_enabled"),
            dflt.critique_council_enabled,
        ),
        critique_council_reviewer_count=_as_int(
            crit.get("council_reviewer_count"),
            dflt.critique_council_reviewer_count,
            min_v=1,
            max_v=3,
        ),
        critique_council_chairman_temperature=_as_float(
            crit.get("council_chairman_temperature"),
            dflt.critique_council_chairman_temperature,
            min_v=0.0,
            max_v=1.5,
        ),
        critique_council_reviewer_temperatures=_parse_reviewer_temperatures(
            crit.get("council_reviewer_temperatures")
        ),
        export_quote_max_chars=_as_int(
            exp.get("quote_max_chars"),
            dflt.export_quote_max_chars,
            min_v=80,
            max_v=1_000_000,
        ),
        extraction_chain_of_thought=_as_bool(
            ext.get("chain_of_thought"),
            dflt.extraction_chain_of_thought,
        ),
        extraction_multipass_blackboard=_as_bool(
            ext.get("multipass_blackboard"),
            dflt.extraction_multipass_blackboard,
        ),
        extraction_max_refinement_hops=_as_int(
            ext.get("max_refinement_hops"),
            dflt.extraction_max_refinement_hops,
            min_v=0,
            max_v=8,
        ),
        extraction_refinement_evidence_blocks=_as_int(
            ext.get("refinement_evidence_blocks"),
            dflt.extraction_refinement_evidence_blocks,
            min_v=1,
            max_v=32,
        ),
        streamlit_auto_critique_after_trial=_as_bool(
            st.get("auto_critique_after_trial"),
            dflt.streamlit_auto_critique_after_trial,
        ),
        streamlit_extraction_batch=_as_int(
            st.get("extraction_batch"),
            dflt.streamlit_extraction_batch,
            min_v=1,
            max_v=256,
        ),
        streamlit_extraction_concurrency=_as_int(
            st.get("extraction_concurrency"),
            dflt.streamlit_extraction_concurrency,
            min_v=1,
            max_v=256,
        ),
        grounding_enabled=_as_bool(gr.get("enabled"), dflt.grounding_enabled),
        grounding_require_substring=_as_bool(
            gr.get("require_substring"), dflt.grounding_require_substring
        ),
        grounding_use_nli=_as_bool(gr.get("use_nli"), dflt.grounding_use_nli),
        wonder_queue_max_pressure_to_enqueue=_as_float(
            wq.get("max_pressure_to_enqueue"),
            dflt.wonder_queue_max_pressure_to_enqueue,
            min_v=0.0,
            max_v=1_000_000.0,
        ),
        wonder_queue_max_entries_per_export=_as_int(
            wq.get("max_entries_per_export"),
            dflt.wonder_queue_max_entries_per_export,
            min_v=1,
            max_v=50_000,
        ),
        extraction_evidence_chain_in_schema=_as_bool(
            ext.get("evidence_chain_in_schema"),
            dflt.extraction_evidence_chain_in_schema,
        ),
        retrieval_hunger_weight_retrieval=_as_bool(
            ret.get("hunger_weight_retrieval"),
            dflt.retrieval_hunger_weight_retrieval,
        ),
        retrieval_hunger_top_k_bonus=_as_int(
            ret.get("hunger_top_k_bonus"),
            dflt.retrieval_hunger_top_k_bonus,
            min_v=0,
            max_v=64,
        ),
        retrieval_anneal_walk_steps=_as_int(
            ret.get("anneal_walk_steps"),
            dflt.retrieval_anneal_walk_steps,
            min_v=0,
            max_v=500,
        ),
    )
    return _apply_extraction_multipass_env(out)


def _apply_extraction_multipass_env(cfg: Prompt2DatasetConfig) -> Prompt2DatasetConfig:
    """PROMPT2DATASET_EXTRACTION_MULTIPASS=0|1|true|false toggles multipass (YAML is default)."""
    raw = (os.environ.get("PROMPT2DATASET_EXTRACTION_MULTIPASS") or "").strip().lower()
    if not raw:
        return cfg
    on = raw in ("1", "true", "yes", "on")
    off = raw in ("0", "false", "no", "off")
    if not on and not off:
        return cfg
    mp = cfg.extraction_multipass_blackboard
    if on:
        mp = True
    elif off:
        mp = False
    return Prompt2DatasetConfig(
        critique_max_output_tokens=cfg.critique_max_output_tokens,
        critique_council_enabled=cfg.critique_council_enabled,
        critique_council_reviewer_count=cfg.critique_council_reviewer_count,
        critique_council_chairman_temperature=cfg.critique_council_chairman_temperature,
        critique_council_reviewer_temperatures=cfg.critique_council_reviewer_temperatures,
        export_quote_max_chars=cfg.export_quote_max_chars,
        extraction_chain_of_thought=cfg.extraction_chain_of_thought,
        extraction_multipass_blackboard=mp,
        extraction_max_refinement_hops=cfg.extraction_max_refinement_hops,
        extraction_refinement_evidence_blocks=cfg.extraction_refinement_evidence_blocks,
        streamlit_auto_critique_after_trial=cfg.streamlit_auto_critique_after_trial,
        streamlit_extraction_batch=cfg.streamlit_extraction_batch,
        streamlit_extraction_concurrency=cfg.streamlit_extraction_concurrency,
        grounding_enabled=cfg.grounding_enabled,
        grounding_require_substring=cfg.grounding_require_substring,
        grounding_use_nli=cfg.grounding_use_nli,
        wonder_queue_max_pressure_to_enqueue=cfg.wonder_queue_max_pressure_to_enqueue,
        wonder_queue_max_entries_per_export=cfg.wonder_queue_max_entries_per_export,
        extraction_evidence_chain_in_schema=cfg.extraction_evidence_chain_in_schema,
        retrieval_hunger_weight_retrieval=cfg.retrieval_hunger_weight_retrieval,
        retrieval_hunger_top_k_bonus=cfg.retrieval_hunger_top_k_bonus,
        retrieval_anneal_walk_steps=cfg.retrieval_anneal_walk_steps,
    )
