"""Epistemic blackboard normalization (legacy flat → per-doc)."""
from __future__ import annotations

from prompt2dataset.utils.epistemic_blackboard import (
    get_doc_blackboard,
    normalize_epistemic_root,
)


def test_normalize_legacy_flat_pressure():
    raw = {"beliefs": [], "field_pressure": {"d1::foo": 2.5, "d2::bar": 1.0}, "evidence_dag": {}}
    out = normalize_epistemic_root(raw)
    assert out["d1"]["field_pressure"]["foo"] == 2.5
    assert out["d2"]["field_pressure"]["bar"] == 1.0


def test_normalize_per_doc_passthrough():
    raw = {"d1": {"beliefs": [], "field_pressure": {"x": 1.0}, "evidence_dag": {}}}
    out = normalize_epistemic_root(raw)
    assert out["d1"]["field_pressure"]["x"] == 1.0


def test_get_doc_blackboard_mutates_root():
    root: dict = {}
    bb = get_doc_blackboard(root, "docA")
    bb["field_pressure"]["f"] = 3.0
    assert "docA" in root
    assert root["docA"]["field_pressure"]["f"] == 3.0
