"""Content-derived keys for corpora — shared ground between ingest cache, indexes, and (later) library/grid workflows.

Today ``filing_id`` / ``doc_id`` are often MD5(path), so the same PDF moved or the same
folder registered twice under different ``corpus_id`` does not unify in the index.

- ``doc_signature``: sample-based fingerprint (same algorithm as ``ingest_cache.hash_pdf``).
  Use for dedupe, cache joins, and optional content-keyed ``filing_id``.
- ``corpus_fingerprint``: hash of sorted per-doc signatures — stable for a *set* of PDFs
  regardless of scan order (paths are sorted before hashing).

Environment:
  ``PROMPT2DATASET_SKIP_CONTENT_SIGNATURES`` — if truthy, skip per-file reads (fast path;
  manifest still written with empty fingerprint).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _skip_signatures() -> bool:
    return os.environ.get("PROMPT2DATASET_SKIP_CONTENT_SIGNATURES", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def pdf_content_signature(pdf_path: str | Path) -> str:
    """16-char hex fingerprint; matches :func:`prompt2dataset.utils.ingest_cache.hash_pdf`."""
    from prompt2dataset.utils.ingest_cache import hash_pdf

    return hash_pdf(pdf_path)


def attach_doc_signatures(rows: list[dict[str, Any]], path_key: str = "local_path") -> None:
    """Mutate rows in place, adding ``doc_signature`` when path exists."""
    if _skip_signatures():
        for r in rows:
            r.setdefault("doc_signature", "")
        return
    for r in rows:
        lp = r.get(path_key) or r.get("local_path") or ""
        if not lp:
            r["doc_signature"] = ""
            continue
        p = Path(str(lp))
        if not p.is_file():
            r["doc_signature"] = ""
            continue
        try:
            r["doc_signature"] = pdf_content_signature(p)
        except Exception as exc:
            logger.debug("doc_signature skipped for %s: %s", p, exc)
            r["doc_signature"] = ""


def corpus_fingerprint_from_signatures(signatures: list[str]) -> str:
    """Deterministic hash for the *set* of documents (order-independent)."""
    cleaned = sorted({s for s in signatures if s})
    if not cleaned:
        return ""
    h = hashlib.sha256()
    for s in cleaned:
        h.update(s.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def write_library_manifest(
    *,
    output_dir: Path,
    corpus_id: str,
    docs_dir: str,
    n_docs: int,
    filing_id_strategy: str,
    doc_signatures: list[str],
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write ``corpus_library_manifest.json`` next to pipeline artifacts (provenance hook)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    fp = corpus_fingerprint_from_signatures(doc_signatures)
    body: dict[str, Any] = {
        "schema_version": 1,
        "corpus_id": corpus_id,
        "docs_dir_resolved": str(Path(docs_dir).expanduser().resolve()) if docs_dir else "",
        "n_docs": n_docs,
        "filing_id_strategy": filing_id_strategy,
        "corpus_fingerprint": fp,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        body.update(extra)
    path = output_dir / "corpus_library_manifest.json"
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("write_library_manifest: %s", path)
    return path
