"""Critique JSON salvage when streaming truncates or breaks the outer object."""
from __future__ import annotations

from prompt2dataset.dataset_graph.critique_salvage import merge_critique_meta, salvage_critique_meta


def test_salvage_full_json_blob():
    text = """{ "overall_quality": "needs_work", "field_issues": [ { "field": "company_name", "issue": "null", "severity": "high", "suggestion": "fix" } ], "overall_suggestion": "Improve entity ID." }"""
    m = salvage_critique_meta(text)
    assert m["overall_quality"] == "needs_work"
    assert len(m["field_issues"]) == 1
    assert m["field_issues"][0]["field"] == "company_name"


def test_salvage_truncated_after_field_issues():
    """Outer JSON incomplete but individual issue objects parse."""
    text = """{ "overall_quality": "needs_work", "field_issues": [ { "field": "a", "issue": "i1", "severity": "high", "suggestion": "s1" }, { "field": "b", "issue": "i2", "severity": "medium", "suggestion": "s2" """
    m = salvage_critique_meta(text)
    assert m["overall_quality"] == "needs_work"
    assert len(m["field_issues"]) == 1
    assert m["field_issues"][0]["field"] == "a"


def test_merge_fills_empty_issues():
    primary = {"overall_quality": "ok", "field_issues": []}
    salv = {"field_issues": [{"field": "x", "issue": "y", "severity": "low", "suggestion": "z"}]}
    merged = merge_critique_meta(primary, salv)
    assert merged["overall_quality"] == "ok"
    assert len(merged["field_issues"]) == 1
