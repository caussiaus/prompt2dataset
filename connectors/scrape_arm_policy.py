"""Policy gates for Thomas scrape-arm calls from this repo.

Browser automation (Camoufox / browser_agent on :8886) is OFF by default so scheduled
jobs, accidental imports, or overnight agents cannot open a headed browser unless you
explicitly enable it.

Search and HTTP fetch via scrape_api (:9000) are separate; they remain available unless
you disable the whole bridge (see SCRAPE_ARM_DISABLED).

Env:
  SCRAPER_BROWSER_AUTOMATION_ENABLED — "1"/"true"/"yes" to allow browser_task, acquire_document,
    fetch_url(use_bridge=True), search(use_bridge=True). Default: disabled.
  SCRAPE_ARM_DISABLED — "1" to make get_scrape_arm() return a no-op bridge that refuses all calls.
"""
from __future__ import annotations

import os

_TRUE = frozenset({"1", "true", "yes", "on"})


def scrape_arm_disabled() -> bool:
    return os.environ.get("SCRAPE_ARM_DISABLED", "").strip().lower() in _TRUE


def browser_automation_enabled() -> bool:
    return os.environ.get("SCRAPER_BROWSER_AUTOMATION_ENABLED", "").strip().lower() in _TRUE
