"""DocSourceRouter — unified document acquisition interface.

Routes document acquisition to the correct backend based on source mode:
  local_folder   — Docling parses PDFs directly from a local folder (IMPLEMENTED)
  sedar_live     — Satellite navigates SEDAR index (STUBBED)
  search_fetch   — SearXNG + satellite visits top results (STUBBED)
  url_list       — Satellite visits each URL (STUBBED)
  live_web       — SearXNG + satellite DOM extraction (STUBBED)
  mixed          — Auto-detected mix of local and live (STUBBED)

Live-scrape modes fail gracefully with a descriptive error — they never crash
the pipeline. The local_folder mode is fully functional.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


SourceMode = Literal["local_folder", "sedar_live", "search_fetch", "url_list", "live_web", "mixed"]


class SourceModeUnavailable(RuntimeError):
    """Raised when a source mode is not yet implemented (stubbed)."""


@dataclass
class DocSourceConfig:
    """Configuration for a single document acquisition job."""
    mode: SourceMode = "local_folder"
    local_path: str = ""           # for local_folder: absolute path to PDF folder
    entity_names: list[str] = field(default_factory=list)  # for sedar_live
    search_query: str = ""         # for search_fetch, live_web
    url_list: list[str] = field(default_factory=list)      # for url_list
    doc_type: str = "pdf"
    max_docs: int = 0              # 0 = no limit
    corpus_id: str = ""


@dataclass
class DocAcquisitionResult:
    """Result of a document acquisition operation."""
    mode: SourceMode
    doc_paths: list[str]           # absolute paths to acquired documents
    errors: list[str]              # non-fatal errors encountered
    metadata: list[dict]           # per-doc metadata dicts


class DocSourceRouter:
    """Routes document acquisition to the correct backend.

    Usage:
        router = DocSourceRouter()
        result = router.acquire(config)
        # result.doc_paths contains paths to all acquired documents
    """

    def acquire(self, config: DocSourceConfig) -> DocAcquisitionResult:
        """Acquire documents according to config.mode.

        Raises SourceModeUnavailable for unimplemented modes.
        Never raises for local_folder mode.
        """
        if config.mode == "local_folder":
            return self._acquire_local(config)
        elif config.mode in ("sedar_live", "search_fetch", "url_list", "live_web", "mixed"):
            raise SourceModeUnavailable(
                f"Source mode '{config.mode}' is not yet implemented. "
                f"Use 'local_folder' for now. Live-scrape modes will be available "
                f"in a future release (requires Satellite browser arm)."
            )
        else:
            raise ValueError(f"Unknown source mode: {config.mode!r}")

    def _acquire_local(self, config: DocSourceConfig) -> DocAcquisitionResult:
        """Collect PDF paths from a local folder. No Docling parsing here —
        parsing happens downstream in the ingestion pipeline.
        """
        folder = Path(config.local_path)
        if not folder.exists():
            return DocAcquisitionResult(
                mode="local_folder",
                doc_paths=[],
                errors=[f"Folder not found: {config.local_path}"],
                metadata=[],
            )

        patterns = ["*.pdf", "*.PDF"]
        paths: list[Path] = []
        for p in patterns:
            paths.extend(folder.rglob(p))

        paths = sorted(set(paths))

        if config.max_docs > 0:
            paths = paths[:config.max_docs]

        logger.info(
            "DocSourceRouter local_folder: found %d PDF files in %s",
            len(paths),
            folder,
        )

        metadata = [
            {
                "doc_id": p.stem,
                "doc_path": str(p),
                "doc_type": "pdf",
                "corpus_id": config.corpus_id,
            }
            for p in paths
        ]

        return DocAcquisitionResult(
            mode="local_folder",
            doc_paths=[str(p) for p in paths],
            errors=[],
            metadata=metadata,
        )

    def detect_mode(self, user_input: str) -> SourceMode:
        """Heuristically detect the source mode from user input.

        - Absolute/relative path that exists → local_folder
        - URL list → url_list
        - Company names / tickers → sedar_live
        - Everything else → search_fetch
        """
        import re

        stripped = user_input.strip()

        p = Path(stripped)
        if p.exists() and p.is_dir():
            return "local_folder"

        if any(stripped.lower().startswith(s) for s in ("http://", "https://", "www.")):
            return "url_list"

        if re.fullmatch(r"[A-Z]{2,5}(:[A-Z]+)?", stripped.split()[0] if stripped else ""):
            return "sedar_live"

        return "search_fetch"
