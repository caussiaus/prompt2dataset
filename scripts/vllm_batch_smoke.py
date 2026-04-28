#!/usr/bin/env python3
"""Concurrent vLLM chat smoke — proves the card answers batched load like Streamlit extraction.

Loads ``ISF-PEECEE/.env`` then ``prompt2dataset/.env`` (same as autonomy tick), then fires
``--total`` minimal chat completions with at most ``--concurrency`` in flight at once.

Run from repo root (recommended):
  ./.venv/bin/python prompt2dataset/scripts/vllm_batch_smoke.py
  ./.venv/bin/python prompt2dataset/scripts/vllm_batch_smoke.py --concurrency 12 --total 48 --json-out

Claw / CI: exit 0 only if every request returns HTTP 200 and a non-empty assistant message.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

# Stable cwd so pydantic ``env_file=.env`` resolves next to ``prompt2dataset/`` when agents
# run from arbitrary directories (same cwd issue as Claw when not started from repo root).
_P2D_ROOT = Path(__file__).resolve().parents[1]
os.chdir(_P2D_ROOT)

for _p in (_P2D_ROOT.parent, _P2D_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _percentile_nearest(sorted_x: list[float], pct: float) -> float:
    """Linear interpolation; ``pct`` in 0..100."""
    if not sorted_x:
        return 0.0
    if len(sorted_x) == 1:
        return sorted_x[0]
    k = (len(sorted_x) - 1) * (pct / 100.0)
    lo = int(math.floor(k))
    hi = min(lo + 1, len(sorted_x) - 1)
    if hi <= lo:
        return sorted_x[lo]
    return sorted_x[lo] + (sorted_x[hi] - sorted_x[lo]) * (k - lo)


async def _one_chat(
    client,
    base: str,
    model: str,
    api_key: str,
    req_id: int,
    max_tokens: int,
    timeout: float,
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    url = f"{base.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": f'Reply with a single JSON object only: {{"ok": true, "n": {req_id}}}',
            }
        ],
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }
    t0 = time.perf_counter()
    async with sem:
        try:
            r = await client.post(url, json=body, headers=headers, timeout=timeout)
            dt = time.perf_counter() - t0
            ok_http = r.status_code == 200
            text = ""
            err = ""
            if ok_http:
                try:
                    data = r.json()
                    choices = data.get("choices") or []
                    if choices:
                        msg = (choices[0].get("message") or {})
                        text = (msg.get("content") or "").strip()
                except Exception as e:
                    err = f"json_parse:{e}"
            else:
                err = (r.text or "")[:500]
            return {
                "req_id": req_id,
                "http": r.status_code,
                "latency_s": round(dt, 3),
                "chars": len(text),
                "error": err,
                "ok": ok_http and len(text) > 0,
            }
        except Exception as e:
            dt = time.perf_counter() - t0
            return {
                "req_id": req_id,
                "http": -1,
                "latency_s": round(dt, 3),
                "chars": 0,
                "error": str(e)[:500],
                "ok": False,
            }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    import httpx

    from prompt2dataset.utils.config import ensure_hf_hub_env_for_process, get_settings

    ensure_hf_hub_env_for_process()
    s = get_settings()
    base = (s.vllm_base_url or "").rstrip("/")
    if not base:
        return {"ok": False, "error": "empty VLLM_BASE_URL"}

    hdr = {"Authorization": f"Bearer {s.vllm_api_key}"}
    async with httpx.AsyncClient() as client:
        t_models = time.perf_counter()
        try:
            rm = await client.get(f"{base}/models", headers=hdr, timeout=max(30.0, args.timeout_per_req))
            rm.raise_for_status()
            ids = [m.get("id", "") for m in rm.json().get("data", []) if isinstance(m, dict)]
        except Exception as e:
            return {"ok": False, "phase": "models", "error": str(e)}
        models_latency_s = round(time.perf_counter() - t_models, 3)

        if s.vllm_model_name not in ids:
            return {
                "ok": False,
                "phase": "models",
                "error": f"VLLM_MODEL_NAME {s.vllm_model_name!r} not in /models list",
                "ids_sample": ids[:16],
                "models_latency_s": models_latency_s,
            }

        sem = asyncio.Semaphore(max(1, args.concurrency))
        wall0 = time.perf_counter()
        tasks = [
            _one_chat(
                client,
                base,
                s.vllm_model_name,
                s.vllm_api_key,
                i,
                args.max_tokens,
                args.timeout_per_req,
                sem,
            )
            for i in range(args.total)
        ]
        rows = await asyncio.gather(*tasks)
        wall_s = round(time.perf_counter() - wall0, 3)

    oks = [r for r in rows if r.get("ok")]
    fails = [r for r in rows if not r.get("ok")]
    latencies = [float(r["latency_s"]) for r in rows if r.get("latency_s") is not None]

    summary: dict[str, Any] = {
        "ok": len(fails) == 0,
        "vllm_base_url": base,
        "model": s.vllm_model_name,
        "concurrency": args.concurrency,
        "total_requests": args.total,
        "max_tokens": args.max_tokens,
        "models_latency_s": models_latency_s,
        "wall_clock_s": wall_s,
        "successes": len(oks),
        "failures": len(fails),
        "throughput_rps": round(args.total / wall_s, 3) if wall_s > 0 else None,
    }
    if latencies:
        lat_sorted = sorted(latencies)
        summary["latency_p50_s"] = round(statistics.median(lat_sorted), 3)
        summary["latency_p95_s"] = round(_percentile_nearest(lat_sorted, 95.0), 3)
        summary["latency_max_s"] = round(max(lat_sorted), 3)
    if fails:
        summary["fail_samples"] = fails[:8]

    return summary


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--concurrency", type=int, default=8, help="Max in-flight chat completions (default 8)")
    p.add_argument("--total", type=int, default=24, help="Total completions to run (default 24)")
    p.add_argument("--max-tokens", type=int, default=32, help="max_tokens per completion (default 32)")
    p.add_argument("--timeout-per-req", type=float, default=180.0, help="HTTP timeout per request (seconds)")
    p.add_argument("--json-out", action="store_true", help="Print one JSON object to stdout")
    args = p.parse_args()

    if args.total < 1:
        print("total must be >= 1", file=sys.stderr)
        return 2
    if args.concurrency < 1:
        print("concurrency must be >= 1", file=sys.stderr)
        return 2

    try:
        out = asyncio.run(_run(args))
    except KeyboardInterrupt:
        out = {"ok": False, "fatal": "KeyboardInterrupt"}
        if args.json_out:
            print(json.dumps(out, indent=2))
        else:
            print(json.dumps(out, indent=2), file=sys.stderr)
        return 130
    except Exception as e:
        out = {
            "ok": False,
            "fatal": f"{type(e).__name__}: {e}",
        }
        if args.json_out:
            print(json.dumps(out, indent=2, default=str))
        else:
            print("vllm_batch_smoke FATAL:", json.dumps(out, indent=2), file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1

    if args.json_out:
        print(json.dumps(out, indent=2, default=str))
    else:
        print("vllm_batch_smoke:", json.dumps(out, indent=2, default=str))

    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
