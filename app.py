"""Dataset Builder — single-page Streamlit app.

Layout:
  Left sidebar   = dark thread list + field inspector
  Main area      = chat thread + sticky results table
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# App home = ``ISF-PEECEE/prompt2dataset``; parent repo root must be on path for ``import prompt2dataset``.
_APP_HOME = Path(__file__).resolve().parent
_REPO_ROOT = _APP_HOME.parent
for _p in (_REPO_ROOT, _APP_HOME):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from prompt2dataset.utils.config import ensure_hf_hub_env_for_process

ensure_hf_hub_env_for_process()

st.set_page_config(
    page_title="Dataset Builder",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --bg:           #FFFFFF;
  --bg2:          #F9F9F9;
  --bg3:          #F0F0F0;
  --sidebar:      #161B22;
  --sidebar2:     #21262D;
  --border:       #E5E7EB;
  --border2:      #D1D5DB;
  --text:         #111827;
  --text2:        #4B5563;
  --text-muted:   #9CA3AF;
  --accent:       #2563EB;
  --accent-hover: #1D4ED8;
  --accent-light: #EFF6FF;
  --green:        #059669;
  --green-light:  #ECFDF5;
  --red:          #DC2626;
  --red-light:    #FEF2F2;
  --yellow:       #D97706;
  --yellow-light: #FFFBEB;
  --term-green:   #34D399;
  --term-blue:    #93C5FD;
  --term-dim:     #6B7280;
  --font:         'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --mono:         'JetBrains Mono', 'Fira Code', monospace;
  --r:            6px;
  --r2:           10px;
  --chat-max:     700px;
}

/* ── Reset ── */
html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
  background: var(--bg) !important;
  font-family: var(--font) !important;
  color: var(--text) !important;
}
[data-testid="stToolbar"], #MainMenu, footer, header { display: none !important; }

/* ── Main area — constrain chat width like OpenWebUI ── */
[data-testid="stMain"] > div { max-width: 860px; margin: 0 auto; padding: 0 1.5rem; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
  background: var(--sidebar) !important;
  border-right: 1px solid #30363D !important;
  min-width: 220px !important; max-width: 240px !important;
}
[data-testid="stSidebar"] * { color: #C9D1D9 !important; font-family: var(--font) !important; font-size: 0.85rem !important; }
[data-testid="stSidebar"] hr { border-color: #30363D !important; }
[data-testid="stSidebar"] .stButton > button {
  background: transparent !important; color: #C9D1D9 !important;
  border: 1px solid #30363D !important; font-size: 0.82rem !important;
  text-align: left !important; padding: 6px 10px !important;
  border-radius: var(--r) !important; width: 100% !important;
  transition: background 0.1s !important;
}
[data-testid="stSidebar"] .stButton > button:hover { background: #21262D !important; }
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
  background: var(--accent) !important; border-color: var(--accent) !important; color: #fff !important;
}

/* ── Typography ── */
h1 { font-size: 1.25rem !important; font-weight: 600 !important; color: var(--text) !important; letter-spacing: -0.02em; margin-bottom: 4px; }
h2 { font-size: 1.05rem !important; font-weight: 600 !important; }
h3 { font-size: 0.95rem !important; font-weight: 600 !important; }
p, li { font-size: 0.93rem !important; line-height: 1.6; }
label { font-size: 0.85rem !important; font-weight: 500 !important; color: var(--text2) !important; }
.stCaption > p { font-size: 0.77rem !important; color: var(--text-muted) !important; }
code { font-family: var(--mono) !important; font-size: 0.82rem !important; background: var(--bg2) !important; color: var(--accent) !important; padding: 1px 5px; border-radius: 3px; }

/* ── Inputs ── */
input[type="text"], input[type="password"], [data-baseweb="input"] input, [data-baseweb="textarea"] textarea {
  background: #fff !important; border: 1px solid var(--border2) !important;
  border-radius: var(--r) !important; font-family: var(--font) !important;
  font-size: 0.93rem !important; color: var(--text) !important;
}
input:focus, textarea:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 3px rgba(37,99,235,0.1) !important; outline: none !important;
}

/* ── Buttons ── */
.stButton > button {
  background: var(--accent) !important; color: #fff !important; border: none !important;
  border-radius: var(--r) !important; font-size: 0.88rem !important; font-weight: 500 !important;
  padding: 7px 16px !important; transition: background 0.1s !important; cursor: pointer !important;
}
.stButton > button:hover { background: var(--accent-hover) !important; }
.stButton > button[kind="secondary"] {
  background: #fff !important; color: var(--text) !important;
  border: 1px solid var(--border2) !important;
}
.stButton > button[kind="secondary"]:hover { background: var(--bg2) !important; }

/* ── Stop button — always red, easy to hit ── */
.stop-bar .stButton > button {
  background: #DC2626 !important; color: #fff !important;
  border: none !important; font-weight: 600 !important;
  font-size: 0.85rem !important; padding: 5px 14px !important;
  border-radius: 999px !important;
}
.stop-bar .stButton > button:hover { background: #B91C1C !important; }

/* ── Alerts ── */
.stInfo    { background: var(--accent-light) !important; border-left: 3px solid var(--accent) !important; border-radius: var(--r) !important; font-size: 0.88rem !important; }
.stSuccess { background: var(--green-light) !important; border-left: 3px solid var(--green) !important; border-radius: var(--r) !important; font-size: 0.88rem !important; }
.stWarning { background: var(--yellow-light) !important; border-left: 3px solid var(--yellow) !important; border-radius: var(--r) !important; font-size: 0.88rem !important; }
.stError   { background: var(--red-light) !important; border-left: 3px solid var(--red) !important; border-radius: var(--r) !important; font-size: 0.88rem !important; }

/* ── Progress ── */
[data-testid="stProgress"] > div > div { background: var(--accent) !important; }
[data-testid="stProgress"] > div { background: var(--bg3) !important; border-radius: 999px !important; }

/* ── Download button ── */
[data-testid="stDownloadButton"] > button {
  background: var(--bg2) !important; color: var(--text) !important;
  border: 1px solid var(--border2) !important; font-weight: 500 !important;
}
[data-testid="stDownloadButton"] > button:hover { background: var(--bg3) !important; }

/* ── Chat messages — clean bubbles ── */
[data-testid="stChatMessage"] {
  background: transparent !important; border: none !important;
  border-radius: 0 !important; margin-bottom: 2px !important; padding: 4px 0 !important;
}
[data-testid="stChatMessage"][data-role="user"] > div > div {
  background: var(--accent-light) !important;
  border-radius: var(--r2) !important; padding: 10px 14px !important;
}
[data-testid="stChatMessage"][data-role="assistant"] > div > div {
  background: var(--bg2) !important;
  border-radius: var(--r2) !important; padding: 10px 14px !important;
}

/* Chat input — big, sticky-feel bar */
[data-testid="stChatInputContainer"] {
  background: var(--bg) !important; border-top: 1px solid var(--border) !important;
  padding: 10px 0 4px !important;
}
[data-testid="stChatInputContainer"] textarea {
  border-radius: var(--r2) !important; font-size: 0.95rem !important;
  border: 1px solid var(--border2) !important; padding: 10px 14px !important;
}

/* ── Dataframe ── */
[data-testid="stDataFrame"] { border: 1px solid var(--border) !important; border-radius: var(--r) !important; }

/* ── Schema cards ── */
.schema-card-header { font-weight: 600; font-size: 0.9rem; padding: 4px 0 8px; border-bottom: 1px solid var(--border); margin-bottom: 8px; }
.schema-field { display: flex; gap: 10px; align-items: baseline; padding: 4px 0; border-bottom: 1px solid var(--bg3); font-size: 0.86rem; }
.schema-field:last-child { border-bottom: none; }
.field-name { font-family: var(--mono); font-size: 0.82rem; font-weight: 600; min-width: 150px; }
.field-type { font-family: var(--mono); font-size: 0.71rem; color: var(--accent); background: var(--accent-light); border: 1px solid #BFDBFE; padding: 1px 6px; border-radius: 3px; white-space: nowrap; }
.field-desc { font-size: 0.81rem; color: var(--text2); flex: 1; }

/* ── Log lines ── */
.log-msg { font-family: var(--mono); font-size: 0.77rem; color: var(--term-dim); padding: 1px 0; line-height: 1.6; white-space: pre-wrap; }
.log-info { color: var(--term-green); }
.log-warn { color: #FCD34D; }
.log-error { color: #F87171; }
.log-step { color: var(--term-blue); font-weight: 600; }

/* ── Evidence ── */
.evidence-quote { font-size: 0.83rem; background: var(--accent-light); border: 1px solid #BFDBFE; border-radius: var(--r); padding: 7px 10px; color: var(--text2); margin-top: 4px; font-style: italic; line-height: 1.5; }

/* ── Pills ── */
.pill { display: inline-block; font-size: 0.73rem; font-weight: 600; padding: 2px 9px; border-radius: 999px; letter-spacing: 0.03em; }
.pill-green  { background: var(--green-light); color: var(--green); border: 1px solid #A7F3D0; }
.pill-indigo { background: var(--accent-light); color: var(--accent); border: 1px solid #BFDBFE; }
.pill-red    { background: var(--red-light); color: var(--red); border: 1px solid #FCA5A5; }
.pill-amber  { background: var(--yellow-light); color: var(--yellow); border: 1px solid #FDE68A; }

hr { border: none; border-top: 1px solid var(--border); margin: 10px 0; }
</style>
""", unsafe_allow_html=True)


