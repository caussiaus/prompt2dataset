"""Unit tests for deterministic grounding (no LLM)."""
from __future__ import annotations

from dataclasses import replace

from prompt2dataset.dataset_graph.grounding_gate import (
    apply_grounding_to_state,
    collapse_ws,
    quote_substring_verified,
)


def test_collapse_ws_normalizes():
    assert collapse_ws("  Hello   World\n") == "hello world"


def test_quote_substring_verified_positive():
    src = "The company reported Scope 3 emissions of 1.2 million tonnes in 2023."
    q = "Scope 3 emissions of 1.2 million tonnes"
    assert quote_substring_verified(q, src) is True


def test_quote_substring_verified_too_short():
    assert quote_substring_verified("short", "this is a longer source short") is False


def test_quote_substring_verified_negative():
    src = "Only benign disclosure text here."
    assert quote_substring_verified("totally absent phrase from model", src) is False


def test_grounding_clears_bad_quote(monkeypatch):
    from prompt2dataset.utils import prompt2dataset_settings as p2s

    cfg = replace(
        p2s.Prompt2DatasetConfig.defaults(),
        grounding_enabled=True,
        grounding_require_substring=True,
        grounding_use_nli=False,
    )
    monkeypatch.setattr(
        "prompt2dataset.dataset_graph.grounding_gate.load_prompt2dataset_config",
        lambda *a, **k: cfg,
    )

    state = {
        "proposed_columns": [{"name": "foo", "type": "string", "default": ""}],
        "identity_fields": ["doc_id"],
        "rows": [
            {
                "doc_id": "d1",
                "foo": "x",
                "foo_evidence_quote": "hallucinated sentence not in chunk",
                "foo_chunk_id": "c1",
                "foo_chunk_text": "Real chunk only mentions widgets.",
            }
        ],
        "corpus_chunks_parquet": "",
        "corpus_id": "",
    }
    out = apply_grounding_to_state(state)  # type: ignore[arg-type]
    row = out["rows"][0]
    assert row.get("foo_evidence_quote") is None
    assert out.get("epistemic_blackboard", {}).get("d1", {}).get("field_pressure", {}).get("foo", 0) >= 1.0


def test_grounding_skipped_when_disabled(monkeypatch):
    from prompt2dataset.utils import prompt2dataset_settings as p2s

    cfg = replace(p2s.Prompt2DatasetConfig.defaults(), grounding_enabled=False)
    monkeypatch.setattr(
        "prompt2dataset.dataset_graph.grounding_gate.load_prompt2dataset_config",
        lambda *a, **k: cfg,
    )

    rows = [
        {
            "doc_id": "d1",
            "foo": "x",
            "foo_evidence_quote": "nope",
            "foo_chunk_id": "c1",
            "foo_chunk_text": "different",
        }
    ]
    state = {"rows": rows, "proposed_columns": [{"name": "foo", "type": "string", "default": ""}]}
    out = apply_grounding_to_state(state)  # type: ignore[arg-type]
    assert out["rows"][0].get("foo_evidence_quote") == "nope"
