"""Universal Metadata Constructor.

Enriches any extracted dataset row with entity metadata from the KG vault.
Works for any domain — not just SEDAR — by:

  1. Reading the document's company name (from chunk metadata or document header)
  2. Fuzzy-matching it against vault/Entities/ notes
  3. Returning a flat dict of canonical metadata fields

Also provides ``build_dataset_metadata`` which constructs the full set of
identity + enrichment columns for an entire extracted dataset, given a
corpus index and the vault.

Usage in export_node:
    from prompt2dataset.utils.metadata_constructor import MetadataConstructor
    mc = MetadataConstructor()
    enriched_row = mc.enrich_row(raw_row)

Usage for bulk enrichment:
    mc = MetadataConstructor()
    df = mc.enrich_dataframe(df, company_col="company_name")
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any

import pandas as pd

from prompt2dataset.utils.nlp_utils import match_company_name, normalize_company_name

logger = logging.getLogger(__name__)


def _blank_series_mask(s: pd.Series) -> pd.Series:
    return s.isna() | (s.astype(str).str.strip() == "")


def _coalesce_registry_into_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Copy dataframe_enrichment_from_registry columns into canonical names where empty."""
    if df.empty:
        return df
    out = df.copy()
    pairs = [
        ("registry_profile_number", "profile_number"),
        ("registry_lei", "lei"),
        ("registry_naics", "naics"),
        ("registry_cik", "cik"),
    ]
    for src, dst in pairs:
        if src not in out.columns:
            continue
        if dst not in out.columns:
            out[dst] = None
        m = _blank_series_mask(out[dst])
        out.loc[m, dst] = out.loc[m, src]
    if "registry_company_name" in out.columns:
        for dst in ("issuer_name", "company_name", "entity_name", "sedar_name"):
            if dst not in out.columns:
                continue
            m = _blank_series_mask(out[dst])
            out.loc[m, dst] = out.loc[m, "registry_company_name"]
    if "registry_naics" in out.columns and "naics_sector" in out.columns:
        m = _blank_series_mask(out["naics_sector"])
        out.loc[m, "naics_sector"] = out.loc[m, "registry_naics"]
    return out

# ── Fields sourced from the KG entity note ────────────────────────────────────
# These become extra columns in every extracted dataset row when available.
# profile_number is the canonical SEDAR identifier (short integer, e.g. 131).
# profile_id (long hash) is scraper-internal and is intentionally excluded here.
_KG_FIELD_MAP = {
    "profile_number": "profile_number",
    "ticker": "ticker",
    "gvkey": "gvkey",
    "naics": "naics",
    "size": "issuer_size",
    "principal_jurisdiction": "jurisdiction",
    "issuer_type": "issuer_type",
    "listed_on_exchange": "exchange",
    "lei": "lei",
}


