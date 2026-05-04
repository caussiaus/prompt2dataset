"""Content-addressed ingest cache for PDF documents.

Each PDF is identified by a SHA256 hash of its content (first 64KB sampled
for speed — enough to detect duplicates without reading full files).

Cache structure:
  state/ingest_cache/
    manifest.duckdb     ← registry of all cached docs

Workflow:
  1. hash_pdf(path) → 16-char hex fingerprint
  2. is_cached(fingerprint, corpus_id) → bool (check DuckDB)
  3. register_parse(fingerprint, filing_id, corpus_id, json_path, ...) → write to DuckDB
  4. get_cached_path(fingerprint, corpus_id) → str|None → return existing JSON path

The cache is corpus-aware: the same PDF can appear in multiple corpora
(same content, different context) but is only PARSED once. The docling JSON
is symlinked (or the path is shared) across corpora.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parents[1] / "state" / "ingest_cache"
_MANIFEST_DB = _CACHE_DIR / "manifest.duckdb"


def _get_db(db_path: Path | None = None):
    """Get a DuckDB connection to the manifest database."""
    import duckdb
    p = db_path or _MANIFEST_DB
    p.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(p))
    con.execute("""
        CREATE TABLE IF NOT EXISTS doc_cache (
            file_hash       TEXT PRIMARY KEY,
            filing_id       TEXT NOT NULL,
            corpus_id       TEXT NOT NULL,
            original_path   TEXT,
            json_path       TEXT,
            parse_status    TEXT DEFAULT 'OK',
            file_size_bytes INTEGER DEFAULT 0,
            char_count      INTEGER DEFAULT 0,
            parsed_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reused_by       TEXT DEFAULT ''
        )
    """)
    return con


def hash_pdf(pdf_path: str | Path, sample_bytes: int = 65536) -> str:
    """Return a 16-char hex fingerprint for a PDF.

    Samples the first and last `sample_bytes/2` of the file for speed.
    Collision-resistant enough for a document cache.
    """
    p = Path(pdf_path)
    try:
        size = p.stat().st_size
        h = hashlib.sha256()
        h.update(str(p.name).encode())  # include filename
        h.update(size.to_bytes(8, "little"))
        with open(p, "rb") as f:
            h.update(f.read(sample_bytes // 2))
            if size > sample_bytes:
                f.seek(max(0, size - sample_bytes // 2))
                h.update(f.read(sample_bytes // 2))
        return h.hexdigest()[:16]
    except Exception as exc:
        logger.warning("hash_pdf failed for %s: %s", p, exc)
        return hashlib.md5(str(p).encode()).hexdigest()[:16]


def is_cached(file_hash: str, *, db_path: Path | None = None) -> bool:
    """Return True if this file_hash exists in the cache with a valid JSON path."""
    try:
        con = _get_db(db_path)
        result = con.execute(
            "SELECT json_path FROM doc_cache WHERE file_hash = ? AND parse_status LIKE 'OK%'",
            [file_hash]
        ).fetchone()
        con.close()
        if result:
            return Path(result[0]).is_file()
        return False
    except Exception as exc:
        logger.debug("is_cached check failed: %s", exc)
        return False


def get_cached_json_path(file_hash: str, *, db_path: Path | None = None) -> str | None:
    """Return the cached docling JSON path if it exists, else None."""
    try:
        con = _get_db(db_path)
        result = con.execute(
            "SELECT json_path FROM doc_cache WHERE file_hash = ? AND parse_status LIKE 'OK%'",
            [file_hash]
        ).fetchone()
        con.close()
        if result and Path(result[0]).is_file():
            return result[0]
        return None
    except Exception:
        return None


def register_parse(
    file_hash: str,
    filing_id: str,
    corpus_id: str,
    original_path: str,
    json_path: str,
    *,
    parse_status: str = "OK",
    file_size_bytes: int = 0,
    char_count: int = 0,
    db_path: Path | None = None,
) -> None:
    """Register a successfully parsed document in the cache.

    If file_hash already exists (same PDF in different corpus), records
    the new corpus in `reused_by` rather than overwriting.
    """
    try:
        con = _get_db(db_path)
        existing = con.execute(
            "SELECT reused_by FROM doc_cache WHERE file_hash = ?", [file_hash]
        ).fetchone()

        if existing:
            reused = existing[0] or ""
            if corpus_id not in reused:
                reused = f"{reused},{corpus_id}".strip(",")
            con.execute(
                "UPDATE doc_cache SET reused_by = ? WHERE file_hash = ?",
                [reused, file_hash]
            )
        else:
            con.execute("""
                INSERT INTO doc_cache
                (file_hash, filing_id, corpus_id, original_path, json_path,
                 parse_status, file_size_bytes, char_count, parsed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                file_hash, filing_id, corpus_id, original_path, json_path,
                parse_status, file_size_bytes, char_count,
                datetime.now(timezone.utc).isoformat()
            ])
        con.close()
    except Exception as exc:
        logger.warning("register_parse failed: %s", exc)


def cache_stats(*, db_path: Path | None = None) -> dict:
    """Return cache statistics."""
    try:
        con = _get_db(db_path)
        row = con.execute("""
            SELECT COUNT(*) as total,
                   COUNT(DISTINCT corpus_id) as n_corpora,
                   SUM(CASE WHEN reused_by != '' THEN 1 ELSE 0 END) as reused,
                   SUM(file_size_bytes) as total_bytes
            FROM doc_cache WHERE parse_status LIKE 'OK%'
        """).fetchone()
        con.close()
        return {
            "total_cached": row[0] if row else 0,
            "n_corpora": row[1] if row else 0,
            "reused_count": row[2] if row else 0,
            "total_bytes": row[3] if row else 0,
        }
    except Exception:
        return {"total_cached": 0, "n_corpora": 0, "reused_count": 0, "total_bytes": 0}
