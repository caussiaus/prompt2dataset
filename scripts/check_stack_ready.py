#!/usr/bin/env python3
"""Verify services needed for prompt2dataset extraction (vLLM first; optional controller).

Exit codes:
  0 — vLLM /v1/models OK and VLLM_MODEL_NAME is listed
  1 — vLLM unreachable (firewall, wrong port, server down, WSL host routing)
  2 — vLLM OK but configured model id not in /models
  3 — vLLM OK but optional controller /health failed (warning only unless --strict-controller)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT.parent, _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import httpx

from prompt2dataset.utils.config import get_settings


def _controller_url() -> str:
    return (os.environ.get("CONTROLLER_URL") or "http://127.0.0.1:8432").rstrip("/")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--strict-controller",
        action="store_true",
        help="Fail if controller :8432/health is not OK (default: warn only)",
    )
    args = p.parse_args()

    s = get_settings()
    base = (s.vllm_base_url or "").rstrip("/")
    print("project_root:", s.project_root, flush=True)
    wsl = (os.environ.get("VLLM_USE_WSL2_HOST") or "").strip().lower() in ("1", "true", "yes", "on")
    if wsl:
        print("VLLM_USE_WSL2_HOST: on (127.0.0.1 may be rewritten to Windows host IP)", flush=True)
    print("VLLM_BASE_URL:", base, flush=True)
    print("VLLM_MODEL_NAME:", s.vllm_model_name, flush=True)

    hdrs = {"Authorization": f"Bearer {s.vllm_api_key}"}
    try:
        r = httpx.get(f"{base}/models", headers=hdrs, timeout=15.0)
        r.raise_for_status()
        payload = r.json()
        ids = [m.get("id", "") for m in payload.get("data", [])]
        print("GET /v1/models: OK —", len(ids), "model(s)", flush=True)
        for mid in ids[:16]:
            print("  -", mid, flush=True)
        if s.vllm_model_name not in ids:
            print(
                "ERROR: VLLM_MODEL_NAME not in /models — set it to an exact id from the list above.",
                file=sys.stderr,
            )
            return 2
    except Exception as exc:
        print("GET /v1/models: FAILED —", exc, file=sys.stderr)
        print(
            "\nStart vLLM (Qwen3.6-27B AWQ/Marlin) on the host/port in VLLM_BASE_URL. "
            "If vLLM runs on Windows: vLLM --host 0.0.0.0, set VLLM_USE_WSL2_HOST=1, "
            "and allow TCP through Windows Firewall. See prompt2dataset/.env.example.",
            file=sys.stderr,
        )
        return 1

    ctrl = _controller_url()
    try:
        cr = httpx.get(f"{ctrl}/health", timeout=3.0)
        cr.raise_for_status()
        print("controller:", ctrl, "health OK", flush=True)
    except Exception as exc:
        msg = f"controller {ctrl}/health: skip ({exc})"
        if args.strict_controller:
            print("ERROR:", msg, file=sys.stderr)
            return 3
        print(msg, flush=True)

    print("check_stack_ready: OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
