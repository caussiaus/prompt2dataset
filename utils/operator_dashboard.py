"""Shared helpers for Streamlit operator pages (metrics, probes, paths).

No Streamlit imports — safe for unit tests and scripts."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def isf_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def autonomy_last_path(repo: Path | None = None) -> Path:
    r = repo or isf_repo_root()
    return (r / "state" / "autonomy_last.json").resolve()


def wonder_queue_path(repo: Path | None = None) -> Path:
    r = repo or isf_repo_root()
    override = (os.environ.get("ISF_GLOBAL_WONDER_QUEUE_PATH") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (r / "state" / "wonder_queue.jsonl").resolve()


def load_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        if not raw.strip():
            return None
        out = json.loads(raw)
        return out if isinstance(out, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def iso_mtime(path: Path) -> str | None:
    try:
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except OSError:
        return None


def scrape_arm_probe_json(repo: Path | None = None, *, timeout: int = 90) -> tuple[dict[str, Any] | None, str, int]:
    """Run ``isf-health scrape-json --json``. Returns (parsed, raw_stdout, exit_code)."""
    r = repo or isf_repo_root()
    script = r / "scripts" / "isf-health"
    proc = subprocess.run(
        ["bash", str(script), "scrape-json", "--json"],
        cwd=str(r),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    raw = (proc.stdout or "").strip()
    if not raw and proc.stderr:
        raw = proc.stderr.strip()
    try:
        return json.loads(raw), raw, proc.returncode
    except json.JSONDecodeError:
        return None, raw, proc.returncode


def scrape_services_table(arm: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not arm:
        return []
    svcs = arm.get("services")
    if not isinstance(svcs, dict):
        return []
    rows: list[dict[str, Any]] = []
    for name, meta in svcs.items():
        if not isinstance(meta, dict):
            continue
        rows.append(
            {
                "service": name,
                "status": meta.get("status"),
                "host": meta.get("host"),
                "port": meta.get("port"),
            }
        )
    return rows


def autonomy_metric_cards(data: dict[str, Any] | None) -> dict[str, Any]:
    """Flatten nested autonomy_last.json for metric widgets."""
    out: dict[str, Any] = {
        "has_snapshot": bool(data),
        "deferred": None,
        "deferral_reason": None,
        "controller_url": None,
        "health_http": None,
        "status_http": None,
        "controller_mode": None,
        "vllm_base": None,
        "vllm_models_ok": None,
        "vllm_n_models": None,
        "vllm_error": None,
        "gw_pending": None,
        "gw_path": None,
        "wq_run_loaded": None,
    }
    if not data:
        return out
    out["deferred"] = data.get("deferred")
    out["deferral_reason"] = data.get("deferral_reason")
    out["controller_url"] = data.get("controller_url")
    c = data.get("controller") or {}
    out["health_http"] = c.get("health_status")
    out["status_http"] = c.get("status_status")
    sb = c.get("status")
    if isinstance(sb, dict):
        out["controller_mode"] = sb.get("mode") or sb.get("state")
    v = data.get("vllm") or {}
    out["vllm_base"] = v.get("base_url")
    pr = v.get("probe") or {}
    out["vllm_models_ok"] = pr.get("ok")
    out["vllm_n_models"] = pr.get("n_models")
    out["vllm_error"] = (pr.get("error") or "")[:200] or None
    gw = data.get("global_wonder_queue") or {}
    out["gw_pending"] = gw.get("pending_count")
    out["gw_path"] = gw.get("path")
    wq = data.get("wonder_queue") or {}
    out["wq_run_loaded"] = wq.get("n_total_loaded")
    return out


def pending_wonder_rows(pending: list[dict[str, Any]], *, limit: int = 40) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ev in pending[-limit:]:
        if not isinstance(ev, dict):
            continue
        task = ev.get("task") if isinstance(ev.get("task"), dict) else {}
        rows.append(
            {
                "event_id": ev.get("event_id"),
                "created_at": ev.get("created_at"),
                "priority": ev.get("priority"),
                "source": ev.get("source"),
                "kind": task.get("kind"),
                "title": task.get("title") or task.get("summary"),
            }
        )
    return rows


def run_repo_command(
    argv: list[str],
    repo: Path | None = None,
    *,
    timeout: int,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    r = repo or isf_repo_root()
    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        argv,
        cwd=str(r),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=merged,
    )
