"""Scrape Arm Bridge — HTTP client to the browser automation arm (Camoufox stack).

**Casey WSL:** run services from **`~/scrape-arm`** (``bash ~/scrape-arm/start_all.sh default``).
This package does not ship scrape-arm source — only HTTP. Configure ``.env`` here with
``SCRAPE_ARM_HOST`` / ``SCRAPE_ARM_*_URL`` / tokens so they match **scrape-arm**'s ``.env``.

**Thomas / Windows-hosted stack:** use ``SCRAPE_ARM_HOST`` = Windows LAN IP when ``127.0.0.1``
does not reach the bridge from WSL.

Services (default instance):
  :9000  scrape_api_server.py    — cache, crawl, fetch, SearxNG proxy
  :8886  browser_agent_server.py — autonomous multi-step browser tasks
  :8887  camoufox_bridge_server.py — single-action RPC (navigate, click, screenshot)

Usage:
    bridge = ScrapeArmBridge()
    if bridge.health_check().get("ok"):
        result = bridge.browser_task(
            "Download the 2024 Annual MD&A for Canadian Natural Resources from SEDAR",
            context={"sedar_profile_number": "000025609", "doc_type": "Annual MD&A"}
        )
        print(result)

Acquisition jobs are written to output/acquisition_jobs.jsonl so future requests
can skip already-downloaded documents.

Environment (see scrape_arm_policy.py):
  SCRAPER_BROWSER_AUTOMATION_ENABLED=1 — required to call browser agent / headed fetch.
  SCRAPE_ARM_DISABLED=1 — block all Thomas HTTP calls from this process.
"""
from __future__ import annotations

import datetime
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from prompt2dataset.connectors.network_settings import resolve_scrape_arm_urls
from prompt2dataset.connectors.scrape_arm_policy import browser_automation_enabled, scrape_arm_disabled

logger = logging.getLogger(__name__)

_BLOCKED_BROWSER = {
    "ok": False,
    "error": (
        "SCRAPER_BROWSER_AUTOMATION_ENABLED is not set (browser automation disabled by default). "
        "Set SCRAPER_BROWSER_AUTOMATION_ENABLED=1 only for interactive acquisition. "
        "Overnight runs should keep this unset."
    ),
}

_SCRAPE_ARM_OFF = {
    "ok": False,
    "error": "SCRAPE_ARM_DISABLED=1 — scrape arm calls are disabled in this process.",
}

_ROOT = Path(__file__).resolve().parents[1]
_JOBS_FILE = _ROOT / "output" / "acquisition_jobs.jsonl"


# ── Token defaults (URLs come from resolve_scrape_arm_urls() at init time) ─

_DEFAULT_TOKEN = "scrape-token"
_DEFAULT_AGENT_TOKEN = "scrape-agent"
_DEFAULT_BRIDGE_TOKEN = "camoufox-bridge"


