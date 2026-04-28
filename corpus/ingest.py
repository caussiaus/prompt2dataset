"""Generic corpus ingestion: PDF directory → index CSV → chunks parquet.

Handles any folder structure a user drops PDFs into:
  - Flat dump:             docs_dir/*.pdf
  - One level:             docs_dir/company/*.pdf
  - Two levels:            docs_dir/company/filing_type/*.pdf
  - Three+ levels:         docs_dir/company/year/type/*.pdf
  - csv_manifest:          metadata CSV with a local_path column

The universal scanner always:
  1. Recursively finds all *.pdf files (case-insensitive)
  2. Uses the FIRST subdirectory as company_name (if any)
  3. Uses the SECOND subdirectory as doc_type hint (if any)
  4. Extracts date from the filename stem via regex

Produces:
  {output_dir}/index.csv          — one row per document with identity fields
  {output_dir}/chunks/            — Docling parse + chunking outputs
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd

from prompt2dataset.corpus.config import CorpusConfig
from prompt2dataset.corpus.content_keys import attach_doc_signatures, write_library_manifest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def scan_documents(cfg: CorpusConfig, root: Path | None = None) -> list[dict[str, Any]]:
    """Discover PDFs and build a raw document list from the corpus config.

    Uses the universal recursive scanner for all directory layouts.
    The only special case is 'csv_manifest', where the user supplies
    a pre-built metadata CSV with a local_path column.

    Legacy pattern names ('flat', 'nested_company_year', 'nested_date') all
    route to the same universal recursive scanner — no configuration needed.
    """
    docs_dir = cfg.resolve(cfg.docs_dir, root)
    if not docs_dir.exists():
        raise FileNotFoundError(f"docs_dir does not exist: {docs_dir}")

    if cfg.file_pattern == "csv_manifest":
        return _scan_csv_manifest(cfg, root)

    # All other patterns (including "auto", "flat", "nested_*") use the
    # universal recursive scanner that reads structure from directory depth.
    return _scan_recursive(docs_dir)


def _doc_id(path: Path) -> str:
    return hashlib.md5(str(path).encode()).hexdigest()


def _scan_recursive(docs_dir: Path) -> list[dict]:
    """Universal scanner: works for any folder structure a user drops PDFs into.

    Extracts metadata purely from directory position:
      - Depth 0 (file directly in docs_dir):  company_name = ""
      - Depth 1 (company/file.pdf):            company_name = parts[0]
      - Depth 2 (company/type/file.pdf):       company_name = parts[0], doc_type = parts[1]
      - Depth 3+ (company/year/type/file.pdf): company_name = parts[0], year = parts[1], doc_type = parts[2]

    Date is always extracted from the filename stem via regex.
    """
    seen: set[str] = set()
    paths: list[Path] = []
    for pat in ("**/*.pdf", "**/*.PDF", "**/*.Pdf"):
        for p in docs_dir.glob(pat):
            key = str(p).lower()
            if key not in seen:
                seen.add(key)
                paths.append(p)
    paths.sort()
    logger.info("_scan_recursive: found %d PDFs in %s", len(paths), docs_dir)

    docs = []
    for p in paths:
        rel_parts = p.relative_to(docs_dir).parts  # e.g. ('acme_corp', 'general', '2024-03_report.pdf')
        depth = len(rel_parts) - 1  # number of directory levels above the file

        company_name = ""
        doc_type = ""
        year = ""

        if depth >= 1:
            company_name = rel_parts[0].replace("_", " ").strip()
        if depth >= 2:
            doc_type = rel_parts[1].replace("_", " ").strip()
        if depth >= 3:
            year = rel_parts[2]

        file_meta = _parse_filename(p.stem)

        docs.append({
            "doc_id": _doc_id(p),
            "local_path": str(p),
            "filename": p.name,
            "company_name": company_name,
            "doc_type": doc_type,
            "year": year,
            **file_meta,
        })
    return docs


def _scan_csv_manifest(cfg: CorpusConfig, root: Path | None = None) -> list[dict]:
    if not cfg.metadata_csv:
        raise ValueError("csv_manifest pattern requires metadata_csv path in CorpusConfig")
    csv_path = cfg.resolve(cfg.metadata_csv, root)
    df = pd.read_csv(csv_path, dtype=str).fillna("")
    return df.to_dict("records")


_DATE_RE = re.compile(r"(\d{4}[-_]\d{2}[-_]\d{2}|\d{8}|\d{4})")
_TICKER_RE = re.compile(r"\b([A-Z]{2,5})\b")

# Index rows sometimes store the first words of the *filing title* (filename stem)
# instead of the issuer folder under .../filings/<issuer>/... — repair from path.
_DOC_TITLE_FALSE_ISSUER = re.compile(
    r"(annual\s+md|final\s+short|management\s+information|consent\s+letter|"
    r"notice\s+of|form\s+of|qualification|undertaking|auditors?'?|non[- ]issuer)",
    re.I,
)


def _pretty_issuer_segment(seg: str) -> str:
    return seg.replace("_", " ").replace("-", " ").strip()


def issuer_folder_from_local_path(local_path: str) -> str | None:
    """Issuer slug from .../filings/<issuer>/... or .../<issuer>/general/<file>.pdf."""
    if not local_path or not str(local_path).strip():
        return None
    parts = [p for p in Path(str(local_path).replace("\\", "/")).parts if p]
    if len(parts) < 2:
        return None
    lower = [p.lower() for p in parts]
    if "filings" in lower:
        i = lower.index("filings")
        if i + 1 < len(parts) and not parts[i + 1].lower().endswith(".pdf"):
            return _pretty_issuer_segment(parts[i + 1])
    if (
        len(parts) >= 3
        and parts[-1].lower().endswith(".pdf")
        and parts[-2].lower()
        in ("general", "annual", "interim", "english", "french", "documents")
    ):
        return _pretty_issuer_segment(parts[-3])
    return None


def _index_company_looks_like_filename_title(company: str, filename: str) -> bool:
    """True when company_name matches the start of the dated filing stem (wrong column)."""
    cur = (company or "").strip()
    if not cur or not filename:
        return False
    if _DOC_TITLE_FALSE_ISSUER.search(cur):
        return True
    stem = Path(str(filename)).stem
    stem_clean = re.sub(
        r"^\d{4}[-_]\d{2}[-_]\d{2}[_\s\-–]+",
        "",
        stem,
        flags=re.I,
    )
    s_low = stem_clean.lower()
    c_low = cur.lower()
    return bool(s_low.startswith(c_low) and len(c_low) >= 6)


def repair_company_names_from_paths(df: pd.DataFrame) -> pd.DataFrame:
    """Overwrite bogus ``company_name`` values using the issuer folder in ``local_path``."""
    if df.empty or "local_path" not in df.columns or "company_name" not in df.columns:
        return df
    out = df.copy()
    fixed = 0
    for i in out.index:
        lp = str(out.at[i, "local_path"] or "")
        fn = str(out.at[i, "filename"] or "")
        cur = str(out.at[i, "company_name"] or "").strip()
        iss = issuer_folder_from_local_path(lp)
        if not iss:
            continue
        if cur.casefold() == iss.casefold():
            continue
        if not cur or _index_company_looks_like_filename_title(cur, fn):
            out.at[i, "company_name"] = iss
            fixed += 1
    if fixed:
        logger.info(
            "repair_company_names_from_paths: corrected company_name for %d rows (issuer folder from path)",
            fixed,
        )
    return out


def _parse_filename(stem: str) -> dict[str, str]:
    """Best-effort extraction of date from a filename stem.

    We intentionally do NOT set company_name here — the directory structure
    (parts[0] in nested scans) is the authoritative company source.
    """
    out: dict[str, str] = {}
    date_m = _DATE_RE.search(stem)
    if date_m:
        out["date"] = date_m.group(1).replace("_", "-")
    return out


# ---------------------------------------------------------------------------
# Index CSV
# ---------------------------------------------------------------------------

def build_index(
    cfg: CorpusConfig,
    root: Path | None = None,
    *,
    overwrite: bool = False,
) -> pd.DataFrame:
    """Scan documents and write/update the corpus index CSV."""
    index_path = cfg.resolve(cfg.index_csv, root)

    if index_path.exists() and not overwrite:
        df = pd.read_csv(index_path, dtype=str)
        logger.info("build_index: loaded existing index (%d rows) from %s", len(df), index_path)
        before_cn = (
            df["company_name"].fillna("").astype(str).tolist()
            if "company_name" in df.columns
            else []
        )
        df = repair_company_names_from_paths(df)
        after_cn = (
            df["company_name"].fillna("").astype(str).tolist()
            if "company_name" in df.columns
            else []
        )
        repaired_cn = before_cn != after_cn
        # Backfill entity_id if missing (registry may have been loaded since last scan)
        try:
            need = "entity_id" not in df.columns or (
                df["entity_id"].fillna("").astype(str).str.strip() == ""
            ).all()
            if need and not df.empty:
                from prompt2dataset.utils.entity_registry import stamp_index_dataframe

                df = stamp_index_dataframe(df, db_path=None)
                df.to_csv(index_path, index=False)
            elif repaired_cn:
                df.to_csv(index_path, index=False)
                logger.info("build_index: saved index after company_name path repair")
        except Exception as _bf_exc:
            logger.debug("build_index: entity backfill skipped: %s", _bf_exc)
            if repaired_cn:
                try:
                    df.to_csv(index_path, index=False)
                    logger.info("build_index: saved index after company_name path repair")
                except Exception as _save_exc:
                    logger.warning("build_index: could not save repaired index: %s", _save_exc)
        return df

    docs = scan_documents(cfg, root)
    if not docs:
        logger.warning(
            "build_index: 0 documents found in docs_dir=%s (pattern=%s glob=%s). "
            "Check the path exists, contains .pdf files, and is accessible.",
            cfg.docs_dir, cfg.file_pattern, cfg.file_glob,
        )
        # Write an empty index so downstream stages don't crash
        df_empty = pd.DataFrame(columns=["doc_id", "local_path", "filename"])
        index_path.parent.mkdir(parents=True, exist_ok=True)
        df_empty.to_csv(index_path, index=False)
        print(f"  [ingest] WARNING: 0 PDFs found in {cfg.docs_dir} — empty index written")
        return df_empty

    pk = "local_path"
    if docs:
        sample = docs[0]
        if "local_path" not in sample and cfg.doc_path_field in sample:
            pk = cfg.doc_path_field
    attach_doc_signatures(docs, path_key=pk)
    df = pd.DataFrame(docs)
    df = repair_company_names_from_paths(df)

    # Ensure doc_id column exists
    if cfg.doc_id_field not in df.columns:
        if "doc_id" in df.columns:
            df = df.rename(columns={"doc_id": cfg.doc_id_field})
        else:
            df[cfg.doc_id_field] = df.apply(
                lambda r: _doc_id(Path(str(r.get(cfg.doc_path_field, "") or ""))),
                axis=1,
            )

    # Ensure path column exists
    if cfg.doc_path_field not in df.columns and "local_path" in df.columns:
        df = df.rename(columns={"local_path": cfg.doc_path_field})

    # Optional: canonical row key from PDF bytes (library / cross-path dedupe)
    _strategy = (os.environ.get("PROMPT2DATASET_FILING_ID_STRATEGY") or "").strip()
    if _strategy not in ("path_md5", "content_sample"):
        _strategy = getattr(cfg, "filing_id_strategy", "path_md5")
    if _strategy == "content_sample" and "doc_signature" in df.columns:
        def _content_fid(row: pd.Series) -> str:
            sig = str(row.get("doc_signature") or "").strip()
            if sig:
                return sig
            lp = str(row.get(cfg.doc_path_field, "") or "")
            return _doc_id(Path(lp)) if lp else ""

        df[cfg.doc_id_field] = df.apply(_content_fid, axis=1)

    # Stamp deterministic entity_id via DuckDB registry (exact profile / name / doc fallback)
    try:
        from prompt2dataset.utils.entity_registry import stamp_index_dataframe

        df = stamp_index_dataframe(df, db_path=None)
    except Exception as _stamp_exc:
        logger.debug("build_index: entity stamp skipped: %s", _stamp_exc)

    index_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(index_path, index=False)
    logger.info("build_index: wrote %d rows to %s", len(df), index_path)
    try:
        sigs = (
            df["doc_signature"].fillna("").astype(str).tolist()
            if "doc_signature" in df.columns
            else []
        )
        write_library_manifest(
            output_dir=index_path.parent,
            corpus_id=cfg.corpus_id,
            docs_dir=str(cfg.resolve(cfg.docs_dir, root)),
            n_docs=len(df),
            filing_id_strategy=_strategy,
            doc_signatures=sigs,
        )
    except Exception as _man_exc:
        logger.debug("build_index: library manifest skipped: %s", _man_exc)
    try:
        from prompt2dataset.utils.lakehouse import Lakehouse

        Lakehouse().register_corpus(cfg, project_root=root or Path.cwd(), source_kind="ingest_index")
    except Exception as _cat_exc:
        logger.debug("build_index: federated catalog register skipped: %s", _cat_exc)
    return df


# ---------------------------------------------------------------------------
# Pipeline stage runner
# ---------------------------------------------------------------------------

def run_ingestion_pipeline(
    cfg: CorpusConfig,
    root: Path | None = None,
    *,
    stages: list[str] | None = None,
    progress_callback=None,  # optional: called with (stage, pct, message)
) -> dict[str, Any]:
    """Run the full ingestion pipeline for a corpus config.

    stages: subset of ["index", "parse", "chunk", "llm_chunk"]
            default: all stages
    Returns dict with paths to produced artifacts.
    """
    stages = stages or ["index", "parse", "chunk", "llm_chunk"]

    results: dict[str, Any] = {}

    def _progress(stage: str, pct: int, msg: str) -> None:
        logger.info("[%s] %d%% — %s", stage, pct, msg)
        if progress_callback:
            progress_callback(stage, pct, msg)

    # ── Index ─────────────────────────────────────────────────────────
    if "index" in stages:
        _progress("index", 0, "Scanning documents…")
        df = build_index(cfg, root)
        results["index_csv"] = cfg.index_csv
        results["n_documents"] = len(df)
        _progress("index", 100, f"{len(df)} documents indexed")
        try:
            from prompt2dataset.utils.entity_registry import (
                sync_doc_registry_from_index,
                sync_master_csv_to_registry,
            )

            r = root or Path.cwd()
            mm = getattr(cfg, "master_metadata_csv", "") or ""
            if mm:
                mp = cfg.resolve(mm, r)
                if mp.is_file():
                    sync_master_csv_to_registry(mp)
            else:
                default_m = r / "data" / "metadata" / "master_sedar_issuers01_enriched.csv"
                if default_m.is_file():
                    sync_master_csv_to_registry(default_m)
            sync_doc_registry_from_index(cfg, r)
        except Exception as _syn_exc:
            logger.debug("run_ingestion_pipeline: entity registry sync: %s", _syn_exc)

    # ── Parse (Docling) ───────────────────────────────────────────────
    if "parse" in stages:
        _progress("parse", 0, "Parsing PDFs with Docling…")
        try:
            from prompt2dataset.corpus.runtime import apply_corpus_env
            from prompt2dataset.utils.docling_pipeline import run_docling_on_filings
            # Apply corpus-specific env vars so get_settings() resolves the right paths
            if root is not None:
                apply_corpus_env(cfg, root)
            parse_df = run_docling_on_filings()
            n_parsed = len(parse_df)
            results["parse_df"] = parse_df
            results["n_parsed"] = n_parsed
            if n_parsed == 0:
                msg = (
                    f"[PARSE_ERROR] 0 documents parsed. Check that {cfg.docs_dir!r} "
                    f"contains PDF files and the index CSV exists."
                )
                logger.error(msg)
                print(msg)
                if progress_callback:
                    progress_callback("parse", 100, msg)
            else:
                _progress("parse", 100, f"Parsed {n_parsed} documents")
        except Exception as exc:
            msg = f"[PARSE_ERROR] Parse stage failed: {exc}"
            logger.error(msg)
            print(msg)
            _progress("parse", 100, f"Parse failed: {exc}")
            results["parse_error"] = str(exc)

    # ── Chunk ─────────────────────────────────────────────────────────
    if "chunk" in stages:
        _progress("chunk", 0, "Chunking parsed documents…")
        results["chunks_parquet"] = cfg.chunks_parquet
        _progress("chunk", 100, "Chunking complete")

    # ── LLM chunk (Pass-1) ────────────────────────────────────────────
    if "llm_chunk" in stages:
        _progress("llm_chunk", 0, "Running Pass-1 LLM on chunks…")
        results["chunks_llm_parquet"] = cfg.chunks_llm_parquet
        _progress("llm_chunk", 100, "Pass-1 complete")

    return results


# ---------------------------------------------------------------------------
# Corpus status
# ---------------------------------------------------------------------------

def corpus_status(cfg: CorpusConfig, root: Path | None = None) -> dict[str, Any]:
    """Return a status dict describing which pipeline stages have been completed."""
    def _exists(p: str) -> bool:
        return cfg.resolve(p, root).exists()

    def _count(p: str) -> int:
        path = cfg.resolve(p, root)
        if not path.exists():
            return 0
        try:
            if path.suffix == ".parquet":
                import pandas as pd
                return len(pd.read_parquet(path))
            if path.suffix == ".csv":
                import pandas as pd
                return len(pd.read_csv(path))
        except Exception:
            pass
        return 0

    return {
        "corpus_id": cfg.corpus_id,
        "name": cfg.name,
        "index_exists": _exists(cfg.index_csv),
        "n_documents": _count(cfg.index_csv),
        "chunks_exist": _exists(cfg.chunks_parquet),
        "n_chunks": _count(cfg.chunks_parquet),
        "llm_chunks_exist": _exists(cfg.chunks_llm_parquet),
        "n_llm_chunks": _count(cfg.chunks_llm_parquet),
        "docs_llm_exists": _exists(cfg.docs_llm_csv),
        "n_docs_llm": _count(cfg.docs_llm_csv),
        "n_datasets": len(list(cfg.resolve(cfg.datasets_dir, root).glob("*.csv")))
        if _exists(cfg.datasets_dir) else 0,
    }
