"""Streamlit — operator hub: metrics, inputs, scrape-arm grid embed, probes, dispatch.

Run: ``streamlit run app.py`` from ``prompt2dataset/`` (sidebar: **Operator hub**).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import streamlit as st

_APP = Path(__file__).resolve().parents[1]
_REPO = _APP.parent
for _p in (_REPO, _APP):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    import streamlit.components.v1 as components
except ImportError:  # pragma: no cover
    components = None  # type: ignore[misc, assignment]

from prompt2dataset.utils.operator_dashboard import (
    autonomy_last_path,
    autonomy_metric_cards,
    iso_mtime,
    load_json_object,
    pending_wonder_rows,
    run_repo_command,
    scrape_arm_probe_json,
    scrape_services_table,
    wonder_queue_path,
)


def _load_global_wonder_queue():
    path = _REPO / "prompt2dataset" / "utils" / "global_wonder_queue.py"
    spec = importlib.util.spec_from_file_location("_gwq_cp", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _python_exe() -> str:
    v = _REPO / ".venv" / "bin" / "python"
    return str(v) if v.is_file() else sys.executable


def _library_root() -> Path:
    return Path(os.environ.get("LIBRARY_DIR", Path.home() / "library")).expanduser().resolve()


st.set_page_config(page_title="Operator hub", page_icon="🛰️", layout="wide")

st.title("Operator hub")
st.caption(
    "Live **metrics**, **inputs** (wonder queue + ad-hoc autonomy), **embedded scrape-arm grid** "
    "(`grid_monitor.py`), stack **probes**, and Claw **dispatch**."
)

gwq_mod = None
try:
    gwq_mod = _load_global_wonder_queue()
except Exception as e:
    st.warning(f"Wonder queue module: {e}")

last_path = autonomy_last_path(_REPO)
wq_path = wonder_queue_path(_REPO)
autonomy_data = load_json_object(last_path)
cards = autonomy_metric_cards(autonomy_data)

tab_overview, tab_scrape, tab_inputs, tab_probes, tab_dispatch, tab_queue = st.tabs(
    ["Overview", "Scrape grid", "Inputs", "Probes", "Claw dispatch", "Queue"]
)

# ── Overview ───────────────────────────────────────────────────────────────
with tab_overview:
    st.subheader("Snapshot files")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("autonomy_last.json", "ok" if cards["has_snapshot"] else "missing")
        st.caption(iso_mtime(last_path) or "—")
    with c2:
        st.metric("global wonder pending", cards["gw_pending"] if cards["gw_pending"] is not None else "—")
    with c3:
        st.metric("vLLM /models", "OK" if cards["vllm_models_ok"] else ("fail" if cards["has_snapshot"] else "—"))
    with c4:
        st.metric("GPU deferred", "yes" if cards["deferred"] else ("no" if cards["has_snapshot"] else "—"))

    r1, r2, r3 = st.columns(3)
    with r1:
        st.metric("Controller health HTTP", cards["health_http"] if cards["health_http"] is not None else "—")
    with r2:
        st.metric("Controller status HTTP", cards["status_http"] if cards["status_http"] is not None else "—")
    with r3:
        st.metric("Per-run wonder loaded", cards["wq_run_loaded"] if cards["wq_run_loaded"] is not None else "—")

    st.markdown("**Controller** · mode / URL")
    st.write(
        {
            "controller_url": cards["controller_url"],
            "mode": cards["controller_mode"],
            "deferral_reason": cards["deferral_reason"],
        }
    )
    st.markdown("**vLLM (analyst client)**")
    st.write(
        {
            "base_url": cards["vllm_base"],
            "models_probe_ok": cards["vllm_models_ok"],
            "n_models": cards["vllm_n_models"],
            "error": cards["vllm_error"],
        }
    )

    if st.button("Refresh scrape-arm JSON probe", type="secondary"):
        with st.spinner("Probing scrape-arm…"):
            parsed, raw, rc = scrape_arm_probe_json(_REPO, timeout=90)
        st.session_state["scrape_arm_probe"] = {"parsed": parsed, "raw": raw, "rc": rc}

    probe = st.session_state.get("scrape_arm_probe")
    if probe:
        st.markdown("**Scrape-arm probe** (last refresh in this session)")
        p = probe.get("parsed")
        if isinstance(p, dict):
            st.write(
                {
                    "overall": p.get("overall"),
                    "probe_hosts": p.get("probe_hosts"),
                    "health_daemon": p.get("health_daemon"),
                }
            )
            rows = scrape_services_table(p)
            if rows:
                st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.caption(f"exit={probe.get('rc')} — stdout not JSON; see Probes tab")

    if autonomy_data and isinstance((autonomy_data.get("global_wonder_queue") or {}).get("pending_sample"), list):
        st.subheader("Global wonder — sample from last autonomy tick")
        samp = (autonomy_data.get("global_wonder_queue") or {})["pending_sample"] or []
        st.dataframe(pending_wonder_rows(samp, limit=30), use_container_width=True, hide_index=True)

    st.caption(f"`autonomy_last.json`: `{last_path}` · `wonder_queue.jsonl`: `{wq_path}`")

# ── Scrape grid (grid_monitor) ─────────────────────────────────────────────
with tab_scrape:
    st.markdown(
        "Embedded **grid_monitor** UI (live tiles + graph tab inside that app). "
        "Start the monitor from WSL, repo `scrape-arm/`:  \n"
        "`cd scrape-arm && python3 grid_monitor.py`  (port **7700** by default; env `GRID_MONITOR_PORT`)."
    )
    default_grid = (os.environ.get("GRID_MONITOR_URL") or "http://127.0.0.1:7700/").strip()
    grid_url = st.text_input("Grid monitor URL", value=default_grid, key="grid_monitor_url")
    grid_h = st.slider("Embed height (px)", min_value=400, max_value=1400, value=780, step=20)

    if components is not None:
        try:
            components.iframe(grid_url, height=int(grid_h), scrolling=True)
        except Exception as e:
            st.error(f"iframe failed: {e}")
            st.info("Use **Open in browser** below.")
    else:
        st.warning("streamlit.components not available; use open in browser.")

    st.link_button("Open grid in new tab", grid_url, use_container_width=False)

    st.divider()
    st.markdown("**Related ports** (see `scrape-arm/README.md`)")
    st.dataframe(
        [
            {"service": "SearxNG", "port": 8888},
            {"service": "Camoufox bridge", "port": 8887},
            {"service": "Scrape API", "port": 9000},
            {"service": "Browser agent", "port": 8886},
            {"service": "Grid monitor", "port": 7700},
        ],
        use_container_width=True,
        hide_index=True,
    )

# ── Inputs ───────────────────────────────────────────────────────────────────
with tab_inputs:
    st.markdown("### Library / vault hint")
    lib_override = st.text_input(
        "LIBRARY_DIR (optional, this session only)",
        value=os.environ.get("LIBRARY_DIR", ""),
        placeholder=str(Path.home() / "library"),
        help="Used for mandate path in dispatch handoff; does not change shell env for subprocesses unless set externally.",
    )
    lib = Path(lib_override).expanduser().resolve() if lib_override.strip() else _library_root()
    st.code(str(lib / "01-Projects" / "Mandates" / "mandate-queue.md"), language="text")

    st.markdown("### Append custom `global_wonder`")
    default_task = '{\n  "kind": "operator_note",\n  "title": "Short label",\n  "note": "What Tier-1 should do"\n}'
    custom_json = st.text_area("Task JSON object", value=default_task, height=160, key="custom_gw_json")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        c_pri = st.selectbox("Priority", ["normal", "high"], key="custom_pri")
    with col_b:
        c_run = st.text_input("run_id (optional)", "", key="custom_run")
    with col_c:
        c_src = st.text_input("source label", "streamlit_operator", key="custom_src")

    if st.button("Append to global wonder queue", type="primary", key="btn_append_custom"):
        if gwq_mod is None:
            st.error("Wonder queue not loaded.")
        else:
            try:
                task = json.loads(custom_json)
                if not isinstance(task, dict):
                    st.error("Task JSON must be an object {{ ... }}.")
                else:
                    eid = gwq_mod.append_global_wonder(
                        task,
                        priority=c_pri,
                        run_id=c_run.strip() or None,
                        source=c_src.strip() or "streamlit_operator",
                    )
                    st.success(f"Appended `{eid}`")
            except json.JSONDecodeError as e:
                st.error(f"Invalid JSON: {e}")

    st.divider()
    st.markdown("### Run autonomy cycle (stdout only)")
    st.caption(
        "Does **not** replace `state/autonomy_last.json` (that is the **systemd tick** script). "
        "Use this to experiment with flags and read JSON in the expander below."
    )
    ac_timeout = st.number_input("HTTP timeout (sec)", min_value=4.0, max_value=120.0, value=22.0, step=1.0)
    ac_run_id = st.text_input("run_id (optional)", "", key="ac_run")
    ac_gw = st.checkbox("--global-wonder", value=True, key="ac_gw")
    ac_skip_c = st.checkbox("--skip-controller", value=False)
    ac_skip_v = st.checkbox("--skip-vllm", value=False)
    ac_council = st.checkbox("--council (needs --state-json path)", value=False)
    ac_state = st.text_input("--state-json path", "", key="ac_state")
    ac_bb = st.text_input("--blackboard-json path (optional)", "", key="ac_bb")

    if st.button("Run run_autonomy_cycle.py", type="secondary"):
        exe = _python_exe()
        script = str(_REPO / "prompt2dataset" / "scripts" / "run_autonomy_cycle.py")
        parts = [exe, script, "--json-out", "--http-timeout", str(ac_timeout)]
        if ac_gw:
            parts.append("--global-wonder")
        if ac_skip_c:
            parts.append("--skip-controller")
        if ac_skip_v:
            parts.append("--skip-vllm")
        if ac_run_id.strip():
            parts += ["--run-id", ac_run_id.strip()]
        if ac_bb.strip():
            parts += ["--blackboard-json", ac_bb.strip()]
        if ac_council:
            parts.append("--council")
            if ac_state.strip():
                parts += ["--state-json", ac_state.strip()]
        env = {**os.environ}
        # Ensure prompt2dataset env resolution for child (same as tick)
        try:
            from prompt2dataset.utils.config import ensure_hf_hub_env_for_process

            ensure_hf_hub_env_for_process()
            env.update(os.environ)
        except Exception:
            pass
        st.code(shlex.join(parts), language="bash")
        try:
            r = run_repo_command(parts, _REPO, timeout=int(max(30, ac_timeout + 25)), env=env)
            st.session_state["last_adhoc_autonomy"] = {
                "stdout": r.stdout or "",
                "stderr": r.stderr or "",
                "rc": r.returncode,
            }
        except Exception as e:
            st.error(str(e))

    adhoc = st.session_state.get("last_adhoc_autonomy")
    if adhoc:
        st.metric("Exit code", adhoc.get("rc"))
        if adhoc.get("stderr"):
            with st.expander("stderr"):
                st.code(adhoc["stderr"][-8000:], language="")
        raw_out = (adhoc.get("stdout") or "").strip()
        with st.expander("stdout JSON", expanded=True):
            st.code(raw_out[:48000], language="json")
        try:
            st.json(json.loads(raw_out))
        except json.JSONDecodeError:
            pass

# ── Probes ─────────────────────────────────────────────────────────────────
with tab_probes:

    def _bash_script(rel: str, *args: str, timeout: int) -> subprocess.CompletedProcess[str]:
        return run_repo_command(["bash", str(_REPO / rel), *args], _REPO, timeout=timeout)

    st.markdown("Shell probes from repo root (`scripts/isf-health`).")
    c1, c2, c3 = st.columns(3)
    with c1:
        b_all = st.button("isf-health **all**", key="ph_all")
    with c2:
        b_gpu = st.button("isf-health gpu", key="ph_gpu")
    with c3:
        b_sj = st.button("scrape-json --json", key="ph_sj")

    if b_all:
        with st.spinner("isf-health all…"):
            r = _bash_script("scripts/isf-health", "all", timeout=120)
        st.session_state["last_isf_health"] = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        st.session_state["last_isf_health_rc"] = r.returncode
    if b_gpu:
        with st.spinner("isf-health gpu…"):
            r = _bash_script("scripts/isf-health", "gpu", timeout=60)
        st.session_state["last_isf_health"] = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        st.session_state["last_isf_health_rc"] = r.returncode
    if b_sj:
        with st.spinner("scrape-json…"):
            r = _bash_script("scripts/isf-health", "scrape-json", "--json", timeout=90)
        st.session_state["last_scrape_json"] = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        st.session_state["last_scrape_json_rc"] = r.returncode

    if "last_isf_health" in st.session_state:
        st.subheader(f"isf-health (exit {st.session_state.get('last_isf_health_rc', '?')})")
        st.code(st.session_state["last_isf_health"][-24000:] or "(empty)", language="")

    if "last_scrape_json" in st.session_state:
        st.subheader(f"scrape-json (exit {st.session_state.get('last_scrape_json_rc', '?')})")
        raw = st.session_state["last_scrape_json"][-24000:] or "(empty)"
        st.code(raw, language="json")
        try:
            st.json(json.loads(raw))
        except json.JSONDecodeError:
            st.caption("Not valid JSON as a single document.")

    st.divider()
    st.markdown("**vLLM batch smoke** — concurrent tiny chats (same path as extraction: `httpx` → `/v1/chat/completions`). Proves the model id matches `/models` and the card tolerates batched in-flight requests.")
    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        sm_conc = st.number_input("Concurrency", min_value=1, max_value=64, value=8, step=1, key="sm_conc")
    with bc2:
        sm_tot = st.number_input("Total requests", min_value=1, max_value=256, value=24, step=1, key="sm_tot")
    with bc3:
        sm_tok = st.number_input("max_tokens each", min_value=8, max_value=256, value=32, step=4, key="sm_tok")
    if st.button("Run vLLM batch smoke", type="primary", key="btn_vllm_smoke"):
        exe = _python_exe()
        script = str(_REPO / "prompt2dataset" / "scripts" / "vllm_batch_smoke.py")
        smoke_timeout = int(90 + sm_tot * (sm_tok / 8) + sm_conc * 15)
        smoke_timeout = min(900, max(120, smoke_timeout))
        parts = [
            exe,
            script,
            "--concurrency",
            str(int(sm_conc)),
            "--total",
            str(int(sm_tot)),
            "--max-tokens",
            str(int(sm_tok)),
            "--json-out",
        ]
        try:
            from prompt2dataset.utils.config import ensure_hf_hub_env_for_process

            ensure_hf_hub_env_for_process()
        except Exception:
            pass
        st.code(shlex.join(parts), language="bash")
        try:
            r = run_repo_command(parts, _REPO, timeout=smoke_timeout, env={**os.environ})
            st.session_state["last_vllm_smoke"] = {
                "stdout": r.stdout or "",
                "stderr": r.stderr or "",
                "rc": r.returncode,
            }
            if r.returncode != 0:
                st.warning(
                    f"vLLM smoke exited **{r.returncode}** (vLLM down, model id mismatch, or timeouts). "
                    "See stderr / raw stdout below."
                )
        except subprocess.TimeoutExpired:
            st.error(
                f"Operator hub killed the smoke subprocess after **{smoke_timeout}s**. "
                "Lower **Total requests** or **Concurrency**, or run: "
                f"`bash {_REPO}/scripts/vllm_batch_smoke.sh …` in a terminal."
            )
            st.session_state["last_vllm_smoke"] = {
                "stdout": "",
                "stderr": "TimeoutExpired (hub subprocess cap)",
                "rc": -9,
            }
        except Exception as e:
            st.error(str(e))
    sm = st.session_state.get("last_vllm_smoke")
    if sm:
        st.metric("Exit code", sm.get("rc"))
        if sm.get("stderr"):
            st.code(sm["stderr"][-4000:], language="")
        raw_out = (sm.get("stdout") or "").strip()
        if raw_out:
            try:
                st.json(json.loads(raw_out))
            except json.JSONDecodeError:
                st.code(raw_out[:12000], language="json")
        elif sm.get("rc") not in (0, None):
            st.caption("No stdout (process may have been killed or crashed before printing JSON).")

# ── Claw dispatch (preset) ─────────────────────────────────────────────────
with tab_dispatch:
    st.markdown(
        "Enqueue a preset **`operator_system_sweep`** for Tier-1 (Claw). "
        "See `prompts/WONDER_ORCHESTRATOR.md`."
    )
    pri = st.selectbox("Priority", ["normal", "high"], index=0, key="dispatch_pri")
    mandate_md = lib / "01-Projects" / "Mandates" / "mandate-queue.md"

    if st.button("Enqueue: system sweep + mandate triage", type="primary", key="dispatch_preset") and gwq_mod is not None:
        repo = str(_REPO.resolve())
        task = {
            "kind": "operator_system_sweep",
            "title": "Probe stack + triage mandate queue",
            "mandate_queue_path": str(mandate_md),
            "commands": [
                f"bash {repo}/scripts/isf-health all",
                f"bash {repo}/scripts/isf-health scrape-json --json",
                f"python3 {repo}/prompt2dataset/scripts/run_autonomy_cycle.py --json-out --global-wonder",
                f"python3 {repo}/scripts/wonder_queue_cli.py pending -n 30",
            ],
            "read_first": [
                f"{repo}/CLAUDE.md",
                f"{repo}/prompts/WONDER_ORCHESTRATOR.md",
                f"{repo}/prompts/ENGINEER_MANDATE.md",
                f"{repo}/.claude/agents/pm-orchestrator.md",
            ],
            "resolve_hint": "Resolve with wonder_queue_cli.py resolve when done.",
        }
        try:
            eid = gwq_mod.append_global_wonder(
                task,
                priority=pri,
                run_id="",
                source="streamlit_operator_hub",
            )
            st.success(f"Enqueued `{eid}`")
            st.session_state["last_dispatch_eid"] = eid
            st.session_state["last_dispatch_task"] = task
        except OSError as e:
            st.error(str(e))

    if st.button("Enqueue: vLLM batch smoke (card proof)", key="dispatch_smoke") and gwq_mod is not None:
        repo = str(_REPO.resolve())
        task = {
            "kind": "vllm_batch_smoke",
            "title": "Prove batched chat completions on local vLLM",
            "commands": [
                f"bash {repo}/scripts/vllm_batch_smoke.sh --concurrency 8 --total 32 --json-out",
                f"python3 {repo}/prompt2dataset/scripts/check_vllm.py --chat",
            ],
            "read_first": [
                f"{repo}/prompts/ENGINEER_MANDATE.md",
                f"{repo}/prompt2dataset/config/prompt2dataset.yaml",
            ],
            "resolve_hint": "Exit 0 from batch smoke + check_vllm --chat → resolve with summary.",
        }
        try:
            eid = gwq_mod.append_global_wonder(
                task,
                priority=pri,
                run_id="",
                source="streamlit_operator_hub",
            )
            st.success(f"Enqueued `{eid}` (vLLM batch smoke)")
            st.session_state["last_dispatch_eid"] = eid
            st.session_state["last_dispatch_task"] = task
        except OSError as e:
            st.error(str(e))

    eid = st.session_state.get("last_dispatch_eid")
    task = st.session_state.get("last_dispatch_task")
    if eid and task:
        st.subheader("Paste into Claw")
        mq = task.get("mandate_queue_path")
        mq_line = f"mandate_queue_path: {mq}\n" if mq else ""
        reads = task.get("read_first") or []
        read_block = "\n".join("  - " + p for p in reads) if reads else "  (none)"
        handoff = f"""Tier-1 on ISF-PEECEE — global_wonder from Operator hub.

