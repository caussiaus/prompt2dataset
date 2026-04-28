"""Central Orchestrator — control plane for the distributed scrape fleet.

Architecture role
─────────────────
  Planner → Orchestrator → Worker (satellite)

The planner (LLM + scope_node) emits typed job specs.
The orchestrator queues them, leases them to eligible workers, tracks state,
and returns artifacts.  Workers never talk to each other or to the planner.

Transport
─────────
  Same-network worker   → HTTP + Bearer token (no TLS required)
  Remote/external worker → same API, but behind a Cloudflare Tunnel or mTLS
                           overlay (the orchestrator only trusts signed tokens)

Usage
─────
  # In a separate tmux pane alongside Streamlit:
  uvicorn connectors.orchestrator_server:app --host 0.0.0.0 --port 8990

  Workers connect to http://<host>:8990 (local) or the tunnel URL (remote).

Worker protocol (8 messages)
─────────────────────────────
  POST /workers/register          → WorkerRegistration → WorkerCredential
  POST /workers/{id}/heartbeat    → HeartbeatPayload → OK
  GET  /jobs/lease                → LeaseResponse (204 = nothing queued)
  POST /jobs/{id}/events          → JobEvent → OK
  POST /jobs/{id}/artifact        → ArtifactRef → OK
  POST /jobs/{id}/complete        → CompletionPayload → OK
  POST /jobs/{id}/fail            → FailurePayload → OK
  GET  /jobs/{id}/status          → JobStatus (for UI polling)

Planner/UI protocol (3 messages)
─────────────────────────────────
  POST /jobs/submit               → TaskSpec → JobStatus
  GET  /jobs                      → list[JobStatus]
  GET  /jobs/{id}/artifacts       → list[ArtifactRef]
"""
from __future__ import annotations

import datetime
import logging
import os
import secrets
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]
_ARTIFACTS_DIR = _ROOT / "output" / "artifacts"
_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Auth ──────────────────────────────────────────────────────────────────────

_ORCHESTRATOR_SECRET = os.environ.get("ORCHESTRATOR_SECRET", "orchestrator-dev-secret")

# In production replace with per-worker signed JWTs.
# For same-network use, a shared secret is acceptable.
_worker_registry: dict[str, "WorkerRecord"] = {}  # worker_id → record
_job_queue: list[str] = []                          # ordered job_id list
_jobs: dict[str, "JobRecord"] = {}                  # job_id → record


def _require_worker_auth(x_worker_token: str = Header(...)) -> str:
    """Validate a worker token. Returns worker_id."""
    for wid, wr in _worker_registry.items():
        if wr.token == x_worker_token:
            return wid
    raise HTTPException(status_code=401, detail="Unknown or invalid worker token")


def _require_planner_auth(x_api_key: str = Header(...)) -> None:
    if x_api_key != _ORCHESTRATOR_SECRET:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ── Pydantic models (the typed message contract) ──────────────────────────────

class WorkerCapabilities(BaseModel):
    """Advertised worker capabilities — sent on registration."""
    browser: str = "chromium"          # chromium | firefox | webkit
    has_gpu: bool = False
    gpu_vram_gb: float = 0.0
    has_local_model: bool = False
    local_model_name: str = ""         # e.g. "facebook/sam-vit-huge"
    network: str = "direct"            # direct | proxy | residential
    os: str = "linux"                  # linux | windows | macos
    max_concurrent_tabs: int = 1
    tenant_id: str = "default"         # multi-tenant isolation tag


class WorkerRegistration(BaseModel):
    """Worker → Orchestrator on startup."""
    worker_name: str
    capabilities: WorkerCapabilities


class WorkerCredential(BaseModel):
    """Orchestrator → Worker after registration."""
    worker_id: str
    token: str
    lease_poll_interval_s: int = 5


