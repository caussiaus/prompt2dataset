#!/usr/bin/env python3
"""Measure index ↔ chunks ↔ retrieval alignment for a corpus (no LLM).

Poor "table quality" in the UI is often:
  - doc_ids in index with no rows in chunks.parquet → 0 evidence blocks
  - trial queue picking head-of-index docs that were never parsed
  - doc_id = md5(path): different host/path → different id than chunking run

Usage::
  python scripts/diagnose_extraction_evidence.py --config output/corpus_configs/filings.yaml
  python scripts/diagnose_extraction_evidence.py --index output/filings/index.csv --chunks output/filings/chunks/chunks.parquet
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT.parent, ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=str, default="", help="CorpusConfig YAML")
    ap.add_argument("--index", type=str, default="", help="Override index CSV")
    ap.add_argument("--chunks", type=str, default="", help="Override chunks parquet")
    ap.add_argument("--sample", type=int, default=3, help="Sample docs for retrieval preview")
    args = ap.parse_args()

    from prompt2dataset.corpus.config import CorpusConfig
    from prompt2dataset.corpus.paths import resolve_corpus_path
    from prompt2dataset.utils.config import get_settings
    from prompt2dataset.utils.call_config import enrich_proposed_columns_for_extraction
    from prompt2dataset.utils.retrieval import retrieve_evidence_blocks, semantic_query_string

    cfg = get_settings()
    project_root = cfg.project_root

    if args.config:
        corpus = CorpusConfig.from_yaml(Path(args.config).expanduser())
        idx_path = corpus.resolve(corpus.index_csv, project_root)
        ch_path = corpus.resolve(corpus.chunks_parquet, project_root)
        topic = corpus.topic or ""
        cid = corpus.corpus_id
    else:
        idx_path = Path(args.index or "")
        ch_path = Path(args.chunks or "")
        topic = "revenue by segment"
        cid = "filings"

    if not idx_path.is_file():
        print(f"ERROR: index not found: {idx_path}")
        return 1
    if not ch_path.is_file():
        print(f"ERROR: chunks parquet not found: {ch_path}")
        return 1

    import pandas as pd

    idx = pd.read_csv(idx_path, dtype=str)
    ch = pd.read_parquet(str(ch_path))
    id_col = "filing_id" if "filing_id" in ch.columns else "doc_id"
    idx_id = "doc_id" if "doc_id" in idx.columns else "filing_id"

    idx_ids = set(idx[idx_id].dropna().astype(str).unique())
    ch_ids = set(ch[id_col].dropna().astype(str).unique())
    overlap = idx_ids & ch_ids
    only_idx = idx_ids - ch_ids
    print("=== Index vs chunks ===")
    print(f"  index rows:     {len(idx)}")
    print(f"  unique doc ids (index): {len(idx_ids)}")
    print(f"  unique doc ids (chunks): {len(ch_ids)}")
    print(f"  overlap (both): {len(overlap)}")
    print(f"  index docs with ZERO chunks: {len(only_idx)}")
    if len(only_idx) == len(idx_ids) and len(ch_ids) > 0:
        print("  WARNING: no overlap — doc_id likely from different path strings than chunking run.")

    # Prefer overlapping docs for retrieval demo
    pool = list(overlap) if overlap else list(ch_ids)[: args.sample]
    raw_cols = [
        {
            "name": "revenue_segment",
            "type": "string|null",
            "description": "Segment",
            "extraction_instruction": "revenue by segment operating segment",
        },
        {
            "name": "revenue_segment_value",
            "type": "float|null",
            "description": "Amount",
            "extraction_instruction": "segment revenue millions",
        },
    ]
    cols = enrich_proposed_columns_for_extraction(raw_cols, corpus_topic=topic)

    print("\n=== Retrieval preview (schema-aligned query, no LLM) ===")
    print(f"  semantic_query_string: {semantic_query_string(cols, topic)[:240]}…")
    for fid in pool[: args.sample]:
        sub = ch[ch[id_col].astype(str) == str(fid)]
        blocks, total, kw = retrieve_evidence_blocks(
            cols,
            sub,
            doc_id=str(fid),
            corpus_id=cid if cid else None,
            corpus_topic=topic or None,
        )
        row = idx[idx[idx_id].astype(str) == str(fid)]
        fn = str(row.iloc[0].get("filename", "")) if len(row) else "?"
        print(f"\n  doc_id={fid[:12]}… file={fn[:56]}")
        print(f"    chunks_in_parquet={len(sub)} total_for_retrieval={total} keyword_hits={kw} blocks_to_llm={len(blocks)}")
        for j, b in enumerate(blocks[:2]):
            t = (b.get("text") or "").replace("\n", " ")[:200]
            print(f"    block[{j}] p{b.get('page_start')}-{b.get('page_end')}: {t}…")

    print("\n=== Recommendations ===")
    if len(only_idx) > len(overlap):
        print("  - Re-run parse/chunk for this corpus until overlap ≈ index size, or restrict")
        print("    extraction to doc_ids that exist in chunks (see build_doc_queue in pipeline_runner).")
        print("  - If you moved files or changed paths, rebuild index with overwrite=True so doc_id")
        print("    matches a single consistent root (FILINGS_PDF_ROOT / same machine).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
