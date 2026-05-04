"""Corpus refresh hook — placeholder until a single refresh orchestration exists.

Callers should trigger ingest / re-extract through the workspace or corpus CLI;
this class only validates that core ingest is importable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

RefreshMode = Literal["manual", "scheduled", "incremental", "schema_update"]


@dataclass
class RefreshResult:
    mode: RefreshMode
    success: bool
    message: str
    new_docs: int = 0
    updated_rows: int = 0


class CorpusRefresher:
    def __init__(self, corpus_id: str, ws_state: dict | None = None):
        self.corpus_id = corpus_id
        self.ws_state = ws_state or {}

    def refresh(self, mode: RefreshMode = "manual") -> RefreshResult:
        if mode != "manual":
            return RefreshResult(
                mode=mode,
                success=False,
                message=f"Mode {mode!r} is not implemented; use manual or drive ingest from the UI.",
            )
        logger.info("CorpusRefresher: manual refresh for corpus %s", self.corpus_id)
        try:
            from prompt2dataset.corpus.ingest import run_ingestion_pipeline  # noqa: F401

            return RefreshResult(
                mode="manual",
                success=True,
                message="Ingest pipeline available — start processing from the workspace or corpus tools.",
            )
        except Exception as exc:
            return RefreshResult(mode="manual", success=False, message=str(exc))