class HeartbeatPayload(BaseModel):
    """Worker → Orchestrator every N seconds."""
    cpu_pct: float = 0.0
    ram_free_gb: float = 0.0
    gpu_load_pct: float = 0.0
    browser_slots_free: int = 1
    outbound_ip: str = ""
    browser_health: str = "ok"         # ok | degraded | error


class TaskSpec(BaseModel):
    """Planner → Orchestrator: one unit of work."""
    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    tenant_id: str = "default"
    # Target
    target_domains: list[str] = []
    target_url: str = ""               # direct URL if known
    # Capability requirements (orchestrator matches against worker registry)
    requires_gpu: bool = False
    requires_local_model: str = ""     # model name, or "" = any
    requires_network: str = "direct"   # direct | proxy | residential
    requires_browser: str = "chromium"
    # What to do
    task_description: str = ""         # natural language for the VLM
    extraction_schema: dict = Field(default_factory=dict)  # JSON schema for result
    context: dict = Field(default_factory=dict)  # KG checkpoint spec injected into task
    # Constraints
    max_retries: int = 2
    timeout_s: int = 300
    # Evidence contract
    requires_screenshot: bool = False
    requires_dom_snapshot: bool = False
    requires_pdf_download: bool = True
    output_dir: str = ""               # where worker should save files (absolute WSL path)
    success_criteria: str = ""         # what "done" looks like


class JobEvent(BaseModel):
    """Worker → Orchestrator: incremental progress."""
    event_type: Literal[
        "navigation_started", "page_loaded", "challenge_encountered",
        "extraction_started", "extraction_complete", "download_started",
        "download_complete", "error", "info",
    ]
    message: str = ""
    url: str = ""
    screenshot_ref: str = ""           # artifact key if screenshot was captured


class ArtifactRef(BaseModel):
    """Worker → Orchestrator: reference to a produced artifact."""
    artifact_type: Literal["pdf", "screenshot", "dom_snapshot", "json_result", "log"]
    local_path: str                    # absolute path on the worker machine
    size_bytes: int = 0
    checksum_md5: str = ""


class CompletionPayload(BaseModel):
    """Worker → Orchestrator: task finished successfully."""
    result: dict = Field(default_factory=dict)     # normalized extraction result
    artifacts: list[ArtifactRef] = []
    duration_s: float = 0.0


class FailurePayload(BaseModel):
    """Worker → Orchestrator: task failed."""
    error_class: Literal[
        "navigation_error", "captcha_unsolved", "login_required",
        "element_not_found", "timeout", "parse_error", "auth_error", "unknown",
    ]
    error_message: str
    retry_eligible: bool = True
    last_url: str = ""
    screenshot_ref: str = ""


class JobStatus(BaseModel):
    job_id: str
    task_id: str
    status: Literal["queued", "leased", "running", "complete", "failed", "cancelled"]
    worker_id: str = ""
    created_at: str = ""
    leased_at: str = ""
    completed_at: str = ""
    retry_count: int = 0
    error: str = ""
    result: dict = Field(default_factory=dict)
    artifacts: list[ArtifactRef] = []
    events: list[JobEvent] = []


# ── In-memory records ─────────────────────────────────────────────────────────

class WorkerRecord(BaseModel):
    worker_id: str
    worker_name: str
    token: str
    capabilities: WorkerCapabilities
    registered_at: str
    last_heartbeat: str = ""
    heartbeat: HeartbeatPayload = Field(default_factory=HeartbeatPayload)
    active_job_id: str = ""


class JobRecord(BaseModel):
    job_id: str
    spec: TaskSpec
    status: JobStatus


# ── FastAPI app ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Scrape Fleet Orchestrator",
    description="Control plane for the distributed browser scrape fleet.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Worker-facing endpoints ────────────────────────────────────────────────────

