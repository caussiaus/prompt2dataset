"""export_node CSV + cells JSONL."""
from __future__ import annotations

from pathlib import Path

from prompt2dataset.dataset_graph.graph import export_node


def test_export_writes_csv_and_cells_jsonl(tmp_path: Path) -> None:
    state = {
        "rows": [
            {
                "doc_id": "d1",
                "filing_id": "d1",
                "widget": "hello",
                "widget_evidence_quote": "quote",
                "widget_evidence_pages": "1-1",
                "widget_evidence_section": "A",
            }
        ],
        "proposed_columns": [
            {"name": "widget", "type": "string", "default": ""},
        ],
        "identity_fields": ["doc_id", "filing_id"],
        "dataset_name": "unit_export",
        "cells": [
            {
                "row_id": "d1",
                "field_name": "widget",
                "proposed_value": "hello",
                "decision": "proposed",
            }
        ],
        "datasets_export_dir": str(tmp_path),
    }
    out = export_node(state)
    assert not out.get("error"), out.get("error")
    csv_path = Path(out["dataset_path"])
    assert csv_path.is_file()
    cells_path = Path(out.get("cells_dataset_path", ""))
    assert cells_path.is_file()
    text = cells_path.read_text(encoding="utf-8")
    assert "widget" in text and "d1" in text
