#!/usr/bin/env python3
"""Run ``extraction_node`` using a JSON schema file + a corpus YAML (index + chunks).

Typical flow (repo PDFs under ``data/pdfs/ESG_Reports_2024``)::

  python3 scripts/check_stack_ready.py
  python3 scripts/run_extraction_from_schema.py \\
      --corpus-yaml output/corpus_configs/esg_smoke_2024_86.yaml \\
      --schema-json data/schema.json

Requires vLLM reachable (same contract as the Dataset Builder). Optional ``--ingest``
runs parse+chunk first via ``run_corpus_pipeline.py --stage ingest``.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT.parent, _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _default_for_type(typ: str, *, required: bool) -> object:
    t = (typ or "string").lower()
    if t == "boolean":
        return False
    if t in ("integer", "int", "float", "number", "double"):
        return None if not required else 0
    return "" if required else None


def schema_to_proposed_columns(raw: dict) -> list[dict]:
    cols: list[dict] = []
    for c in raw.get("extraction_schema", []):
        name = str(c.get("name", "")).strip()
        if not name:
            continue
        typ = str(c.get("type", "string")).strip()
        desc = str(c.get("description", "")).strip()
        if c.get("unit"):
            desc = f"{desc} (unit: {c['unit']})".strip()
        if c.get("enum"):
            desc = f"{desc} Allowed values: {c['enum']}".strip()
        req = bool(c.get("required"))
        cols.append(
            {
                "name": name,
                "type": typ,
                "description": desc,
                "extraction_instruction": desc or f"Extract {name} from the document.",
                "keywords": [w for w in (name.replace("_", " "),) if w],
                "default": _default_for_type(typ, required=req),
                "mode": "direct",
            }
        )
    return cols


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--corpus-yaml",
        default=str(_ROOT / "output/corpus_configs/esg_smoke_2024_86.yaml"),
        help="CorpusConfig YAML (after apply_corpus_env, FILINGS_INDEX_PATH / CHUNKS_PARQUET come from here)",
    )
    p.add_argument("--schema-json", default=str(_ROOT / "data/schema.json"))
    p.add_argument(
        "--ingest",
        action="store_true",
        help="Run ``scripts/run_corpus_pipeline.py --stage ingest --no-skip`` for this corpus first",
    )
    p.add_argument(
        "--skip-vllm-check",
        action="store_true",
        help="Do not run check_stack_ready before extraction (not recommended)",
    )
    args = p.parse_args()

    project_root = _ROOT
    corpus_path = Path(args.corpus_yaml).expanduser()
    schema_path = Path(args.schema_json).expanduser()
    if not corpus_path.is_file():
        print("Missing corpus yaml:", corpus_path, file=sys.stderr)
        return 1
    if not schema_path.is_file():
        print("Missing schema json:", schema_path, file=sys.stderr)
        return 1

    if args.ingest:
        cmd = [
            sys.executable,
            str(project_root / "scripts/run_corpus_pipeline.py"),
            "--config",
            str(corpus_path),
            "--stage",
            "ingest",
            "--no-skip",
        ]
        print("Running:", " ".join(cmd), flush=True)
        r = subprocess.run(cmd, cwd=str(project_root))
        if r.returncode != 0:
            return r.returncode

    from prompt2dataset.corpus.config import CorpusConfig
    from prompt2dataset.corpus.runtime import apply_corpus_env
    from prompt2dataset.dataset_graph.extraction_node import extraction_node
    from prompt2dataset.dataset_graph.feedback_store import new_run_id
    from prompt2dataset.dataset_graph.state import DatasetState
    from prompt2dataset.utils.config import get_settings
    import pandas as pd

    cfg = CorpusConfig.from_yaml(corpus_path)
    applied = apply_corpus_env(cfg, project_root)
    for k in sorted(applied):
        print(f"  {k}={applied[k]}", flush=True)

    s = get_settings()
    idx_path = s.resolve(s.filings_index_path)
    ch_path = s.resolve(s.chunks_parquet)
    if not idx_path.is_file():
        print("Index missing after corpus env:", idx_path, file=sys.stderr)
        return 1
    if not ch_path.is_file():
        print("Chunks parquet missing:", ch_path, file=sys.stderr)
        print("Re-run with --ingest or complete Docling/chunking for this corpus.", file=sys.stderr)
        return 1

    idx = pd.read_csv(idx_path, dtype=str)
    ch = pd.read_parquet(str(ch_path))
    id_col = "filing_id" if "filing_id" in idx.columns else "doc_id"
    n_idx = len(idx)
    ch_ids = set(ch["filing_id"].astype(str)) if "filing_id" in ch.columns else set(ch["doc_id"].astype(str))
    covered = sum(1 for _, r in idx.iterrows() if str(r.get(id_col, "")) in ch_ids)
    print(f"index rows={n_idx} chunks rows={len(ch)} docs_with_chunks={covered}", flush=True)
    if covered < n_idx:
        print(
            f"WARNING: only {covered}/{n_idx} index documents appear in chunks — "
            "extraction may return sparse or default rows for missing docs.",
            file=sys.stderr,
        )

    if not args.skip_vllm_check:
        check_py = project_root / "scripts/check_stack_ready.py"
        cr = subprocess.run([sys.executable, str(check_py)], cwd=str(project_root))
        if cr.returncode != 0:
            print("Aborting: fix vLLM (see check_stack_ready output) or pass --skip-vllm-check.", file=sys.stderr)
            return cr.returncode

    raw = json.loads(schema_path.read_text(encoding="utf-8"))
    proposed = schema_to_proposed_columns(raw)
    if not proposed:
        print("No extraction_schema columns in", schema_path, file=sys.stderr)
        return 1

    run_id = new_run_id()
    datasets_dir = Path(applied.get("DATASETS_DIR") or "").expanduser()
    if not datasets_dir.is_absolute():
        datasets_dir = (project_root / datasets_dir).resolve()
    datasets_dir.mkdir(parents=True, exist_ok=True)

    topic = (cfg.topic or "").strip() or str(raw.get("project_name") or "extraction")
    state: DatasetState = {
        "proposed_columns": proposed,
        "schema_approved": True,
        "schema_iteration": 1,
        "use_sample": False,
        "extraction_mode": "direct",
        "corpus_topic": topic,
        "corpus_id": cfg.corpus_id,
        "identity_fields": list(cfg.identity_fields or []),
        "feedback_run_id": run_id,
        "run_id": run_id,
        "datasets_export_dir": str(datasets_dir),
        "extraction_row_granularity": "one_row_per_document",
    }

    print("extraction_node starting…", flush=True)
    out = extraction_node(state)
    if out.get("error"):
        print("extraction_node error:", out["error"], file=sys.stderr)
        return 1

    rows = out.get("rows") or []
    out_json = datasets_dir / f"extraction_from_schema_{run_id}.json"
    out_json.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    print("Wrote", out_json, "rows=", len(rows), flush=True)
    if rows:
        r0 = rows[0]
        keys = [k for k in ("doc_id", "filing_id", "company_name") if k in r0]
        for k in keys:
            print(f"  sample {k}:", str(r0.get(k, ""))[:120], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
