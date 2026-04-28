"""Multi-reviewer critique with chairman consensus (informational epistemics).

Independent reviewers each adopt a different *lens* (evidence literalism vs schema
coherence vs cross-row skepticism). A chairman model synthesizes a single
verdict, explicit agreement score, and dissent notes — the pipeline's consensus
step before export/rework routing.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Generator, List, Literal

import instructor
from openai import OpenAI
from pydantic import BaseModel, Field

from prompt2dataset.dataset_graph.critique_node import (
    _CritiqueOut,
    _FieldIssue,
    _build_critique_messages,
    _state_from_structured,
)
from prompt2dataset.dataset_graph.state import DatasetState
from prompt2dataset.prompts.dataset_prompt import (
    CHAIRMAN_CONSENSUS_SYSTEM_PROMPT,
    build_chairman_user_prompt,
    context_budget,
)
from prompt2dataset.utils.config import get_settings
from prompt2dataset.utils.prompt2dataset_settings import load_prompt2dataset_config

logger = logging.getLogger(__name__)

# Epistemically diverse reviewer lenses (appended to the shared critique system prompt).
_REVIEWER_LENSES: list[tuple[str, str]] = [
    (
        "literal_evidence",
        "\n\n## Your reviewer role: literal evidence\n"
        "Prioritize verbatim grounding and hallucination risk. Flag non-default values that "
        "look unsupported or weakly supported in the **sample rows** (use `_row_note` and "
        "consistency pre-flags). Do not blame the user's schema for empty rows caused by "
        "pipeline or connectivity failures.",
    ),
    (
        "schema_coherence",
        "\n\n## Your reviewer role: schema coherence\n"
        "Prioritize whether column definitions, types, and extraction instructions match what "
        "the sample shows — too narrow (always default), too broad (boilerplate), or "
        "ambiguous instructions. Recommend concrete instruction tweaks when extraction succeeded.",
    ),
    (
        "cross_sample_skeptic",
        "\n\n## Your reviewer role: cross-sample skeptic\n"
        "Look for **inconsistency or contradiction** across rows in the sample, unstable "
        "formats, or fields that swing implausibly between documents. Flag systematic drift "
        "that a single-pass reviewer might miss.",
    ),
]


class _ChairmanConsensusOut(BaseModel):
    """Chairman: merges reviewer JSON + reports epistemic status."""

    overall_quality: Literal["good", "ok", "needs_work"] = "ok"
    field_issues: List[_FieldIssue] = Field(default_factory=list)
    overall_suggestion: str = ""
    reviewer_agreement_score: float = Field(default=0.7, ge=0.0, le=1.0)
    dissent_summary: str = ""
    consensus_rationale: str = ""


def _vote_agreement(qualities: list[str]) -> float:
    """Fraction of reviewers aligned with the modal overall_quality label."""
    valid = [q for q in qualities if q in ("good", "ok", "needs_work")]
    if not valid:
        return 0.5
    maj = max(Counter(valid).values())
    return maj / len(valid)


def _one_reviewer(
    *,
    lens_id: str,
    lens_suffix: str,
    messages: list[dict],
    model: str,
    base_url: str,
    api_key: str,
    timeout: float,
    max_out: int,
    temperature: float,
) -> dict[str, Any]:
    """Run a single structured critique call; returns trace dict + parsed outcome."""
    sys0 = messages[0]["content"]
    adj_messages = [
        {"role": "system", "content": sys0 + lens_suffix},
        *messages[1:],
    ]
    try:
        raw_client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
        )
        client = instructor.from_openai(raw_client, mode=instructor.Mode.JSON)
        out: _CritiqueOut = client.chat.completions.create(
            model=model,
            messages=adj_messages,
            response_model=_CritiqueOut,
            temperature=temperature,
            max_tokens=max_out,
            max_retries=2,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        return {
            "lens": lens_id,
            "overall_quality": out.overall_quality,
            "field_issues": [fi.model_dump() for fi in out.field_issues if fi.field],
            "overall_suggestion": (out.overall_suggestion or "").strip(),
            "parse_ok": True,
            "raw": out.model_dump_json(),
        }
    except Exception as exc:
        logger.warning("council reviewer %s failed: %s", lens_id, exc)
        return {
            "lens": lens_id,
            "overall_quality": "needs_work",
            "field_issues": [],
            "overall_suggestion": "",
            "parse_ok": False,
            "raw": json.dumps({"error": str(exc)}),
        }


def _run_reviewers_parallel(
    messages: list[dict],
    n_reviewers: int,
    temps: list[float],
) -> list[dict[str, Any]]:
    cfg = get_settings()
    max_out = context_budget()["critique_max_out"]
    n = max(1, min(n_reviewers, len(_REVIEWER_LENSES)))
    tasks: list[tuple[str, str, float]] = []
    for i in range(n):
        lid, suffix = _REVIEWER_LENSES[i]
        t = temps[i] if i < len(temps) else 0.35
        tasks.append((lid, suffix, float(t)))

    traces: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = {
            ex.submit(
                _one_reviewer,
                lens_id=lid,
                lens_suffix=suf,
                messages=messages,
                model=cfg.vllm_model_name,
                base_url=cfg.vllm_base_url,
                api_key=cfg.vllm_api_key,
                timeout=float(cfg.vllm_timeout_sec),
                max_out=max_out,
                temperature=temp,
            ): lid
            for lid, suf, temp in tasks
        }
        for fut in as_completed(futs):
            traces.append(fut.result())
    traces.sort(key=lambda tr: next((i for i, (a, _) in enumerate(_REVIEWER_LENSES) if a == tr["lens"]), 99))
    return traces


def _chairman_synthesis(
    traces: list[dict[str, Any]],
    chairman_temperature: float,
) -> tuple[_ChairmanConsensusOut, str]:
    cfg = get_settings()
    max_out = context_budget()["critique_max_out"]
    vote_agreement = _vote_agreement([str(t.get("overall_quality", "ok")) for t in traces])
    user = build_chairman_user_prompt(traces, vote_agreement=float(vote_agreement))

    raw_client = OpenAI(
        base_url=cfg.vllm_base_url,
        api_key=cfg.vllm_api_key,
        timeout=float(cfg.vllm_timeout_sec),
    )
    client = instructor.from_openai(raw_client, mode=instructor.Mode.JSON)
    out: _ChairmanConsensusOut = client.chat.completions.create(
        model=cfg.vllm_model_name,
        messages=[
            {"role": "system", "content": CHAIRMAN_CONSENSUS_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        response_model=_ChairmanConsensusOut,
        temperature=chairman_temperature,
        max_tokens=max_out,
        max_retries=3,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    # Conservative epistemics: never claim higher agreement than the vote; cap "good" under strong disagreement.
    agree = min(float(out.reviewer_agreement_score), float(vote_agreement))
    out = out.model_copy(update={"reviewer_agreement_score": agree})
    if vote_agreement < 0.5 and out.overall_quality == "good":
        out = out.model_copy(update={"overall_quality": "ok"})
    raw_audit = json.dumps({"reviewer_traces": traces, "chairman": out.model_dump()}, indent=2, default=str)
    return out, raw_audit


def run_critique_with_council(state: DatasetState) -> DatasetState:
    """Critique path: parallel lenses + chairman consensus."""
    rows = state.get("rows", [])
    if not rows:
        return {**state, "critique_text": "No rows extracted yet.", "critique_quality": "needs_work"}

    p2d = load_prompt2dataset_config()
    messages = _build_critique_messages(state)
    temps = p2d.critique_council_reviewer_temperatures_list()
    traces = _run_reviewers_parallel(
        messages,
        n_reviewers=p2d.critique_council_reviewer_count,
        temps=temps,
    )
    try:
        chairman, raw_audit = _chairman_synthesis(
            traces,
            chairman_temperature=p2d.critique_council_chairman_temperature,
        )
    except Exception as exc:
        logger.error("critique council chairman failed: %s", exc)
        return {
            **state,
            "critique_text": f"Council critique failed (chairman): {exc}",
            "critique_quality": "needs_work",
            "critique_council_trace": traces,
            "critique_consensus": {"error": str(exc), "reviewer_agreement_score": 0.0},
        }

    coerced = _CritiqueOut(
        overall_quality=chairman.overall_quality,
        field_issues=chairman.field_issues,
        overall_suggestion=chairman.overall_suggestion or None,
    )
    out_state = _state_from_structured(state, coerced)
    consensus = {
        "reviewer_agreement_score": chairman.reviewer_agreement_score,
        "dissent_summary": chairman.dissent_summary,
        "consensus_rationale": chairman.consensus_rationale,
        "reviewer_qualities": [t.get("overall_quality") for t in traces],
        "lenses": [t.get("lens") for t in traces],
    }
    return {
        **out_state,
        "critique_council_trace": traces,
        "critique_consensus": consensus,
        "critique_llm_raw": raw_audit[:120_000],
    }


def _chunk_text(s: str, size: int) -> list[str]:
    if not s:
        return []
    return [s[i : i + size] for i in range(0, len(s), size)]


def stream_critique_with_council(
    state: DatasetState,
) -> Generator[tuple[str, DatasetState | None], None, None]:
    """Run reviewers then chairman (structured); stream the final summary text for the UI."""
    rows = state.get("rows", [])
    if not rows:
        yield "", {**state, "critique_text": "No rows extracted yet.", "critique_quality": "needs_work"}
        return

    yield "*Validation council — stage 1/2: independent reviewers…*", None

    p2d = load_prompt2dataset_config()
    messages = _build_critique_messages(state)
    temps = p2d.critique_council_reviewer_temperatures_list()
    traces = _run_reviewers_parallel(
        messages,
        n_reviewers=p2d.critique_council_reviewer_count,
        temps=temps,
    )

    yield "\n\n*Stage 2/2: chairman consensus (structured)…*\n\n", None

    try:
        chairman, raw_audit = _chairman_synthesis(
            traces,
            chairman_temperature=p2d.critique_council_chairman_temperature,
        )
    except Exception as exc:
        logger.error("critique council stream/chairman failed: %s", exc)
        yield "", {
            **state,
            "critique_text": f"Council critique failed: {exc}",
            "critique_quality": "needs_work",
            "critique_council_trace": traces,
            "critique_consensus": {"error": str(exc)},
        }
        return

    coerced = _CritiqueOut(
        overall_quality=chairman.overall_quality,
        field_issues=chairman.field_issues,
        overall_suggestion=chairman.overall_suggestion or None,
    )
    out_state = _state_from_structured(state, coerced)
    consensus = {
        "reviewer_agreement_score": chairman.reviewer_agreement_score,
        "dissent_summary": chairman.dissent_summary,
        "consensus_rationale": chairman.consensus_rationale,
        "reviewer_qualities": [t.get("overall_quality") for t in traces],
        "lenses": [t.get("lens") for t in traces],
    }
    final_state = {
        **out_state,
        "critique_council_trace": traces,
        "critique_consensus": consensus,
        "critique_llm_raw": raw_audit[:120_000],
    }
    body = (final_state.get("critique_text") or "").strip()
    epistemic_header = (
        f"\n\n**Consensus** — reviewer agreement: **{chairman.reviewer_agreement_score:.0%}** "
        f"(modal vote alignment with individual `overall_quality` labels).\n"
    )
    if chairman.dissent_summary.strip():
        epistemic_header += f"\n**Dissent / tension:** {chairman.dissent_summary.strip()}\n"
    if chairman.consensus_rationale.strip():
        epistemic_header += f"\n*{chairman.consensus_rationale.strip()}*\n"

    stream_text = epistemic_header + "\n---\n\n" + body
    for part in _chunk_text(stream_text, 160):
        yield part, None

    yield "", final_state
