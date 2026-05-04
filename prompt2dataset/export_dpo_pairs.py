#!/usr/bin/env python3
"""Build DPO-style (prompt, rejected, chosen) records from training_events.jsonl.

Pairs each ``human_override`` with the most recent prior ``llm_extract`` for the same
``run_id``, ``doc_id``, and ``schema_hash`` (MDP scope lock). If ``chunk_id`` is present
on both, it must match; otherwise chunk_id match is not required.

When ``llm_extract`` rows include ``action.system_prompt`` / ``action.user_prompt`` /
``action.schema_json`` (newer logs), output includes a TRL-style ``prompt`` string
built from those parts. Older JSONL lines without them still emit ``prompt_stub`` only
for the prompt slot (backward compatible).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _override_matches_extract(override_ev: dict[str, Any], extract_ev: dict[str, Any]) -> bool:
    """Same MDP episode: run_id, doc_id, schema_hash; optional chunk_id via retrieved_chunks."""
    if (override_ev.get("run_id") or "") != (extract_ev.get("run_id") or ""):
        return False
    ost = override_ev.get("state") or {}
    est = extract_ev.get("state") or {}
    if (ost.get("doc_id") or "") != (est.get("doc_id") or ""):
        return False
    osh, esh = str(ost.get("schema_hash") or ""), str(est.get("schema_hash") or "")
    if osh and esh and osh != esh:
        return False
    o_chunk = str(ost.get("chunk_id") or "").strip()
    rchunks = [str(c) for c in (est.get("retrieved_chunks") or [])]
    if o_chunk:
        return o_chunk in rchunks
    return True


def _splice_chosen(rejected: str, field: str, override: Any) -> str:
    """Best-effort: replace one top-level JSON value for field_name."""
    try:
        data = json.loads(rejected)
        if isinstance(data, dict) and field in data:
            data[field] = override
            return json.dumps(data, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return json.dumps(
        {"_note": "parse_failed", "field": field, "override": override, "raw_tail": (rejected or "")[:2000]},
        ensure_ascii=False,
    )


def build_dpo_prompt(extract_ev: dict[str, Any]) -> str:
    """Single training string from stored system/user/schema (or empty if legacy)."""
    ac = extract_ev.get("action") or {}
    sys_p = str(ac.get("system_prompt") or "").strip()
    usr_p = str(ac.get("user_prompt") or "").strip()
    sch = str(ac.get("schema_json") or "").strip()
    parts: list[str] = []
    if sys_p:
        parts.append("### system\n" + sys_p[:48_000])
    if usr_p:
        parts.append("### user\n" + usr_p[:48_000])
    if sch:
        parts.append("### schema\n" + sch[:24_000])
    return "\n\n".join(parts).strip()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("training_events", type=Path, help="Path to training_events.jsonl")
    p.add_argument("-o", "--out", type=Path, required=True, help="Output JSONL path")
    args = p.parse_args()

    lines = [
        json.loads(ln)
        for ln in args.training_events.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]

    n = 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for i, ev in enumerate(lines):
            if ev.get("event_type") != "human_override":
                continue
            st = ev.get("state") or {}
            ac = ev.get("action") or {}
            field = str(st.get("field_name") or ac.get("field_name") or "")
            extract_ev: dict[str, Any] | None = None
            for j in range(i - 1, -1, -1):
                prev = lines[j]
                if prev.get("event_type") != "llm_extract":
                    continue
                if _override_matches_extract(ev, prev):
                    extract_ev = prev
                    break
            if not extract_ev:
                continue

            ex_st = extract_ev.get("state") or {}
            ex_ac = extract_ev.get("action") or {}
            sh = str(st.get("schema_hash") or "")
            doc = str(st.get("doc_id") or "")
            raw = str(ex_ac.get("llm_raw_output") or "")
            override = ac.get("override_value")
            prompt_full = build_dpo_prompt(extract_ev)
            rec: dict[str, Any] = {
                "run_id": ev.get("run_id", ""),
                "doc_id": doc,
                "schema_hash": sh,
                "field_name": field,
                "prompt_stub": {
                    "retrieved_chunks": ex_st.get("retrieved_chunks", []),
                    "retrieved_chunk_hashes": ex_st.get("retrieved_chunk_hashes", []),
                    "schema_hash": sh,
                },
                "rejected": raw,
                "chosen": _splice_chosen(raw, field, override) if field else str(override),
            }
            if prompt_full:
                rec["prompt"] = prompt_full
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            n += 1

    print(f"Wrote {n} DPO-style records to {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