class MetadataConstructor:
    """Thread-safe lazy-loaded metadata enricher backed by the vault KG.

    Maintains an in-memory index of (normalized_name → frontmatter_dict)
    for fast repeated lookups. Re-loads from vault on demand or after
    a configurable TTL.
    """

    def __init__(
        self,
        vault_path: str | Path | None = None,
        *,
        match_threshold: float = 0.72,
    ):
        self._vault_path = vault_path
        self._threshold = match_threshold
        self._lock = threading.Lock()
        self._index: dict[str, dict[str, Any]] = {}   # normalised_name → frontmatter
        self._raw_names: list[str] = []               # original entity_names (for match)
        self._loaded = False

    # ── Index management ──────────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._load_index()
            self._loaded = True

    def _load_index(self) -> None:
        try:
            from connectors.obsidian_bridge import get_obsidian_bridge
            bridge = get_obsidian_bridge(self._vault_path)
            entity_keys = bridge.list_entities()
            index: dict[str, dict[str, Any]] = {}
            raw_names: list[str] = []
            for key in entity_keys:
                result = bridge._read_note("Entities", key)
                if not result:
                    continue
                fm, _ = result
                raw_name = str(fm.get("entity_name") or key)
                norm_name = normalize_company_name(raw_name)
                index[norm_name] = fm
                raw_names.append(raw_name)
            self._index = index
            self._raw_names = raw_names
            logger.info("MetadataConstructor: loaded %d entities from vault", len(self._index))
        except Exception as exc:
            logger.warning("MetadataConstructor: could not load vault entities: %s", exc)
            self._index = {}
            self._raw_names = []

    def invalidate(self) -> None:
        """Force reload from vault on next access."""
        with self._lock:
            self._loaded = False

    # ── Lookup ────────────────────────────────────────────────────────────────

    def lookup(self, company_name: str) -> dict[str, Any] | None:
        """Return KG entity frontmatter for a company name, or None if not found."""
        self._ensure_loaded()
        if not company_name or not self._raw_names:
            return None

        best, score = match_company_name(company_name, self._raw_names, self._threshold)
        if best is None:
            return None

        norm = normalize_company_name(best)
        return self._index.get(norm)

    def lookup_field(self, company_name: str, field: str, default: Any = None) -> Any:
        """Convenience: lookup a single field from the KG for a company."""
        fm = self.lookup(company_name)
        if fm is None:
            return default
        return fm.get(field, default)

    # ── Row enrichment ────────────────────────────────────────────────────────

    def enrich_row(
        self,
        row: dict[str, Any],
        *,
        company_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add KG metadata columns to a single extracted row.

        Tries company name from ``company_fields`` in order.
        Fields already present in ``row`` are NOT overwritten.
        """
        company_fields = company_fields or [
            "company_name", "entity_name", "sedar_name", "ticker",
        ]
        enriched = dict(row)
        eid = str(enriched.get("entity_id", "") or "").strip()
        if eid:
            try:
                from prompt2dataset.utils.entity_registry import lookup_entity_row

                reg = lookup_entity_row(eid)
            except Exception as exc:
                logger.debug("MetadataConstructor: registry lookup failed: %s", exc)
                reg = None
            if reg:
                if reg.get("sedar_profile_number") and not enriched.get("profile_number"):
                    enriched["profile_number"] = reg["sedar_profile_number"]
                if reg.get("company_name"):
                    for k in ("issuer_name", "company_name", "entity_name"):
                        if not str(enriched.get(k, "") or "").strip():
                            enriched[k] = reg["company_name"]
                if reg.get("naics") and not enriched.get("naics") and not enriched.get("naics_sector"):
                    enriched["naics"] = reg["naics"]
                    if "naics_sector" in enriched:
                        enriched["naics_sector"] = reg["naics"]
                if reg.get("lei") and not enriched.get("lei"):
                    enriched["lei"] = reg["lei"]
                return enriched

        company_name: str | None = None
        for f in company_fields:
            v = str(enriched.get(f, "") or "").strip()
            if v and len(v) > 2:
                company_name = v
                break

        if not company_name:
            return enriched

        fm = self.lookup(company_name)
        if fm is None:
            return enriched

        for kg_field, out_field in _KG_FIELD_MAP.items():
            if out_field not in enriched or not enriched[out_field]:
                val = fm.get(kg_field)
                if val:
                    enriched[out_field] = val

        return enriched

    def enrich_dataframe(
        self,
        df: pd.DataFrame,
        *,
        company_col: str = "company_name",
        extra_cols: list[str] | None = None,
    ) -> pd.DataFrame:
        """Bulk-enrich a DataFrame with KG metadata columns.

        Adds columns for profile_number, ticker, naics, etc. using fuzzy
        company-name matching. Vectorised: builds a mapping per unique
        company value rather than hitting the index N times.

        Rows with non-empty ``entity_id`` are enriched from DuckDB first; vault
        fuzzy matching is applied only to rows without a resolving registry row
        or with blank ``entity_id``.
        """
        df = df.copy()
        if "entity_id" in df.columns:
            try:
                from prompt2dataset.utils.entity_registry import dataframe_enrichment_from_registry

                merged = dataframe_enrichment_from_registry(df)
                merged = _coalesce_registry_into_columns(merged)
            except Exception as exc:
                logger.debug("MetadataConstructor: registry dataframe merge skipped: %s", exc)
                merged = df
            eid = merged["entity_id"].fillna("").astype(str).str.strip()
            has_reg = pd.Series(False, index=merged.index)
            for c in ("registry_profile_number", "registry_company_name", "registry_naics"):
                if c in merged.columns:
                    has_reg = has_reg | (
                        merged[c].fillna("").astype(str).str.strip() != ""
                    )
            need_fuzzy = ~(eid.ne("") & has_reg)
            if not need_fuzzy.any():
                return merged
            df_work = merged
        else:
            need_fuzzy = pd.Series(True, index=df.index)
            df_work = df

        self._ensure_loaded()
        if not self._raw_names or company_col not in df_work.columns:
            return df_work

        fuzzy_df = df_work.loc[need_fuzzy].copy()
        if fuzzy_df.empty:
            return df_work

        unique_companies = fuzzy_df[company_col].dropna().unique().tolist()
        company_to_fm: dict[str, dict[str, Any]] = {}
        for co in unique_companies:
            fm = self.lookup(str(co))
            if fm:
                company_to_fm[str(co)] = fm

        if not company_to_fm:
            return df_work

        target_fields = list(_KG_FIELD_MAP.items()) + [
            (f, f) for f in (extra_cols or [])
        ]
        for kg_field, out_field in target_fields:
            if out_field not in df_work.columns:
                df_work[out_field] = None
            m = need_fuzzy & df_work[company_col].isin(company_to_fm)
            df_work.loc[m, out_field] = df_work.loc[m, company_col].map(
                lambda co, kf=kg_field: company_to_fm.get(str(co), {}).get(kf)
            )

        return df_work


# ── Dataset-level metadata schema ─────────────────────────────────────────────

def build_dataset_metadata_spec(
    topic: str,
    schema_cols: list[dict],
    corpus_id: str = "unknown",
) -> dict[str, Any]:
    """Build the metadata spec for an entire extracted dataset.

    This is the 'dataset identity card' stored in vault/Schemas/ alongside
    the field schema. It records:
      - What the dataset measures (topic, domain tags)
      - How rows are identified (identity fields)
      - What metadata sources were used for enrichment
      - Field-level definitions (types, keywords, default values)

    The spec drives:
      - The column ordering in export CSVs
      - Which identity fields are used for deduplication
      - What gets written to the KG run note
    """
    from prompt2dataset.utils.nlp_utils import classify_topic, generate_corpus_keywords

    tags = classify_topic(topic)
    kws = generate_corpus_keywords(topic, schema_cols)

    # Standard identity columns (always included, ordered first)
    # profile_number is the canonical SEDAR row key (short integer).
    identity_fields = [
        "entity_id", "profile_number", "company_name", "ticker", "filing_date", "doc_type",
    ]

    # KG enrichment columns (added when KG lookup succeeds)
    enrichment_fields = [
        "profile_number", "naics", "issuer_size", "jurisdiction",
        "issuer_type", "exchange", "lei", "gvkey",
    ]

    return {
        "corpus_id": corpus_id,
        "topic": topic,
        "domain_tags": tags,
        "bm25_keywords": kws[:20],
        "identity_fields": identity_fields,
        "enrichment_fields": enrichment_fields,
        "extraction_fields": [c.get("name") for c in schema_cols],
        "field_definitions": [
            {
                "name": c.get("name"),
                "type": c.get("type", "str"),
                "description": c.get("description", ""),
                "keywords": c.get("keywords", []),
                "default": c.get("default"),
            }
            for c in schema_cols
        ],
        "metadata_sources": [
            "DuckDB entity_registry (exact join on entity_id)",
            "vault/Entities (KG fuzzy match when entity_id unresolved)",
            "master_sedar_issuers01_enriched.csv",
        ],
    }


def resolve_corpus_identity_fields(
    corpus_index_df: pd.DataFrame,
    schema_cols: list[dict],
) -> list[str]:
    """Return ordered identity column names suitable for this corpus.

    Prioritises columns that exist in the corpus index and are likely to
    uniquely identify a filing (profile_id → company_name → ticker → date).
    Falls back to available columns.
    """
    preferred = [
        "profile_number", "company_name", "ticker", "sedar_name",
        "filing_id", "doc_id", "date", "filing_date", "year",
    ]
    available = set(corpus_index_df.columns.tolist())
    ordered = [c for c in preferred if c in available]
    if not ordered:
        ordered = list(available)[:3]
    return ordered


# ── Singleton ─────────────────────────────────────────────────────────────────
_mc_instance: MetadataConstructor | None = None


def get_metadata_constructor(vault_path: str | Path | None = None) -> MetadataConstructor:
    global _mc_instance
    if _mc_instance is None:
        _mc_instance = MetadataConstructor(vault_path)
    return _mc_instance
