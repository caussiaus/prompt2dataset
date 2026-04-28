"""Pipeline orchestration for the Streamlit UI.

Manages:
  - Ingest subprocess (Docling parse + chunk)
  - Document queue (ws_doc_queue) for extraction (serial or batched)
  - Consistency check after each extraction batch
  - Critique dispatch (streaming)

Session state keys used (all generic names):
  ws_state          DatasetState dict
  ws_ingest_done    bool — True when ingest subprocess exited
  ws_ingest_rc      int — subprocess return code
  ws_proc           subprocess.Popen — running ingest process
  ws_queue          Queue — stdout line queue from ingest
  ws_doc_queue      list[dict] — rows to extract (popped per rerun)
  ws_doc_total      int — total docs queued for this extraction run
  ws_focus_field    str — which field is highlighted in table inspector
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from queue import Empty, Queue
from threading import Thread as PThread
from typing import Any

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app_pages.thread_store import Thread, save_thread
from prompt2dataset.corpus.paths import resolve_corpus_path
from prompt2dataset.dataset_graph.extraction_node import (
    extract_one_filing,
    rebuild_cells_from_rows,
    run_consistency_check,
)
from prompt2dataset.dataset_graph.state import (
    DatasetState,
    SEDAR_IDENTITY_FIELDS,
)

_CONFIG_DIR = ROOT / "output" / "corpus_configs"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _sync_cells(ws_state: DatasetState) -> None:
    """Keep ``cells`` aligned with ``rows`` (matches ``extraction_node`` graph output)."""
    rows = ws_state.get("rows") or []
    columns = ws_state.get("proposed_columns") or []
    if not columns:
        ws_state["cells"] = []
        return
    identity_fields = ws_state.get("identity_fields") or SEDAR_IDENTITY_FIELDS
    ws_state["cells"] = rebuild_cells_from_rows(rows, columns, identity_fields)


# ── Subprocess management ──────────────────────────────────────────────────────


def _pipeline_cmd(t: Thread, trial_n: int = 0) -> list[str]:
    yaml = _CONFIG_DIR / f"{t.corpus_id}.yaml"
    script = str(ROOT / "scripts" / "run_corpus_pipeline.py")
    cmd = [sys.executable, script]
    cmd += ["--config", str(yaml)] if yaml.exists() else ["--corpus", t.corpus_id]
    cmd += ["--stage", "ingest"]
    if trial_n > 0:
        cmd += ["--trial-n", str(trial_n)]
    return cmd


def _drain(proc: subprocess.Popen, q: Queue) -> None:
    assert proc.stdout
    for line in proc.stdout:
        q.put(line.rstrip())
    proc.wait()
    q.put(None)


def launch_ingest(t: Thread, trial_n: int = 0) -> None:
    """Fire off the Docling ingest subprocess and set up the queue drain."""
    cmd = _pipeline_cmd(t, trial_n=trial_n)
    cmd_display = " ".join(Path(c).name if os.sep in c else c for c in cmd)
    t.add_log(f"$ {cmd_display}")
    t.status = "ingesting"
    save_thread(t)

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, cwd=str(ROOT),
        # New process group so we can kill Docling workers on Stop
        preexec_fn=os.setsid,
    )
    q: Queue = Queue()
    PThread(target=_drain, args=(proc, q), daemon=True).start()

    st.session_state["ws_proc"] = proc
    st.session_state["ws_queue"] = q
    st.session_state["ws_ingest_done"] = False
    st.session_state["ws_ingest_rc"] = 0


def poll_ingest(t: Thread) -> bool:
    """Drain stdout from the ingest queue into thread.log. Returns True when done.

    Detects incremental progress signals emitted by run_corpus_pipeline.py:
      [PARSE_PROGRESS] N_docs total_chunks  — update live counter
      [EXTRACTION_READY]                    — enough docs chunked; enable extraction
      [QUEUE_GREW] N_docs                   — more docs available; expand queue
    """
    q: Queue | None = st.session_state.get("ws_queue")
    if q is None:
        return True

    finished = False
    lines: list[str] = []
    try:
        while True:
            item = q.get_nowait()
            if item is None:
                proc = st.session_state.get("ws_proc")
                rc = proc.returncode if proc else 0
                st.session_state["ws_ingest_done"] = True
                st.session_state["ws_ingest_rc"] = rc
                finished = True
                break
            lines.append(item)
    except Empty:
        pass

    extraction_ready = False
    for ln in lines:
        # ── Incremental signals ──────────────────────────────────────────────
        if ln.startswith("[PARSE_PROGRESS]"):
            # Format: [PARSE_PROGRESS] n_docs total_chunks
            parts = ln.split()
            if len(parts) >= 3:
                try:
                    st.session_state["ws_parsed_docs"] = int(parts[1])
                    st.session_state["ws_parsed_chunks"] = int(parts[2])
                except ValueError:
                    pass
            continue  # don't log raw signal lines

        if ln.startswith("[EXTRACTION_READY]"):
            st.session_state["ws_ingest_done"] = True  # unlock extraction UI
            extraction_ready = True
            t.add_log("<span class='log-info'>✓ Sample batch ready — starting extraction while full corpus continues…</span>")
            continue

        if ln.startswith("[PARSE_ZERO_DOCS]") or ln.startswith("[PARSE_ERROR]"):
            st.session_state["ws_parse_error"] = ln
            t.add_log(f"<span class='log-error'>✗ {ln}</span>")
            continue

        if ln.startswith("[PARSE_ZERO_CHUNKS]"):
            st.session_state["ws_parse_error"] = ln
            t.add_log(f"<span class='log-warn'>⚠ {ln}</span>")
            continue

        if ln.startswith("[CHUNK_ZERO]") or ln.startswith("[CHUNK_ERROR]"):
            t.add_log(f"<span class='log-warn'>⚠ {ln}</span>")
            continue

        if ln.startswith("[QUEUE_GREW]"):
            # Signal that more chunks are available — note it but don't interrupt extraction
            parts = ln.split()
            if len(parts) >= 2:
                try:
                    st.session_state["ws_background_docs"] = int(parts[1])
                except ValueError:
                    pass
            continue

        # ── Standard log lines ───────────────────────────────────────────────
        lo = ln.lower()
        if any(x in lo for x in ("error", "traceback")):
            cls = "log-error"
        elif any(x in lo for x in ("warn", "skip")):
            cls = "log-warn"
        else:
            cls = "log-info"
        t.add_log(f"<span class='{cls}'>{ln}</span>")

    if lines:
        save_thread(t)

    if finished:
        rc = st.session_state.get("ws_ingest_rc", 0)
        t.add_log(f"{'✓ Ingest complete.' if rc == 0 else f'✗ Ingest exited with code {rc}.'}")
        t.proc_done = True
        t.proc_rc = rc
        save_thread(t)

    return finished or st.session_state.get("ws_ingest_done", False)


def kill_ingest() -> None:
    """Kill the running ingest subprocess AND all its child processes.

    Docling spawns worker processes that keep the GPU hot even after the main
    process is terminated.  We kill the entire process group to catch them all.
    """
    proc = st.session_state.get("ws_proc")
    if proc:
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        try:
            proc.wait(timeout=3)
        except Exception:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except Exception:
                pass
    st.session_state["ws_ingest_done"] = True
    st.session_state["ws_proc"] = None
    st.session_state["ws_queue"] = None


# ── Doc queue helpers ──────────────────────────────────────────────────────────


def build_doc_queue(t: Thread, ws_state: DatasetState) -> int:
    """Populate ws_doc_queue from the corpus index.

    For trial mode: pick ws_state['sample_doc_ids'] rows; if not set, pick
    first trial_n rows from the index.
    For full mode: all rows.
    Returns the number of docs queued.
    """
    from prompt2dataset.utils.config import get_settings
    cfg = get_settings()

    idx_path = resolve_corpus_path(
        cfg.project_root,
        ws_state.get("corpus_index_csv"),
        cfg.filings_index_path,
    )
    if not idx_path.is_file():
        st.error(
            "**Cannot load corpus index** — file not found:\n\n"
            f"`{idx_path}`\n\n"
            "If ingest just finished, wait for the log to show the index was written. "
            "If you used **Retry ingest** with a new folder, that path must be saved to the corpus YAML "
            "(the UI now does this automatically when you retry from **Fix path**).\n\n"
            "Otherwise point **Advanced** → index CSV at an existing file, or fix WSL access to your PDF folder."
        )
        return 0
    try:
        idx = pd.read_csv(idx_path, dtype=str)
    except Exception as e:
        st.error(f"Cannot load corpus index: {e}")
        return 0

    try:
        need = "entity_id" not in idx.columns or (
            idx["entity_id"].fillna("").astype(str).str.strip() == ""
        ).all()
        if need and not idx.empty:
            from prompt2dataset.utils.entity_registry import stamp_index_dataframe

            idx = stamp_index_dataframe(idx)
    except Exception:
        pass

    use_sample = ws_state.get("use_sample", True)
    sample_ids = ws_state.get("sample_doc_ids") or []

    if use_sample and sample_ids:
        for col in ("doc_id", "filing_id", "ticker", "entity_slug"):
            if col in idx.columns:
                sub = idx[idx[col].isin(sample_ids)]
                if not sub.empty:
                    idx = sub
                    break

    elif use_sample:
        n = t.trial_n or 7
        # Prefer docs that already have rows in chunks.parquet. Ingest processes
        # PDFs smallest-first, while index.csv is scan order — idx.head(n) can
        # disagree completely with the first n chunked docs, yielding zero evidence.
        prefer = idx
        chunks_path = resolve_corpus_path(
            cfg.project_root,
            ws_state.get("corpus_chunks_parquet"),
            cfg.chunks_parquet,
        )
        try:
            if chunks_path.is_file():
                ch = pd.read_parquet(chunks_path)
                id_col = next((c for c in ("filing_id", "doc_id") if c in ch.columns), None)
                if id_col:
                    have = set(ch[id_col].dropna().astype(str).unique())
                    for col in ("doc_id", "filing_id"):
                        if col in idx.columns:
                            sub = idx[idx[col].astype(str).isin(have)]
                            if not sub.empty:
                                prefer = sub
                                break
        except Exception:
            pass
        idx = prefer.head(n)

    rows = idx.to_dict("records")
    st.session_state["ws_doc_queue"] = rows
    st.session_state["ws_doc_total"] = len(rows)
    return len(rows)


def pop_and_extract_one(t: Thread, ws_state: DatasetState) -> tuple[dict | None, bool]:
    """Pop one doc from ws_doc_queue and extract it.

    Returns (row_dict, queue_is_empty).
    Returns (None, True) if queue was already empty.
    """
    queue: list[dict] = st.session_state.get("ws_doc_queue", [])
    if not queue:
        return None, True

    doc_meta = queue.pop(0)
    st.session_state["ws_doc_queue"] = queue

    if getattr(t, "run_id", ""):
        ws_state.setdefault("run_id", t.run_id)

    try:
        row = extract_one_filing(ws_state, doc_meta)
    except Exception as e:
        identity_fields = ws_state.get("identity_fields") or SEDAR_IDENTITY_FIELDS
        row = {f: doc_meta.get(f, "") for f in identity_fields}
        row["_extraction_error"] = str(e)

    # Append to thread rows
    existing = ws_state.get("rows", [])
    ws_state["rows"] = [*existing, row]
    _sync_cells(ws_state)
    st.session_state["ws_state"] = ws_state
    t.rows = ws_state["rows"]
    save_thread(t)

    return row, len(queue) == 0


def pop_and_extract_batch(
    t: Thread,
    ws_state: DatasetState,
    *,
    batch_size: int = 10,
    concurrency: int = 4,
) -> tuple[list[dict], bool]:
    """Pop up to ``batch_size`` docs from ws_doc_queue and extract them in parallel.

    Uses ``asyncio.gather`` under the hood with a Semaphore capped at
    ``concurrency`` (default 4) so vLLM isn't overwhelmed.

    Returns (new_rows, queue_is_empty).
    Returns ([], True) if the queue was already empty.
    """
    from prompt2dataset.dataset_graph.extraction_node import extract_batch_filings

    queue: list[dict] = st.session_state.get("ws_doc_queue", [])
    if not queue:
        return [], True

    batch = queue[:batch_size]
    remaining = queue[batch_size:]
    st.session_state["ws_doc_queue"] = remaining

    if getattr(t, "run_id", ""):
        ws_state.setdefault("run_id", t.run_id)

    try:
        new_rows = extract_batch_filings(
            ws_state, batch, concurrency=concurrency
        )
    except Exception as exc:
        identity_fields = ws_state.get("identity_fields") or SEDAR_IDENTITY_FIELDS
        new_rows = []
        for doc_meta in batch:
            row = {f: doc_meta.get(f, "") for f in identity_fields}
            row["_extraction_error"] = str(exc)
            new_rows.append(row)

    existing = ws_state.get("rows", [])
    ws_state["rows"] = [*existing, *new_rows]
    _sync_cells(ws_state)
    st.session_state["ws_state"] = ws_state
    t.rows = ws_state["rows"]
    save_thread(t)

    return new_rows, len(remaining) == 0


def run_consistency_after_extraction(t: Thread, ws_state: DatasetState) -> DatasetState:
    """Run consistency_check on all extracted rows and persist flags."""
    columns = ws_state.get("proposed_columns", [])
    identity_fields = ws_state.get("identity_fields") or SEDAR_IDENTITY_FIELDS
    rows = ws_state.get("rows", [])

    if rows and columns:
        flags = run_consistency_check(rows, columns, identity_fields)
        ws_state["consistency_flags"] = flags
        _sync_cells(ws_state)
    else:
        ws_state["consistency_flags"] = {}
        ws_state.setdefault("cells", [])

    st.session_state["ws_state"] = ws_state
    return ws_state


def clear_extraction_state() -> None:
    """Reset extraction queue state (used by Stop button)."""
    st.session_state["ws_doc_queue"] = []
    st.session_state["ws_doc_total"] = 0


# ── Eval window helpers ────────────────────────────────────────────────────────


def eval_window_ready(ws_state: DatasetState) -> bool:
    """Return True if enough docs have been parsed for schema grounding."""
    from prompt2dataset.dataset_graph.schema_node import _sample_chunks_from_parquet
    from prompt2dataset.utils.config import get_settings

    cfg = get_settings()
    eval_min = ws_state.get("eval_window_min", 6)
    chunks_path = resolve_corpus_path(
        cfg.project_root,
        ws_state.get("corpus_chunks_parquet"),
        cfg.chunks_parquet,
    )
    samples = _sample_chunks_from_parquet(str(chunks_path), n=eval_min)
    return len(samples) >= eval_min


def count_parsed_docs(ws_state: DatasetState) -> int:
    """Return how many docs are represented in chunks parquet, or OK rows in docling parse index.

    Docling can burn CPU/GPU while chunking fails (e.g. schema drift in docling JSON); then
    parquet stays empty but ``docling_parse_index.csv`` still shows successful parses.
    """
    from prompt2dataset.utils.config import get_settings

    cfg = get_settings()
    chunks_path = resolve_corpus_path(
        cfg.project_root,
        ws_state.get("corpus_chunks_parquet"),
        cfg.chunks_parquet,
    )
    n_parquet = 0
    try:
        p = chunks_path
        if p.exists():
            import pandas as _pd
            df = _pd.read_parquet(p)
            id_col = next((c for c in ("doc_id", "filing_id") if c in df.columns), None)
            n_parquet = int(df[id_col].nunique() if id_col else len(df))
    except Exception:
        n_parquet = 0

    parse_csv = (ws_state.get("corpus_parse_index_csv") or "").strip()
    if not parse_csv:
        try:
            cand = chunks_path.parent.parent / "docling_parse_index.csv"
            if cand.is_file():
                parse_csv = str(cand)
        except Exception:
            parse_csv = ""

    n_parse = 0
    if parse_csv:
        try:
            pp = Path(parse_csv)
            if pp.is_file():
                import pandas as _pd2
                pdf = _pd2.read_csv(pp, dtype=str)
                if "parse_status" in pdf.columns and "filing_id" in pdf.columns:
                    ok = pdf[pdf["parse_status"].str.startswith("OK", na=False)]
                    n_parse = int(ok["filing_id"].nunique())
                elif "parse_status" in pdf.columns:
                    n_parse = int(pdf["parse_status"].str.startswith("OK", na=False).sum())
                else:
                    n_parse = len(pdf)
        except Exception:
            n_parse = 0

    return max(n_parquet, n_parse)
