"""LLM output normalization for extraction."""
from prompt2dataset.dataset_graph.extraction_node import _normalize_extraction_payload


def test_flat_evidence_keys_folded_into_nested():
    columns = [
        {"name": "widget", "type": "string|null", "default": None},
    ]
    data = {
        "widget": "hello",
        "widget_evidence_quote": "q1",
        "widget_chunk_id": "c9",
        "widget_evidence_pages": "2-3",
    }
    out = _normalize_extraction_payload(data, columns)
    ev = out.get("widget_evidence")
    assert isinstance(ev, dict)
    assert ev.get("quote") == "q1"
    assert ev.get("chunk_id") == "c9"
    assert ev.get("page_start") == 2
    assert ev.get("page_end") == 3


def test_nested_evidence_left_unchanged():
    columns = [{"name": "x", "type": "string|null", "default": None}]
    data = {"x": "a", "x_evidence": {"quote": "q", "chunk_id": None, "page_start": 1, "page_end": 1, "section_path": None}}
    out = _normalize_extraction_payload(data, columns)
    assert out["x_evidence"]["quote"] == "q"
