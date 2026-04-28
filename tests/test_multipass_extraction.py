"""Smoke tests for multipass blackboard extraction helpers (no vLLM)."""
from __future__ import annotations

from prompt2dataset.utils.retrieval import (
    effective_retrieval_query_string,
    merge_evidence_block_lists,
    semantic_query_string,
)
from prompt2dataset.dataset_graph.extraction_node import _normalize_scout_payload, _refinement_query_from_scout


def test_merge_evidence_block_lists_dedupes_and_caps() -> None:
    a = [{"chunk_id": "1", "text": "a"}, {"chunk_id": "2", "text": "b"}]
    b = [{"chunk_id": "1", "text": "dup"}, {"chunk_id": "3", "text": "c"}]
    m = merge_evidence_block_lists(a, b, max_total=12)
    assert len(m) == 3
    assert m[0]["chunk_id"] == "1" and m[0]["text"] == "a"
    m2 = merge_evidence_block_lists(a, b, max_total=2)
    assert len(m2) == 2


def test_effective_query_override() -> None:
    cols: list[dict] = [
        {"name": "revenue", "type": "string|null", "description": "R", "extraction_instruction": "rev"},
    ]
    assert effective_retrieval_query_string(cols, None, "  net zero 2050  ").strip() == "net zero 2050"
    base = semantic_query_string(cols, None)
    assert effective_retrieval_query_string(cols, None, None) == base


def test_normalize_scout_payload() -> None:
    d = _normalize_scout_payload(
        {
            "resolved_fields": {"a": 1},
            "hypotheses": [{"target_fields": ["b"], "summary": "s", "anchor_chunk_ids": [], "needs": "n"}],
            "unresolved_fields": ["b", "b"],
        }
    )
    assert d["resolved_fields"] == {"a": 1}
    assert len(d["unresolved_fields"]) == 1


def test_refinement_query_from_scout() -> None:
    cols: list[dict] = [
        {
            "name": "f1",
            "type": "string",
            "description": "d",
            "keywords": ["k1", "k2"],
            "extraction_instruction": "look",
        }
    ]
    bb = {
        "unresolved_fields": ["f1"],
        "hypotheses": [{"needs": "clause about litigation", "summary": "hint"}],
    }
    q = _refinement_query_from_scout(cols, bb, "topic")
    assert "k1" in q or "litigation" in q or "look" in q