@app.post("/workers/register", response_model=WorkerCredential)
def register_worker(reg: WorkerRegistration) -> WorkerCredential:
    """Worker announces capabilities and receives an auth token.

    In production, validate against a pre-shared enrollment token or mTLS cert.
    Here we issue a short-lived random token.
    """
    worker_id = uuid.uuid4().hex[:10]
    token = secrets.token_hex(24)
    record = WorkerRecord(
        worker_id=worker_id,
        worker_name=reg.worker_name,
        token=token,
        capabilities=reg.capabilities,
        registered_at=_now(),
    )
    _worker_registry[worker_id] = record
    logger.info("worker registered: %s (%s) caps=%s", worker_id, reg.worker_name, reg.capabilities)
    return WorkerCredential(worker_id=worker_id, token=token)


@app.post("/workers/{worker_id}/heartbeat")
def worker_heartbeat(
    worker_id: str,
    payload: HeartbeatPayload,
    wid: str = Header(None, alias="x-worker-id"),
    x_worker_token: str = Header(...),
) -> dict:
    _require_worker_auth(x_worker_token)
    if worker_id not in _worker_registry:
        raise HTTPException(404, "Worker not found")
    wr = _worker_registry[worker_id]
    wr.last_heartbeat = _now()
    wr.heartbeat = payload
    return {"ok": True}


@app.get("/jobs/lease")
def lease_job(
    x_worker_token: str = Header(...),
) -> JobStatus | dict:
    """Worker polls for the next eligible job. Returns 204 if nothing queued."""
    worker_id = _require_worker_auth(x_worker_token)
    worker = _worker_registry[worker_id]

    for job_id in list(_job_queue):
        rec = _jobs.get(job_id)
        if not rec or rec.status.status != "queued":
            continue
        spec = rec.spec

        # Capability matching
        if spec.requires_gpu and not worker.capabilities.has_gpu:
            continue
        if spec.requires_local_model and spec.requires_local_model != worker.capabilities.local_model_name:
            continue
        if spec.requires_network != "direct" and spec.requires_network != worker.capabilities.network:
            continue
        if spec.tenant_id != "default" and spec.tenant_id != worker.capabilities.tenant_id:
            continue

        # Lease it
        _job_queue.remove(job_id)
        rec.status.status = "leased"
        rec.status.worker_id = worker_id
        rec.status.leased_at = _now()
        worker.active_job_id = job_id
        logger.info("job %s leased to worker %s", job_id, worker_id)
        return rec.status

    return {}  # 200 with empty body = nothing available


@app.post("/jobs/{job_id}/events")
def post_job_event(
    job_id: str,
    event: JobEvent,
    x_worker_token: str = Header(...),
) -> dict:
    _require_worker_auth(x_worker_token)
    rec = _jobs.get(job_id)
    if not rec:
        raise HTTPException(404, "Job not found")
    rec.status.events.append(event)
    rec.status.status = "running"
    logger.debug("job %s event: %s — %s", job_id, event.event_type, event.message[:80])
    return {"ok": True}


@app.post("/jobs/{job_id}/artifact")
def upload_artifact(
    job_id: str,
    artifact: ArtifactRef,
    x_worker_token: str = Header(...),
) -> dict:
    _require_worker_auth(x_worker_token)
    rec = _jobs.get(job_id)
    if not rec:
        raise HTTPException(404, "Job not found")
    rec.status.artifacts.append(artifact)
    return {"ok": True, "artifact_count": len(rec.status.artifacts)}


@app.post("/jobs/{job_id}/complete")
def complete_job(
    job_id: str,
    payload: CompletionPayload,
    x_worker_token: str = Header(...),
) -> dict:
    worker_id = _require_worker_auth(x_worker_token)
    rec = _jobs.get(job_id)
    if not rec:
        raise HTTPException(404, "Job not found")
    rec.status.status = "complete"
    rec.status.completed_at = _now()
    rec.status.result = payload.result
    rec.status.artifacts.extend(payload.artifacts)
    if worker_id in _worker_registry:
        _worker_registry[worker_id].active_job_id = ""
    logger.info("job %s complete — %d artifacts", job_id, len(rec.status.artifacts))
    return {"ok": True}


