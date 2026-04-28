"""Normalize extracted rows before CSV export — tighter quotes, type coercion, stable strings.

Academic / analysis-ready tables benefit from consistent scalars and bounded verbatim quotes.
Quote length cap: ``config/prompt2dataset.yaml`` → ``export.quote_max_chars``.
"""
from __future__ import annotations

import re
from typing import Any

from prompt2dataset.dataset_graph.state import SchemaColumn

_WS_RE = re.compile(r"\s+")
_NUM_CLEAN_RE = re.compile(r"[,_\s]")


def _quote_cap() -> int:
    try:
        from prompt2dataset.utils.prompt2dataset_settings import load_prompt2dataset_config

        return max(80, load_prompt2dataset_config().export_quote_max_chars)
    except Exception:
        return 1200


def _condense_quote(s: str, max_chars: int) -> str:
    s = s.strip()
    if not s:
        return s
    s = _WS_RE.sub(" ", s)
    if len(s) <= max_chars:
        return s
    return s[: max(1, max_chars - 3)].rstrip() + "..."


def _coerce_bool(val: Any, default: Any) -> Any:
    if val is None or val == "":
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val) if val in (0, 1) else default
    s = str(val).strip().lower()
    if s in ("true", "yes", "y", "1", "t"):
        return True
    if s in ("false", "no", "n", "0", "f"):
        return False
    return default


def _coerce_int(val: Any, default: Any) -> Any:
    if val is None or val == "":
        return default
    if isinstance(val, int) and not isinstance(val, bool):
        return val
    if isinstance(val, float) and val == int(val):
        return int(val)
    s = _NUM_CLEAN_RE.sub("", str(val).strip())
    try:
        return int(float(s))
    except ValueError:
        return default


def _coerce_float(val: Any, default: Any) -> Any:
    if val is None or val == "":
        return default
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    s = str(val).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return default


def _coerce_string(val: Any, default: Any) -> Any:
    if val is None:
        return default
    if isinstance(val, str):
        return val.strip()
    return str(val).strip() if val != "" else default


def normalize_scalar_for_schema(val: Any, col: SchemaColumn) -> Any:
    """Coerce a single cell toward the schema column type."""
    name = (col.get("type") or "string|null").lower().strip()
    default = col.get("default")

    if name in ("boolean", "bool"):
        return _coerce_bool(val, default if default is not None else False)
    if name in ("integer", "integer|null", "int", "int|null"):
        return _coerce_int(val, default)
    if name in ("number", "number|null", "float", "float|null"):
        return _coerce_float(val, default)
    if name in ("string", "string|null", "str", "text"):
        out = _coerce_string(val, default)
        return out if out != "" else default
    return val


def normalize_row_for_export(
    row: dict[str, Any],
    schema_cols: list[SchemaColumn],
    *,
    quote_max: int | None = None,
) -> dict[str, Any]:
    """Return a shallow-copied row with normalized schema values and condensed evidence quotes."""
    qmax = quote_max if quote_max is not None else _quote_cap()
    out = dict(row)

    for col in schema_cols:
        n = col.get("name")
        if not n or n not in out:
            continue
        out[n] = normalize_scalar_for_schema(out.get(n), col)

    for k in list(out.keys()):
        if k.endswith("_evidence_quote") or k.endswith("_exact_quote"):
            v = out.get(k)
            if isinstance(v, str):
                out[k] = _condense_quote(v, qmax) or None
            elif v is not None:
                out[k] = _condense_quote(str(v), qmax) or None

    # Structured chains live in cells JSONL — keep CSV narrow.
    out.pop("_evidence_chains", None)

    return out


def normalize_rows_for_export(
    rows: list[dict[str, Any]],
    schema_cols: list[SchemaColumn],
    *,
    quote_max: int | None = None,
) -> list[dict[str, Any]]:
    return [normalize_row_for_export(r, schema_cols, quote_max=quote_max) for r in rows]