event_id: {eid}
kind: {task.get("kind")}
{mq_line}
Commands (repo root):
{chr(10).join("  - " + c for c in task.get("commands", []))}

Read first:
{read_block}

Resolve: python3 scripts/wonder_queue_cli.py resolve {eid} --summary "<summary>"
"""
        st.code(handoff, language="markdown")

# ── Queue table ────────────────────────────────────────────────────────────
with tab_queue:
    if gwq_mod is None:
        st.info("Wonder queue module unavailable.")
    else:
        p = gwq_mod.global_wonder_queue_path()
        st.caption(f"`{p}`")
        if st.button("Refresh", key="q_refresh"):
            st.rerun()
        pending = gwq_mod.pending_global_wonders(limit=80)
        st.metric("Pending", len(pending))
        rows = pending_wonder_rows(pending, limit=80)
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True, height=min(520, 36 + len(rows) * 36))
        else:
            st.info("No pending items.")

        with st.expander("Raw JSON (last 6 pending)", expanded=False):
            st.json(pending[-6:])

st.divider()
st.markdown(
    f"**Autonomy timer + file snapshot:** sidebar **Autonomy** · "
    f"`bash {_REPO}/scripts/autonomy-tick-once.sh` · "
    f"`{_REPO}/prompt2dataset/AUTONOMY_LOOP.md`"
)
