from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_project_root() -> Path:
    # ``utils/config.py`` lives at ``prompt2dataset/utils/`` — package root is one level up.
    return Path(__file__).resolve().parents[1]


def isf_repo_root() -> Path:
    """``prompt2dataset/utils/config.py`` → ``ISF-PEECEE`` repo root (parent of ``prompt2dataset/``)."""
    return Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_root: Path = Field(default_factory=_default_project_root)

    vllm_base_url: str = Field(
        default="http://127.0.0.1:8430/v1",
        validation_alias=AliasChoices("VLLM_BASE_URL"),
    )
    vllm_api_key: str = Field(default="EMPTY", validation_alias=AliasChoices("VLLM_API_KEY"))
    # Served id from GET {VLLM_BASE_URL}/models — typically Qwen3.6-27B AWQ INT4 on vLLM with Marlin where enabled.
    vllm_model_name: str = Field(
        default="cyankiwi/Qwen3.6-27B-AWQ-INT4",
        validation_alias=AliasChoices("VLLM_MODEL_NAME"),
    )
    vllm_max_tokens: int = Field(default=3000, validation_alias=AliasChoices("VLLM_MAX_TOKENS"))
    # Hard limit from vLLM / model (input + output must fit). Used to cap Pass-1 chunk body + overhead.
    vllm_model_max_context_tokens: int = Field(
        default=110_000,
        validation_alias=AliasChoices("VLLM_MODEL_MAX_CONTEXT_TOKENS"),
    )
    # Reserve for system prompt, user wrapper, JSON instructions, and tokenizer mismatch vs estimate_tokens().
    llm_chunk_prompt_reserve_tokens: int = Field(
        default=12_000,
        validation_alias=AliasChoices("LLM_CHUNK_PROMPT_RESERVE_TOKENS"),
    )
    # Pass-1 completion budget (structured JSON can exceed 2048). Pass-2 still uses VLLM_MAX_TOKENS × 1.5 floor.
    llm_chunk_max_tokens: int = Field(
        default=4096,
        validation_alias=AliasChoices("LLM_CHUNK_MAX_TOKENS"),
    )
    vllm_temperature: float = Field(default=0.0, validation_alias=AliasChoices("VLLM_TEMPERATURE"))
    vllm_top_p: float = Field(default=1.0, validation_alias=AliasChoices("VLLM_TOP_P"))
    # In-flight HTTP requests (flood vLLM CB queue); start ~32 on 4090 AWQ Marlin, raise if SM util <85%.
    # No VLLM_BATCH_SIZE — throughput is asyncio.gather + this semaphore + vLLM continuous batching.
    vllm_max_concurrent_requests: int = Field(
        default=32,
        validation_alias=AliasChoices("VLLM_MAX_CONCURRENT_REQUESTS", "VLLM_CONCURRENCY"),
    )
    # Bound asyncio.gather fan-out for Pass-1 (real LLM rows only); semaphore still caps live HTTP.
    llm_chunk_gather_batch_size: int = Field(
        default=512,
        validation_alias=AliasChoices("LLM_CHUNK_GATHER_BATCH_SIZE"),
    )
    # After this many new LLM completions, merge with prior parquet and flush (0 = only at end of stage).
    llm_chunk_checkpoint_every: int = Field(
        default=250,
        validation_alias=AliasChoices("LLM_CHUNK_CHECKPOINT_EVERY"),
    )
    vllm_timeout_sec: float = Field(default=600.0, validation_alias=AliasChoices("VLLM_TIMEOUT_SEC"))
    vllm_max_retries: int = Field(default=4, validation_alias=AliasChoices("VLLM_MAX_RETRIES"))
    # json_schema (OpenAI SDK), json_object, or none/off. If USE_GUIDED_DECODING, json_schema may be
    # downgraded client-side to json_object while schema is sent as extra_body guided_json (vLLM).
    vllm_response_format: str = Field(
        default="json_object",
        validation_alias=AliasChoices("VLLM_RESPONSE_FORMAT"),
    )
    # vLLM OpenAI-compat: pass-through fields in extra_body (see async_llm_client._build_vllm_extra_body).
    use_guided_decoding: bool = Field(default=True, validation_alias=AliasChoices("USE_GUIDED_DECODING"))
    # Qwen3: JSON string parsed into extra_body["chat_template_kwargs"] (e.g. enable_thinking false).
    vllm_chat_template_kwargs_json: str = Field(
        default='{"enable_thinking": false}',
        validation_alias=AliasChoices("VLLM_CHAT_TEMPLATE_KWARGS"),
    )
    # After Docling, optionally `systemctl start` this unit then wait for VLLM_BASE_URL /v1/models (e.g. thomas-vllm).
    pipeline_vllm_systemd_unit: str = Field(
        default="",
        validation_alias=AliasChoices("PIPELINE_VLLM_SYSTEMD_UNIT"),
    )
    pipeline_vllm_start_timeout_sec: float = Field(
        default=600.0,
        validation_alias=AliasChoices("PIPELINE_VLLM_START_TIMEOUT_SEC"),
    )
    # Optional bash script to spawn vLLM after Docling when no systemd unit is set (path must exist).
    vllm_start_script: str = Field(default="", validation_alias=AliasChoices("VLLM_START_SCRIPT"))

    # Default CSV when no corpus-scoped path in DatasetState / CorpusConfig — not the only index.
    filings_index_path: str = Field(
        default="data/metadata/filings_index.csv",
        validation_alias=AliasChoices("FILINGS_INDEX_PATH"),
    )
    tickers_path: str = Field(
        default="data/metadata/tickers_with_profiles.csv",
        validation_alias=AliasChoices("TICKERS_PATH"),
    )
    # Master SEDAR issuer CSV with NAICS codes for sector enrichment (can be Windows /mnt/c path in WSL).
    sedar_master_issuers_path: str = Field(
        default="data/metadata/master_sedar_issuers01_enriched.csv",
        validation_alias=AliasChoices("SEDAR_MASTER_ISSUERS_PATH"),
    )
    doc_json_dir: str = Field(default="output/docling_json", validation_alias=AliasChoices("DOC_JSON_DIR"))
    chunks_parquet: str = Field(
        default="output/chunks/chunks.parquet",
        validation_alias=AliasChoices("CHUNKS_PARQUET"),
    )
    parse_index_csv: str = Field(
        default="output/docling_parse_index.csv",
        validation_alias=AliasChoices("PARSE_INDEX_CSV"),
    )
    chunks_llm_parquet: str = Field(
        default="output/llm_raw/chunks_llm.parquet",
        validation_alias=AliasChoices("CHUNKS_LLM_PARQUET"),
    )
    filings_llm_parquet: str = Field(
        default="output/llm_docs/filings_llm.parquet",
        validation_alias=AliasChoices("FILINGS_LLM_PARQUET"),
    )
    filings_llm_csv: str = Field(
        default="output/csv/filings_llm.csv",
        validation_alias=AliasChoices("FILINGS_LLM_CSV"),
    )
    issuer_year_csv: str = Field(
        default="output/csv/issuer_year_tariff_signals.csv",
        validation_alias=AliasChoices("ISSUER_YEAR_CSV"),
    )
    consistency_report_csv: str = Field(
        default="output/csv/filings_llm_consistency.csv",
        validation_alias=AliasChoices("CONSISTENCY_REPORT_CSV"),
    )
    review_csv: str = Field(
        default="output/human_review/review_ready.csv",
        validation_alias=AliasChoices("REVIEW_CSV"),
    )
    # Directory for interactively generated custom datasets
    datasets_dir: str = Field(
        default="output/datasets",
        validation_alias=AliasChoices("DATASETS_DIR"),
    )

    # Empty = LangGraph InMemorySaver only. Set for cross-session resume (sync SqliteSaver + invoke).
    checkpoint_sqlite_path: str = Field(
        default="",
        validation_alias=AliasChoices("CHECKPOINT_SQLITE_PATH"),
    )

    filings_pdf_root: str = Field(default="", validation_alias=AliasChoices("FILINGS_PDF_ROOT"))
    # Per-ticker JSON mirrors: output/companies/{ticker}/{filing_id}_filing_llm.json
    companies_output_dir: str = Field(
        default="output/companies",
        validation_alias=AliasChoices("COMPANIES_OUTPUT_DIR"),
    )

    chunk_target_tokens: int = Field(default=1200, validation_alias=AliasChoices("CHUNK_TARGET_TOKENS"))

    # Docling: layout/table/OCR stack. With CUDA PyTorch, use auto or cuda (see DOCLING_DEVICE in .env.example).
    docling_device: str = Field(default="auto", validation_alias=AliasChoices("DOCLING_DEVICE"))
    docling_num_threads: int = Field(default=4, validation_alias=AliasChoices("DOCLING_NUM_THREADS"))
    docling_do_ocr: bool = Field(default=True, validation_alias=AliasChoices("DOCLING_DO_OCR"))
    docling_do_table_structure: bool = Field(
        default=True,
        validation_alias=AliasChoices("DOCLING_DO_TABLE_STRUCTURE"),
    )
    # TableFormer: fast (throughput) vs accurate (default). Only applies to TableFormer V1 options.
    docling_table_former_mode: str = Field(
        default="accurate",
        validation_alias=AliasChoices("DOCLING_TABLE_FORMER_MODE"),
    )
    # Threaded StandardPdfPipeline batch sizes — raise on a 4090 if VRAM allows (e.g. 8–16).
    docling_ocr_batch_size: int = Field(default=4, validation_alias=AliasChoices("DOCLING_OCR_BATCH_SIZE"))
    docling_layout_batch_size: int = Field(
        default=4,
        validation_alias=AliasChoices("DOCLING_LAYOUT_BATCH_SIZE"),
    )
    docling_table_batch_size: int = Field(default=4, validation_alias=AliasChoices("DOCLING_TABLE_BATCH_SIZE"))
    # Layout-only speed tradeoff; keep false if you rely on table–cell linkage.
    docling_skip_cell_assignment: bool = Field(
        default=False,
        validation_alias=AliasChoices("DOCLING_SKIP_CELL_ASSIGNMENT"),
    )
    # After each PDF, call torch.cuda.empty_cache() when CUDA is in use (may reduce rare native crashes).
    docling_cuda_empty_cache_each_pdf: bool = Field(
        default=True,
        validation_alias=AliasChoices("DOCLING_CUDA_EMPTY_CACHE_EACH_PDF"),
    )
    # Rebuild DocumentConverter objects every N successful converts (0 = never). Mitigates GPU memory creep / segfaults.
    docling_converter_reset_every: int = Field(
        default=0,
        validation_alias=AliasChoices("DOCLING_CONVERTER_RESET_EVERY"),
    )

    skip_parse_if_exists: bool = Field(default=True, validation_alias=AliasChoices("SKIP_PARSE_IF_EXISTS"))
    skip_chunk_if_exists: bool = Field(default=True, validation_alias=AliasChoices("SKIP_CHUNK_IF_EXISTS"))
    skip_llm_chunk_if_exists: bool = Field(
        default=True,
        validation_alias=AliasChoices("SKIP_LLM_CHUNK_IF_EXISTS"),
    )
    skip_llm_doc_if_exists: bool = Field(
        default=True,
        validation_alias=AliasChoices("SKIP_LLM_DOC_IF_EXISTS"),
    )
    skip_aggregate_if_exists: bool = Field(
        default=True,
        validation_alias=AliasChoices("SKIP_AGGREGATE_IF_EXISTS"),
    )

    @staticmethod
    def _env_bool(v: object) -> bool:
        if v is None:
            return True
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if s in ("0", "false", "no", "off", ""):
            return False
        if s in ("1", "true", "yes", "on"):
            return True
        return bool(v)

    @field_validator(
        "use_guided_decoding",
        mode="before",
    )
    @classmethod
    def _coerce_guided(cls, v: object) -> bool:
        return cls._env_bool(v)

    @field_validator(
        "skip_parse_if_exists",
        "skip_chunk_if_exists",
        "skip_llm_chunk_if_exists",
        "skip_llm_doc_if_exists",
        "skip_aggregate_if_exists",
        mode="before",
    )
    @classmethod
    def _coerce_skip_flags(cls, v: object) -> bool:
        return cls._env_bool(v)

    @field_validator(
        "docling_do_ocr",
        "docling_do_table_structure",
        "docling_skip_cell_assignment",
        "docling_cuda_empty_cache_each_pdf",
        mode="before",
    )
    @classmethod
    def _coerce_docling_flags(cls, v: object) -> bool:
        return cls._env_bool(v)

    @field_validator("docling_table_former_mode", mode="before")
    @classmethod
    def _normalize_table_mode(cls, v: object) -> str:
        s = str(v or "accurate").strip().lower()
        if s in ("fast", "quick", "speed"):
            return "fast"
        return "accurate"

    @field_validator("docling_converter_reset_every", mode="before")
    @classmethod
    def _docling_reset_nonneg(cls, v: object) -> int:
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return 0

    @field_validator(
        "docling_ocr_batch_size",
        "docling_layout_batch_size",
        "docling_table_batch_size",
        "llm_chunk_gather_batch_size",
        mode="before",
    )
    @classmethod
    def _docling_batch_positive(cls, v: object) -> int:
        n = int(v)  # type: ignore[arg-type]
        return max(1, n)

    @field_validator("llm_chunk_max_tokens", mode="before")
    @classmethod
    def _llm_chunk_max_tokens_floor(cls, v: object) -> int:
        return max(256, int(v))  # type: ignore[arg-type]

    @field_validator("llm_chunk_checkpoint_every", mode="before")
    @classmethod
    def _llm_checkpoint_nonneg(cls, v: object) -> int:
        return max(0, int(v))  # type: ignore[arg-type]

    @field_validator("vllm_model_max_context_tokens", "llm_chunk_prompt_reserve_tokens", mode="before")
    @classmethod
    def _positive_int_ctx(cls, v: object) -> int:
        return max(1, int(v))  # type: ignore[arg-type]

    def resolve(self, p: str | Path) -> Path:
        path = Path(p)
        if path.is_absolute():
            return path
        return self.project_root / path


