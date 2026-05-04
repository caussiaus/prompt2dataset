"""Satellite Worker Client — the protocol a satellite device speaks.

Copy this file to any satellite (Mac, cloud node, Windows Thomas arm).
The satellite:
  1. Calls /workers/register → receives worker_id + token
  2. Polls /jobs/lease every N seconds → receives TaskSpec
  3. Executes the task (browser + optional GPU model)
  4. Streams events to /jobs/{id}/events
  5. Uploads artifacts to /jobs/{id}/artifact
  6. Calls /jobs/{id}/complete or /fail

The satellite never connects to other satellites or to the planner.
It only speaks to the orchestrator.

Usage (on the satellite machine) — set the orchestrator host via env, never hardcode:

    ORCHESTRATOR_URL=http://10.10.0.1:8990 \\
    ORCHESTRATOR_SECRET=orchestrator-dev-secret \\
    python connectors/satellite_client.py --name "mac-arm-1" --gpu

Or compose: ORCHESTRATOR_HOST + ORCHESTRATOR_PORT (see connectors/network_settings.py).

Or set HAS_LOCAL_MODEL and LOCAL_MODEL_NAME if the satellite runs a VLM.
"""
from __future__ import annotations

import argparse
import logging
import os
import time
import uuid
from typing import Any

import httpx

from prompt2dataset.connectors.network_settings import resolve_orchestrator_url

logger = logging.getLogger(__name__)

_ORCHESTRATOR_URL = resolve_orchestrator_url()
_POLL_INTERVAL_S  = int(os.environ.get("LEASE_POLL_INTERVAL_S", "5"))


