# prompt2dataset (PDF → structured dataset)

Canonical **application and Python package** for the Streamlit + Docling + LangGraph dataset builder. It lives under **ISF-PEECEE** next to the rest of your automation (`pipeline-scripts/`, `library/`, etc.).

## Layout

| Path | Role |
|------|------|
| `app.py` | Streamlit entry |
| `app_pages/` | Workspace UI, chat, table, pipeline runner |
| `dataset_graph/` | LangGraph pipeline (schema, extraction, critique, council, export) |
| `corpus/` | Corpus config, ingest, paths, runtime |
| `utils/` | Docling, chunking, vLLM client, retrieval, `config.Settings` |
| `prompts/` | LLM prompt builders |
| `state.py` | Chunk/doc record helpers for headless SFT builders |
| `watcher.py` | Optional filesystem watcher |
| `tests/` | pytest; smoke: `python -m prompt2dataset.tests.run_smoke_test` |
| `connectors/` | Obsidian bridge, optional scrape/network helpers |
| `config/` | YAML knobs (e.g. `prompt2dataset.yaml`) |
| `scripts/` | Headless corpus pipeline, dataset build, diagnostics, `run_autonomy_cycle.py` |
| `AUTONOMY_LOOP.md` | Claw/automation: controller + wonder queue + optional council |
| `training_events.py` | Append-only trajectory log for RLHF / PRM / DPO rollups |
| `__init__.py` | Package exports (`build_dataset_graph`, `DatasetState`, training helpers) |

## Python path

Entrypoints put **both** directories on `sys.path`:

1. **ISF-PEECEE** (parent of this folder) — so `import prompt2dataset` resolves (`prompt2dataset.dataset_graph`, `prompt2dataset.utils`, …).
2. **This directory** — so `import app_pages`, `import connectors` also resolve (Streamlit sibling packages).

`app.py` and `scripts/*.py` bootstrap this automatically.

## Run the UI

From ISF-PEECEE:

```bash
bash scripts/run_prompt2dataset_ui.sh
```

Or:

```bash
python3 pipeline-scripts/prompt2dataset/run_prompt2dataset.py workspace --port 8501
```

Or directly:

```bash
cd prompt2dataset && source .venv/bin/activate  # or ISF-PEECEE/.venv
pip install -r requirements.txt   # first time
streamlit run app.py --server.port 8501
```

Set vLLM and related vars in `.env` (see `.env.example`).

## Run headless ingest

```bash
cd prompt2dataset
python scripts/run_corpus_pipeline.py --corpus tsx_esg_2023 --stage ingest --trial-n 1
```

## Environment

- **`PROMPT2DATASET_ROOT`** — override app root (default: `ISF-PEECEE/prompt2dataset`).
- **`PROMPT2DATASET_FEEDBACK_DIR`** — base dir for `training_events.jsonl` when not using `datasets_export_dir` / custom path (see `training_events.py`).
- **`TRAINING_EVENTS_DISABLE`** — disable trajectory JSONL (`1` / `true` / `yes` / `on`).
- **`PROJECT_ROOT`** — optional; `prompt2dataset.utils.config.Settings` may use it to relocate `project_root` (defaults to this app directory).

## Upstream git

Historical development tracked **`caussiaus/pipeline`** (formerly checked out as `tariff-sedar-pipeline`). This tree is the **in-repo home** for ongoing work; sync or compare against that remote as needed.

## Related

- **Autonomy tick (Claw, controller, wonder queue, optional council):** [`AUTONOMY_LOOP.md`](./AUTONOMY_LOOP.md)
- **Roadmap (stigmergic / wonder queue / grounding / training loop):** [`../project-outlines/prompt2dataset-stigmergic-roadmap.md`](../project-outlines/prompt2dataset-stigmergic-roadmap.md)
- **All local services (vLLM, app, scrape, health checks):** [`../LOCAL-SERVICES.md`](../LOCAL-SERVICES.md)
- Launchers and PM entry points: [`pipeline-scripts/prompt2dataset/`](../pipeline-scripts/prompt2dataset/)
- Registry entries: [`pipeline-scripts/registry.yaml`](../pipeline-scripts/registry.yaml)