# ── Startup: backup checkpoints and init storage infra ───────────────────────

@st.cache_resource
def _startup_once():
    from prompt2dataset.dataset_graph.graph import _backup_checkpoints
    _backup_checkpoints()

    # KG health check — surface vault issues as a warning at startup
    try:
        from connectors.obsidian_bridge import kg_health_check
        health = kg_health_check()
        if not health["healthy"]:
            import streamlit as _st
            msg = f"Vault health check failed: {health.get('error') or 'vault directory not found'}"
            _st.warning(f"⚠ Knowledge Graph: {msg}")
    except Exception:
        pass  # KG is optional — never crash startup

    # DuckDB + lance extension init
    try:
        import duckdb
        _state_dir = Path(__file__).resolve().parent / "state"
        _state_dir.mkdir(exist_ok=True)
        _con = duckdb.connect(str(_state_dir / "pipeline.duckdb"))
        _con.execute("INSTALL lance; LOAD lance;")
        _con.close()
    except Exception:
        pass  # lance extension unavailable — DuckDB still works for row queries

    return True

_startup_once()

# ── Main workspace (sidebar + all routing handled inside) ─────────────────────

from app_pages import workspace


# ── Global error boundary ─────────────────────────────────────────────────────
def _run_workspace_with_error_boundary():
    """Catch unhandled exceptions from workspace.render() and show a red banner."""
    import traceback
    try:
        workspace.render()
    except Exception as exc:
        tb = traceback.format_exc()
        st.error(
            f"**Pipeline error — unexpected exception caught.**\n\n"
            f"`{type(exc).__name__}: {exc}`\n\n"
            f"The pipeline state has been preserved. Refresh the page to retry.\n\n"
            f"<details><summary>Traceback</summary>\n\n```\n{tb}\n```\n</details>",
            icon="🔴",
        )
        # Try to persist the error to DatasetContext if possible
        try:
            ws_state = st.session_state.get("ws_state", {})
            thread_id = st.session_state.get("ws_thread_id", "")
            if thread_id:
                from app_pages.thread_store import load_context, save_context, context_from_state
                ctx = load_context(thread_id) or context_from_state(thread_id, ws_state)
                ctx.last_error = f"{type(exc).__name__}: {str(exc)[:500]}"
                save_context(ctx)
        except Exception:
            pass

_run_workspace_with_error_boundary()
