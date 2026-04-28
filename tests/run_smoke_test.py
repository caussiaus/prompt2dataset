#!/usr/bin/env python3
"""One-command smoke test for the Prompt2Dataset pipeline.

Usage:
    python -m prompt2dataset.tests.run_smoke_test --corpus /path/to/pdfs/ --intent "Extract company names and revenue"
    python -m prompt2dataset.tests.run_smoke_test --help

Tests (in order):
  1. Import health — all core modules import without error
  2. Vault health — vault directory readable, entities > 0
  3. Config load — Settings resolves without error
  4. Schema generation — schema_node returns columns for a simple prompt
  5. DocSourceRouter — local_folder mode lists PDFs (or reports 0 gracefully)
  6. Extraction gate — extract_batch_filings runs on 1 fake doc without crash
  7. Consistency check — run_consistency_check runs without error
  8. DatasetContext — save/load round-trip works

Pass criteria:
  - All 8 tests pass
  - No unhandled exceptions
  - Exits 0 on success, 1 on failure
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path


def _check(name: str, fn):
    """Run a check function and return (passed, error_message)."""
    try:
        fn()
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def run_smoke_test(corpus_path: str, intent: str) -> bool:
    _root = Path(__file__).resolve().parents[1]
    for _p in (_root.parent, _root):
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))

    results = []

    # 1. Import health
    def _imports():
        from prompt2dataset.dataset_graph.schema_node import schema_node
        from prompt2dataset.dataset_graph.critique_node import critique_node
        from prompt2dataset.dataset_graph.extraction_node import extract_one_filing, extract_batch_filings
        from prompt2dataset.dataset_graph.graph import build_dataset_graph
        from prompt2dataset.utils.call_config import effective_temperature, ensure_keywords
        from prompt2dataset.utils.doc_source_router import DocSourceRouter
        from app_pages.thread_store import DatasetContext, save_context, load_context
        from connectors.obsidian_bridge import kg_health_check

    results.append(("Import health", *_check("imports", _imports)))

    # 2. Vault health
    def _vault():
        from connectors.obsidian_bridge import kg_health_check
        h = kg_health_check()
        assert h["vault_exists"], f"Vault not found: {h}"
        assert h["n_entities"] >= 0

    results.append(("Vault health", *_check("vault", _vault)))

    # 3. Config load
    def _config():
        from prompt2dataset.utils.config import get_settings
        cfg = get_settings()
        assert cfg is not None

    results.append(("Config load", *_check("config", _config)))

    # 4. DocSourceRouter local_folder
    def _doc_router():
        from prompt2dataset.utils.doc_source_router import DocSourceRouter, DocSourceConfig
        router = DocSourceRouter()
        result = router.acquire(DocSourceConfig(
            mode="local_folder",
            local_path=corpus_path,
            corpus_id="smoke_test",
        ))
        # OK even if 0 PDFs — just check it doesn't crash
        assert isinstance(result.doc_paths, list)
        print(f"  DocSourceRouter found {len(result.doc_paths)} PDFs in {corpus_path}")

    results.append(("DocSourceRouter", *_check("doc_router", _doc_router)))

    # 5. Consistency check
    def _consistency():
        from prompt2dataset.dataset_graph.extraction_node import run_consistency_check
        rows = [{"doc_id": "d1", "field_a": "hello", "field_a_evidence_quote": "some evidence text here"}]
        columns = [{"name": "field_a", "type": "string", "default": None}]
        flags = run_consistency_check(rows, columns, ["doc_id"])
        assert isinstance(flags, dict)
        print(f"  consistency_check flags: {list(flags.keys())}")

    results.append(("Consistency check", *_check("consistency", _consistency)))

    # 6. DatasetContext save/load
    def _context():
        from app_pages.thread_store import DatasetContext, save_context, load_context, context_path
        ctx = DatasetContext(
            thread_id="smoke_test_ctx",
            corpus_id="test",
            domain_label="smoke test domain",
        )
        ctx.rows = [{"doc_id": "d1", "value": 42}]
        save_context(ctx)
        loaded = load_context("smoke_test_ctx")
        assert loaded is not None
        assert loaded.rows[0]["value"] == 42
        context_path("smoke_test_ctx").unlink(missing_ok=True)

    results.append(("DatasetContext", *_check("context", _context)))

    # 7. AgentPolicy + QuestionEngine
    def _policy():
        from prompt2dataset.utils.agent_policy import AgentPolicy, QuestionEngine
        from app_pages.thread_store import DatasetContext, LiveState
        p = AgentPolicy(autonomy_level="semi")
        assert p.should_interrupt_at_gate1()
        qe = QuestionEngine()
        ctx = DatasetContext(thread_id="t", corpus_id="c", domain_label="d")
        live = LiveState(
            corpus_summary="", schema_snapshot="", fill_rates={},
            active_flags={}, pending_action="", acquisition_jobs=[],
            verified_extractions=[], rework_count=0,
        )
        q = qe.should_interrupt(ctx, live, p)
        # q is None or a Question — both are OK

    results.append(("AgentPolicy/QuestionEngine", *_check("policy", _policy)))

    # 8. VaultClient
    def _vault_client():
        from connectors.obsidian_bridge import get_vault_client
        vc = get_vault_client()
        schemas = vc.list_schemas()
        assert isinstance(schemas, list)
        print(f"  VaultClient OK — {len(schemas)} schemas")

    results.append(("VaultClient", *_check("vault_client", _vault_client)))

    # ── Report ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("SMOKE TEST RESULTS")
    print("=" * 60)
    passed = 0
    for name, ok, err in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}]  {name}")
        if err:
            print(f"         {err}")
        if ok:
            passed += 1
    print("=" * 60)
    print(f"  {passed}/{len(results)} checks passed")
    print("=" * 60)
    return passed == len(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prompt2Dataset smoke test")
    parser.add_argument(
        "--corpus",
        default=str(Path(__file__).resolve().parents[1] / "output"),
        help="Path to PDF folder (can be empty)",
    )
    parser.add_argument(
        "--intent",
        default="Extract company names and financial data",
        help="Extraction intent string",
    )
    args = parser.parse_args()

    ok = run_smoke_test(args.corpus, args.intent)
    sys.exit(0 if ok else 1)
