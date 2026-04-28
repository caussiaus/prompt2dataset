"""Lakehouse coordinator — federated dataset of parsed documents.

The lakehouse spans all corpora. A single DuckDB instance indexes everything:
  - doc_registry: every parsed PDF across all corpora
  - corpus_registry: federated catalog row per corpus (PDF root, index CSV, chunks parquet,
    Lance table name ``chunks_<corpus_id>``) — not one global "filings index"
  - schema_history: approved schema versions
  - extraction_jobs: run history

LanceDB tables are per-corpus (chunks_{corpus_id}); hybrid search keys off ``corpus_id``.
DuckDB can query LanceDB tables directly via the lance extension.

Usage:
    from prompt2dataset.utils.lakehouse import Lakehouse
    lh = Lakehouse()
    lh.register_corpus(corpus_cfg)
    lh.index_corpus_chunks(corpus_id, chunks_df)
    stats = lh.stats()
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)


class Lakehouse:
    """Coordinator for the federated document lakehouse.

    Manages:
    - DuckDB doc_registry + corpus_registry (metadata)
    - LanceDB chunk tables (per-corpus vector store)
    - Ingest cache (hash-based deduplication)
    """

    def __init__(self, db_path: Path | str | None = None):
        from prompt2dataset.utils.lance_store import _LAKEHOUSE_DB
        self.db_path = Path(db_path) if db_path else _LAKEHOUSE_DB

    def register_corpus(
        self,
        corpus_cfg,
        project_root: Path | None = None,
        *,
        source_kind: str = "config",
    ) -> None:
        """Register a corpus in the federated corpus_registry (paths + Lance table name)."""
        from prompt2dataset.utils.lance_store import upsert_corpus_registry

        from prompt2dataset.utils.config import get_settings
        root = project_root or get_settings().project_root
        try:
            import pandas as pd

            idx_resolved = corpus_cfg.resolve(corpus_cfg.index_csv, root)
            doc_count = len(pd.read_csv(idx_resolved, dtype=str)) if idx_resolved.is_file() else 0
            index_csv_path = str(idx_resolved) if corpus_cfg.index_csv else ""
        except Exception:
            doc_count = 0
            index_csv_path = str(corpus_cfg.index_csv or "")
        try:
            chunks_parquet_path = str(corpus_cfg.resolve(corpus_cfg.chunks_parquet, root))
        except Exception:
            chunks_parquet_path = corpus_cfg.chunks_parquet or ""
        try:
            docs_dir = str(corpus_cfg.resolve(corpus_cfg.docs_dir, root))
        except Exception:
            docs_dir = corpus_cfg.docs_dir or ""

        upsert_corpus_registry(
            corpus_cfg.corpus_id,
            corpus_cfg.name,
            topic=corpus_cfg.topic or "",
            doc_count=doc_count,
            index_csv_path=index_csv_path,
            docs_dir=docs_dir,
            chunks_parquet_path=chunks_parquet_path,
            source_kind=source_kind,
            db_path=self.db_path,
        )
        logger.info(
            "Lakehouse: registered corpus %s (%d docs, source=%s)",
            corpus_cfg.corpus_id,
            doc_count,
            source_kind,
        )

    def index_corpus_chunks(
        self,
        corpus_id: str,
        chunks_df: "pd.DataFrame",
        *,
        overwrite: bool = False,
        corpus_cfg=None,
    ) -> int:
        """Index a corpus's chunks into LanceDB and sync catalog row (chunk + Lance counts).

        Returns the number of rows written to Lance (0 if skipped or unavailable).
        If the Lance table already exists and overwrite=False, skips re-embedding but still
        updates corpus_registry with parquet chunk counts so the catalog matches reality.
        """
        from prompt2dataset.utils.lance_store import build_lance_index, corpus_table_exists, upsert_corpus_registry

        cname = corpus_cfg.name if corpus_cfg is not None else corpus_id
        n = 0
        if not overwrite and corpus_table_exists(corpus_id):
            logger.info(
                "Lakehouse: Lance table chunks_%s already exists — skipping re-embed (syncing catalog)",
                corpus_id,
            )
        else:
            n = build_lance_index(chunks_df, corpus_id, overwrite=overwrite)

        lance_rows = int(n) if n else 0
        if not lance_rows and corpus_table_exists(corpus_id):
            try:
                import lancedb
                from prompt2dataset.utils.lance_store import _LANCE_BASE
                db = lancedb.connect(str(_LANCE_BASE))
                tname = f"chunks_{corpus_id}"
                if tname in db.table_names():
                    lance_rows = int(db.open_table(tname).count_rows())
            except Exception:
                lance_rows = len(chunks_df)

        upsert_corpus_registry(
            corpus_id,
            cname,
            chunk_count=len(chunks_df),
            lance_chunk_rows=lance_rows,
            db_path=self.db_path,
        )
        logger.info("Lakehouse: Lance rows=%d parquet_chunks=%d for corpus %s", lance_rows, len(chunks_df), corpus_id)
        return n

    def register_parsed_doc(
        self,
        filing_id: str,
        corpus_id: str,
        *,
        original_path: str = "",
        json_path: str = "",
        chunk_count: int = 0,
        entity_name: str = "",
        doc_type: str = "",
        doc_date: str = "",
        entity_id: str = "",
        fiscal_year: int | None = None,
        period_end: str | None = None,
        profile_number: str = "",
    ) -> None:
        """Register a single parsed document in the doc_registry."""
        from prompt2dataset.utils.ingest_cache import hash_pdf, register_parse
        from prompt2dataset.utils.lance_store import register_doc_in_lakehouse

        file_hash = ""
        if original_path:
            try:
                file_hash = hash_pdf(original_path)
                register_parse(
                    file_hash, filing_id, corpus_id, original_path, json_path
                )
            except Exception:
                pass

        register_doc_in_lakehouse(
            filing_id, corpus_id,
            file_hash=file_hash,
            entity_name=entity_name,
            doc_type=doc_type,
            doc_date=doc_date,
            chunk_count=chunk_count,
            json_path=json_path,
            entity_id=entity_id,
            fiscal_year=fiscal_year,
            period_end=period_end,
            profile_number=profile_number,
            db_path=self.db_path,
        )

    def stats(self) -> dict:
        """Return lakehouse statistics."""
        from prompt2dataset.utils.lance_store import get_lakehouse_stats
        from prompt2dataset.utils.ingest_cache import cache_stats
        lh = get_lakehouse_stats(db_path=self.db_path)
        cache = cache_stats()
        return {**lh, "cache": cache}

    def is_pdf_cached(self, pdf_path: str) -> tuple[bool, str]:
        """Check if a PDF has already been parsed.

        Returns (is_cached, cached_json_path).
        """
        from prompt2dataset.utils.ingest_cache import hash_pdf, get_cached_json_path
        try:
            fh = hash_pdf(pdf_path)
            cached = get_cached_json_path(fh)
            return cached is not None, cached or ""
        except Exception:
            return False, ""
