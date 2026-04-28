"""Routing and topology checks for the dataset LangGraph."""
from __future__ import annotations

from prompt2dataset.dataset_graph.graph import (
    _route_after_critique,
    _route_after_schema,
    build_dataset_graph,
    prepare_rework_node,
)
from prompt2dataset.dataset_graph.state import DatasetState


def test_route_after_schema_approved_goes_extraction():
    s: DatasetState = {"schema_approved": True}
    assert _route_after_schema(s) == "extraction"


def test_route_after_schema_not_approved_loops():
    s: DatasetState = {"schema_approved": False}
    assert _route_after_schema(s) == "schema_design"


def test_route_after_critique_export_when_flagged():
    s: DatasetState = {"export_approved": True, "critique_quality": "needs_work"}
    assert _route_after_critique(s) == "export"


def test_route_after_critique_prepare_rework_when_needs_work_under_cap():
    s: DatasetState = {
        "export_approved": False,
        "critique_quality": "needs_work",
        "rework_count": 0,
    }
    assert _route_after_critique(s) == "prepare_rework"


def test_route_after_critique_export_when_rework_cap():
    s: DatasetState = {
        "export_approved": False,
        "critique_quality": "needs_work",
        "rework_count": 3,
    }
    assert _route_after_critique(s) == "export"


def test_route_after_critique_export_when_quality_ok():
    s: DatasetState = {
        "export_approved": False,
        "critique_quality": "ok",
        "rework_count": 0,
    }
    assert _route_after_critique(s) == "export"


def test_prepare_rework_increments_and_clears_approval():
    s: DatasetState = {
        "rework_count": 0,
        "schema_approved": True,
        "critique_suggestions": [{"field": "x", "suggestion": "fix"}],
    }
    out = prepare_rework_node(s)
    assert out["rework_count"] == 1
    assert out["schema_approved"] is False
    assert "[x]" in (out.get("schema_feedback") or "")


def test_build_graph_includes_prepare_rework_and_converges_to_end():
    g = build_dataset_graph()
    raw = g.get_graph()
    nodes = set(raw.nodes)
    assert "schema_design" in nodes
    assert "extraction" in nodes
    assert "grounding_gate" in nodes
    assert "critique" in nodes
    assert "prepare_rework" in nodes
    assert "export" in nodes
    assert "__end__" in nodes
