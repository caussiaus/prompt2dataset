"""Guardrails: extraction quality depends on index rows having chunk rows with the same doc_id."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _paths():
    idx = ROOT / "output" / "filings" / "index.csv"
    ch = ROOT / "output" / "filings" / "chunks" / "chunks.parquet"
    return idx, ch


@pytest.mark.skipif(not _paths()[0].is_file(), reason="filings index not present")
@pytest.mark.skipif(not _paths()[1].is_file(), reason="filings chunks not present")
def test_filing_index_chunk_overlap_is_documented():
    """When overlap is tiny, extraction sees empty evidence for most index docs.

    This test documents current workspace state; tighten the threshold once
    ingest has chunked the full corpus.
    """
    idx_p, ch_p = _paths()
    idx = pd.read_csv(idx_p, dtype=str)
    ch = pd.read_parquet(str(ch_p))
    id_col = "filing_id" if "filing_id" in ch.columns else "doc_id"
    idx_ids = set(idx["doc_id"].dropna().astype(str).unique())
    ch_ids = set(ch[id_col].dropna().astype(str).unique())
    overlap = idx_ids & ch_ids
    # Fail loudly if literally nothing matches (broken config)
    assert len(ch_ids) == 0 or len(overlap) > 0, (
        "chunks parquet doc_ids do not intersect index — check path/doc_id consistency"
    )
    ratio = len(overlap) / max(len(idx_ids), 1)
    # Document: expect low ratio until full chunking run completes
    print(
        f"index_docs={len(idx_ids)} chunk_docs={len(ch_ids)} overlap={len(overlap)} "
        f"ratio={ratio:.4f}"
    )


def test_retrieve_evidence_returns_empty_when_no_chunks_for_doc():
    """Retrieval must not crash when a doc has zero chunk rows."""
    from prompt2dataset.utils.call_config import enrich_proposed_columns_for_extraction
    from prompt2dataset.utils.retrieval import retrieve_evidence_blocks

    cols = enrich_proposed_columns_for_extraction(
        [
            {
                "name": "x",
                "type": "string|null",
                "description": "test",
                "extraction_instruction": "test field",
            }
        ],
        corpus_topic="",
    )
    empty = pd.DataFrame(columns=["doc_id", "text", "chunk_id", "page_start", "page_end"])
    blocks, total, kw = retrieve_evidence_blocks(cols, empty, doc_id="nope", corpus_id=None)
    assert blocks == [] and total == 0 and kw == 0
