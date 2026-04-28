# Autonomy loop (Claw ↔ vLLM — ISF-PEECEE)

**Purpose:** A single headless “tick” that (1) **respects the GPU controller**, (2) **reads** stigmergic sidecars (wonder queue, optional blackboard), and (3) **optionally** runs the **validation council** when it is safe to use the card for inference.

**Scope:** This is a **repo-wide** harness (systemd + `scripts/` + `state/`). The Python entrypoint lives under **`prompt2dataset/scripts/`** only because it imports **`prompt2dataset.*`** — autonomy is **not** owned exclusively by the `prompt2dataset/` subtree.

**Where things live (not “inside prompt2dataset” only):**

| Piece | Path |
|-------|------|
| systemd shell + logs | `ISF-PEECEE/scripts/autonomy-tick-once.sh`, `state/autonomy_last.json` |
| Python tick | `ISF-PEECEE/prompt2dataset/scripts/run_autonomy_cycle.py` |
| **Env load order** (in code) | **`ISF-PEECEE/.env`** first, then **`prompt2dataset/.env`**, then vLLM keys forced from `prompt2dataset/.env` file (`utils/config.py` → `ensure_hf_hub_env_for_process`) — must run **before** `argparse` reads defaults, so `CONTROLLER_BASE_URL` / `ISF_AUTONOMY_HTTP_TIMEOUT_SEC` in repo root `.env` work. |
| **vLLM server** | Not a Python import — process from **`ISF-PEECEE/gpu-stack/serve_vllm.sh`** (OpenAI API on `:8430`). Client URL + model id in **`prompt2dataset/.env`**. |

**Script:** `prompt2dataset/scripts/run_autonomy_cycle.py`  
**Installed loop (recommended):** user **systemd timer** — `bash scripts/install-autonomy-systemd.sh` (ticks every **5 min**; logs under `state/autonomy_loop.log` + `state/autonomy_last.json`). Optional env: copy `scripts/autonomy-loop.env.example` → `scripts/autonomy-loop.env` (e.g. set `ISF_AUTONOMY_RUN_ID` for `--log-event`). **Disable:** `systemctl --user disable --now isf-autonomy-tick.timer`. **Foreground loop (tmux):** `bash scripts/autonomy-loop-daemon.sh`.

**Dashboard:** start the Dataset Builder app (`streamlit run app.py` from `prompt2dataset/`) → sidebar **Autonomy** (`pages/01_🧠_Autonomy.py`) shows timer status, last JSON, log tail. Sidebar **Operator hub** (`pages/02_Operator_hub.py`) adds **Overview** metrics, **Scrape grid** (`streamlit.components.v1.iframe` → `grid_monitor.py`, default `http://127.0.0.1:7700/`), **Inputs** (custom `global_wonder` JSON, ad-hoc autonomy cycle), **Probes**, **Claw dispatch**, and a **Queue** table.

**Typical use (Claw, cron, or a watcher):**

```bash
cd /home/casey/ISF-PEECEE
# Snapshot JSON for agents (stdout) — exit 2 if controller is in training (back off)
python3 prompt2dataset/scripts/run_autonomy_cycle.py \
  --run-id YOUR_RUN_ID \
  --global-wonder \
  --log-event \
  --json-out
```

One-shot wrapper (same as timer): `bash scripts/autonomy-tick-once.sh`

**Global stigmergic queue (Claw PM):** `state/wonder_queue.jsonl` — CLI `scripts/wonder_queue_cli.py`, module `prompt2dataset.utils.global_wonder_queue`. Claw instructions: `prompts/WONDER_ORCHESTRATOR.md`.

## Resource policy (do not starve training)

- **Controller:** `CONTROLLER_BASE_URL` (default `http://127.0.0.1:8432`) — `GET /health` and `GET /status`.
- If `/status` reports **training** (`mode` contains `train` / `training`):
  - The cycle sets **`deferred: true`**, **skips** `--council` (unless `--force-council-on-training`), and **exits with code 2** so automation backs off.
- **Codegen / heavy work** for Tier-1 engineering still goes through the controller pattern in `.cursor/rules/compute-interface.mdc` (`/codegen`, `/request-training`, etc.); this script is for **orchestrating** Tier-2 reads and optional council.

## What gets wired in

| Piece | Code | Role in this tick |
|-------|------|-------------------|
| Wonder queue | `utils/wonder_queue.py` | Reads `wonder_queue.jsonl` for `--run-id` (with optional `--datasets-export-dir` for path resolution). |
| Epistemic blackboard | `utils/epistemic_blackboard.py` | Optional `--blackboard-json` path: counts normalized docs / field pressure. |
| Validation council | `dataset_graph/critique_council.py` | Optional `--council` + `--state-json` to a `DatasetState` export (GPU-heavy, skipped when deferred). |
| vLLM reachability | `utils/config` + `GET /v1/models` | Light probe using `VLLM_BASE_URL` from `prompt2dataset/.env`. |
| Audit | `training_events.py` | With `--log-event`, appends `event_type: autonomy_cycle` to `training_events.jsonl` for the run. |

## Optional: export `DatasetState` for council (advanced)

1. From the Streamlit app or a one-off script, write the current `ws_state` (or a minimal dict with `rows`, `proposed_columns`, and run metadata) to e.g. `/tmp/council_state.json`.
2. Run with `--council --state-json /tmp/council_state.json` when the controller is **not** training.

## Claw handoff

- Give Claw **read access** to `ISF-PEECEE` and `prompt2dataset/.env` (vLLM URL), not private SSH keys in-repo.
- Preferred command is **shell:** `python3 /home/casey/ISF-PEECEE/prompt2dataset/scripts/run_autonomy_cycle.py …` with `--json-out` for machine-readable output.
- **Exit codes:** `0` = ok; `2` = deferred (GPU in training) — treat as “try later,” not a hard failure.

## Related

- Stigmergic roadmap: `../project-outlines/prompt2dataset-stigmergic-roadmap.md`  
- Controller / codegen: `../.cursor/rules/compute-interface.mdc`, `../library/compute/AGENT-INTERFACE.md` (on this machine)  
- Local services: `../LOCAL-SERVICES.md`