_HF_CACHE_ENV_KEYS = (
    "HF_HOME",
    "HF_HUB_CACHE",
    "HUGGINGFACE_HUB_CACHE",
    "TRANSFORMERS_CACHE",
    "HF_DATASETS_CACHE",
)


def _clear_broken_hf_cache_env() -> None:
    """Remove HF cache vars that point at unwritable WSL /mnt/d/... or claw-hf-cache paths."""
    for key in _HF_CACHE_ENV_KEYS:
        val = os.environ.get(key, "").strip()
        if not val:
            continue
        norm = val.replace("\\", "/").lower()
        if "/mnt/d/" in norm or "claw-hf-cache" in norm:
            os.environ.pop(key, None)


logger = logging.getLogger(__name__)


def _is_wsl() -> bool:
    try:
        with open("/proc/version", encoding="utf-8") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


def _wsl_ipv4_for_windows_host() -> str | None:
    """Best-effort IP to reach services bound on the Windows host from WSL2.

    Override with ``VLLM_WSL_HOST_IP`` when autodetection is wrong (VPN, Tailscale, etc.).
    """
    manual = (os.environ.get("VLLM_WSL_HOST_IP") or "").strip()
    if manual:
        return manual

    try:
        out = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        line = (out.stdout or "").strip().splitlines()[0] if out.stdout else ""
        # default via 192.168.x.1 dev eth0
        m = re.search(r"\bvia\s+(\d{1,3}(?:\.\d{1,3}){3})\b", line)
        if m:
            return m.group(1)
    except Exception as exc:
        logger.debug("wsl host ip: ip route failed: %s", exc)

    try:
        with open("/etc/resolv.conf", encoding="utf-8") as fh:
            for raw in fh:
                if raw.strip().lower().startswith("nameserver"):
                    parts = raw.split()
                    if len(parts) >= 2:
                        ip = parts[1].strip()
                        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip) and not ip.startswith("127."):
                            return ip
    except OSError as exc:
        logger.debug("wsl host ip: resolv.conf failed: %s", exc)
    return None


