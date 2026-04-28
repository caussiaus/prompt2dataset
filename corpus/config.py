"""Corpus configuration — makes the dataset pipeline corpus-agnostic.

A CorpusConfig describes *any* PDF corpus: where the documents live,
what metadata fields each document has, where pipeline outputs go.

The existing SEDAR tariff pipeline is one instance of this; a corpus
of SEC 10-K filings or clinical trial reports is another.

Save/load via YAML so configs persist across sessions:

    corpus = CorpusConfig.from_yaml("my_corpus.yaml")
    corpus.to_yaml("my_corpus.yaml")
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from prompt2dataset.corpus.paths import normalize_host_path


_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def _slugify(s: str) -> str:
    return _SLUG_RE.sub("_", s.lower().strip()).strip("_") or "corpus"


def default_pipeline_output_base_dir() -> str:
    """Production default: library vault. Override with PIPELINE_OUTPUT_BASE_DIR."""
    return os.environ.get(
        "PIPELINE_OUTPUT_BASE_DIR",
        "/home/casey/library/pipeline-output/prompt2dataset",
    )


def new_run_id() -> str:
    """UTC date + short uuid — unique per pipeline/workspace run."""
    return f"run_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"


# Paths derived in __post_init__ (safe to clear when rebasing under runs/{run_id})
_OUTPUT_PATH_FIELDS = (
    "index_csv",
    "doc_json_dir",
    "parse_index_csv",
    "chunks_parquet",
    "chunks_llm_parquet",
    "filings_llm_parquet",
    "docs_llm_csv",
    "consistency_report_csv",
    "datasets_dir",
    "feedback_dir",
)


def corpus_with_run_id(cfg: "CorpusConfig", run_id: str) -> "CorpusConfig":
    """Return a copy with ``run_id`` set and output paths re-derived under ``runs/{run_id}/``.

    Paths under ``output_base_dir / corpus_id`` are cleared so ``__post_init__`` fills
    new locations. Metadata paths outside that tree (e.g. ``data/metadata/*.csv``) are kept.
    """
    rid = (run_id or "").strip()
    if not rid:
        return cfg
    d = asdict(cfg)
    d["run_id"] = rid
    try:
        old_base = (Path(d["output_base_dir"]).expanduser().resolve() / d["corpus_id"])
        old_base_s = str(old_base)
    except Exception:
        old_base_s = ""
    if old_base_s:
        for key in _OUTPUT_PATH_FIELDS:
            val = d.get(key) or ""
            if not val:
                continue
            try:
                p_s = str(Path(val).expanduser().resolve())
            except Exception:
                continue
            if p_s == old_base_s or p_s.startswith(old_base_s + os.sep):
                d[key] = ""
    return CorpusConfig(**d)


# ---------------------------------------------------------------------------
# File-structure patterns
# ---------------------------------------------------------------------------

FILE_PATTERNS = {
    "auto": {
        "description": (
            "Universal recursive scanner — works for any folder dump. "
            "company_name = first subdirectory, doc_type = second subdirectory, "
            "date extracted from filename. No configuration needed."
        ),
        "example": "company_name/filing_type/2024-03_annual_report.pdf",
    },
    "csv_manifest": {
        "description": "Metadata CSV with a local_path column pointing to each PDF",
        "example": "metadata.csv + local_path column",
    },
}


# ---------------------------------------------------------------------------
# CorpusConfig
# ---------------------------------------------------------------------------

@dataclass
class CorpusConfig:
    # Identity
    name: str                           # "SEDAR Tariff Filings 2023-2025"
    corpus_id: str                      # slug: "sedar_tariff"
    topic: str                          # "tariff exposure in MD&A" — guides schema design prompt

    # Source documents
    docs_dir: str                       # absolute or relative path to PDF root
    file_pattern: str = "auto"          # "auto" (universal recursive) or "csv_manifest"
    file_glob: str = "**/*.pdf"         # unused for "auto"; kept for csv_manifest compat

    # Metadata
    metadata_csv: str = ""              # optional: path to pre-existing metadata CSV
    doc_id_field: str = "doc_id"        # column that is the canonical row key
    doc_path_field: str = "local_path"  # column with path to the PDF
    # path_md5 — stable per path (legacy). content_sample — fingerprint from PDF bytes
    # (matches ``ingest_cache``); same file under different paths / corpora shares identity.
    filing_id_strategy: str = "path_md5"
    identity_fields: list[str] = field(default_factory=lambda: [
        "doc_id", "entity_id", "company_name", "date",
    ])                                  # columns carried as identity in every dataset row
    extra_context_fields: list[str] = field(default_factory=list)
    # e.g. ["sector", "country"] — included in extraction prompt for NAICS-like context

    # Pipeline outputs — under output_base_dir / corpus_id [/ runs / run_id]
    output_base_dir: str = field(default_factory=default_pipeline_output_base_dir)
    # Derived paths (overridable)
    index_csv: str = ""
    chunks_parquet: str = ""
    chunks_llm_parquet: str = ""
    docs_llm_csv: str = ""
    datasets_dir: str = ""
    feedback_dir: str = ""
    # Docling / Pass-2 paths (default under ``output/{corpus_id}/``)
    doc_json_dir: str = ""
    parse_index_csv: str = ""
    filings_llm_parquet: str = ""
    consistency_report_csv: str = ""
    # When index ``local_path`` is relative (SEDAR), set to PDF root (WSL path OK).
    filings_pdf_root_env: str = ""
    # If set, artifact paths are rooted at output_base_dir/corpus_id/runs/{run_id}/
    run_id: str = ""

    # External metadata enrichment (optional — no-op if empty)
    master_metadata_csv: str = ""       # path to master enriched issuers CSV (e.g. master_sedar_issuers01_enriched.csv)
    supplemental_metadata_csv: str = "" # path to supplemental CSV (e.g. WRDS financial data)

    # Dynamic keyword rules (auto-generated from topic at corpus setup time)
    # Serialised as a JSON list of keyword strings; rebuilt into regex rules at runtime.
    # This makes the keyword pre-filter domain-agnostic — any topic works.
    keyword_list: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.corpus_id:
            self.corpus_id = _slugify(self.name)
        base = Path(self.output_base_dir) / self.corpus_id
        if (self.run_id or "").strip():
            base = base / "runs" / self.run_id.strip()
        if not self.index_csv:
            self.index_csv = str(base / "index.csv")
        if not self.doc_json_dir:
            self.doc_json_dir = str(base / "docling_json")
        if not self.parse_index_csv:
            self.parse_index_csv = str(base / "docling_parse_index.csv")
        if not self.chunks_parquet:
            self.chunks_parquet = str(base / "chunks" / "chunks.parquet")
        if not self.chunks_llm_parquet:
            self.chunks_llm_parquet = str(base / "llm_raw" / "chunks_llm.parquet")
        if not self.filings_llm_parquet:
            self.filings_llm_parquet = str(base / "llm_docs" / "filings_llm.parquet")
        if not self.docs_llm_csv:
            self.docs_llm_csv = str(base / "csv" / "docs_llm.csv")
        if not self.consistency_report_csv:
            self.consistency_report_csv = str(base / "csv" / "filings_llm_consistency.csv")
        if not self.datasets_dir:
            self.datasets_dir = str(base / "datasets")
        if not self.feedback_dir:
            self.feedback_dir = str(base / "feedback")

    # ── Serialisation ──────────────────────────────────────────────────

    def to_yaml(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(asdict(self), f, default_flow_style=False, sort_keys=False)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "CorpusConfig":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CorpusConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    # ── Resolve paths relative to a project root ───────────────────────

    def resolve(self, path: str, root: Path | None = None) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        if root:
            return root / p
        return Path.cwd() / p

    def output_dir(self, root: Path | None = None) -> Path:
        d = self.resolve(self.output_base_dir, root) / self.corpus_id
        if (self.run_id or "").strip():
            d = d / "runs" / self.run_id.strip()
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── SEDAR default ──────────────────────────────────────────────────

    @classmethod
    def sedar_default(cls, project_root: Path) -> "CorpusConfig":
        """Pre-configured instance for the existing SEDAR tariff pipeline."""
        root = str(project_root)
        return cls(
            name="SEDAR Tariff Filings 2023-2025",
            corpus_id="sedar_tariff",
            topic="tariff exposure, supply chain risk, and trade policy impact in Canadian company MD&A and AIF filings",
            docs_dir=str(project_root / "raw_data" / "pdfs"),
            file_pattern="csv_manifest",
            metadata_csv=str(project_root / "data" / "metadata" / "filings_index.csv"),
            doc_id_field="filing_id",
            doc_path_field="local_path",
            identity_fields=[
                "filing_id", "entity_id", "ticker", "issuer_name", "profile_number",
                "filing_date", "filing_type",
            ],
            extra_context_fields=["naics_sector", "mechanism", "exposure_vector"],
            output_base_dir=str(project_root / "output"),
            index_csv=str(project_root / "data" / "metadata" / "filings_index.csv"),
            doc_json_dir=str(project_root / "output" / "docling_json"),
            parse_index_csv=str(project_root / "output" / "docling_parse_index.csv"),
            chunks_parquet=str(project_root / "output" / "chunks" / "chunks.parquet"),
            chunks_llm_parquet=str(project_root / "output" / "llm_raw" / "chunks_llm.parquet"),
            filings_llm_parquet=str(project_root / "output" / "llm_docs" / "filings_llm.parquet"),
            docs_llm_csv=str(project_root / "output" / "csv" / "filings_llm.csv"),
            consistency_report_csv=str(project_root / "output" / "csv" / "filings_llm_consistency.csv"),
            datasets_dir=str(project_root / "output" / "datasets"),
            feedback_dir=str(project_root / "output" / "feedback"),
            filings_pdf_root_env="",
        )

    @classmethod
    def sedar_prateek_filings(cls, project_root: Path) -> "CorpusConfig":
        """Same SEDAR index as production; PDF root = prateek portable scrape folder.

        Set this when ``filings_index.csv`` uses paths relative to that directory
        (e.g. ``issuer_slug/general/file.pdf``).
        """
        base = cls.sedar_default(project_root)
        root_nt = normalize_host_path(
            r"C:\Users\casey\ISF\greenyield\sedar_scrape_portable\sedar_scrape_portable\data\prateek\filings"
        )
        return CorpusConfig(
            **{
                **asdict(base),
                "name": "SEDAR filings (prateek portable root)",
                "corpus_id": "sedar_prateek_filings",
                "filings_pdf_root_env": str(root_nt),
            }
        )

    @classmethod
    def tsx_esg_2023(cls, project_root: Path) -> "CorpusConfig":
        root = Path(project_root)
        docs = normalize_host_path(
            r"C:\Users\casey\ISF\ISF Research team\1. Project\TSX Report\2023\TSX_2023_ESGReports"
        )
        idx = root / "data" / "metadata" / "corpus_tsx_esg_2023_index.csv"
        return cls(
            name="TSX ESG reports 2023",
            corpus_id="tsx_esg_2023",
            topic=(
                "Environmental, social, and governance (ESG) disclosures, sustainability metrics, "
                "climate risk and TCFD-style reporting for TSX-listed issuers (2023 cohort)"
            ),
            docs_dir=str(docs),
            file_pattern="csv_manifest",
            metadata_csv=str(idx),
            doc_id_field="filing_id",
            doc_path_field="local_path",
            identity_fields=[
                "filing_id", "entity_id", "ticker", "issuer_name", "filing_type", "filing_date",
            ],
            extra_context_fields=[],
            output_base_dir=default_pipeline_output_base_dir(),
            index_csv=str(idx),
        )

    @classmethod
    def tsx_esg_2024(cls, project_root: Path) -> "CorpusConfig":
        root = Path(project_root)
        docs = normalize_host_path(
            r"C:\Users\casey\ISF\ISF Research team\1. Project\TSX Report\2024\ESG Reports 2024"
        )
        idx = root / "data" / "metadata" / "corpus_tsx_esg_2024_index.csv"
        return cls(
            name="TSX ESG reports 2024",
            corpus_id="tsx_esg_2024",
            topic=(
                "Environmental, social, and governance (ESG) disclosures, sustainability metrics, "
                "and climate-related reporting for TSX-listed issuers (2024 cohort)"
            ),
            docs_dir=str(docs),
            file_pattern="csv_manifest",
            metadata_csv=str(idx),
            doc_id_field="filing_id",
            doc_path_field="local_path",
            identity_fields=[
                "filing_id", "entity_id", "ticker", "issuer_name", "filing_type", "filing_date",
            ],
            extra_context_fields=[],
            output_base_dir=default_pipeline_output_base_dir(),
            index_csv=str(idx),
        )

    @classmethod
    def pdf_agents_esg_default(cls, project_root: Path) -> "CorpusConfig":
        """Corpus from ``~/pdf-agents/PDFs`` (ESG / integrated reports sample set).

        PDFs live outside this repo; ``local_path`` in the index is absolute so
        Docling resolves files without ``FILINGS_PDF_ROOT``.  Outputs for parse /
        chunk / LLM stages go under ``output/pdf_agents_esg/`` — run the main
        pipeline with ``FILINGS_INDEX_PATH`` / chunk paths pointed here, or ingest
        via a future corpus-specific runner.

        On disk today (typical): 2 non-empty PDFs + one empty placeholder.
        """
        root = Path(project_root)
        pdf_dir = Path.home() / "pdf-agents" / "PDFs"
        ob = Path(default_pipeline_output_base_dir())
        return cls(
            name="pdf-agents ESG / integrated reports (sample)",
            corpus_id="pdf_agents_esg",
            topic=(
                "ESG metrics, climate risk, governance, and sustainability disclosures "
                "in corporate ESG and integrated annual reports"
            ),
            docs_dir=str(pdf_dir),
            file_pattern="csv_manifest",
            metadata_csv=str(root / "data" / "metadata" / "pdf_agents_index.csv"),
            doc_id_field="filing_id",
            doc_path_field="local_path",
            identity_fields=[
                "filing_id",
                "entity_id",
                "issuer_name",
                "filing_type",
                "filing_date",
                "ticker",
            ],
            extra_context_fields=[],
            output_base_dir=str(ob),
            index_csv=str(root / "data" / "metadata" / "pdf_agents_index.csv"),
            chunks_parquet=str(ob / "pdf_agents_esg" / "chunks" / "chunks.parquet"),
            chunks_llm_parquet=str(ob / "pdf_agents_esg" / "llm_raw" / "chunks_llm.parquet"),
            docs_llm_csv=str(ob / "pdf_agents_esg" / "csv" / "docs_llm.csv"),
            datasets_dir=str(ob / "pdf_agents_esg" / "datasets"),
            feedback_dir=str(ob / "pdf_agents_esg" / "feedback"),
        )
