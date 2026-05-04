"""DuckDB entity registry — deterministic identity resolution (join authority).

Registration-time resolution only; extraction and scope probe read exact keys.
See plan: entity_registry + entity_identifiers + document_registry in pipeline.duckdb.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]

# ── Scraped `listed_on_exchange` blobs (master_sedar_issuers01_enriched) ─────
_LEI_EX = re.compile(r"\bLEI\s+([A-Z0-9]{18,20})\b", re.I)
_TSX_TICK = re.compile(r"TSX\)\s*-\s*([A-Z0-9\.]+)")
_CUSIP_EX = re.compile(r"CUSIP\s+([A-Z0-9]{6,9})", re.I)
_ISIN_EX = re.compile(r"ISIN\s+([A-Z]{2}[A-Z0-9]{10})", re.I)
_PREV_NAME_EN = re.compile(
    r"Previous\s+name\s+in\s+English\s+([^\n]+?)\s+(?:Previous|Effective)",
    re.I,
)
_FORMERLY_PARENS = re.compile(r"\(formerly\s+([^)]+)\)", re.I)


def normalize_sedar_profile(raw: str) -> str:
    d = "".join(c for c in str(raw) if c.isdigit())
    return d.zfill(9) if d else ""


def make_entity_id_from_profile(profile_norm: str) -> str:
    """Canonical entity_id = zero-padded SEDAR profile_number (stable anchor)."""
    return profile_norm if profile_norm else ""


def make_provisional_entity_id(seed: str) -> str:
    """Issuers not in registry (or non-SEDAR docs) — never fuzzy-matched to a profile."""
    h = hashlib.sha256(str(seed).encode()).hexdigest()[:16]
    return f"prov_{h}"


def make_entity_id_doc_fallback(doc_id: str) -> str:
    """Deprecated alias for provisional IDs."""
    return make_provisional_entity_id(doc_id)


def parse_listed_on_exchange(raw: Any) -> dict[str, str]:
    """Extract LEI / TSX ticker / CUSIP / ISIN from HTML-scraped exchange text."""
    out: dict[str, str] = {}
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return out
    s = str(raw).strip()
    if not s:
        return out
    for key, pat in (
        ("lei", _LEI_EX),
        ("tsx_ticker", _TSX_TICK),
        ("cusip", _CUSIP_EX),
        ("isin", _ISIN_EX),
    ):
        m = pat.search(s)
        if m:
            v = m.group(1).strip().upper()
            if v:
                out[key] = v
    return out


def _lei_from_csv_column(val: str) -> str:
    """Use dedicated `lei` column only when it looks like a real LEI."""
    v = (val or "").strip().upper().replace(" ", "")
    if 18 <= len(v) <= 20 and re.match(r"^[A-Z0-9]+$", v):
        return v
    return ""


def historical_name_aliases(sedar_name: str, effective_blob: str) -> list[str]:
    """Former names from parentheses + `effective_from_date` / history text."""
    found: list[str] = []
    sn = (sedar_name or "").strip()
    if sn:
        for m in _FORMERLY_PARENS.finditer(sn):
            t = (m.group(1) or "").strip()
            if len(t) > 2:
                found.append(t)
    blob = (effective_blob or "").strip()
    if blob:
        for m in _PREV_NAME_EN.finditer(blob):
            t = (m.group(1) or "").strip()
            if len(t) > 2:
                found.append(t)
    # de-dupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for a in found:
        k = a.lower()
        if k not in seen:
            seen.add(k)
            out.append(a)
    return out


def _default_strict_stamp() -> bool:
    return os.environ.get("ENTITY_REGISTRY_STRICT_STAMP", "1").lower() not in (
        "0", "false", "no", "",
    )


def _vault_slug_from_company(name: str) -> str:
    s = re.sub(r"[^\w\s]", "", str(name).lower())
    return re.sub(r"\s+", "_", s.strip())[:80]


def upsert_entity_row(
    con,
    *,
    entity_id: str,
    company_name: str = "",
    cik: str = "",
    lei: str = "",
    sedar_profile_number: str = "",
    vault_note_id: str = "",
    naics: str = "",
    sedar_name: str = "",
    legal_name_en: str = "",
    issuer_type: str = "",
    principal_jurisdiction: str = "",
    profile_id: str = "",
    website: str = "",
    size: str = "",
    financial_year_end: str = "",
    has_secondary_key: bool | None = None,
) -> None:
    """Upsert one row aligned to master_sedar_issuers01_enriched semantics."""
    display = (sedar_name or company_name or legal_name_en or "").strip() or "Unknown"
    sn = (sedar_name or display).strip()
    ln = (legal_name_en or "").strip()
    con.execute(
        """
        INSERT INTO entity_registry
        (entity_id, cik, lei, sedar_profile_number, company_name, naics, vault_note_id,
         sedar_name, legal_name_en, issuer_type, principal_jurisdiction, profile_id,
         website, size, financial_year_end, has_secondary_key, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())
        ON CONFLICT(entity_id) DO UPDATE SET
            company_name = CASE WHEN excluded.company_name != ''
                THEN excluded.company_name ELSE entity_registry.company_name END,
            sedar_name = CASE WHEN excluded.sedar_name != ''
                THEN excluded.sedar_name ELSE entity_registry.sedar_name END,
            legal_name_en = CASE WHEN excluded.legal_name_en != ''
                THEN excluded.legal_name_en ELSE entity_registry.legal_name_en END,
            cik = COALESCE(NULLIF(excluded.cik, ''), entity_registry.cik),
            lei = COALESCE(NULLIF(excluded.lei, ''), entity_registry.lei),
            sedar_profile_number = COALESCE(
                NULLIF(excluded.sedar_profile_number, ''),
                entity_registry.sedar_profile_number
            ),
            issuer_type = COALESCE(NULLIF(excluded.issuer_type, ''), entity_registry.issuer_type),
            principal_jurisdiction = COALESCE(
                NULLIF(excluded.principal_jurisdiction, ''),
                entity_registry.principal_jurisdiction
            ),
            profile_id = COALESCE(NULLIF(excluded.profile_id, ''), entity_registry.profile_id),
            website = COALESCE(NULLIF(excluded.website, ''), entity_registry.website),
            naics = COALESCE(NULLIF(excluded.naics, ''), entity_registry.naics),
            size = COALESCE(NULLIF(excluded.size, ''), entity_registry.size),
            financial_year_end = COALESCE(
                NULLIF(excluded.financial_year_end, ''),
                entity_registry.financial_year_end
            ),
            has_secondary_key = CASE
                WHEN excluded.has_secondary_key IS NOT NULL THEN excluded.has_secondary_key
                ELSE entity_registry.has_secondary_key END,
            vault_note_id = COALESCE(
                NULLIF(excluded.vault_note_id, ''),
                entity_registry.vault_note_id
            ),
            updated_at = now()
        """,
        [
            entity_id,
            cik or None,
            lei or None,
            sedar_profile_number or None,
            display,
            naics or "",
            vault_note_id or None,
            sn,
            ln or None,
            issuer_type or None,
            principal_jurisdiction or None,
            profile_id or None,
            website or None,
            size or None,
            financial_year_end or None,
            has_secondary_key,
        ],
    )


def upsert_identifier(
    con,
    *,
    entity_id: str,
    id_type: str,
    id_value: str,
    valid_from: str | None = None,
    valid_to: str | None = None,
    source: str = "",
) -> None:
    if not entity_id or not id_type or not id_value:
        return
    try:
        con.execute(
            """
            INSERT INTO entity_identifiers
            (entity_id, id_type, id_value, valid_from, valid_to, source)
            VALUES (?, ?, ?, CAST(? AS DATE), CAST(? AS DATE), ?)
            """,
            [entity_id, id_type, id_value, valid_from, valid_to, source],
        )
    except Exception:
        pass  # duplicate (entity_id, id_type, id_value, valid_from)


def sync_master_csv_to_registry(
    csv_path: str | Path,
    *,
    db_path: Path | None = None,
    max_rows: int | None = None,
) -> int:
    """Load master_sedar_issuers01_enriched-style CSV into entity_registry + entity_identifiers.

    - ``entity_id`` = zero-padded ``profile_number`` (not a synthetic prefix).
    - LEI / TSX ticker / CUSIP / ISIN parsed from ``listed_on_exchange`` blobs.
    - Historical names from ``effective_from_date`` and "(formerly …)" in ``sedar_name``.

    Returns number of entity rows upserted.
    """
    from prompt2dataset.utils.lance_store import _get_lakehouse_db

    p = Path(csv_path)
    if not p.is_file():
        logger.warning("entity_registry: master CSV not found: %s", p)
        return 0

    try:
        df = pd.read_csv(p, dtype=str, low_memory=False, on_bad_lines="skip")
    except TypeError:
        df = pd.read_csv(p, dtype=str, low_memory=False)
    if max_rows:
        df = df.head(max_rows)

    con = _get_lakehouse_db(db_path)
    n = 0
    eff_col_name: str | None = None
    if "effective_from_date" in df.columns:
        eff_col_name = "effective_from_date"
    else:
        for c in df.columns:
            cl = c.lower().replace(" ", "").replace("_", "")
            if "effective" in cl and "date" in cl:
                eff_col_name = c
                break

    for _, row in df.iterrows():
        profile = normalize_sedar_profile(str(row.get("profile_number", "") or ""))
        if not profile:
            continue
        eid = make_entity_id_from_profile(profile)
        sedar_name = str(row.get("sedar_name", "") or "").strip()
        legal_name_en = str(row.get("legal_name_en", "") or "").strip()
        display_name = sedar_name or legal_name_en
        exc = parse_listed_on_exchange(row.get("listed_on_exchange"))
        lei_col = _lei_from_csv_column(str(row.get("lei", "") or ""))
        lei_eff = (exc.get("lei") or lei_col or "").strip().upper() or None
        cik = str(row.get("cik", "") or "").strip()
        vault_note = _vault_slug_from_company(display_name) if display_name else ""

        naics_val = str(row.get("naics", "") or "").strip()
        issuer_type = str(row.get("issuer_type", "") or "").strip()
        jurisdiction = str(row.get("principal_jurisdiction", "") or "").strip()
        profile_id = str(row.get("profile_id", "") or "").strip()
        website = ""
        for wcol in ("website", "web_site", "url"):
            if wcol in df.columns:
                website = str(row.get(wcol, "") or "").strip()
                if website:
                    break
        size_val = str(row.get("size", "") or "").strip()
        fye = str(row.get("financial_year_end", "") or "").strip()
        if not fye and "financial_year_end" not in df.columns:
            for alt in ("fiscal_year_end", "year_end"):
                if alt in df.columns:
                    fye = str(row.get(alt, "") or "").strip()
                    break

        legacy_ticker = str(row.get("ticker", "") or "").strip().upper().split(":")[-1]
        tsx_from_row = exc.get("tsx_ticker") or legacy_ticker or ""
        has_secondary = bool(
            tsx_from_row
            or exc.get("cusip")
            or exc.get("isin")
            or lei_eff
            or legacy_ticker
        )

        eff_blob = str(row.get(eff_col_name, "") or "") if eff_col_name else ""

        upsert_entity_row(
            con,
            entity_id=eid,
            company_name=display_name,
            cik=cik,
            lei=lei_eff or "",
            sedar_profile_number=profile,
            vault_note_id=vault_note,
            naics=naics_val,
            sedar_name=sedar_name or display_name,
            legal_name_en=legal_name_en,
            issuer_type=issuer_type,
            principal_jurisdiction=jurisdiction,
            profile_id=profile_id,
            website=website,
            size=size_val,
            financial_year_end=fye,
            has_secondary_key=has_secondary,
        )

        if lei_eff:
            upsert_identifier(
                con, entity_id=eid, id_type="lei", id_value=lei_eff, source="sedar_master_csv"
            )
        if tsx_from_row:
            upsert_identifier(
                con,
                entity_id=eid,
                id_type="tsx_ticker",
                id_value=tsx_from_row,
                source="sedar_master_csv",
            )
            upsert_identifier(
                con,
                entity_id=eid,
                id_type="ticker",
                id_value=tsx_from_row,
                source="sedar_master_csv",
            )
        if exc.get("cusip"):
            upsert_identifier(
                con,
                entity_id=eid,
                id_type="cusip",
                id_value=exc["cusip"],
                source="sedar_master_csv",
            )
        if exc.get("isin"):
            upsert_identifier(
                con,
                entity_id=eid,
                id_type="isin",
                id_value=exc["isin"],
                source="sedar_master_csv",
            )

        if sedar_name:
            upsert_identifier(
                con,
                entity_id=eid,
                id_type="name_alias",
                id_value=sedar_name.lower(),
                source="sedar_master_csv",
            )
        if legal_name_en and legal_name_en.lower() != sedar_name.lower():
            upsert_identifier(
                con,
                entity_id=eid,
                id_type="name_alias",
                id_value=legal_name_en.lower(),
                source="sedar_master_csv",
            )

        for hist in historical_name_aliases(sedar_name, eff_blob):
            upsert_identifier(
                con,
                entity_id=eid,
                id_type="name_alias",
                id_value=hist.lower(),
                source="sedar_master_csv_predecessor",
            )

        n += 1

    con.close()
    logger.info("entity_registry: upserted %d entities from %s", n, p.name)
    return n


def load_profile_to_entity_id_map(con) -> dict[str, str]:
    """Map normalized SEDAR profile -> entity_id."""
    rows = con.execute(
        "SELECT sedar_profile_number, entity_id FROM entity_registry "
        "WHERE sedar_profile_number IS NOT NULL AND sedar_profile_number != ''"
    ).fetchall()
    return {str(r[0]): str(r[1]) for r in rows}


def load_company_lower_to_entity_id(con) -> dict[str, str]:
    rows = con.execute(
        "SELECT lower(company_name), entity_id FROM entity_registry "
        "WHERE company_name IS NOT NULL AND company_name != ''"
    ).fetchall()
    out: dict[str, str] = {}
    for name_low, eid in rows:
        key = str(name_low or "").strip()
        if key:
            out[key] = str(eid)
    return out


def lookup_resolution_from_duckdb_ticker(
    ticker_upper: str,
    *,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    """Resolve a TSX-style ticker via ``entity_identifiers`` (after master sync)."""
    from prompt2dataset.utils.lance_store import _get_lakehouse_db

    t = (ticker_upper or "").strip().upper().split(":")[-1]
    if not t:
        return None
    con = _get_lakehouse_db(db_path)
    try:
        row = con.execute(
            """
            SELECT er.entity_id, er.sedar_profile_number, er.company_name, er.naics
            FROM entity_identifiers ei
            INNER JOIN entity_registry er ON er.entity_id = ei.entity_id
            WHERE ei.id_type IN ('tsx_ticker', 'ticker') AND upper(ei.id_value) = ?
            LIMIT 1
            """,
            [t],
        ).fetchone()
    finally:
        con.close()
    if not row:
        return None
    sp = str(row[1] or "").strip()
    eid = str(row[0] or "")
    return {
        "entity_id": eid,
        "profile_number": sp or eid,
        "sedar_name": str(row[2] or ""),
        "naics_sector": str(row[3] or ""),
    }


def lookup_resolution_from_duckdb_name_alias(
    name_lower: str,
    *,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    """Exact ``name_alias`` hit (current / legal / predecessor names)."""
    from prompt2dataset.utils.lance_store import _get_lakehouse_db

    nl = (name_lower or "").strip().lower()
    if len(nl) < 2:
        return None
    con = _get_lakehouse_db(db_path)
    try:
        row = con.execute(
            """
            SELECT er.entity_id, er.sedar_profile_number, er.company_name, er.naics
            FROM entity_identifiers ei
            INNER JOIN entity_registry er ON er.entity_id = ei.entity_id
            WHERE ei.id_type = 'name_alias' AND ei.id_value = ?
            LIMIT 1
            """,
            [nl],
        ).fetchone()
    finally:
        con.close()
    if not row:
        return None
    sp = str(row[1] or "").strip()
    eid = str(row[0] or "")
    return {
        "entity_id": eid,
        "profile_number": sp or eid,
        "sedar_name": str(row[2] or ""),
        "naics_sector": str(row[3] or ""),
    }


def stamp_index_dataframe(
    df: pd.DataFrame,
    *,
    db_path: Path | None = None,
    strict: bool | None = None,
) -> pd.DataFrame:
    """Add ``entity_id``: canonical profile when the row exists in ``entity_registry``; else ``prov_*``.

    With ``strict=True`` (default, overridable via ``ENTITY_REGISTRY_STRICT_STAMP``), company-name
    keys are never used to invent an ``entity_id`` — only ``profile_number`` matches the registry.
    """
    from prompt2dataset.utils.lance_store import _get_lakehouse_db

    if df.empty:
        return df

    df = df.copy()
    doc_col = "doc_id" if "doc_id" in df.columns else ("filing_id" if "filing_id" in df.columns else None)
    if not doc_col:
        return df

    st = _default_strict_stamp() if strict is None else strict

    con = _get_lakehouse_db(db_path)
    prof_map = load_profile_to_entity_id_map(con)
    name_map = load_company_lower_to_entity_id(con) if not st else {}
    con.close()

    def _doc_id_key(r: pd.Series) -> str:
        return str(r.get("doc_id") or r.get("filing_id", "") or "")

    entity_ids: list[str] = []
    for _, r in df.iterrows():
        eid = ""
        pn = ""
        if "profile_number" in df.columns:
            pn = normalize_sedar_profile(str(r.get("profile_number", "") or ""))
            if pn and pn in prof_map:
                eid = prof_map[pn]
        if not eid and not st and "company_name" in df.columns:
            cn = str(r.get("company_name", "") or "").lower().strip()
            eid = name_map.get(cn, "")
        if not eid:
            seed = f"profile:{pn}" if pn else _doc_id_key(r)
            eid = make_provisional_entity_id(seed)
        entity_ids.append(eid)

    df["entity_id"] = entity_ids
    return df


def resolve_entity_id_for_index_row(
    profile_raw: str,
    filing_or_doc_id: str,
    prof_map: dict[str, str],
    *,
    strict: bool | None = None,
) -> tuple[str, str]:
    """Return (entity_id, normalized profile or '')."""
    st = _default_strict_stamp() if strict is None else strict
    pn = normalize_sedar_profile(str(profile_raw or ""))
    if pn and pn in prof_map:
        return prof_map[pn], pn
    seed = f"profile:{pn}" if pn else str(filing_or_doc_id or "unknown")
    return make_provisional_entity_id(seed), pn if pn else ""


def sync_doc_registry_from_index(
    corpus_cfg,
    project_root: Path | None = None,
    *,
    db_path: Path | None = None,
) -> int:
    """Upsert doc_registry + document_registry from corpus index (entity_id, filing_id).

    Ensures scope_node / DuckDB probes have rows even if register_doc_in_lakehouse
    was never called during parse.
    """
    from prompt2dataset.utils.lance_store import _get_lakehouse_db

    root = project_root or _ROOT
    idx_path = corpus_cfg.resolve(corpus_cfg.index_csv, root)
    if not idx_path.is_file():
        return 0

    df = pd.read_csv(idx_path, dtype=str)
    if df.empty:
        return 0

    cid = corpus_cfg.corpus_id
    con = _get_lakehouse_db(db_path)
    prof_map = load_profile_to_entity_id_map(con)
    n = 0
    for _, r in df.iterrows():
        fid = str(r.get("filing_id") or r.get("doc_id", "") or "")
        if not fid:
            continue
        pn_idx = str(r.get("profile_number", "") or "").strip()
        eid = str(r.get("entity_id", "") or "").strip()
        if not eid:
            eid, _pn = resolve_entity_id_for_index_row(pn_idx, fid, prof_map)
        prof_norm = normalize_sedar_profile(pn_idx) if pn_idx else ""
        fh = ""
        try:
            from prompt2dataset.utils.ingest_cache import hash_pdf
            from prompt2dataset.utils.docling_pipeline import resolve_pdf_path
            from prompt2dataset.utils.config import get_settings

            lp = str(r.get("local_path", "") or "")
            if lp:
                pdf_p = resolve_pdf_path(lp, get_settings())
                if pdf_p.is_file():
                    fh = hash_pdf(pdf_p)
        except Exception:
            pass
        if not fh:
            fh = hashlib.md5(f"{fid}:{cid}".encode()).hexdigest()

        ent_name = str(r.get("company_name", "") or "")
        doc_type = str(r.get("doc_type", "") or "")
        doc_date = str(r.get("date", "") or r.get("filing_date", "") or "")
        fy = None
        if "fiscal_year" in df.columns and pd.notna(r.get("fiscal_year")):
            try:
                fy = int(str(r["fiscal_year"]).split(".")[0])
            except (ValueError, TypeError):
                fy = None
        ped = str(r.get("period_end", "") or "").strip() or None

        con.execute(
            "DELETE FROM doc_registry WHERE filing_id = ? AND corpus_id = ?",
            [fid, cid],
        )
        con.execute(
            """
            INSERT INTO doc_registry
            (file_hash, filing_id, corpus_id, entity_name, doc_type, doc_date,
             chunk_count, parse_status, json_path, entity_id, fiscal_year, period_end, registered_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, 'indexed', '', ?, ?, CAST(? AS DATE), now())
            """,
            [fh, fid, cid, ent_name, doc_type, doc_date, eid, fy, ped],
        )
        try:
            con.execute(
                """
                INSERT INTO document_registry
                (doc_id, entity_id, corpus_id, doc_type, fiscal_year, period_end,
                 file_hash, profile_number, indexed_at)
                VALUES (?, ?, ?, ?, ?, CAST(? AS DATE), ?, ?, now())
                ON CONFLICT(doc_id) DO UPDATE SET
                    entity_id = excluded.entity_id,
                    corpus_id = excluded.corpus_id,
                    doc_type = excluded.doc_type,
                    fiscal_year = excluded.fiscal_year,
                    period_end = excluded.period_end,
                    file_hash = excluded.file_hash,
                    profile_number = excluded.profile_number,
                    indexed_at = now()
                """,
                [fid, eid, cid, doc_type, fy, ped, fh, prof_norm],
            )
        except Exception as exc:
            logger.debug("document_registry upsert %s: %s", fid, exc)
        n += 1
    con.close()
    logger.info("entity_registry: synced %d index rows to doc_registry for %s", n, cid)
    return n


def fetch_corpus_entities_dataframe(corpus_id: str, *, db_path: Path | None = None) -> pd.DataFrame:
    """Scope probe: documents in corpus joined to canonical entity_registry."""
    from prompt2dataset.utils.lance_store import _get_lakehouse_db

    con = _get_lakehouse_db(db_path)
    try:
        return con.execute(
            """
            SELECT dr.filing_id AS doc_id,
                   dr.filing_id,
                   dr.corpus_id,
                   dr.entity_id,
                   dr.entity_name,
                   dr.doc_type,
                   dr.doc_date,
                   dr.chunk_count,
                   er.company_name AS registry_company_name,
                   er.cik,
                   er.lei,
                   er.sedar_profile_number,
                   er.vault_note_id
            FROM doc_registry dr
            LEFT JOIN entity_registry er ON er.entity_id = dr.entity_id
            WHERE dr.corpus_id = ?
            ORDER BY dr.registered_at
            """,
            [corpus_id],
        ).fetchdf()
    finally:
        con.close()


def lookup_entity_row(entity_id: str, *, db_path: Path | None = None) -> dict[str, Any] | None:
    from prompt2dataset.utils.lance_store import _get_lakehouse_db

    if not (entity_id or "").strip():
        return None
    con = _get_lakehouse_db(db_path)
    try:
        df = con.execute(
            "SELECT * FROM entity_registry WHERE entity_id = ? LIMIT 1",
            [entity_id.strip()],
        ).fetchdf()
        if df.empty:
            return None
        return {k: (v if pd.notna(v) else None) for k, v in df.iloc[0].items()}
    finally:
        con.close()


def enrich_entity_resolutions_with_registry(
    entities: list[dict],
    *,
    db_path: Path | None = None,
) -> list[dict]:
    """Add entity_id to EntityResolution dicts when profile_number maps in registry."""
    from prompt2dataset.utils.lance_store import _get_lakehouse_db

    con = _get_lakehouse_db(db_path)
    prof_map = load_profile_to_entity_id_map(con)
    con.close()

    out: list[dict] = []
    for e in entities:
        d = dict(e)
        pn = normalize_sedar_profile(str(d.get("profile_number", "") or ""))
        if pn and pn in prof_map:
            d["entity_id"] = prof_map[pn]
        elif str(d.get("entity_id", "") or "").strip():
            pass
        elif pn:
            d["entity_id"] = make_provisional_entity_id(f"unregistered:{pn}")
        else:
            d.setdefault("entity_id", "")
        out.append(d)
    return out


def enrich_entity_resolutions_for_corpus(
    entities: list[dict],
    corpus_id: str,
    *,
    db_path: Path | None = None,
) -> list[dict]:
    """Attach entity_id using DuckDB join (doc_registry + entity_registry) for this corpus.

    When a profile appears in the corpus, prefer that row's entity_id so scope matches indexed docs.
    Falls back to global entity_registry map + doc fallback.
    """
    if not (corpus_id or "").strip():
        return enrich_entity_resolutions_with_registry(entities, db_path=db_path)

    df = fetch_corpus_entities_dataframe(corpus_id.strip(), db_path=db_path)
    prof_to_eid: dict[str, str] = {}
    if not df.empty:
        for _, row in df.iterrows():
            eid = str(row.get("entity_id") or "").strip()
            if not eid:
                continue
            sp = str(row.get("sedar_profile_number") or "").strip()
            pn = normalize_sedar_profile(sp) if sp else normalize_sedar_profile(eid)
            if pn:
                prof_to_eid[pn] = eid

    staged: list[dict] = []
    for e in entities:
        d = dict(e)
        pn = normalize_sedar_profile(str(d.get("profile_number", "") or ""))
        if pn and pn in prof_to_eid:
            d["entity_id"] = prof_to_eid[pn]
        staged.append(d)

    return enrich_entity_resolutions_with_registry(staged, db_path=db_path)


def dataframe_enrichment_from_registry(
    df: pd.DataFrame,
    *,
    db_path: Path | None = None,
) -> pd.DataFrame:
    """Merge entity_registry columns for rows with non-empty entity_id (exact join)."""
    if df.empty or "entity_id" not in df.columns:
        return df

    ids = [str(x).strip() for x in df["entity_id"].dropna().unique().tolist() if str(x).strip()]
    if not ids:
        return df

    from prompt2dataset.utils.lance_store import _get_lakehouse_db

    ph = ",".join(["?"] * len(ids))
    con = _get_lakehouse_db(db_path)
    try:
        reg = con.execute(
            f"SELECT entity_id, sedar_profile_number AS registry_profile_number, "
            f"company_name AS registry_company_name, naics AS registry_naics, "
            f"lei AS registry_lei, cik AS registry_cik, vault_note_id "
            f"FROM entity_registry WHERE entity_id IN ({ph})",
            ids,
        ).fetchdf()
    finally:
        con.close()

    if reg.empty:
        return df

    return df.merge(reg, on="entity_id", how="left")


if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Sync master issuers CSV into DuckDB entity registry.")
    parser.add_argument(
        "--master",
        required=True,
        help="Path to master_sedar_issuers (or compatible) CSV",
    )
    parser.add_argument("--max-rows", type=int, default=None)
    args = parser.parse_args()
    sync_master_csv_to_registry(args.master, max_rows=args.max_rows)
    sys.exit(0)
