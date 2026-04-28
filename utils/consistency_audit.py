"""Filing-level QC report scaffold.

Domain-specific rules (tariff scores, FLS heuristics, etc.) belong in corpus-specific
scripts or pipelines — not here. This module writes a stable CSV shape so tools that
expect ``consistency_report_csv`` keep working; rows default to “no issues”.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from prompt2dataset.utils.config import Settings, get_settings


def evaluate_filing_consistency(
    doc: pd.DataFrame,
    *,
    pass1_any: dict[str, bool] | None = None,
) -> pd.DataFrame:
    """One row per filing: neutral QC columns (extend elsewhere with real checks)."""
    _ = pass1_any
    key = "filing_id" if "filing_id" in doc.columns else ("doc_id" if "doc_id" in doc.columns else None)
    rows: list[dict[str, Any]] = []
    if key is None:
        return pd.DataFrame(
            columns=[
                "filing_id",
                "qc_rule_count",
                "qc_rules",
                "qc_max_severity",
                "qc_error_count",
                "qc_warn_count",
                "qc_info_count",
                "fls_bias",
                "fls_only",
            ]
        )
    for _, r in doc.iterrows():
        fid = str(r.get(key, ""))
        rows.append(
            {
                "filing_id": fid,
                "qc_rule_count": 0,
                "qc_rules": "",
                "qc_max_severity": "none",
                "qc_error_count": 0,
                "qc_warn_count": 0,
                "qc_info_count": 0,
                "fls_bias": "",
                "fls_only": False,
            }
        )
    return pd.DataFrame(rows)


def write_consistency_report(
    doc: pd.DataFrame,
    settings: Settings | None = None,
    *,
    pass1_any: dict[str, bool] | None = None,
) -> Path:
    settings = settings or get_settings()
    out = settings.resolve(settings.consistency_report_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    qc = evaluate_filing_consistency(doc, pass1_any=pass1_any)
    qc.to_csv(out, index=False)
    return out
