#!/usr/bin/env python3
"""Run parse → chunk → (optional) LLM stages for the active corpus.

Uses :func:`prompt2dataset.corpus.runtime.apply_corpus_env` so outputs go to
``$PIPELINE_OUTPUT_BASE_DIR/{corpus_id}/`` (or ``.../runs/{run_id}/`` when
``--run-id`` is set). Default base is the library vault; see ``DOCUMENT_LIFECYCLE.md``.

Examples::

    # TSX 2023 — after indexes exist under data/metadata/
    python scripts/run_corpus_pipeline.py --corpus tsx_esg_2023 --stage parse
    python scripts/run_corpus_pipeline.py --corpus tsx_esg_2023 --stage chunk
    python scripts/run_corpus_pipeline.py --corpus tsx_esg_2023 --stage llm_chunk

    # SEDAR with prateek filings root (relative paths in filings_index.csv)
    python scripts/run_corpus_pipeline.py --corpus sedar_prateek_filings --stage parse

    # Custom YAML + isolated run (vault layout)
    python scripts/run_corpus_pipeline.py --config output/corpus_configs/my_corpus.yaml --run-id run_20260422_devtrial --stage parse

Environment is set **before** pipeline imports reload settings.
"""
from __future__ import annotations

import argparse
import sys
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT.parent, _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load_corpus(corpus: str, config: str | None, project_root: Path):
    from prompt2dataset.corpus.config import CorpusConfig
    if config:
        return CorpusConfig.from_yaml(Path(config).expanduser())
    key = corpus.strip().lower().replace("-", "_")
    if key in ("sedar_tariff", "sedar", ""):
        return CorpusConfig.sedar_default(project_root)
    if key in ("sedar_prateek", "sedar_prateek_filings", "prateek"):
        return CorpusConfig.sedar_prateek_filings(project_root)
    if key in ("tsx_esg_2023", "tsx2023", "tsx_23"):
        return CorpusConfig.tsx_esg_2023(project_root)
    if key in ("tsx_esg_2024", "tsx2024", "tsx_24"):
        return CorpusConfig.tsx_esg_2024(project_root)
    if key in ("pdf_agents", "pdf_agents_esg"):
        return CorpusConfig.pdf_agents_esg_default(project_root)
    # If corpus looks like a file path, try loading as YAML directly
    yaml_path = Path(key)
    if not yaml_path.is_file():
        yaml_path = project_root / "output" / "corpus_configs" / f"{key}.yaml"
    if yaml_path.is_file():
        return CorpusConfig.from_yaml(yaml_path)
    raise SystemExit(f"Unknown --corpus {corpus!r}; use --config path/to/corpus.yaml")


_BOILERPLATE_KEYWORDS = re.compile(
    r"undertaking|consent.letter|qualification.cert|power.of.attorney|"
    r"notice.of.articles|certificate.of|statutory.declaration|material.change",
    re.IGNORECASE,
)

_SUBSTANTIVE_KEYWORDS = re.compile(
    r"md.?a|annual.report|management.discussion|aif|annual.information|"
    r"financial.statement|quarterly|interim|10.k|20.f|prospectus|circular",
    re.IGNORECASE,
)


def _sync_entity_registry_from_corpus(corpus_cfg, project_root: Path) -> None:
    """Load master issuers CSV into DuckDB when present; mirror corpus index to doc_registry."""
    from prompt2dataset.utils.entity_registry import (
        sync_doc_registry_from_index,
        sync_master_csv_to_registry,
    )

    master = getattr(corpus_cfg, "master_metadata_csv", "") or ""
    if master:
        mp = corpus_cfg.resolve(master, project_root)
        if mp.is_file():
            sync_master_csv_to_registry(mp)
    else:
        default_m = project_root / "data" / "metadata" / "master_sedar_issuers01_enriched.csv"
        if default_m.is_file():
            sync_master_csv_to_registry(default_m)
    sync_doc_registry_from_index(corpus_cfg, project_root)