@app.post("/jobs/{job_id}/fail")
def fail_job(
    job_id: str,
    payload: FailurePayload,
    x_worker_token: str = Header(...),
) -> dict:
    worker_id = _require_worker_auth(x_worker_token)
    rec = _jobs.get(job_id)
    if not rec:
        raise HTTPException(404, "Job not found")

    retry_count = rec.status.retry_count
    max_retries = rec.spec.max_retries

    if payload.retry_eligible and retry_count < max_retries:
        rec.status.status = "queued"
        rec.status.retry_count += 1
        rec.status.worker_id = ""
        _job_queue.append(job_id)
        logger.info("job %s retry %d/%d — %s", job_id, retry_count + 1, max_retries, payload.error_class)
    else:
        rec.status.status = "failed"
        rec.status.error = f"{payload.error_class}: {payload.error_message}"
        rec.status.completed_at = _now()
        logger.warning("job %s failed: %s", job_id, payload.error_message[:120])

    if worker_id in _worker_registry:
        _worker_registry[worker_id].active_job_id = ""
    return {"ok": True, "retrying": rec.status.status == "queued"}


# ── Planner/UI-facing endpoints ────────────────────────────────────────────────

@app.post("/jobs/submit", response_model=JobStatus)
def submit_job(
    spec: TaskSpec,
    x_api_key: str = Header(...),
) -> JobStatus:
    """Planner submits a typed task spec. Returns initial JobStatus."""
    _require_planner_auth(x_api_key)
    job_id = uuid.uuid4().hex[:10]
    status = JobStatus(
        job_id=job_id,
        task_id=spec.task_id,
        status="queued",
        created_at=_now(),
    )
    rec = JobRecord(job_id=job_id, spec=spec, status=status)
    _jobs[job_id] = rec
    _job_queue.append(job_id)
    logger.info("job submitted: %s (task_id=%s)", job_id, spec.task_id)
    return status


@app.get("/jobs", response_model=list[JobStatus])
def list_jobs(
    tenant_id: str = Query(""),
    status: str = Query(""),
    x_api_key: str = Header(...),
) -> list[JobStatus]:
    _require_planner_auth(x_api_key)
    result = [r.status for r in _jobs.values()]
    if tenant_id:
        result = [j for j in result if _jobs[j.job_id].spec.tenant_id == tenant_id]
    if status:
        result = [j for j in result if j.status == status]
    return sorted(result, key=lambda j: j.created_at, reverse=True)


@app.get("/jobs/{job_id}/status", response_model=JobStatus)
def get_job_status(
    job_id: str,
    x_api_key: str = Header(...),
) -> JobStatus:
    _require_planner_auth(x_api_key)
    rec = _jobs.get(job_id)
    if not rec:
        raise HTTPException(404, "Job not found")
    return rec.status


@app.get("/jobs/{job_id}/artifacts", response_model=list[ArtifactRef])
def get_artifacts(
    job_id: str,
    x_api_key: str = Header(...),
) -> list[ArtifactRef]:
    _require_planner_auth(x_api_key)
    rec = _jobs.get(job_id)
    if not rec:
        raise HTTPException(404, "Job not found")
    return rec.status.artifacts


@app.get("/workers", response_model=list[dict])
def list_workers(x_api_key: str = Header(...)) -> list[dict]:
    _require_planner_auth(x_api_key)
    return [
        {
            "worker_id": w.worker_id,
            "worker_name": w.worker_name,
            "capabilities": w.capabilities.model_dump(),
            "last_heartbeat": w.last_heartbeat,
            "active_job": w.active_job_id,
        }
        for w in _worker_registry.values()
    ]


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "workers": len(_worker_registry),
        "queued_jobs": len(_job_queue),
        "total_jobs": len(_jobs),
    }


# ── Utilities ─────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
