"""DPO export script: prompt assembly + CLI smoke."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from prompt2dataset.scripts.export_dpo_pairs import build_dpo_prompt


def test_build_dpo_prompt_from_full_action():
    ev = {
        "action": {
            "system_prompt": "SYS",
            "user_prompt": "USR",
            "schema_json": '{"a":1}',
        }
    }
    p = build_dpo_prompt(ev)
    assert "### system" in p and "SYS" in p
    assert "### user" in p and "USR" in p
    assert "### schema" in p


def test_build_dpo_prompt_legacy_empty():
    assert build_dpo_prompt({"action": {"llm_raw_output": "{}"}}) == ""


def test_export_dpo_cli(tmp_path: Path):
    te = tmp_path / "training_events.jsonl"
    out = tmp_path / "dpo.jsonl"
    lines = [
        {
            "event_type": "llm_extract",
            "run_id": "r1",
            "state": {"doc_id": "d1", "schema_hash": "sh1", "retrieved_chunks": ["c1"]},
            "action": {
                "llm_raw_output": json.dumps({"alpha": "wrong"}),
                "system_prompt": "S",
                "user_prompt": "U",
            },
        },
        {
            "event_type": "human_override",
            "run_id": "r1",
            "state": {"doc_id": "d1", "schema_hash": "sh1", "field_name": "alpha"},
            "action": {"override_value": "ok"},
        },
    ]
    te.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "scripts" / "export_dpo_pairs.py"
    r = subprocess.run(
        [sys.executable, str(script), str(te), "-o", str(out)],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert r.returncode == 0, r.stderr
    rec = json.loads(out.read_text(encoding="utf-8").strip())
    assert rec.get("prompt")
    assert "wrong" in rec.get("rejected", "")
    assert "ok" in rec.get("chosen", "")