def _rewrite_vllm_localhost_for_wsl_windows(url: str, host_ip: str) -> str:
    """Replace 127.0.0.1 / localhost so WSL can reach vLLM listening on the Windows host."""
    u = url.strip()
    if not u:
        return u
    for marker in ("127.0.0.1", "localhost"):
        u = u.replace(f"://{marker}:", f"://{host_ip}:").replace(f"://{marker}/", f"://{host_ip}/")
    return u


def _apply_wsl_vllm_host_rewrite() -> None:
    """If ``VLLM_USE_WSL2_HOST`` is set and we are on WSL, point vLLM at the Windows host.

    vLLM on Windows often binds to ``127.0.0.1`` only; it must use ``--host 0.0.0.0`` (or the
    WSL NIC) so connections from WSL are accepted. Windows Firewall may still block port 8430.
    """
    raw = (os.environ.get("VLLM_USE_WSL2_HOST") or "").strip().lower()
    if raw not in ("1", "true", "yes", "on"):
        return
    if not _is_wsl():
        return
    base = (os.environ.get("VLLM_BASE_URL") or "").strip()
    if not base or "127.0.0.1" not in base and "localhost" not in base.lower():
        return
    hip = _wsl_ipv4_for_windows_host()
    if not hip:
        logger.warning(
            "VLLM_USE_WSL2_HOST is set but could not resolve a Windows host IP — "
            "set VLLM_WSL_HOST_IP manually (see .env comments)."
        )
        return
    new_base = _rewrite_vllm_localhost_for_wsl_windows(base, hip)
    if new_base != base:
        os.environ["VLLM_BASE_URL"] = new_base
        logger.info("WSL → Windows vLLM: VLLM_BASE_URL rewritten to %s", new_base)