class SatelliteWorker:
    """Minimal satellite worker that speaks the orchestrator lease protocol."""

    def __init__(
        self,
        name: str,
        orchestrator_url: str = _ORCHESTRATOR_URL,
        has_gpu: bool = False,
        gpu_vram_gb: float = 0.0,
        has_local_model: bool = False,
        local_model_name: str = "",
        network: str = "direct",
        browser: str = "chromium",
        tenant_id: str = "default",
        max_concurrent_tabs: int = 1,
    ):
        self.name = name
        self.base = orchestrator_url.rstrip("/")
        self.worker_id: str = ""
        self.token: str = ""
        self.poll_interval: int = _POLL_INTERVAL_S
        self.capabilities = {
            "browser": browser,
            "has_gpu": has_gpu,
            "gpu_vram_gb": gpu_vram_gb,
            "has_local_model": has_local_model,
            "local_model_name": local_model_name,
            "network": network,
            "os": _detect_os(),
            "max_concurrent_tabs": max_concurrent_tabs,
            "tenant_id": tenant_id,
        }
        self._client = httpx.Client(timeout=30)

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self) -> bool:
        """Register with the orchestrator. Returns True on success."""
        try:
            r = self._client.post(
                f"{self.base}/workers/register",
                json={
                    "worker_name": self.name,
                    "capabilities": self.capabilities,
                },
            )
            r.raise_for_status()
            data = r.json()
            self.worker_id = data["worker_id"]
            self.token = data["token"]
            self.poll_interval = data.get("lease_poll_interval_s", _POLL_INTERVAL_S)
            logger.info("registered as worker %s", self.worker_id)
            return True
        except Exception as exc:
            logger.error("registration failed: %s", exc)
            return False

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    def heartbeat(self) -> None:
        payload = {
            "cpu_pct":          _cpu_pct(),
            "ram_free_gb":      _ram_free_gb(),
            "gpu_load_pct":     _gpu_load_pct() if self.capabilities["has_gpu"] else 0.0,
            "browser_slots_free": 1,
            "outbound_ip":      "",
            "browser_health":   "ok",
        }
        try:
            self._client.post(
                f"{self.base}/workers/{self.worker_id}/heartbeat",
                json=payload,
                headers=self._auth(),
            )
        except Exception as exc:
            logger.debug("heartbeat failed: %s", exc)

    # ── Lease poll ────────────────────────────────────────────────────────────

    def poll_for_job(self) -> dict | None:
        """Request the next eligible job. Returns job status dict or None."""
        try:
            r = self._client.get(
                f"{self.base}/jobs/lease",
                headers=self._auth(),
                timeout=10,
            )
            if r.status_code == 200 and r.json():
                return r.json()
        except Exception as exc:
            logger.debug("lease poll failed: %s", exc)
        return None

    # ── Event streaming ───────────────────────────────────────────────────────

    def send_event(self, job_id: str, event_type: str, message: str = "", url: str = "") -> None:
        try:
            self._client.post(
                f"{self.base}/jobs/{job_id}/events",
                json={"event_type": event_type, "message": message, "url": url},
                headers=self._auth(),
            )
        except Exception as exc:
            logger.debug("send_event failed: %s", exc)

    # ── Artifact upload ───────────────────────────────────────────────────────

    def upload_artifact(self, job_id: str, artifact_type: str, local_path: str) -> None:
        import os as _os
        try:
            size = _os.path.getsize(local_path) if _os.path.exists(local_path) else 0
            self._client.post(
                f"{self.base}/jobs/{job_id}/artifact",
                json={"artifact_type": artifact_type, "local_path": local_path, "size_bytes": size},
                headers=self._auth(),
            )
        except Exception as exc:
            logger.debug("upload_artifact failed: %s", exc)

    # ── Completion / failure ──────────────────────────────────────────────────

    def complete(self, job_id: str, result: dict, artifacts: list[dict] | None = None) -> None:
        try:
            self._client.post(
                f"{self.base}/jobs/{job_id}/complete",
                json={"result": result, "artifacts": artifacts or []},
                headers=self._auth(),
            )
            logger.info("job %s completed", job_id)
        except Exception as exc:
            logger.error("complete failed: %s", exc)

    def fail(
        self,
        job_id: str,
        error_class: str,
        error_message: str,
        retry_eligible: bool = True,
    ) -> None:
        try:
            self._client.post(
                f"{self.base}/jobs/{job_id}/fail",
                json={
                    "error_class": error_class,
                    "error_message": error_message,
                    "retry_eligible": retry_eligible,
                },
                headers=self._auth(),
            )
            logger.warning("job %s failed: %s — %s", job_id, error_class, error_message[:80])
        except Exception as exc:
            logger.error("fail RPC failed: %s", exc)

    # ── Task execution stub (override in satellite implementations) ───────────

    def execute_task(self, job_status: dict) -> dict:
        """Execute a leased task. Override this in your satellite.

        Receives the full JobStatus dict (which includes spec.context, spec.task_description,
        spec.output_dir, spec.extraction_schema etc.).

        Returns a result dict matching the extraction_schema.
        Raises on unrecoverable failure.

        Default stub: demonstrates the event + artifact flow.
        """
        job_id   = job_status["job_id"]
        spec     = job_status  # job_status contains the TaskSpec fields flattened
        task_desc = spec.get("task_description", "")
        out_dir  = spec.get("output_dir", "/tmp")

        self.send_event(job_id, "navigation_started", task_desc[:120])

        # ── YOUR BROWSER / GPU LOGIC HERE ─────────────────────────────────────
        # For the Thomas arm:  call camoufox_bridge_server.py RPC
        # For the Mac arm:     drive Playwright or camoufox
        # For GPU tasks:       run local model inference
        # ──────────────────────────────────────────────────────────────────────

        # Stub: return empty result (replace with real extraction)
        self.send_event(job_id, "extraction_complete", "stub complete")
        return {"status": "stub", "files": []}

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the worker loop: register → poll → execute → report."""
        if not self.register():
            logger.error("Could not register — check orchestrator URL and network")
            return

        hb_interval = 10
        last_hb = 0.0

        logger.info("worker loop started — polling every %ds", self.poll_interval)
        while True:
            now = time.monotonic()
            if now - last_hb >= hb_interval:
                self.heartbeat()
                last_hb = now

            job = self.poll_for_job()
            if job:
                job_id = job["job_id"]
                logger.info("leased job %s", job_id)
                try:
                    result = self.execute_task(job)
                    self.complete(job_id, result)
                except Exception as exc:
                    logger.exception("job %s raised: %s", job_id, exc)
                    self.fail(job_id, "unknown", str(exc)[:300], retry_eligible=True)
            else:
                time.sleep(self.poll_interval)

    # ── Auth header ───────────────────────────────────────────────────────────

    def _auth(self) -> dict[str, str]:
        return {"x-worker-token": self.token, "x-worker-id": self.worker_id}


# ── System telemetry helpers ──────────────────────────────────────────────────

def _detect_os() -> str:
    import sys
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return "linux"


def _cpu_pct() -> float:
    try:
        import psutil
        return psutil.cpu_percent(interval=0.1)
    except ImportError:
        return 0.0


def _ram_free_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().available / 1e9
    except ImportError:
        return 0.0


def _gpu_load_pct() -> float:
    try:
        import subprocess
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            timeout=2,
        ).decode().strip()
        return float(out.split("\n")[0])
    except Exception:
        return 0.0


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    ap = argparse.ArgumentParser(description="Satellite worker for the scrape fleet.")
    ap.add_argument("--name", default="satellite-1", help="Worker name")
    ap.add_argument(
        "--orchestrator",
        default=resolve_orchestrator_url(),
        help="Orchestrator base URL (overrides ORCHESTRATOR_URL / ORCHESTRATOR_HOST+PORT)",
    )
    ap.add_argument("--gpu", action="store_true", help="Advertise GPU capability")
    ap.add_argument("--gpu-vram", type=float, default=0.0, help="GPU VRAM in GB")
    ap.add_argument("--local-model", default="", help="Local model name (e.g. facebook/sam-vit-huge)")
    ap.add_argument("--network", default="direct", choices=["direct", "proxy", "residential"])
    ap.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"])
    ap.add_argument("--tenant", default="default", help="Tenant ID for multi-tenant isolation")
    args = ap.parse_args()

    worker = SatelliteWorker(
        name=args.name,
        orchestrator_url=args.orchestrator,
        has_gpu=args.gpu,
        gpu_vram_gb=args.gpu_vram,
        has_local_model=bool(args.local_model),
        local_model_name=args.local_model,
        network=args.network,
        browser=args.browser,
        tenant_id=args.tenant,
    )
    worker.run()
