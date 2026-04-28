"""Tests for repo-root global wonder queue."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "wonder_queue.jsonl"
    monkeypatch.setenv("ISF_GLOBAL_WONDER_QUEUE_PATH", str(p))
    return p


def test_append_pending_resolve(tmp_queue: Path) -> None:
    from prompt2dataset.utils import global_wonder_queue as gw

    e1 = gw.append_global_wonder({"kind": "t", "x": 1}, priority="high", run_id="r1", source="test")
    e2 = gw.append_global_wonder({"kind": "t", "x": 2}, run_id="r1", source="test")
    pend = gw.pending_global_wonders(limit=50)
    assert len(pend) == 2
    assert {str(x.get("event_id")) for x in pend} == {e1, e2}

    gw.append_wonder_resolved(e1, summary="done", ok=True)
    pend2 = gw.pending_global_wonders(limit=50)
    assert len(pend2) == 1
    assert pend2[0].get("event_id") == e2


def test_mirror_dedupe(tmp_queue: Path) -> None:
    from prompt2dataset.utils import global_wonder_queue as gw

    states = [
        {"doc_id": "d1", "field_name": "f1", "schema_hash": "h1", "reason": "evidenceless"},
    ]
    assert gw.mirror_export_wonders(run_id="run_a", run_wonder_states=states, corpus_id="c1") == 1
    assert gw.mirror_export_wonders(run_id="run_a", run_wonder_states=states, corpus_id="c1") == 0

    lines = tmp_queue.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["event_type"] == "global_wonder"
    assert row["task"]["doc_id"] == "d1"