def _apply_repo_vllm_env_overrides(root: Path) -> None:
    """Force ``prompt2dataset/.env`` values for vLLM routing over stale shell exports.

    ``load_dotenv(..., override=False)`` does not replace e.g. ``VLLM_BASE_URL`` if the
    shell already exported an old value (common after changing port from 8000→8430).
    Streamlit inherits the login shell, so users see ``Connection error`` while
    ``scripts/check_vllm.py`` works in a clean terminal.
    """
    try:
        from dotenv import dotenv_values
    except ImportError:
        return
    env_path = root / ".env"
    if not env_path.is_file():
        return
    data = dotenv_values(env_path)
    for key in (
        "VLLM_BASE_URL",
        "VLLM_API_KEY",
        "VLLM_MODEL_NAME",
        "VLLM_TIMEOUT_SEC",
        "VLLM_MAX_TOKENS",
        "VLLM_MODEL_MAX_CONTEXT_TOKENS",
        "VLLM_MAX_CONCURRENT_REQUESTS",
        "VLLM_CONCURRENCY",
        "USE_GUIDED_DECODING",
        "VLLM_RESPONSE_FORMAT",
        "VLLM_CHAT_TEMPLATE_KWARGS",
    ):
        val = data.get(key)
        if val is None or str(val).strip() == "":
            continue
        os.environ[key] = str(val).strip()
    _apply_wsl_vllm_host_rewrite()
    if os.environ.get("VLLM_BASE_URL"):
        logger.info("vLLM endpoint (effective): %s", os.environ["VLLM_BASE_URL"])


