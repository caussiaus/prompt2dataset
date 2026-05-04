"""Federated document catalog — metadata graph for all corpora (uploads + paths + bulk).

There is no single global "filings index" in the architecture: each corpus has its own
row in DuckDB ``corpus_registry`` (PDF root, index CSV path, chunks parquet path,
``source_kind``, and the LanceDB table name ``chunks_<corpus_id>``).

Hybrid search in :mod:`prompt2dataset.utils.retrieval` uses ``corpus_id`` to open the
matching Lance table; DuckDB joins entities and documents for scope/export.

See :class:`prompt2dataset.utils.lakehouse.Lakehouse` for registration at ingest / UI.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from prompt2dataset.utils.lance_store import get_corpus_catalog_row, lance_table_name_for_corpus


def list_corpora(*, limit: int = 100, db_path: Path | None = None) -> pd.DataFrame:
    """Return catalog rows (newest first)."""
    from prompt2dataset.utils.lance_store import _get_lakehouse_db

    con = _get_lakehouse_db(db_path)
    try:
        return con.execute(
            """
            SELECT corpus_id, name, topic, source_kind, doc_count, chunk_count,
                   lance_chunk_rows, lance_table, index_csv_path, docs_dir,
                   chunks_parquet_path, updated_at
            FROM corpus_registry
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            [limit],
        ).fetchdf()
    finally:
        con.close()


def describe_lance_link(corpus_id: str, *, db_path: Path | None = None) -> str:
    """One-line summary: catalog row + expected Lance table name."""
    row = get_corpus_catalog_row(corpus_id, db_path=db_path)
    t = lance_table_name_for_corpus(corpus_id)
    if not row:
        return (
            f"No catalog row for {corpus_id!r}; retrieval still uses Lance table `{t}` by convention."
        )
    return (
        f"{corpus_id}: Lance `{row.get('lance_table', t)}` "
        f"~{row.get('lance_chunk_rows', 0)} rows | "
        f"index `{row.get('index_csv_path', '')}` | source={row.get('source_kind', '')}"
    )


def corpus_paths_for(corpus_id: str, *, db_path: Path | None = None) -> dict[str, Any] | None:
    """Resolved paths from catalog (empty strings if unknown)."""
    r = get_corpus_catalog_row(corpus_id, db_path=db_path)
    return r
