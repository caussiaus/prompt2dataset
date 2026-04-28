"""Streamlit multipage — autonomy loop observer (systemd timer + JSON snapshot).

Run main app as usual: ``streamlit run app.py`` from ``prompt2dataset/``;
this page appears in the sidebar.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import streamlit as st

from prompt2dataset.utils.operator_dashboard import autonomy_metric_cards, iso_mtime, load_json_object

_APP = Path(__file__).resolve().parents[1]
_REPO = _APP.parent
for _p in (_REPO, _APP):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

st.set_page_config(page_title="Autonomy loop", page_icon="🧠", layout="wide")

STATE = _REPO / "state"
LAST_JSON = STATE / "autonomy_last.json"
LOOP_LOG = STATE / "autonomy_loop.log"
STDERR = STATE / "autonomy_last.stderr"


def _timer_state() -> str:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", "isf-autonomy-tick.timer"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return (r.stdout or r.stderr or "").strip() or f"exit {r.returncode}"
    except Exception as e:
        return f"unavailable ({e})"


def _last_service() -> str:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "show", "isf-autonomy-tick.service", "-p", "ActiveState", "-p", "SubState"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return (r.stdout or "").strip() or r.stderr or ""
    except Exception as e:
        return str(e)


st.title("Autonomy loop")
st.caption(
    "Timer → `autonomy-tick-once.sh` → `run_autonomy_cycle.py`. Logs under `state/`. "
    "Rich metrics, scrape grid embed, custom wonder JSON: sidebar **Operator hub** (`pages/02_Operator_hub.py`)."
)

c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Timer `isf-autonomy-tick.timer`", _timer_state())
with c2:
    st.metric("`autonomy_last.json`", "yes" if LAST_JSON.is_file() else "no")
with c3:
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Refresh"):
            st.rerun()
    with b2:
        if st.button("Run tick now"):
            try:
                r = subprocess.run(
                    ["bash", str(_REPO / "scripts" / "autonomy-tick-once.sh")],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=str(_REPO),
                )
                if r.returncode == 0:
                    st.success("Tick finished OK.")
                else:
                    st.warning(f"Tick exit {r.returncode}")
                if r.stderr:
                    st.code(r.stderr[-4000:], language="")
            except Exception as e:
                st.error(str(e))
            st.rerun()

with st.expander("systemd (read-only)", expanded=False):
    st.caption(
        "`isf-autonomy-tick.service` is **Type=oneshot** — **inactive / dead** between ticks is normal; "
        "watch the **timer**, not long-running `active` on the service."
    )
    st.code(_last_service(), language="properties")

st.divider()

_snap = load_json_object(LAST_JSON)
_cards = autonomy_metric_cards(_snap)
_snap_ts = iso_mtime(LAST_JSON)
st.subheader("Snapshot metrics (from `autonomy_last.json`)")
r1, r2, r3, r4, r5 = st.columns(5)
with r1:
    st.metric("gw pending", _cards["gw_pending"] if _cards["gw_pending"] is not None else "—")
with r2:
    _vm = "—"
    if _snap:
        _vm = "OK" if _cards["vllm_models_ok"] else "fail"
    st.metric("vLLM /models", _vm)
with r3:
    st.metric("health HTTP", _cards["health_http"] if _cards["health_http"] is not None else "—")
with r4:
    st.metric("status HTTP", _cards["status_http"] if _cards["status_http"] is not None else "—")
with r5:
    st.metric("run wonder lines", _cards["wq_run_loaded"] if _cards["wq_run_loaded"] is not None else "—")
st.caption(f"File mtime: {_snap_ts or '—'} · deferred={_cards['deferred']} · mode={_cards['controller_mode'] or '—'}")

st.divider()


def _timeouts_or_unreachable(data: dict) -> bool:
    c = data.get("controller") or {}
    if int(c.get("health_status") or 0) < 0:
        return True
    if int(c.get("status_status") or 0) < 0:
        return True
    hb = str(c.get("health") or "")
    sb = str(c.get("status") or "")
    if "timed out" in hb.lower() or "timed out" in sb.lower():
        return True
    pr = (data.get("vllm") or {}).get("probe") or {}
    if pr.get("ok") is False and "timed out" in str(pr.get("error") or "").lower():
        return True
    return False


if LAST_JSON.is_file():
    raw = LAST_JSON.read_text(encoding="utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        st.error(f"Invalid JSON in autonomy_last.json: {e}")
        with st.expander("Raw file (debug)", expanded=True):
            st.code((raw or "(empty)")[:8000], language="text")
        st.info(
            "Usually **empty file** or **interrupted write** while a tick was running. "
            "`autonomy-tick-once.sh` now writes **atomically** — click **Run tick now** again."
        )
        data = None
    if data is not None:
        if _timeouts_or_unreachable(data):
            st.info(
                "**Probes timed out** — `deferred` can still be `false` (only set after a **parsed** "
                "`/status` JSON shows training).\n\n"
                "**WSL-only checks:**\n"
                "- Processes listening: `ss -lntp | grep -E '8430|8432'`\n"
                "- Manual: `curl -sS -m 5 http://127.0.0.1:8432/health` and "
                "`curl -sS -m 10 http://127.0.0.1:8430/v1/models`\n"
                "- Raise tick budget: `ISF_AUTONOMY_HTTP_TIMEOUT_SEC=45` in `scripts/autonomy-loop.env`\n"
                "- GPU cold / first load: first `/models` can be slow — timeout default **~22s** "
                "(`--http-timeout` on `run_autonomy_cycle.py`).\n\n"
                f"Re-run: `bash {_REPO}/scripts/autonomy-tick-once.sh` or **Run tick now**."
            )
        gw = data.get("global_wonder_queue") or {}
        ctrl = data.get("controller") or {}
        vllm = data.get("vllm") or {}
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.metric("Deferred (GPU busy)", "yes" if data.get("deferred") else "no")
        with col_b:
            st.metric("Global wonder pending", gw.get("pending_count", "—"))
        with col_c:
            probe = (vllm.get("probe") or {})
            st.metric("vLLM /models probe", "OK" if probe.get("ok") else "fail")

        st.subheader("Controller snapshot")
        st.json({"health": ctrl.get("health"), "status": ctrl.get("status")})

        st.subheader("Full `autonomy_last.json`")
        st.json(data)
else:
    st.warning(f"No `{LAST_JSON}` yet — run once: `bash {_REPO}/scripts/autonomy-tick-once.sh`")

st.divider()
st.subheader("`autonomy_loop.log` (tail)")
if LOOP_LOG.is_file():
    lines = LOOP_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    st.code("\n".join(lines[-80:]), language="")
else:
    st.info("No log file yet.")

if STDERR.is_file() and STDERR.stat().st_size:
    st.subheader("Last stderr (Python warnings / tracebacks)")
    st.text(STDERR.read_text(encoding="utf-8", errors="replace")[-8000:])

st.divider()
st.markdown(
    f"""
**Turn timer on:** `systemctl --user enable --now isf-autonomy-tick.timer`  
**Off:** `systemctl --user disable --now isf-autonomy-tick.timer`  
**Manual tick:** `bash {_REPO}/scripts/autonomy-tick-once.sh`  
Docs: `{_REPO}/prompt2dataset/AUTONOMY_LOOP.md`
"""
)