def ensure_hf_hub_env_for_process() -> None:
    """Normalize Hugging Face dirs before importing Docling / huggingface_hub.

    Shell profiles often export HF_HOME to a Windows drive under /mnt/d; that fails with
    Permission denied in WSL. We strip those paths, load ``.env``, then default to
    ``~/.cache/huggingface``.
    """
    _clear_broken_hf_cache_env()
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None  # type: ignore[misc, assignment]
    root = _default_project_root()
    isf = isf_repo_root()
    # Repo root first (operator secrets, CONTROLLER_BASE_URL, ISF_AUTONOMY_*), then package .env.
    if load_dotenv is not None:
        load_dotenv(isf / ".env", override=False)
    if load_dotenv is not None:
        load_dotenv(root / ".env", override=False)
    _apply_repo_vllm_env_overrides(root)
    _clear_broken_hf_cache_env()
    if not os.environ.get("HF_HOME", "").strip():
        fb = Path.home() / ".cache" / "huggingface"
        fb.mkdir(parents=True, exist_ok=True)
        os.environ["HF_HOME"] = str(fb)
    hb = Path(os.environ["HF_HOME"])
    if not os.environ.get("HF_HUB_CACHE", "").strip():
        os.environ["HF_HUB_CACHE"] = str(hb / "hub")


def get_settings() -> Settings:
    ensure_hf_hub_env_for_process()
    s = Settings()
    if os.environ.get("PROJECT_ROOT"):
        s.project_root = Path(os.environ["PROJECT_ROOT"]).resolve()
    return s
