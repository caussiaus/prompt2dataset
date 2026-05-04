"""KG Loader — bulk import external metadata CSVs into the Obsidian vault.

Supported sources:
  - master_sedar_issuers01_enriched.csv  → vault/Entities/ (one note per issuer)
  - gvkey_ticker_from_wrds.csv           → enrich existing entity notes with ticker/gvkey
  - sedar_mapping_p*.csv                 → enrich entities with filing paths

Run via CLI:
    python -m prompt2dataset.utils.kg_loader --master data/metadata/master_sedar_issuers01_enriched.csv
    python -m prompt2dataset.utils.kg_loader --wrds /mnt/c/.../gvkey_ticker_from_wrds.csv
    python -m prompt2dataset.utils.kg_loader --mapping /mnt/c/.../sedar_mapping_p0.csv

Or call programmatically:
    from prompt2dataset.utils.kg_loader import load_master_to_kg, load_wrds_to_kg
    load_master_to_kg(vault_path="vault", csv_path="data/metadata/master_sedar_issuers01_enriched.csv")
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

from prompt2dataset.connectors.obsidian_bridge import ObsidianBridge, get_obsidian_bridge
from prompt2dataset.utils.entity_registry import (
    make_entity_id_from_profile,
    normalize_sedar_profile,
    sync_master_csv_to_registry,
)
from prompt2dataset.utils.nlp_utils import normalize_company_name

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        import math
        if math.isnan(v):
            return ""
    return str(v).strip()


def _entity_key(sedar_name: str) -> str:
    """Stable vault note key for an issuer — lowercase, underscored."""
    s = re.sub(r"[^\w\s]", "", sedar_name.lower())
    return re.sub(r"\s+", "_", s.strip())[:80]


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_master_to_kg(
    csv_path: str | Path,
    vault_path: str | Path | None = None,
    *,
    issuer_type_filter: str | None = None,
    max_rows: int | None = None,
    overwrite: bool = False,
) -> int:
    """Load master_sedar_issuers01_enriched.csv into vault/Entities/.

    Each row becomes one entity note keyed by the sedar_name.
    Already-existing notes are merged (new fields win) unless overwrite=True.

    Returns the number of notes written.
    """
    csv_path = Path(csv_path)
    if not csv_path.is_file():
        logger.warning("kg_loader: master CSV not found at %s", csv_path)
        return 0

    bridge = get_obsidian_bridge(vault_path)

    df = pd.read_csv(csv_path, dtype=str, low_memory=False)
    if max_rows:
        df = df.head(max_rows)

    # Optional filter (e.g. only "Reporting Issuer", skip "Investment fund")
    if issuer_type_filter and "issuer_type" in df.columns:
        df = df[df["issuer_type"].str.contains(issuer_type_filter, case=False, na=False)]

    written = 0
    for _, row in df.iterrows():
        sedar_name = _safe_str(row.get("sedar_name"))
        if not sedar_name:
            continue
        key = _entity_key(sedar_name)

        pn_norm = normalize_sedar_profile(_safe_str(row.get("profile_number")))
        eid = make_entity_id_from_profile(pn_norm) if pn_norm else ""

        frontmatter: dict[str, Any] = {
            "type": "entity",
            "entity_name": sedar_name,
            "entity_name_normalized": normalize_company_name(sedar_name),
            "profile_number": _safe_str(row.get("profile_number")),
            # profile_id (long hash) is scraper-internal — omitted from vault notes
            "naics": _safe_str(row.get("naics")),
            "size": _safe_str(row.get("size")),
            "principal_jurisdiction": _safe_str(row.get("principal_jurisdiction")),
            "issuer_type": _safe_str(row.get("issuer_type")),
            "listed_on_exchange": _safe_str(row.get("listed_on_exchange")),
            "lei": _safe_str(row.get("lei")),
            "legal_name_en": _safe_str(row.get("legal_name_en")),
            "source": "master_sedar_issuers",
        }
        if eid:
            frontmatter["entity_id"] = eid
        # Drop empty strings to keep notes clean
        frontmatter = {k: v for k, v in frontmatter.items() if v}

        if overwrite:
            body = f"# {sedar_name}\n\nSource: master_sedar_issuers01_enriched.csv\n"
            bridge._write_note("Entities", key, frontmatter, body)
        else:
            bridge.write_entity(key, frontmatter)
        written += 1

    try:
        sync_master_csv_to_registry(csv_path)
    except Exception as exc:
        logger.debug("kg_loader: DuckDB registry sync after vault write: %s", exc)

    logger.info("kg_loader: wrote %d entity notes from %s", written, csv_path.name)
    return written


def load_wrds_to_kg(
    csv_path: str | Path,
    vault_path: str | Path | None = None,
) -> int:
    """Enrich existing vault entities with WRDS gvkey/ticker mapping.

    Matches on company_name using normalised fuzzy comparison.
    Returns the number of notes updated.
    """
    csv_path = Path(csv_path)
    if not csv_path.is_file():
        logger.warning("kg_loader: WRDS CSV not found at %s", csv_path)
        return 0

    bridge = get_obsidian_bridge(vault_path)
    from prompt2dataset.utils.nlp_utils import match_company_name

    df = pd.read_csv(csv_path, dtype=str, low_memory=False)
    # Expected columns: gvkey, ticker, company_name
    if "company_name" not in df.columns:
        logger.warning("kg_loader: WRDS CSV missing 'company_name' column")
        return 0

    # Build lookup of existing entity keys → normalized names
    existing_keys = bridge.list_entities()
    existing_names: dict[str, str] = {}
    for key in existing_keys:
        note = bridge._read_note("Entities", key)
        if note:
            name = note[0].get("entity_name") or key
            existing_names[key] = str(name)

    candidate_names = list(existing_names.values())
    updated = 0

    for _, row in df.iterrows():
        wrds_name = _safe_str(row.get("company_name"))
        ticker = _safe_str(row.get("ticker"))
        gvkey = _safe_str(row.get("gvkey"))
        if not wrds_name:
            continue

        best_name, score = match_company_name(wrds_name, candidate_names)
        if best_name is None:
            continue

        # Find the key for this name
        key = next((k for k, v in existing_names.items() if v == best_name), None)
        if not key:
            continue

        # Enrich
        updates: dict[str, Any] = {"source_wrds": True}
        if ticker:
            updates["ticker"] = ticker
        if gvkey:
            updates["gvkey"] = gvkey
        bridge.write_entity(key, updates)
        updated += 1

    logger.info("kg_loader: enriched %d entities with WRDS data", updated)
    return updated


def load_sedar_mapping_to_kg(
    csv_path: str | Path,
    vault_path: str | Path | None = None,
) -> int:
    """Load sedar_mapping_p*.csv filing paths into vault Document nodes.

    Columns expected: company, filing_date, filing_type, file_path, profile_number
    Returns number of document notes written.
    """
    csv_path = Path(csv_path)
    if not csv_path.is_file():
        logger.warning("kg_loader: mapping CSV not found at %s", csv_path)
        return 0

    bridge = get_obsidian_bridge(vault_path)
    df = pd.read_csv(csv_path, dtype=str, low_memory=False)

    written = 0
    for _, row in df.iterrows():
        company = _safe_str(row.get("company"))
        filing_date = _safe_str(row.get("filing_date") or row.get("date"))
        filing_type = _safe_str(row.get("filing_type") or row.get("mine"))
        file_path = _safe_str(row.get("file_path"))
        profile_number = _safe_str(row.get("profile_number"))

        if not (company and filing_date):
            continue

        doc_key = f"{_entity_key(company)}_{filing_date}_{filing_type[:20]}"
        fm: dict[str, Any] = {
            "type": "document",
            "entity": company,
            "entity_normalized": normalize_company_name(company),
            "filing_date": filing_date,
            "doc_type": filing_type,
            "local_path": file_path,
            "profile_number": profile_number,
            "ingest_status": "available",
            "source": "sedar_mapping",
        }
        fm = {k: v for k, v in fm.items() if v}
        bridge.write_document(doc_key, fm)
        written += 1

    logger.info("kg_loader: wrote %d document nodes from %s", written, csv_path.name)
    return written


def load_all_available(
    vault_path: str | Path | None = None,
    *,
    master_csv: str | Path | None = None,
    wrds_csv: str | Path | None = None,
    mapping_globs: list[str] | None = None,
    issuer_type_filter: str = "Company",
) -> dict[str, int]:
    """Convenience loader — discover and load all available metadata sources.

    Searches default paths if specific paths are not provided.
    Returns dict of source → notes_written.
    """
    results: dict[str, int] = {}

    # ── Master SEDAR issuers ──────────────────────────────────────────────────
    if master_csv is None:
        for candidate in [
            _ROOT / "data" / "metadata" / "master_sedar_issuers01_enriched.csv",
            Path("/mnt/c/Users/casey/ISF/greenyield/sedar_scrape_portable"
                 "/sedar_scrape_portable/data/master_sedar_issuers01_enriched.csv"),
        ]:
            if candidate.is_file():
                master_csv = candidate
                break
    if master_csv and Path(master_csv).is_file():
        n = load_master_to_kg(master_csv, vault_path, issuer_type_filter=issuer_type_filter or "Company")
        results["master_sedar"] = n

    # ── WRDS ticker mapping ───────────────────────────────────────────────────
    if wrds_csv is None:
        for candidate in [
            Path("/mnt/c/Users/casey/ISF/greenyield/sedar_scrape_portable"
                 "/sedar_scrape_portable/data/gvkey_ticker_from_wrds.csv"),
        ]:
            if candidate.is_file():
                wrds_csv = candidate
                break
    if wrds_csv and Path(wrds_csv).is_file():
        n = load_wrds_to_kg(wrds_csv, vault_path)
        results["wrds"] = n

    # ── SEDAR mapping files ───────────────────────────────────────────────────
    if mapping_globs is None:
        mapping_globs = [
            str(Path("/mnt/c/Users/casey/ISF/greenyield/sedar_scrape_portable"
                     "/sedar_scrape_portable/data/prateek/mapping_backup_*/sedar_mapping_p0.csv")),
        ]

    import glob
    for pattern in (mapping_globs or []):
        for path in sorted(glob.glob(pattern)):
            n = load_sedar_mapping_to_kg(path, vault_path)
            results[f"mapping_{Path(path).stem}"] = n
            break  # one mapping file is enough for indexing

    return results


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Load metadata CSVs into the Obsidian KG vault.")
    parser.add_argument("--master", help="Path to master_sedar_issuers01_enriched.csv")
    parser.add_argument("--wrds", help="Path to gvkey_ticker_from_wrds.csv")
    parser.add_argument("--mapping", help="Path to sedar_mapping_p*.csv (one file)")
    parser.add_argument("--vault", help="Path to vault directory (default: auto-detect)")
    parser.add_argument("--all", action="store_true", help="Discover and load all available sources")
    parser.add_argument("--filter", default="Reporting Issuer",
                        help="issuer_type filter for master CSV (default: 'Reporting Issuer')")
    parser.add_argument("--max-rows", type=int, default=None, help="Limit rows (for testing)")
    args = parser.parse_args()

    vault = args.vault

    if args.all or (not any([args.master, args.wrds, args.mapping])):
        print("Loading all available metadata sources…")
        r = load_all_available(vault, issuer_type_filter=args.filter)
        for src, n in r.items():
            print(f"  {src}: {n} notes written")
    else:
        if args.master:
            n = load_master_to_kg(args.master, vault,
                                  issuer_type_filter=args.filter,
                                  max_rows=args.max_rows)
            print(f"master_sedar: {n} entity notes written")
        if args.wrds:
            n = load_wrds_to_kg(args.wrds, vault)
            print(f"wrds: {n} entities enriched")
        if args.mapping:
            n = load_sedar_mapping_to_kg(args.mapping, vault)
            print(f"mapping: {n} document nodes written")
