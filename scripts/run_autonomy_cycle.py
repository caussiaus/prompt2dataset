#!/usr/bin/env python3
"""Autonomy tick: controller + vLLM probe + wonder queue; optional blackboard and council.

Claw (Tier-1) runs this while Tier-2 stays gated. See prompt2dataset/AUTONOMY_LOOP.md.
Env: CONTROLLER_BASE_URL (default http://127.0.0.1:8432)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT.parent, _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _http_json(url: str, timeout: float = 5.0) -> tuple[int, Any]:
    import httpx

    try:
        r = httpx.get(url, timeout=timeout)
        try:
            body: Any = r.json()
        except Exception:
            body = (r.text or "")[:2000]
        return r.status_code, body
    except Exception as e:
        return -1, str(e)


def _probe_vllm_models(base: str, api_key: str, *, timeout: float) -> dict[str, Any]:
    import httpx

    b = (base or "").rstrip("/")
    if not b:
        return {"ok": False, "error": "empty VLLM_BASE_URL"}
    try:
        r = httpx.get(f"{b}/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        ids = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]
        return {"ok": True, "n_models": len(ids), "ids_sample": ids[:8]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _run_council_if_requested(state: dict[str, Any]) -> dict[str, Any]:
    from prompt2dataset.dataset_graph.critique_council import run_critique_with_council

    out = run_critique_with_council(state)  # type: ignore[arg-type]
    return {
        "critique_quality": out.get("critique_quality"),
        "critique_text_head": (out.get("critique_text") or "")[:800],
        "consensus": out.get("critique_consensus"),
    }


def main() -> int:
    # Load ``ISF-PEECEE/.env`` then ``prompt2dataset/.env`` before argparse reads env defaults.
    from prompt2dataset.utils.config import ensure_hf_hub_env_for_process

    ensure_hf_hub_env_for_process()

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-id", default="", help="Run id to resolve wonder_queue + training_events paths")
    p.add_argument(
        "--datasets-export-dir",
        default="",
        help="As in DatasetState: .../runs/{run_id}/datasets — improves path resolution for sidecars",
    )
    p.add_argument(
        "--controller-url",
        default=os.environ.get("CONTROLLER_BASE_URL", "http://127.0.0.1:8432").rstrip("/"),
        help="vLLM controller (health + status), default from CONTROLLER_BASE_URL",
    )
    p.add_argument("--max-wonder", type=int, default=40, help="Max wonder_queue lines to return in report")
    p.add_argument(
        "--blackboard-json",
        default="",
        help="Optional path: epistemic_blackboard root JSON for normalization + stats only",
    )
    p.add_argument(
        "--state-json",
        default="",
        help="Optional DatasetState JSON; with --council runs validation council (GPU-heavy)",
    )
    p.add_argument(
        "--council",
        action="store_true",
        help="Run run_critique_with_council on --state-json (skips if controller reports training unless --force-council-on-training)",
    )
    p.add_argument(
        "--force-council-on-training",
        action="store_true",
        help="Allow council even when controller mode suggests training/queue (can starve training)",
    )
    p.add_argument("--log-event", action="store_true", help="Append autonomy_cycle to training_events.jsonl when run-id set")
    p.add_argument("--json-out", action="store_true", help="Print a single JSON object to stdout (for agents)")
    p.add_argument("--skip-controller", action="store_true", help="Do not call controller (offline dev)")
    p.add_argument("--skip-vllm", action="store_true", help="Do not probe vLLM /v1/models")
    p.add_argument(
        "--global-wonder",
        action="store_true",
        help="Include repo state/wonder_queue.jsonl pending summary (see global_wonder_queue.py)",
    )
    p.add_argument(
        "--http-timeout",
        type=float,
        default=float(os.environ.get("ISF_AUTONOMY_HTTP_TIMEOUT_SEC", "22")),
        help="Seconds for controller + vLLM HTTP probes (env ISF_AUTONOMY_HTTP_TIMEOUT_SEC)",
    )
    args = p.parse_args()

    from prompt2dataset.utils.epistemic_blackboard import normalize_epistemic_root
    from prompt2dataset.utils.wonder_queue import load_queue_entries, resolve_wonder_queue_path
    from prompt2dataset.training_events import append_training_event

    report: dict[str, Any] = {
        "controller_url": args.controller_url,
        "deferred": False,
        "deferral_reason": None,
        "controller": {},
        "vllm": {},
        "wonder_queue": {},
        "blackboard": {},
        "council": None,
        "global_wonder_queue": {},
        "error": None,
    }

    if not args.skip_controller:
        tmo = max(4.0, float(args.http_timeout))
        h_code, h_body = _http_json(f"{args.controller_url}/health", timeout=tmo)
        s_code, s_body = _http_json(f"{args.controller_url}/status", timeout=tmo)
        report["controller"] = {
            "health_status": h_code,
            "health": h_body,
            "status_status": s_code,
            "status": s_body,
        }
        mode = None
        if isinstance(s_body, dict):
            mode = s_body.get("mode") or s_body.get("state")
        mode_s = (str(mode) if mode is not None else "").lower()
        if any(x in mode_s for x in ("train", "training")):
            report["deferred"] = True
            report["deferral_reason"] = "controller_training"

    if not args.skip_vllm:
        from prompt2dataset.utils.config import get_settings

        s = get_settings()
        tmo = max(6.0, float(args.http_timeout))
        report["vllm"] = {
            "base_url": s.vllm_base_url,
            "probe": _probe_vllm_models(s.vllm_base_url, s.vllm_api_key, timeout=tmo),
        }

    st_for_paths: dict[str, Any] = {}
    if args.datasets_export_dir:
        st_for_paths["datasets_export_dir"] = args.datasets_export_dir

    if args.global_wonder:
        from prompt2dataset.utils.global_wonder_queue import global_wonder_queue_path, pending_global_wonders

        gw_path = global_wonder_queue_path()
        pend = pending_global_wonders(limit=min(500, max(1, args.max_wonder * 2)))
        report["global_wonder_queue"] = {
            "path": str(gw_path),
            "pending_count": len(pend),
            "pending_sample": pend[-args.max_wonder :],
        }

    if args.run_id:
        wpath = resolve_wonder_queue_path(args.run_id, st_for_paths or None)
        if wpath and wpath.is_file():
            entries = load_queue_entries(wpath, limit=8000)
            report["wonder_queue"] = {
                "path": str(wpath),
                "n_total_loaded": len(entries),
                "sample": [e for e in entries[-args.max_wonder :]],
            }
        else:
            report["wonder_queue"] = {
                "path": str(wpath) if wpath else None,
                "n_total_loaded": 0,
                "sample": [],
            }

    if args.blackboard_json:
        pth = Path(args.blackboard_json).expanduser()
        if pth.is_file():
            raw = json.loads(pth.read_text(encoding="utf-8"))
            norm = normalize_epistemic_root(raw)
            ndocs = len(norm)
            npress = sum(len((norm[d].get("field_pressure") or {})) for d in norm)
            report["blackboard"] = {"normalized_docs": ndocs, "field_pressure_keys": npress}
        else:
            report["blackboard"] = {"error": f"not found: {pth}"}

    council_wanted = args.council and bool(args.state_json)
    if council_wanted and report.get("deferred") and not args.force_council_on_training:
        report["council"] = {
            "skipped": True,
            "reason": report.get("deferral_reason") or "deferred",
        }
    elif council_wanted and args.state_json:
        pth = Path(args.state_json).expanduser()
        if not pth.is_file():
            report["council"] = {"error": f"state-json not found: {pth}"}
        else:
            try:
                st = json.loads(pth.read_text(encoding="utf-8"))
                if not isinstance(st, dict):
                    report["council"] = {"error": "state-json must be a JSON object"}
                else:
                    report["council"] = _run_council_if_requested(st)
            except Exception as e:
                report["council"] = {"error": str(e)}

    if args.log_event and args.run_id:
        snap = {
            k: report[k]
            for k in (
                "deferred",
                "deferral_reason",
                "controller",
                "vllm",
                "wonder_queue",
                "global_wonder_queue",
                "council",
                "blackboard",
            )
            if k in report
        }
        append_training_event(
            args.run_id,
            {
                "event_type": "autonomy_cycle",
                "snapshot": snap,
            },
            state=st_for_paths,
        )

    if args.json_out:
        print(json.dumps(report, default=str, ensure_ascii=False, indent=2))
    else:
        print("=== autonomy cycle ===")
        print("deferred:", report.get("deferred"), report.get("deferral_reason") or "")
        if report.get("vllm", {}).get("probe"):
            print("vLLM models OK:", report["vllm"]["probe"].get("ok"), report["vllm"]["probe"].get("error", ""))
        wq = report.get("wonder_queue") or {}
        if wq:
            print("wonder_queue sample count:", len(wq.get("sample") or []), "from", wq.get("path"))
        if report.get("council") and not (report["council"] or {}).get("skipped"):
            cr = report["council"] or {}
            print("council quality:", cr.get("critique_quality"), cr.get("error", ""))
        if report.get("error"):
            print("error:", report["error"])

    # Exit code: 2 = deferred (Claw / cron should back off)
    if report.get("deferred"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
