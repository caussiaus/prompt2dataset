"""MetadataEngine — lazy singleton for external document metadata enrichment.

Consolidates all supporting metadata CSVs (master enriched issuers, WRDS financial
data, or any supplemental CSV) into one engine that enriches document rows with
additional context fields.

Usage:
    from prompt2dataset.utils.metadata_engine import get_metadata_engine
    engine = get_metadata_engine(cfg)
    enriched_row = engine.enrich_row(doc_meta)
    summary = engine.corpus_context_summary(index_df)

The engine is a no-op if no metadata CSVs are configured — safe to call for
any corpus. For SEDAR corpora, configure master_metadata_csv in CorpusConfig.
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Thread-safe singleton lock
_lock = threading.Lock()
_instances: dict[str, "MetadataEngine"] = {}


def get_metadata_engine(
    cfg=None,
    *,
    master_metadata_csv: str = "",
    supplemental_metadata_csv: str = "",
) -> "MetadataEngine":
    """Return the MetadataEngine singleton for the given config.

    Accepts either a Settings/CorpusConfig object or explicit paths.
    Multiple calls with the same paths return the cached instance.
    """
    # Resolve paths from config if provided
    if cfg is not None:
        master_metadata_csv = master_metadata_csv or getattr(cfg, "master_metadata_csv", "") or ""
        supplemental_metadata_csv = supplemental_metadata_csv or getattr(cfg, "supplemental_metadata_csv", "") or ""
        # SEDAR default: check Settings.sedar_master_issuers_path
        if not master_metadata_csv:
            master_metadata_csv = str(getattr(cfg, "sedar_master_issuers_path", "") or "")

    cache_key = f"{master_metadata_csv}|{supplemental_metadata_csv}"
    with _lock:
        if cache_key not in _instances:
            _instances[cache_key] = MetadataEngine(
                master_metadata_csv=master_metadata_csv,
                supplemental_metadata_csv=supplemental_metadata_csv,
            )
    return _instances[cache_key]


def get_metadata_engine_from_kg(
    corpus_id: str,
    identity_fields: list[str] | None = None,
    schema_cols: list[dict] | None = None,
    vault_path=None,
) -> "MetadataEngine":
    """Return a MetadataEngine configured by KG vault traversal.

    The vault is read to discover which MetadataSource notes apply to this corpus.
    Only sources that pass three checks are loaded:
      1. Source is linked to this corpus (applies_to_corpora includes corpus_id)
      2. Source's join_key exists in identity_fields
      3. Source's provides list overlaps with schema column names

    Falls back to the default get_metadata_engine() if vault not configured.
    """
    try:
        from prompt2dataset.connectors.obsidian_bridge import get_obsidian_bridge
        bridge = get_obsidian_bridge(vault_path)
        sources = bridge.get_metadata_sources_for_corpus(corpus_id)
    except Exception as exc:
        logger.debug("get_metadata_engine_from_kg: vault not available (%s) — using default", exc)
        return get_metadata_engine()

    if not sources:
        logger.debug("get_metadata_engine_from_kg: no metadata sources in vault for %s", corpus_id)
        return get_metadata_engine()

    id_fields_set = set(identity_fields or [])
    schema_col_names = set(c.get("name", "") for c in (schema_cols or []))
    # Resolve supplemental CSV paths relative to the monorepo root (parent of ``prompt2dataset/``).
    try:
        from prompt2dataset.utils.config import get_settings

        root = get_settings().project_root.parent
    except Exception:
        root = Path(__file__).resolve().parents[2]

    master_path = ""
    supplemental_path = ""

    for source in sources:
        join_key = str(source.get("join_key", ""))
        provides = source.get("provides", [])
        provides = provides if isinstance(provides, list) else [provides]
        source_file = str(source.get("source_file", ""))

        # Three-check guard
        check1 = True  # already filtered by corpus_id in get_metadata_sources_for_corpus
        check2 = not id_fields_set or join_key in id_fields_set
        check3 = not schema_col_names or bool(set(provides) & schema_col_names)

        if check1 and check2 and check3:
            resolved = root / source_file if not Path(source_file).is_absolute() else Path(source_file)
            logger.info(
                "get_metadata_engine_from_kg: auto-joining %s via %s (join_key=%s, provides=%s)",
                source.get("_note_name"), resolved.name, join_key, provides,
            )
            if not master_path and resolved.exists():
                master_path = str(resolved)
            elif not supplemental_path and resolved.exists():
                supplemental_path = str(resolved)
        else:
            logger.debug(
                "get_metadata_engine_from_kg: skipping %s (check2=%s check3=%s)",
                source.get("_note_name"), check2, check3,
            )

    return get_metadata_engine(
        master_metadata_csv=master_path,
        supplemental_metadata_csv=supplemental_path,
    )


class MetadataEngine:
    """Enriches document rows with external metadata from master CSV files.

    Join keys (tried in order):
      1. entity_slug / ticker — exact match
      2. entity_name / issuer_name — case-insensitive substring match
    """

    def __init__(
        self,
        master_metadata_csv: str = "",
        supplemental_metadata_csv: str = "",
    ) -> None:
        self._master: pd.DataFrame = pd.DataFrame()
        self._supplemental: pd.DataFrame = pd.DataFrame()
        self._master_path = master_metadata_csv
        self._supplemental_path = supplemental_metadata_csv
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        if self._master_path:
            try:
                p = Path(self._master_path)
                if p.exists():
                    self._master = pd.read_csv(p, dtype=str).fillna("")
                    logger.info(
                        "MetadataEngine: loaded master metadata %d rows from %s",
                        len(self._master), p,
                    )
                else:
                    logger.debug("MetadataEngine: master_metadata_csv not found: %s", p)
            except Exception as e:
                logger.warning("MetadataEngine: failed to load master CSV: %s", e)

        if self._supplemental_path:
            try:
                p = Path(self._supplemental_path)
                if p.exists():
                    self._supplemental = pd.read_csv(p, dtype=str).fillna("")
                    logger.info(
                        "MetadataEngine: loaded supplemental metadata %d rows from %s",
                        len(self._supplemental), p,
                    )
                else:
                    logger.debug("MetadataEngine: supplemental_metadata_csv not found: %s", p)
            except Exception as e:
                logger.warning("MetadataEngine: failed to load supplemental CSV: %s", e)

    def _find_master_row(self, doc_meta: dict[str, Any]) -> dict[str, Any] | None:
        """Find the matching master row for this document. Returns None if not found."""
        if self._master.empty:
            return None

        # Try entity_slug / ticker exact match
        slug = str(doc_meta.get("entity_slug") or doc_meta.get("ticker") or "").strip().upper()
        if slug:
            for col in ("ticker", "entity_slug", "issuer_slug"):
                if col in self._master.columns:
                    matches = self._master[self._master[col].str.upper() == slug]
                    if not matches.empty:
                        return matches.iloc[0].to_dict()

        # Try entity_name / issuer_name case-insensitive substring
        name = str(doc_meta.get("entity_name") or doc_meta.get("issuer_name") or "").lower().strip()
        if name:
            for col in ("issuer_name", "entity_name", "company_name"):
                if col in self._master.columns:
                    mask = self._master[col].str.lower().str.contains(
                        re.escape(name[:30]), na=False, regex=True
                    )
                    if mask.any():
                        return self._master[mask].iloc[0].to_dict()

        return None

    def enrich_row(self, doc_meta: dict[str, Any]) -> dict[str, Any]:
        """Return doc_meta enriched with fields from master and supplemental CSVs.

        Fields added (when available):
          - context_category (from naics_sector or equivalent)
          - context_tag (from mechanism or equivalent)
          - context_detail (from exposure_vector or equivalent)
          - Any supplemental columns prefixed with 'wrds_' or similar
        All existing keys in doc_meta take priority (master data only fills gaps).
        """
        self._load()
        result = dict(doc_meta)

        master_row = self._find_master_row(doc_meta)
        if master_row:
            # Fill context fields from master if not already in doc_meta
            field_map = {
                "context_category": ("naics_sector", "context_category", "sector"),
                "context_tag": ("mechanism", "context_tag", "trade_mechanism"),
                "context_detail": ("exposure_vector", "context_detail"),
            }
            for target, sources in field_map.items():
                if not result.get(target):
                    for src in sources:
                        val = master_row.get(src, "")
                        if val and val not in ("", "nan", "None"):
                            result[target] = val
                            # Also fill the SEDAR alias columns for backward compat
                            if target == "context_category" and not result.get("naics_sector"):
                                result["naics_sector"] = val
                            elif target == "context_tag" and not result.get("mechanism"):
                                result["mechanism"] = val
                            break

            # Copy any supplemental columns from master that start with known prefixes
            for k, v in master_row.items():
                if k.startswith(("wrds_", "financial_", "market_")) and k not in result:
                    result[k] = v

        return result

    def corpus_context_summary(self, index_df: pd.DataFrame) -> str:
        """Return a compact corpus description for injection into schema design prompts.

        Example output:
            "875 docs | 2023–2025 | categories: manufacturing 34%, mining 22%, financial 18%"
        """
        self._load()
        parts: list[str] = []

        n = len(index_df)
        if n:
            parts.append(f"{n} doc{'s' if n != 1 else ''}")

        # Date range
        for col in ("filing_date", "doc_date", "date"):
            if col in index_df.columns:
                dates = index_df[col].dropna().astype(str)
                dates = dates[dates.str.match(r"\d{4}")]
                if not dates.empty:
                    years = dates.str[:4].astype(int)
                    mn, mx = years.min(), years.max()
                    parts.append(f"{mn}" if mn == mx else f"{mn}–{mx}")
                break

        # Category distribution
        for col in ("context_category", "naics_sector", "sector", "category"):
            if col in index_df.columns:
                counts = index_df[col].dropna().value_counts()
                if not counts.empty:
                    top = counts.head(4)
                    total = counts.sum()
                    cat_str = ", ".join(
                        f"{cat} {round(100 * cnt / total)}%"
                        for cat, cnt in top.items()
                    )
                    parts.append(f"categories: {cat_str}")
                break

        return " | ".join(parts) if parts else "document corpus"
