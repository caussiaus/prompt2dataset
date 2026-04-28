"""Recover structured critique JSON when the model truncates output or embeds broken JSON.

Kept free of ``instructor`` / vLLM imports for cheap unit tests.
"""
from __future__ import annotations

import json
import re
from typing import Any

_FIELD_ISSUE_START_RE = re.compile(r'\{\s*"field"\s*:\s*"')


def parse_field_issues_loose(text: str) -> list[dict[str, Any]]:
    """Parse each ``{"field": ...}`` object via ``JSONDecoder.raw_decode``."""
    items: list[dict[str, Any]] = []
    dec = json.JSONDecoder()
    for m in _FIELD_ISSUE_START_RE.finditer(text):
        try:
            obj, _ = dec.raw_decode(text, m.start())
            if isinstance(obj, dict) and obj.get("field"):
                items.append(obj)
        except json.JSONDecodeError:
            continue
    return items


def salvage_critique_meta(text: str) -> dict[str, Any]:
    """Pull ``overall_quality``, ``field_issues``, and ``overall_suggestion`` from messy text."""
    out: dict[str, Any] = {}
    q = re.search(r'"overall_quality"\s*:\s*"(good|ok|needs_work)"', text, re.I)
    if q:
        out["overall_quality"] = q.group(1).lower()
    issues = parse_field_issues_loose(text)
    if issues:
        out["field_issues"] = issues
    osm = re.search(r'"overall_suggestion"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.S)
    if osm:
        raw = osm.group(1).replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
        out["overall_suggestion"] = raw
    elif re.search(r'"overall_suggestion"\s*:\s*null', text):
        out["overall_suggestion"] = ""
    return out


def merge_critique_meta(primary: dict[str, Any], salvage: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    if not isinstance(merged.get("field_issues"), list) or not merged.get("field_issues"):
        if salvage.get("field_issues"):
            merged["field_issues"] = salvage["field_issues"]
    if "overall_quality" not in merged and salvage.get("overall_quality"):
        merged["overall_quality"] = salvage["overall_quality"]
    if not str(merged.get("overall_suggestion") or "").strip() and salvage.get("overall_suggestion") is not None:
        merged["overall_suggestion"] = salvage["overall_suggestion"]
    return merged
