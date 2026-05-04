"""Resolve connector base URLs from environment variables only.

No LAN, WireGuard, or WSL IPs belong in code. Set these in ``.env`` (or the
satellite's shell) per machine:

- **Orchestrator** (``satellite_client`` → PC running ``orchestrator_server``):

  - ``ORCHESTRATOR_URL`` — full base URL (wins over host/port), e.g.
    ``http://10.10.0.1:8990`` (WireGuard on Windows) or
    ``http://192.168.7.10:8990`` (LAN).
  - Or compose: ``ORCHESTRATOR_HOST``, ``ORCHESTRATOR_PORT`` (default ``8990``),
    optional ``ORCHESTRATOR_SCHEME`` (default ``http``).

- **Scrape arm** (HTTP only — this repo does **not** bundle scrape-arm code):

  - **Deployment (Casey WSL):** canonical checkout is **`~/scrape-arm`** — start with
    ``bash ~/scrape-arm/start_all.sh default``. Optional mirror: ``ISF-PEECEE/scrape-arm/``.
    :class:`connectors.scrape_arm_bridge.ScrapeArmBridge` is only an HTTP client.
    Align ``SCRAPE_ARM_*`` in **this** repo's ``.env`` with **scrape-arm**'s ports/tokens.
  - **Classic Thomas layout:** services on Windows with WSL hitting host IP — set
    ``SCRAPE_ARM_HOST`` to the Windows host when ``127.0.0.1`` does not reach Camoufox.
  - Per-service full URLs: ``SCRAPE_ARM_API_URL``, ``SCRAPE_ARM_AGENT_URL``,
    ``SCRAPE_ARM_BRIDGE_URL`` — each overrides that service only.
  - Or compose: ``SCRAPE_ARM_HOST`` (default ``127.0.0.1``; from classic WSL2 use the Windows host IP,
    not loopback, unless mirrored networking / portproxy makes localhost reach Windows),
    ``SCRAPE_ARM_SCHEME``, and optional ``SCRAPE_ARM_PORT_API`` (9000),
    ``SCRAPE_ARM_PORT_AGENT`` (8886), ``SCRAPE_ARM_PORT_BRIDGE`` (8887).

- **Obsidian Local REST API** (optional plugin):

  - ``OBSIDIAN_LOCAL_REST_HOST`` (default ``127.0.0.1``),
    ``OBSIDIAN_LOCAL_REST_PORT`` (default ``27123``).

- **SearXNG** (self-hosted metasearch on WSL/server — discovery layer for the orchestrator):

  - ``SEARXNG_INTERNAL_URL`` (default ``http://127.0.0.1:8888``) — base URL, no trailing
    slash issues handled in resolver. Prefer hosting SearXNG alongside the pipeline in WSL,
    not on the Mac satellite; see ``scripts/infra/searxng/README.txt``.

- **Thomas scrape-arm safety** (see ``connectors/scrape_arm_policy.py``):

  - ``SCRAPER_BROWSER_AUTOMATION_ENABLED`` — set to ``1`` only when this process should
    drive Camoufox (:8886). Default unset/false so scheduled runs do not open a browser.
  - ``SCRAPE_ARM_DISABLED`` — ``1`` to block all scrape_api/agent calls from this repo.

Windows forwards TCP from ``ListenAddress`` (WireGuard or LAN IP) to the
current WSL2 IPv4 — see ``scripts/windows/Set-WslPortProxy.ps1``.
"""
from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOTENV_LOADED = False


def _load_project_dotenv_once() -> None:
    """Load repo ``.env`` so ``SCRAPE_ARM_*`` match the Windows scrape-arm config (override=False)."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = _REPO_ROOT / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)


def resolve_orchestrator_url() -> str:
    """Base URL for the orchestrator API (no trailing slash)."""
    explicit = os.environ.get("ORCHESTRATOR_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    host = os.environ.get("ORCHESTRATOR_HOST", "127.0.0.1").strip()
    port = os.environ.get("ORCHESTRATOR_PORT", "8990").strip()
    scheme = os.environ.get("ORCHESTRATOR_SCHEME", "http").strip()
    return f"{scheme}://{host}:{port}"


def _scrape_one(
    env_url: str,
    port_env: str,
    default_port: int,
) -> str:
    full = os.environ.get(env_url, "").strip()
    if full:
        return full.rstrip("/")
    host = os.environ.get("SCRAPE_ARM_HOST", "127.0.0.1").strip()
    port = os.environ.get(port_env, str(default_port)).strip()
    scheme = os.environ.get("SCRAPE_ARM_SCHEME", "http").strip()
    return f"{scheme}://{host}:{port}"


def resolve_scrape_arm_urls() -> dict[str, str]:
    """api_url, agent_url, bridge_url for :class:`ScrapeArmBridge`."""
    _load_project_dotenv_once()
    return {
        "api_url": _scrape_one("SCRAPE_ARM_API_URL", "SCRAPE_ARM_PORT_API", 9000),
        "agent_url": _scrape_one("SCRAPE_ARM_AGENT_URL", "SCRAPE_ARM_PORT_AGENT", 8886),
        "bridge_url": _scrape_one("SCRAPE_ARM_BRIDGE_URL", "SCRAPE_ARM_PORT_BRIDGE", 8887),
    }


def resolve_obsidian_local_rest() -> tuple[str, int]:
    """Host and port for Obsidian local-rest-api plugin checks and DQL."""
    host = os.environ.get("OBSIDIAN_LOCAL_REST_HOST", "127.0.0.1").strip()
    port = int(os.environ.get("OBSIDIAN_LOCAL_REST_PORT", "27123").strip())
    return host, port


def resolve_searxng_internal_url() -> str:
    """Base URL for self-hosted SearXNG (discovery / orchestrator), no trailing slash."""
    return os.environ.get("SEARXNG_INTERNAL_URL", "http://127.0.0.1:8888").strip().rstrip("/")
