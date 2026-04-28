"""Scope resolution node.

Parses a user's research intent (tickers, company names, date ranges, doc types)
into a structured ScopeSpec, then resolves entities against local metadata CSVs.

Design invariant: no LLM is called in this module.

Resolution path:
  1. Regex: extract tickers (2–5 uppercase), 6-digit SEDAR profile numbers,
     year ranges, doc type keywords.
  2. Ticker / profile-number lookup: deterministic match against
     data/metadata/filings_index.csv (has ticker + profile_number columns).
     Fallback: master_sedar_issuers01_enriched.csv name search.
  3. Unresolved names are returned to the caller for the UI to ask one
     clarifying question — the LLM is never allowed to generate profile numbers.

The LLM may be used UPSTREAM in the scoping chat to turn ambiguous natural language
into a list of candidate company names (list[str]).  Once names are produced,
this module resolves them to profile numbers deterministically.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TypedDict, cast

import pandas as pd

logger = logging.getLogger(__name__)

# ── Known document type keywords → canonical labels ──────────────────────────

_DOC_TYPE_MAP: dict[str, str] = {
    "mda":           "Annual MD&A",
    "md&a":          "Annual MD&A",
    "annual report": "Annual Report",
    "aif":           "Annual Information Form",
    "esg":           "ESG/Sustainability Report",
    "sustainability":"ESG/Sustainability Report",
    "circular":      "Management Information Circular",
    "proxy":         "Management Information Circular",
    "interim":       "Interim MD&A",
    "quarterly":     "Quarterly Report",
}

# ── Regex patterns ────────────────────────────────────────────────────────────

_TICKER_RE = re.compile(
    r"\b(?:(?:TSX|NYSE|NASDAQ|TSX\.V|TSXV|CVE):)?([A-Z]{2,5})\b"
)
_PROFILE_RE = re.compile(r"\b(\d{6,9})\b")          # SEDAR profile numbers
_YEAR_RE    = re.compile(r"\b(20\d{2})\b")
_YEAR_RANGE_RE = re.compile(r"\b(20\d{2})\s*[-–—to]+\s*(20\d{2})\b", re.I)

# Common words that look like tickers but aren't
_TICKER_STOPWORDS = frozenset({
    "CEO", "CFO", "COO", "CTO", "ESG", "IPO", "TSX", "NYSE", "GDP", "USD",
    "CAD", "PDF", "API", "LLM", "AI", "MD", "AIF", "BC", "ON", "QC", "AB",
    "NB", "NS", "PE", "NL", "YT", "NT", "NU", "SK", "MB", "ETF", "REIT",
    "THE", "FOR", "AND", "NOT", "BUT", "ALL", "FROM", "WITH", "THIS", "INTO",
})


# ── ScopeSpec ────────────────────────────────────────────────────────────────

class EntityResolution(TypedDict, total=False):
    ticker: str
    sedar_name: str
    profile_number: str
    entity_id: str           # canonical join key (= profile_number) or prov_* provisional
    naics_sector: str
    resolution_source: str   # "filings_index" | "master_csv" | "unresolved"


class ScopeSpec(TypedDict, total=False):
    raw_prompt: str
    tickers: list[str]          # uppercased, exchange prefix stripped
    profile_numbers: list[str]  # 6–9 digit strings
    company_names: list[str]    # unstructured names from LLM/user
    doc_types: list[str]        # canonical doc type labels
    date_from: int | None       # year integer
    date_to: int | None         # year integer
    entities: list[EntityResolution]   # resolved entities
    unresolved: list[str]       # tickers/names that couldn't be looked up


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_scope_from_prompt(prompt_text: str) -> ScopeSpec:
    """Extract structured scope fields from raw user text. No LLM called."""
    text = prompt_text or ""

    # Tickers
    raw_tickers = [m.group(1) for m in _TICKER_RE.finditer(text)]
    tickers = [t for t in raw_tickers if t not in _TICKER_STOPWORDS]

    # SEDAR profile numbers
    profile_numbers = _PROFILE_RE.findall(text)

    # Date range — prefer explicit range pattern first
    date_from: int | None = None
    date_to: int | None = None
    range_match = _YEAR_RANGE_RE.search(text)
    if range_match:
        date_from = int(range_match.group(1))
        date_to   = int(range_match.group(2))
    else:
        years = [int(y) for y in _YEAR_RE.findall(text)]
        if years:
            date_from = min(years)
            date_to   = max(years)

    # Doc types
    text_lower = text.lower()
    doc_types: list[str] = []
    seen: set[str] = set()
    for kw, canonical in _DOC_TYPE_MAP.items():
        if kw in text_lower and canonical not in seen:
            doc_types.append(canonical)
            seen.add(canonical)

    # Default to MD&A if nothing found
    if not doc_types:
        doc_types = ["Annual MD&A"]

    return ScopeSpec(
        raw_prompt=text,
        tickers=list(dict.fromkeys(tickers)),         # deduplicate, preserve order
        profile_numbers=list(dict.fromkeys(profile_numbers)),
        company_names=[],                             # filled by caller from LLM names
        doc_types=doc_types,
        date_from=date_from,
        date_to=date_to,
        entities=[],
        unresolved=[],
    )


# ── Resolution ────────────────────────────────────────────────────────────────

def _load_filings_index(project_root: Path) -> pd.DataFrame:
    """Load the filings index CSV if available."""
    candidates = [
        project_root / "data" / "metadata" / "filings_index.csv",
        project_root / "data" / "metadata" / "corpus_tariffs_index.csv",
    ]
    for p in candidates:
        if p.exists():
            try:
                return pd.read_csv(p, dtype=str)
            except Exception as exc:
                logger.debug("_load_filings_index: %s failed: %s", p, exc)
    return pd.DataFrame()


def _load_master_csv(project_root: Path) -> pd.DataFrame:
    p = project_root / "data" / "metadata" / "master_sedar_issuers01_enriched.csv"
    if p.exists():
        try:
            return pd.read_csv(p, dtype=str)
        except Exception as exc:
            logger.debug("_load_master_csv: %s", exc)
    return pd.DataFrame()


def resolve_tickers(
    tickers: list[str],
    project_root: Path | None = None,
    index_csv_path: str | None = None,
) -> tuple[list[EntityResolution], list[str]]:
    """Resolve ticker symbols to entity metadata.

    Returns (resolved_list, unresolved_list).
    The LLM is never called here — only CSV lookups.
    """
    root = project_root or Path(__file__).resolve().parents[1]
    idx = pd.read_csv(index_csv_path, dtype=str) if index_csv_path else _load_filings_index(root)
    master = _load_master_csv(root)

    resolved: list[EntityResolution] = []
    unresolved: list[str] = []

    for ticker in tickers:
        ticker_clean = ticker.upper().strip()
        match: EntityResolution | None = None

        # ── Path 1: filings index ticker column ──────────────────────────────
        if not idx.empty and "ticker" in idx.columns:
            # Strip exchange prefix from index (e.g. "TSX:CNQ" → "CNQ")
            idx_tickers = idx["ticker"].str.upper().str.split(":").str[-1]
            hits = idx[idx_tickers == ticker_clean]
            if not hits.empty:
                row = hits.iloc[0]
                match = EntityResolution(
                    ticker=ticker_clean,
                    sedar_name=str(row.get("issuer_name", "")),
                    profile_number=str(row.get("profile_number", "")),
                    naics_sector=str(row.get("naics_sector", row.get("naics", ""))),
                    resolution_source="filings_index",
                )

        # ── Path 2: DuckDB entity_identifiers (tsx_ticker / ticker) ──────────
        if match is None:
            try:
                from prompt2dataset.utils.entity_registry import (
                    lookup_resolution_from_duckdb_ticker,
                )

                hit = lookup_resolution_from_duckdb_ticker(ticker_clean)
            except Exception:
                hit = None
            if hit:
                match = EntityResolution(
                    ticker=ticker_clean,
                    sedar_name=str(hit.get("sedar_name", "")),
                    profile_number=str(hit.get("profile_number", "")),
                    naics_sector=str(hit.get("naics_sector", "")),
                    entity_id=str(hit.get("entity_id", "")),
                    resolution_source="duckdb_identifiers",
                )

        # ── Path 3: master CSV name search ───────────────────────────────────
        if match is None and not master.empty:
            for name_col in ("sedar_name", "legal_name_en"):
                if name_col not in master.columns:
                    continue
                hits = master[master[name_col].str.upper().str.contains(ticker_clean, na=False)]
                if not hits.empty:
                    row = hits.iloc[0]
                    match = EntityResolution(
                        ticker=ticker_clean,
                        sedar_name=str(row.get(name_col, "")),
                        profile_number=str(row.get("profile_number", "")),
                        naics_sector=str(row.get("naics", "")),
                        resolution_source="master_csv",
                    )
                    break

        if match:
            resolved.append(match)
        else:
            unresolved.append(ticker_clean)

    return resolved, unresolved


def resolve_company_names(
    names: list[str],
    project_root: Path | None = None,
) -> tuple[list[EntityResolution], list[str]]:
    """Resolve plain company names (from LLM output) to entity metadata.

    The LLM outputs candidate names, NOT profile numbers.
    This function resolves names → profile numbers deterministically.
    """
    root = project_root or Path(__file__).resolve().parents[1]
    master = _load_master_csv(root)

    resolved: list[EntityResolution] = []
    unresolved: list[str] = []

    for name in names:
        name_lower = name.lower().strip()
        match: EntityResolution | None = None

        try:
            from prompt2dataset.utils.entity_registry import (
                lookup_resolution_from_duckdb_name_alias,
            )

            db_hit = lookup_resolution_from_duckdb_name_alias(name_lower)
        except Exception:
            db_hit = None
        if db_hit:
            match = EntityResolution(
                ticker="",
                sedar_name=str(db_hit.get("sedar_name", "")),
                profile_number=str(db_hit.get("profile_number", "")),
                naics_sector=str(db_hit.get("naics_sector", "")),
                entity_id=str(db_hit.get("entity_id", "")),
                resolution_source="duckdb_name_alias",
            )

        if match is None and not master.empty:
            for name_col in ("sedar_name", "legal_name_en"):
                if name_col not in master.columns:
                    continue
                # First try exact match (case-insensitive), then substring
                exact = master[master[name_col].str.lower() == name_lower]
                if not exact.empty:
                    row = exact.iloc[0]
                elif len(name_lower) >= 4:
                    fuzzy = master[master[name_col].str.lower().str.contains(name_lower[:20], na=False)]
                    row = fuzzy.iloc[0] if not fuzzy.empty else None
                else:
                    row = None

                if row is not None:
                    match = EntityResolution(
                        ticker="",
                        sedar_name=str(row.get(name_col, "")),
                        profile_number=str(row.get("profile_number", "")),
                        naics_sector=str(row.get("naics", "")),
                        resolution_source="master_csv",
                    )
                    break

        if match:
            resolved.append(match)
        else:
            unresolved.append(name)

    return resolved, unresolved


def resolve_scope(
    scope: ScopeSpec,
    project_root: Path | None = None,
    index_csv_path: str | None = None,
    *,
    corpus_id: str | None = None,
    db_path: Path | None = None,
) -> ScopeSpec:
    """Fully resolve a ScopeSpec: tickers + company names → EntityResolution list.

    When ``corpus_id`` is set, ``entity_id`` is aligned with DuckDB (doc_registry
    × entity_registry) for that corpus; otherwise the global registry map is used.
    """
    from prompt2dataset.utils.entity_registry import (
        enrich_entity_resolutions_for_corpus,
        enrich_entity_resolutions_with_registry,
    )

    root = project_root or Path(__file__).resolve().parents[1]
    all_resolved: list[EntityResolution] = []
    all_unresolved: list[str] = []

    # Profile numbers given directly → turn into minimal EntityResolution
    for pnum in scope.get("profile_numbers", []):
        all_resolved.append(EntityResolution(
            ticker="", sedar_name="", profile_number=pnum,
            naics_sector="", resolution_source="direct",
        ))

    # Ticker resolution
    if scope.get("tickers"):
        res, unres = resolve_tickers(scope["tickers"], root, index_csv_path)
        all_resolved.extend(res)
        all_unresolved.extend(unres)

    # Company name resolution (populated externally by LLM-assisted chat)
    if scope.get("company_names"):
        res, unres = resolve_company_names(scope["company_names"], root)
        all_resolved.extend(res)
        all_unresolved.extend(unres)

    as_dicts: list[dict] = [dict(e) for e in all_resolved]
    if corpus_id:
        enriched = enrich_entity_resolutions_for_corpus(
            as_dicts, corpus_id, db_path=db_path
        )
    else:
        enriched = enrich_entity_resolutions_with_registry(as_dicts, db_path=db_path)

    return {**scope, "entities": cast(list[EntityResolution], enriched), "unresolved": all_unresolved}
