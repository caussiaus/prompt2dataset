#!/usr/bin/env python3
"""Load pipeline .env (via get_settings) and verify vLLM OpenAI-compat endpoint + model id.

Run from any cwd:
  python scripts/check_vllm.py
  python scripts/check_vllm.py --chat   # one minimal completion (costs tokens)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT.parent, _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import httpx

from prompt2dataset.utils.config import get_settings


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--chat", action="store_true", help="Send a tiny chat completion")
    args = p.parse_args()

    s = get_settings()
    base = (s.vllm_base_url or "").rstrip("/")
    print("project_root:", s.project_root, flush=True)
    if os.environ.get("VLLM_USE_WSL2_HOST", "").strip().lower() in ("1", "true", "yes", "on"):
        print("VLLM_USE_WSL2_HOST: on (WSL may rewrite 127.0.0.1 → Windows host)", flush=True)
    print("VLLM_BASE_URL:", base, flush=True)
    print("VLLM_MODEL_NAME:", s.vllm_model_name, flush=True)
    print("VLLM_API_KEY:", "(set)" if s.vllm_api_key and s.vllm_api_key != "EMPTY" else "EMPTY", flush=True)

    hdrs = {"Authorization": f"Bearer {s.vllm_api_key}"}
    try:
        r = httpx.get(f"{base}/models", headers=hdrs, timeout=8.0)
        r.raise_for_status()
        payload = r.json()
        ids = [m.get("id", "") for m in payload.get("data", [])]
        print("GET /v1/models: OK —", len(ids), "model(s)", flush=True)
        for mid in ids[:12]:
            print("  -", mid, flush=True)
        if s.vllm_model_name not in ids:
            print(
                "\n⚠ VLLM_MODEL_NAME is not in the list above — extraction will 404.\n"
                "  Set VLLM_MODEL_NAME in prompt2dataset/.env to an exact id from this list.",
                file=sys.stderr,
            )
            return 2
    except Exception as e:
        print("GET /v1/models: FAILED —", e, file=sys.stderr)
        print(
            "\nHints: vLLM must accept connections from WSL. If vLLM runs on Windows: "
            "use --host 0.0.0.0, set VLLM_USE_WSL2_HOST=1 in prompt2dataset/.env, and/or "
            "VLLM_WSL_HOST_IP=<Windows-LAN-IP>. Allow TCP 8430 in Windows Defender Firewall. "
            "If vLLM runs inside WSL, set VLLM_USE_WSL2_HOST=0.",
            file=sys.stderr,
        )
        return 1

    if args.chat:
        from openai import OpenAI

        client = OpenAI(base_url=base, api_key=s.vllm_api_key, timeout=120.0)
        try:
            cr = client.chat.completions.create(
                model=s.vllm_model_name,
                messages=[{"role": "user", "content": 'Reply with exactly: {"ok": true}'}],
                max_tokens=64,
                temperature=0.0,
            )
            txt = (cr.choices[0].message.content or "").strip()
            print("chat completion sample:", txt[:200], flush=True)
        except Exception as e:
            print("chat completion: FAILED —", e, file=sys.stderr)
            return 3

    print("check_vllm: all checks passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
