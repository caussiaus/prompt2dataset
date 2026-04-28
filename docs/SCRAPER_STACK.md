# prompt2dataset ↔ scrape-arm (operational contract)

Two **separate Git repositories**:

| Repo | Role |
|------|------|
| **`https://github.com/caussiaus/prompt2dataset`** | LangGraph / Streamlit / Docling / extraction — **this** tree |
| **`https://github.com/caussiaus/scrape-arm`** | Camoufox, browser agent **:8886**, scrape API **:9000**, bridge **:8887**, Searx **:8888** |

There is **no** Python import dependency from prompt2dataset into scrape-arm source. Integration is **HTTP + env vars** only (`connectors.scrape_arm_bridge`, `connectors.network_settings`).

## WSL layout (recommended)

1. **`~/scrape-arm`** — git clone of **scrape-arm**; `.env`, `venv-wsl/`, `start_all.sh`, runtime `data/`.
2. **`…/ISF-PEECEE/prompt2dataset`** (or a future **`~/prompt2dataset`** clone) — git clone of **prompt2dataset**; `.env` with `VLLM_*` and optional `SCRAPE_ARM_*`.

Start order: **vLLM** (gpu-stack) → **scrape-arm** (`start_all.sh`) → **Streamlit** / pipelines in prompt2dataset. See monorepo **`LOCAL-SERVICES.md`**.

## Env alignment

Copy **`SCRAPE_ARM_*`** and agent/bridge tokens from **`~/scrape-arm/.env`** into **`prompt2dataset/.env`** (or rely on `127.0.0.1` defaults when both stacks run on the same WSL host).

Set **`SCRAPER_BROWSER_AUTOMATION_ENABLED=1`** only when this process should drive headed Camoufox; keep **`0`** for scheduled / batch extraction.

## GitHub hygiene

- **`prompt2dataset/.gitignore`** includes **`data/`** so local PDFs/corpora are **not** pushed.
- Large vault outputs should use **`PIPELINE_OUTPUT_BASE_DIR`** under **`~/library/`** (see `.env.example`).

## VPS agents

Clone **both** repos on the VPS for code work. **Running** Camoufox still targets **WSL** (SSH/tailnet) unless you intentionally port the stack.

## Maintainer: push from ISF-PEECEE monorepo

From **`ISF-PEECEE`** root (script lives in the monorepo, not inside this package):

```bash
bash scripts/prompt2dataset/publish-to-github.sh
# Replace remote main entirely:
# TAKEOVER=1 bash scripts/prompt2dataset/publish-to-github.sh
```