def _write_trial_index(corpus_cfg, project_root: Path, n: int) -> Path | None:
    """Write a temporary index CSV of N trial PDFs.

    Selection strategy:
    1. Exclude boilerplate forms (undertakings, consents, certificates).
    2. Prefer substantive documents (MD&A, Annual Report, AIF) over generic ones.
    3. Within each group sort by smallest file (fastest to parse).
    4. Ensure company diversity: at most 2 docs per company.
       The company_name column is now reliably set by the universal recursive scanner
       from the first subdirectory of the corpus root, not from the filename.
    5. Fall back to any remaining docs if fewer than N are available after filtering.

    Returns the path to the trial index CSV, or None if the corpus index doesn't exist.
    """
    import os
    import pandas as pd
    from prompt2dataset.corpus.runtime import apply_corpus_env

    apply_corpus_env(corpus_cfg, project_root)
    idx_path = Path(os.environ.get("FILINGS_INDEX_PATH", ""))
    if not idx_path.is_file():
        return None
    df = pd.read_csv(idx_path, dtype=str)

    pdf_root_env = os.environ.get("FILINGS_PDF_ROOT", "")

    def _size(row):
        lp = str(row.get("local_path", ""))
        p = Path(lp.replace("\\", "/"))
        if not p.is_absolute() and pdf_root_env:
            p = Path(pdf_root_env) / p
        try:
            return p.stat().st_size
        except OSError:
            return 999_999_999

    df = df.copy()
    df["_sz"] = df.apply(_size, axis=1)

    # Score substantiveness using filename AND doc_type (directory-derived)
    def _substantive_score(row):
        text = " ".join([
            str(row.get("filename", "")),
            str(row.get("doc_type", "")),
        ])
        if _BOILERPLATE_KEYWORDS.search(text):
            return -1  # Penalise boilerplate
        if _SUBSTANTIVE_KEYWORDS.search(text):
            return 1
        return 0

    df["_score"] = df.apply(_substantive_score, axis=1)

    # Exclude boilerplate completely when the corpus has enough non-boilerplate docs
    non_boilerplate = df[df["_score"] >= 0]
    pool = non_boilerplate if len(non_boilerplate) >= n else df[df["_score"] >= 0].reset_index(drop=True)
    if pool.empty:
        pool = df  # last resort: take everything

    pool = pool.sort_values(["_score", "_sz"], ascending=[False, True])

    # Diverse sample: cap at max 2 docs per company
    company_col = next(
        (c for c in ("company_name", "company", "ticker") if c in pool.columns),
        None,
    )

    selected: list[dict] = []
    company_counts: dict[str, int] = {}
    for _, row in pool.iterrows():
        co = str(row.get(company_col, "unknown")).strip() if company_col else "unknown"
        # Treat blank company as "unknown" — still subject to diversity cap
        co = co or "unknown"
        if company_counts.get(co, 0) < 2:
            selected.append(row.to_dict())
            company_counts[co] = company_counts.get(co, 0) + 1
        if len(selected) >= n:
            break

    # Backfill from the full pool (incl. boilerplate) if still short
    if len(selected) < n:
        selected_idx = {r.get("doc_id", r.get("local_path", "")) for r in selected}
        id_col = "doc_id" if "doc_id" in df.columns else "local_path"
        for _, row in df.iterrows():
            if row.get(id_col) not in selected_idx:
                selected.append(row.to_dict())
            if len(selected) >= n:
                break

    out_df = pd.DataFrame(selected).drop(
        columns=[c for c in ("_sz", "_score") if c in pd.DataFrame(selected).columns],
        errors="ignore",
    )

    trial_path = idx_path.with_name(idx_path.stem + f"_trial{n}.csv")
    out_df.to_csv(trial_path, index=False)
    print(f"  Trial index: {trial_path} ({len(out_df)} rows)")
    for _, r in out_df.iterrows():
        co = r.get("company_name") or r.get("company") or "?"
        fname = Path(str(r.get("local_path", r.get("filename", "?")))).name
        score = _substantive_score(r)
        label = "substantive" if score > 0 else ("boilerplate" if score < 0 else "generic")
        print(f"    [{label}] {str(co)[:35]} — {fname[:60]}")
    return trial_path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", default="tsx_esg_2023",
                   help="Preset: sedar_tariff | sedar_prateek_filings | tsx_esg_2023 | tsx_esg_2024 | pdf_agents_esg")
    p.add_argument("--config", default="", help="YAML corpus config (overrides --corpus)")
    p.add_argument("--stage",
                   choices=("parse", "chunk", "llm_chunk", "llm_doc", "all", "ingest"),
                   default="parse",
                   help="ingest = parse+chunk only (no LLM classification); all = full SEDAR pipeline")
    p.add_argument("--no-skip", action="store_true",
                   help="Set SKIP_* env vars to recompute even if outputs exist.")
    p.add_argument("--trial-n", type=int, default=0,
                   help="Process only the N smallest PDFs (trial/sample run). 0 = full corpus.")
    p.add_argument("--run-id", default="",
                   help="Isolate outputs under output_base_dir/corpus_id/runs/RUN_ID (vault layout).")
    args = p.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    from prompt2dataset.corpus.config import corpus_with_run_id

    corpus_cfg = _load_corpus(args.corpus, args.config or None, project_root)
    corpus_cfg = corpus_with_run_id(corpus_cfg, args.run_id)

    from prompt2dataset.corpus.runtime import apply_corpus_env
    from prompt2dataset.utils.config import ensure_hf_hub_env_for_process
    import warnings

    try:
        from requests.exceptions import RequestsDependencyWarning
        warnings.filterwarnings("ignore", category=RequestsDependencyWarning)
    except Exception:
        pass

    ensure_hf_hub_env_for_process()
    applied = apply_corpus_env(corpus_cfg, project_root)
    print("Corpus:", corpus_cfg.name, f"({corpus_cfg.corpus_id})")
    for k in sorted(applied):
        print(f"  {k}={applied[k]}")

    if args.no_skip:
        for k in (
            "SKIP_PARSE_IF_EXISTS",
            "SKIP_CHUNK_IF_EXISTS",
            "SKIP_LLM_CHUNK_IF_EXISTS",
            "SKIP_LLM_DOC_IF_EXISTS",
        ):
            import os
            os.environ[k] = "0"

    # Import after env is set
    from prompt2dataset.utils.docling_pipeline import run_docling_on_filings
    from prompt2dataset.utils.chunking import run_chunking
    from prompt2dataset.utils.llm_client import run_llm_on_chunks
    from prompt2dataset.utils.doc_level import run_doc_level
    from prompt2dataset.utils.vllm_lifecycle import maybe_start_vllm_after_parse

    if args.stage in ("parse", "all", "ingest"):
        # ── Step 1: ensure the full index exists before doing anything else ──────
        import os as _os
        idx_path = Path(_os.environ.get("FILINGS_INDEX_PATH", ""))
        if not idx_path.is_file() and corpus_cfg.docs_dir:
            print(f"  [ingest] No index at {idx_path} — scanning {corpus_cfg.docs_dir} for PDFs…")
            from prompt2dataset.corpus.ingest import build_index
            try:
                df_idx = build_index(corpus_cfg, project_root)
                print(f"  [ingest] Built index: {len(df_idx)} documents")
                # Refresh idx_path after build (build_index writes to the env-configured path)
                idx_path = Path(_os.environ.get("FILINGS_INDEX_PATH", ""))
            except Exception as _e:
                print(f"  [ingest] ERROR building index: {_e}")
                raise
        elif not idx_path.is_file():
            print(f"  [ingest] WARNING: index not found at {idx_path} and no docs_dir set")

        # ── Step 2: NOW create the trial slice (index must exist first) ──────────
        if args.trial_n > 0 and idx_path.is_file():
            import os
            trial_path = _write_trial_index(corpus_cfg, project_root, args.trial_n)
            if trial_path:
                os.environ["FILINGS_INDEX_PATH"] = str(trial_path)
                print(f"  [trial] FILINGS_INDEX_PATH → {trial_path}")

        # ── Build dynamic keyword rules from corpus topic ─────────────────────
        # Replaces hardcoded tariff KEYWORD_RULES with topic-derived patterns.
        # These are used by the chunk pre-filter gate to tag keyword_hit chunks.
        from prompt2dataset.utils.nlp_utils import build_keyword_rules
        from prompt2dataset.utils.chunking import set_active_keyword_rules

        _corpus_topic = corpus_cfg.topic or ""
        if corpus_cfg.keyword_list:
            # Corpus already has a saved keyword list — rebuild rules from it
            import re as _re
            _kw_rules = []
            for kw in corpus_cfg.keyword_list:
                try:
                    escaped = _re.escape(kw).replace(r"\ ", r"[\s\-]?")
                    pat = _re.compile(rf"\b{escaped}\b", _re.I)
                    _kw_rules.append((pat, _re.sub(r"\s+", "_", kw.lower())[:30]))
                except _re.error:
                    continue
        else:
            _kw_rules = build_keyword_rules(_corpus_topic)
            if _kw_rules:
                corpus_cfg.keyword_list = [
                    kw for _, kw in _kw_rules
                ]  # persist labels for next run
        set_active_keyword_rules(_kw_rules if _kw_rules else None)
        print(f"  [chunk] Using {len(_kw_rules)} keyword rules for topic: {_corpus_topic[:60]!r}")

        # ── Incremental chunking callback ────────────────────────────────────
        # After each doc is parsed, chunk it immediately and append to the
        # chunks parquet.  This means the UI sees results after the FIRST doc
        # is ready rather than waiting for the entire corpus.
        from prompt2dataset.utils.chunking import chunk_document_path_with_fallback
        from prompt2dataset.utils.config import get_settings
        import pandas as _pd

        _settings_inc = get_settings()
        _out_parquet = _settings_inc.resolve(_settings_inc.chunks_parquet)
        _out_parquet.parent.mkdir(parents=True, exist_ok=True)
        _inc_chunks: list[dict] = []
        _inc_n_done = 0
        _inc_min_eval = args.trial_n if args.trial_n > 0 else 6

        # Seed from existing parquet (prior run) so skip-if-exists still works
        if _out_parquet.is_file():
            try:
                _prev = _pd.read_parquet(_out_parquet)
                _inc_chunks = _prev.to_dict("records")
                _inc_n_done = _prev["filing_id"].nunique() if "filing_id" in _prev.columns else 0
                print(f"  [ingest] Seeded {_inc_n_done} docs from prior chunks parquet")
            except Exception:
                pass

        def _on_doc_done(filing_id: str, doc_json_path: Path, row: "Any") -> None:
            nonlocal _inc_n_done
            new = chunk_document_path_with_fallback(
                doc_json_path, row, _settings_inc.chunk_target_tokens
            )
            if not new:
                print(
                    f"[CHUNK_ZERO] {filing_id} — Docling JSON produced no chunks "
                    "(empty text after parse?).",
                    flush=True,
                )
                return
            fid = str(filing_id)
            # Replace any prior rows for this filing (skip/re-chunk must not duplicate).
            _inc_chunks[:] = [c for c in _inc_chunks if str(c.get("filing_id")) != fid]
            _inc_chunks.extend(c.model_dump() for c in new)
            _out_df = _pd.DataFrame(_inc_chunks)
            _out_df.to_parquet(_out_parquet, index=False)
            _inc_n_done = (
                int(_out_df["filing_id"].nunique())
                if "filing_id" in _out_df.columns
                else _inc_n_done + 1
            )
            total_c = len(_inc_chunks)
            print(f"[PARSE_PROGRESS] {_inc_n_done} {total_c}")
            if _inc_n_done == _inc_min_eval:
                print("[EXTRACTION_READY]")
            # Also update after EVERY subsequent doc so the queue grows
            if _inc_n_done > _inc_min_eval:
                print(f"[QUEUE_GREW] {_inc_n_done}")

        _parse_result_df = run_docling_on_filings(force=args.no_skip, on_doc_done=_on_doc_done)
        maybe_start_vllm_after_parse()
        try:
            _sync_entity_registry_from_corpus(corpus_cfg, project_root)
        except Exception as _reg_exc:
            print(f"  [entity_registry] sync skipped: {_reg_exc}")
        if _inc_n_done == 0:
            ok_parse = 0
            try:
                if (
                    _parse_result_df is not None
                    and not _parse_result_df.empty
                    and "parse_status" in _parse_result_df.columns
                ):
                    ok_parse = int(
                        _parse_result_df["parse_status"].str.startswith("OK", na=False).sum()
                    )
            except Exception:
                ok_parse = 0
            if ok_parse > 0:
                print(
                    "[PARSE_ZERO_CHUNKS] Docling reported "
                    f"{ok_parse} successful parse(s) but incremental chunking wrote zero rows. "
                    "Common causes: chunk validation failed (now retried with a text fallback), "
                    "or every PDF resolved as PDF_MISSING. Check ingest log for [CHUNK_ZERO]. "
                    "Recovery: `python scripts/run_corpus_pipeline.py --config <yaml> --stage chunk`."
                )
            else:
                print(
                    "[PARSE_ZERO_DOCS] No documents were parsed. Check that the PDF folder exists "
                    "and contains .pdf files."
                )

        # Auto-detect if chunks parquet is missing (parse completed but chunk never ran)
        _out_parquet_check = Path(_settings_inc.resolve(_settings_inc.chunks_parquet))
        if not _out_parquet_check.is_file() and _inc_n_done > 0:
            print(f"  [ingest] WARNING: {_inc_n_done} docs parsed but chunks.parquet not found.")
            print(f"  [ingest] This can happen if a previous session was interrupted mid-chunk.")
            print(f"  [ingest] Re-running batch chunker to recover...")
            run_chunking(force=True)

    if args.stage == "chunk":
        try:
            _sync_entity_registry_from_corpus(corpus_cfg, project_root)
        except Exception as _reg_exc:
            print(f"  [entity_registry] sync skipped: {_reg_exc}")

    if args.stage in ("chunk", "all", "ingest"):
        # Only run the batch chunker if we DON'T have an incremental parquet
        # (i.e. the on_doc_done callback wasn't active — e.g. explicit chunk stage).
        _settings_chk = get_settings() if "get_settings" in dir() else None
        if _settings_chk:
            _chk_parquet = _settings_chk.resolve(_settings_chk.chunks_parquet)
            if _chk_parquet.is_file():
                print(f"  [chunk] Incremental parquet exists ({_chk_parquet.stat().st_size // 1024}KB) — skipping batch re-chunk")
            else:
                run_chunking(force=args.no_skip)
        else:
            run_chunking(force=args.no_skip)

        # Register corpus and chunks in the lakehouse
        try:
            from prompt2dataset.utils.lakehouse import Lakehouse
            lh = Lakehouse()
            lh.register_corpus(corpus_cfg, project_root=project_root, source_kind="pipeline")
            _chk_path = _settings_chk.resolve(_settings_chk.chunks_parquet) if _settings_chk else None
            if _chk_path and _chk_path.is_file():
                import pandas as _pd2
                _chunks_df = _pd2.read_parquet(_chk_path)
                lh.index_corpus_chunks(
                    corpus_cfg.corpus_id,
                    _chunks_df,
                    overwrite=False,
                    corpus_cfg=corpus_cfg,
                )
                print(f"  [lakehouse] Registered {len(_chunks_df)} chunks for corpus {corpus_cfg.corpus_id}")
        except Exception as _lh_exc:
            print(f"  [lakehouse] Registration skipped: {_lh_exc}")
    if args.stage in ("llm_chunk", "all"):
        run_llm_on_chunks(force=args.no_skip)
    if args.stage in ("llm_doc", "all"):
        run_doc_level(force=args.no_skip)

    print("Done:", args.stage)


if __name__ == "__main__":
    main()