class ScrapeArmBridge:
    """HTTP client to the Thomas arm services.

    All methods are synchronous. Use httpx for connection timeouts — the arm
    can be slow when navigating SEDAR pages or solving CAPTCHAs.
    """

    def __init__(
        self,
        api_url: str | None = None,
        agent_url: str | None = None,
        bridge_url: str | None = None,
        api_token: str | None = None,
        agent_token: str | None = None,
        bridge_token: str | None = None,
        timeout: float = 30.0,
    ):
        import os

        u = resolve_scrape_arm_urls()
        self.api_url = (api_url or u["api_url"]).rstrip("/")
        self.agent_url = (agent_url or u["agent_url"]).rstrip("/")
        self.bridge_url = (bridge_url or u["bridge_url"]).rstrip("/")
        if api_token is None:
            api_token = os.environ.get("SCRAPE_ARM_TOKEN", _DEFAULT_TOKEN)
        if agent_token is None:
            agent_token = os.environ.get("SCRAPE_ARM_AGENT_TOKEN", _DEFAULT_AGENT_TOKEN)
        if bridge_token is None:
            bridge_token = os.environ.get("SCRAPE_ARM_BRIDGE_TOKEN", _DEFAULT_BRIDGE_TOKEN)
        self._api_headers = {"X-Api-Token": api_token}
        self._agent_headers = {"X-Agent-Token": agent_token}
        self._bridge_headers = {
            "X-Bridge-Token": bridge_token,
            "Authorization": f"Bearer {bridge_token}",
        }
        self.timeout = timeout

    def _api(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        import httpx
        if scrape_arm_disabled():
            return dict(_SCRAPE_ARM_OFF)
        url = f"{self.api_url}{path}"
        try:
            r = httpx.request(method, url, headers=self._api_headers,
                              timeout=self.timeout, **kwargs)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            logger.warning("scrape_arm API %s %s failed: %s", method, path, exc)
            return {"ok": False, "error": str(exc)}

    def _agent(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        import httpx
        if scrape_arm_disabled():
            return dict(_SCRAPE_ARM_OFF)
        if not browser_automation_enabled():
            return dict(_BLOCKED_BROWSER)
        url = f"{self.agent_url}{path}"
        try:
            r = httpx.request(method, url, headers=self._agent_headers,
                              timeout=self.timeout, **kwargs)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            logger.warning("scrape_arm agent %s %s failed: %s", method, path, exc)
            return {"ok": False, "error": str(exc)}

    def camoufox_rpc(
        self,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """POST to Camoufox bridge ``/rpc`` (navigate, text, links, click_*, screenshot, …).

        Uses ``X-Bridge-Token`` and ``bridge_url`` (default port 8887). Requires
        ``SCRAPER_BROWSER_AUTOMATION_ENABLED=1`` (see :mod:`connectors.scrape_arm_policy`).
        """
        import httpx

        if scrape_arm_disabled():
            return dict(_SCRAPE_ARM_OFF)
        if not browser_automation_enabled():
            return dict(_BLOCKED_BROWSER)
        url = f"{self.bridge_url}/rpc"
        t = self.timeout if timeout is None else timeout
        try:
            # Short connect timeout so a dead host does not block for the full read budget.
            connect_cap = min(15.0, float(t))
            timeout_spec = httpx.Timeout(
                connect=connect_cap,
                read=float(t),
                write=connect_cap,
                pool=connect_cap,
            )
            r = httpx.post(
                url,
                headers=self._bridge_headers,
                json=payload,
                timeout=timeout_spec,
            )
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            logger.warning("scrape_arm bridge POST /rpc failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    # ── Health ────────────────────────────────────────────────────────────────

    def health_check(self) -> dict[str, Any]:
        """Check if the scrape arm is up. Returns {"ok": true, "bridge_ready": ...}."""
        return self._api("GET", "/health")

    def is_available(self) -> bool:
        """Quick boolean availability check."""
        return bool(self.health_check().get("ok"))

    # ── Document fetch (cache-first) ─────────────────────────────────────────

    def fetch_url(self, url: str, use_bridge: bool = False) -> dict[str, Any]:
        """Fetch a URL via the scrape API (cache-first, optional headed browser).

        Returns {"ok": true, "content": "...", "cached": true/false}.
        """
        if use_bridge and not browser_automation_enabled():
            return dict(_BLOCKED_BROWSER)
        return self._api("POST", "/fetch", json={"url": url, "use_bridge": use_bridge})

    # ── Search ────────────────────────────────────────────────────────────────

    def search(self, query: str, use_bridge: bool = False) -> list[dict[str, Any]]:
        """Search via SearxNG proxy. Returns list of result dicts."""
        if use_bridge and not browser_automation_enabled():
            return []
        result = self._api("POST", "/searxng/search",
                           json={"query": query, "use_bridge": use_bridge})
        return result.get("results", []) if isinstance(result, dict) else []

    # ── Browser agent (multi-step autonomous task) ────────────────────────────

    def browser_task(
        self,
        task: str,
        context: dict[str, Any] | None = None,
        max_iters: int = 30,
        agent_timeout: float = 300.0,
    ) -> dict[str, Any]:
        """Send a natural-language task to the browser agent.

        The browser agent (port 8886) controls Camoufox autonomously.
        Returns {"ok": true, "result": "...", "steps": [...]} or {"ok": false, "error": ...}.

        context: optional structured data injected into the task prompt
                 (e.g. sedar_profile_number, doc_type, output_dir).
        """
        if not browser_automation_enabled():
            return dict(_BLOCKED_BROWSER)
        payload: dict[str, Any] = {"task": task, "max_iters": max_iters}
        if context:
            # Embed context into the task description as a structured suffix
            ctx_lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
            payload["task"] = f"{task}\n\nContext:\n{ctx_lines}"

        old_timeout = self.timeout
        self.timeout = agent_timeout
        try:
            result = self._agent("POST", "/task", json=payload)
        finally:
            self.timeout = old_timeout
        return result

    # ── Document acquisition ──────────────────────────────────────────────────

    def acquire_document(
        self,
        entity_name: str,
        profile_number: str,
        doc_type: str,
        date_range: tuple[int, int],
        output_dir: str,
    ) -> dict[str, Any]:
        """Acquire a document from SEDAR for one entity.

        Builds a structured task description from the KG checkpoint spec for SEDAR
        and sends it to the browser agent.  Returns job dict with status/local_path.
        """
        if not browser_automation_enabled():
            jid = uuid.uuid4().hex[:10]
            failed: dict[str, Any] = {
                "job_id": jid,
                "entity": entity_name,
                "profile_number": profile_number,
                "doc_type": doc_type,
                "date_range": list(date_range),
                "output_dir": output_dir,
                "status": "failed",
                "local_path": None,
                "error": _BLOCKED_BROWSER["error"],
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            _append_job(failed)
            return failed
        year_from, year_to = date_range
        task = (
            f"Navigate to SEDAR (sedar.com) and download the {doc_type} "
            f"for {entity_name} (SEDAR profile number {profile_number}) "
            f"for years {year_from} to {year_to}. "
            f"Save all downloaded PDFs to: {output_dir}. "
            f"Return the list of downloaded file paths."
        )
        context = {
            "entity":         entity_name,
            "profile_number": profile_number,
            "doc_type":       doc_type,
            "year_from":      year_from,
            "year_to":        year_to,
            "output_dir":     output_dir,
            "site":           "sedar.com",
        }

        job_id = uuid.uuid4().hex[:10]
        job: dict[str, Any] = {
            "job_id":      job_id,
            "entity":      entity_name,
            "profile_number": profile_number,
            "doc_type":    doc_type,
            "date_range":  list(date_range),
            "output_dir":  output_dir,
            "status":      "running",
            "local_path":  None,
            "error":       None,
            "created_at":  datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "completed_at": None,
        }
        _append_job(job)

        try:
            result = self.browser_task(task, context=context, agent_timeout=360.0)
            success = result.get("ok", False)
            job.update({
                "status":       "complete" if success else "failed",
                "local_path":   result.get("result"),
                "error":        result.get("error"),
                "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            })
        except Exception as exc:
            job.update({
                "status":       "failed",
                "error":        str(exc),
                "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            })

        _append_job(job)  # append updated record (both pending and final exist in log)
        return job


# ── Job log helpers ───────────────────────────────────────────────────────────

def _append_job(job: dict[str, Any]) -> None:
    """Append a job record to the JSONL acquisition log."""
    _JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _JOBS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(job, default=str) + "\n")


def load_acquisition_jobs(
    status_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Load acquisition jobs from the JSONL log.

    Returns the LAST record per job_id (so updates overwrite initial records).
    Optionally filter by status ("complete", "failed", "running").
    """
    if not _JOBS_FILE.exists():
        return []

    jobs_by_id: dict[str, dict] = {}
    try:
        for line in _JOBS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            job = json.loads(line)
            jobs_by_id[job["job_id"]] = job
    except Exception as exc:
        logger.warning("load_acquisition_jobs: %s", exc)
        return []

    jobs = list(jobs_by_id.values())
    if status_filter:
        jobs = [j for j in jobs if j.get("status") == status_filter]
    return sorted(jobs, key=lambda j: j.get("created_at", ""), reverse=True)


def check_already_acquired(
    entity_name: str,
    doc_type: str,
    year: int,
) -> dict[str, Any] | None:
    """Return the completed job record if this document is already acquired, else None."""
    for job in load_acquisition_jobs(status_filter="complete"):
        if (job.get("entity", "").lower() in entity_name.lower() and
                job.get("doc_type") == doc_type and
                job.get("date_range") and
                job["date_range"][0] <= year <= job["date_range"][1]):
            return job
    return None


# ── Singleton factory ─────────────────────────────────────────────────────────

_bridge: ScrapeArmBridge | None = None


def get_scrape_arm() -> ScrapeArmBridge:
    """Return the shared ScrapeArmBridge instance (lazy singleton)."""
    global _bridge
    if _bridge is None:
        u = resolve_scrape_arm_urls()
        _bridge = ScrapeArmBridge(
            api_url=u["api_url"],
            agent_url=u["agent_url"],
            bridge_url=u["bridge_url"],
        )
    return _bridge
