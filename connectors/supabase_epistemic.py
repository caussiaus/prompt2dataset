"""Supabase pgvector helpers + OpenAI-compatible Nomic embeddings (768-d).

Env (repo root or process):
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
  ISF_EMBEDDING_OPENAI_BASE_URL  e.g. http://127.0.0.1:8000/v1  (TEI / vLLM embeddings)
  ISF_EMBEDDING_API_KEY          optional Bearer token
  ISF_EMBEDDING_MODEL            default nomic-ai/nomic-embed-text-v1.5

Requires: pip install supabase httpx
"""
from __future__ import annotations

import os
from typing import Any, Sequence

import httpx

try:
    from supabase import Client, create_client
except ImportError as e:  # pragma: no cover
    create_client = None  # type: ignore[misc, assignment]
    Client = Any  # type: ignore[misc, valid-type]
    _IMPORT_ERROR = e
else:
    _IMPORT_ERROR = None


def _require_supabase() -> None:
    if _IMPORT_ERROR is not None or create_client is None:
        raise RuntimeError(
            "Install supabase-py: pip install supabase  (" + str(_IMPORT_ERROR) + ")"
        ) from _IMPORT_ERROR


def get_supabase_client() -> Client:
    _require_supabase()
    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(url, key)


def embed_texts(texts: Sequence[str], *, timeout: float = 120.0) -> list[list[float]]:
    """Call OpenAI-compatible ``/v1/embeddings`` for ``ISF_EMBEDDING_MODEL``."""
    base = (os.environ.get("ISF_EMBEDDING_OPENAI_BASE_URL") or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("ISF_EMBEDDING_OPENAI_BASE_URL is not set")
    model = (os.environ.get("ISF_EMBEDDING_MODEL") or "nomic-ai/nomic-embed-text-v1.5").strip()
    key = (os.environ.get("ISF_EMBEDDING_API_KEY") or "").strip()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload: dict[str, Any] = {"model": model, "input": list(texts)}
    r = httpx.post(f"{base}/embeddings", json=payload, headers=headers, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    out: list[list[float]] = []
    for item in sorted(data.get("data", []), key=lambda x: int(x.get("index", 0))):
        emb = item.get("embedding")
        if not isinstance(emb, list):
            continue
        out.append([float(x) for x in emb])
    if len(out) != len(texts):
        raise RuntimeError(f"embedding count mismatch: got {len(out)} expected {len(texts)}")
    return out


def embed_one(text: str) -> list[float]:
    v = embed_texts([text])
    return v[0]


def upsert_chunk(
    sb: Client,
    *,
    content: str,
    embedding: Sequence[float],
    source_kind: str = "vault",
    source_uri: str | None = None,
    corpus_id: str | None = None,
    run_id: str | None = None,
    doc_id: str | None = None,
    chunk_index: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if len(embedding) != 768:
        raise ValueError(f"expected 768-d Nomic v1.5 embedding, got {len(embedding)}")
    row = {
        "content": content,
        "embedding": embedding,
        "source_kind": source_kind,
        "source_uri": source_uri,
        "corpus_id": corpus_id,
        "run_id": run_id,
        "doc_id": doc_id,
        "chunk_index": chunk_index,
        "metadata": metadata or {},
    }
    res = sb.table("epistemic_chunks").insert(row).execute()
    return res.data[0] if res.data else row


def match_chunks(
    sb: Client,
    *,
    query_embedding: Sequence[float],
    match_count: int = 12,
    corpus_id: str | None = None,
) -> list[dict[str, Any]]:
    if len(query_embedding) != 768:
        raise ValueError(f"expected 768-d query embedding, got {len(query_embedding)}")
    # PostgREST passes vector as JSON array
    res = sb.rpc(
        "match_epistemic_chunks",
        {
            "query_embedding": list(query_embedding),
            "match_count": match_count,
            "corpus_filter": corpus_id,
        },
    ).execute()
    return list(res.data or [])
