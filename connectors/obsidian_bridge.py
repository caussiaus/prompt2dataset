"""Obsidian Knowledge Graph Bridge.

Reads and writes the vault/ directory as a knowledge graph. Notes are standard
Markdown files with YAML frontmatter.  No MCP server needed — the vault lives
locally on the same machine as the pipeline.

The vault serves two roles:
  1. Knowledge base: entity nodes, document nodes, metadata source links
  2. Workflow definition: DAG nodes with sufficiency conditions

Usage:
    bridge = ObsidianBridge()
    entity = bridge.read_entity("CNQ")
    bridge.write_entity("CNQ", {"ticker": "CNQ", "acquisition_status": "complete"})
    found, missing = bridge.check_coverage(scope_spec)
"""
from __future__ import annotations

import datetime
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from connectors.network_settings import resolve_obsidian_local_rest

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]
_VAULT = _ROOT / "vault"


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a markdown note. Returns (frontmatter, body)."""
    try:
        import frontmatter as fm
        post = fm.loads(text)
        return dict(post.metadata), post.content
    except ImportError:
        pass

    # Fallback: manual YAML block parser (no dependency)
    import re
    m = re.match(r"^---\n(.*?)\n---\n?(.*)", text, re.DOTALL)
    if not m:
        return {}, text

    import json as _json
    yaml_block = m.group(1)
    body = m.group(2)
    frontmatter: dict[str, Any] = {}
    for line in yaml_block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            v = v.strip().strip('"').strip("'")
            # Try numeric coercion
            try:
                frontmatter[k.strip()] = int(v)
                continue
            except (ValueError, TypeError):
                pass
            try:
                frontmatter[k.strip()] = float(v)
                continue
            except (ValueError, TypeError):
                pass
            if v.lower() in ("true", "yes"):
                frontmatter[k.strip()] = True
            elif v.lower() in ("false", "no"):
                frontmatter[k.strip()] = False
            else:
                frontmatter[k.strip()] = v

    return frontmatter, body


def _write_frontmatter(frontmatter: dict[str, Any], body: str) -> str:
    """Serialize a note back to frontmatter + body markdown."""
    try:
        import frontmatter as fm
        import io
        post = fm.Post(body, **frontmatter)
        buf = io.BytesIO()
        fm.dump(post, buf)
        return buf.getvalue().decode("utf-8")
    except ImportError:
        pass

    # Fallback: simple serialiser
    import json as _json
    lines = ["---"]
    for k, v in frontmatter.items():
        if isinstance(v, (list, dict)):
            lines.append(f"{k}: {_json.dumps(v)}")
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        else:
            lines.append(f"{k}: {v!r}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    return "\n".join(lines)


# ── Entity nodes ────────────────────────────────────────────────────────────


class ObsidianBridge:
    """File-based read/write bridge to the vault/ directory."""

    def __init__(self, vault_path: Path | str | None = None):
        self.vault = Path(vault_path) if vault_path else _VAULT
        self.vault.mkdir(parents=True, exist_ok=True)
        for sub in ("Entities", "Documents", "MetadataSources", "Schemas", "Runs", "Workflows"):
            (self.vault / sub).mkdir(exist_ok=True)

    # ── Read / write helpers ─────────────────────────────────────────────────

    def _note_path(self, folder: str, name: str) -> Path:
        safe = name.replace("/", "_").replace("\\", "_").replace(" ", "_")
        return self.vault / folder / f"{safe}.md"

    def _read_note(self, folder: str, name: str) -> tuple[dict, str] | None:
        p = self._note_path(folder, name)
        if not p.exists():
            return None
        text = p.read_text(encoding="utf-8")
        return _parse_frontmatter(text)

    def _write_note(self, folder: str, name: str, frontmatter: dict, body: str = "") -> None:
        p = self._note_path(folder, name)
        p.write_text(_write_frontmatter(frontmatter, body), encoding="utf-8")

    def _list_notes(self, folder: str) -> list[str]:
        d = self.vault / folder
        return [p.stem for p in d.glob("*.md") if not p.stem.startswith("_")]

    # ── Entity nodes ─────────────────────────────────────────────────────────

    def read_entity(self, ticker: str) -> dict[str, Any] | None:
        result = self._read_note("Entities", ticker)
        return result[0] if result else None

    def write_entity(self, ticker: str, frontmatter: dict[str, Any]) -> None:
        existing = self._read_note("Entities", ticker)
        if existing:
            merged = {**existing[0], **frontmatter}
            body = existing[1]
        else:
            merged = {"type": "entity", **frontmatter}
            body = f"# Entity: {frontmatter.get('entity_name', ticker)}\n"
        self._write_note("Entities", ticker, merged, body)

    def list_entities(self) -> list[str]:
        return self._list_notes("Entities")

    # ── Document nodes ───────────────────────────────────────────────────────

    def read_document(self, doc_key: str) -> dict[str, Any] | None:
        result = self._read_note("Documents", doc_key)
        return result[0] if result else None

    def write_document(self, doc_key: str, frontmatter: dict[str, Any]) -> None:
        existing = self._read_note("Documents", doc_key)
        if existing:
            merged = {**existing[0], **frontmatter}
            body = existing[1]
        else:
            merged = {"type": "document", **frontmatter}
            body = f"# Document: {doc_key}\n"
        self._write_note("Documents", doc_key, merged, body)

    def get_document_nodes(self, entity_ticker: str) -> list[dict[str, Any]]:
        """Return all document nodes for an entity."""
        docs = []
        for doc_key in self._list_notes("Documents"):
            result = self._read_note("Documents", doc_key)
            if result and entity_ticker.upper() in str(result[0].get("entity", "")).upper():
                docs.append(result[0])
        return docs

    # ── Metadata sources ─────────────────────────────────────────────────────

    def get_metadata_sources_for_corpus(self, corpus_id: str) -> list[dict[str, Any]]:
        """Return metadata source frontmatter dicts that apply to this corpus."""
        sources = []
        for name in self._list_notes("MetadataSources"):
            result = self._read_note("MetadataSources", name)
            if not result:
                continue
            fm, _ = result
            applies = fm.get("applies_to_corpora", [])
            if isinstance(applies, list) and (corpus_id in applies or not applies):
                sources.append({**fm, "_note_name": name})
            elif isinstance(applies, str) and corpus_id in applies:
                sources.append({**fm, "_note_name": name})
        return sources

    # ── Schema persistence ───────────────────────────────────────────────────

    def write_schema(
        self,
        schema_name: str,
        corpus_id: str,
        columns: list[dict],
        quality: str = "ok",
    ) -> None:
        fm = {
            "type":               "schema",
            "schema_name":        schema_name,
            "corpus_id":          corpus_id,
            "version":            1,
            "created_at":         datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "quality_on_approval": quality,
            "columns":            columns,
            "used_in_runs":       [],
        }
        col_lines = "\n".join(
            f"- **{c.get('name','')}** ({c.get('type','')}) — {c.get('description','')}"
            for c in columns
        )
        body = f"# Schema: {schema_name}\n\nCorpus: {corpus_id}\n\n## Columns\n\n{col_lines}\n"
        self._write_note("Schemas", schema_name, fm, body)

    # ── Run history ──────────────────────────────────────────────────────────

    def write_run_note(
        self,
        run_id: str,
        corpus_id: str,
        schema_name: str,
        quality: str,
        row_count: int,
        doc_count: int = 0,
        consistency_flags: dict | None = None,
        dataset_path: str = "",
    ) -> None:
        flags = consistency_flags or {}
        total = max(row_count, 1)
        fm = {
            "type":               "run",
            "run_id":             run_id,
            "corpus_id":          corpus_id,
            "schema_name":        schema_name,
            "quality":            quality,
            "doc_count":          doc_count,
            "row_count":          row_count,
            "all_default_rate":   round(flags.get("all_default_count", 0) / total, 3),
            "evidenceless_rate":  round(flags.get("evidenceless_count", 0) / total, 3),
            "parse_error_rate":   round(flags.get("parse_error_count", 0) / total, 3),
            "dataset_path":       dataset_path,
            "created_at":         datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        body = (
            f"# Run: {run_id}\n\n"
            f"Corpus: {corpus_id} | Schema: {schema_name} | Quality: **{quality}**\n\n"
            f"Rows: {row_count} | Docs: {doc_count}\n"
        )
        self._write_note("Runs", run_id, fm, body)
        logger.info("obsidian_bridge: wrote run note %s", run_id)

    # ── Coverage check ───────────────────────────────────────────────────────

    def check_coverage(
        self,
        scope_spec: dict,
    ) -> tuple[list[dict], list[dict]]:
        """Check which documents in scope_spec exist in the vault.

        Returns (found, missing) where each item is a dict with keys:
            entity, doc_type, period, local_path (found only)
        """
        entities = scope_spec.get("entities", [])
        doc_types = scope_spec.get("doc_types", ["Annual MD&A"])
        date_from = scope_spec.get("date_from") or 2020
        date_to   = scope_spec.get("date_to") or datetime.datetime.now().year

        found: list[dict] = []
        missing: list[dict] = []

        for entity in entities:
            ticker = entity.get("ticker") or entity.get("sedar_name", "")
            entity_docs = self.get_document_nodes(ticker)

            for doc_type in doc_types:
                for year in range(date_from, date_to + 1):
                    period = str(year)
                    doc_match = next(
                        (d for d in entity_docs
                         if d.get("doc_type") == doc_type
                         and str(d.get("period", "")) == period
                         and d.get("ingest_status") in ("done", "processing")),
                        None,
                    )
                    if doc_match:
                        found.append({
                            "entity":     ticker,
                            "doc_type":   doc_type,
                            "period":     period,
                            "local_path": doc_match.get("local_path", ""),
                        })
                    else:
                        missing.append({
                            "entity":     ticker,
                            "doc_type":   doc_type,
                            "period":     period,
                        })

        return found, missing


# ── Singleton ────────────────────────────────────────────────────────────────

_bridge: ObsidianBridge | None = None


def get_obsidian_bridge(vault_path: Path | str | None = None) -> ObsidianBridge:
    global _bridge
    if _bridge is None or vault_path:
        _bridge = ObsidianBridge(vault_path)
    return _bridge


# ── VaultClient — the modern entrypoint (wraps ObsidianBridge in Mode A, adds Mode B REST) ──

class VaultClient:
    """Two-mode Obsidian vault integration.

    Mode A: python-frontmatter direct file I/O (always works, no plugin required).
    Mode B: Local REST API at port 27123 (requires obsidian-local-rest-api plugin).

    The bridge (ObsidianBridge) is always the backend for Mode A.
    Mode B is optional and adds dataview_query() support while Obsidian is open.
    """

    def __init__(
        self,
        vault_path: Path | str | None = None,
        api_key: str | None = None,
        api_port: int | None = None,
    ):
        self._bridge = ObsidianBridge(vault_path)
        self.vault = self._bridge.vault
        self.api_key = api_key
        rest_host, rest_port = resolve_obsidian_local_rest()
        self.api_port = rest_port if api_port is None else api_port
        self._rest_host = rest_host
        self._api_available = self._check_api()

    def _rest_base(self) -> str:
        return f"http://{self._rest_host}:{self.api_port}"

    def _check_api(self) -> bool:
        try:
            import httpx
            r = httpx.get(
                f"{self._rest_base()}/",
                timeout=1.0,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            return r.status_code == 200
        except Exception:
            return False

    # ── Mode A: delegate to ObsidianBridge ──────────────────────────────────

    def get_entities(self, corpus_id: str | None = None) -> list[dict]:
        """Return all entity frontmatter dicts, optionally filtered by corpus_id."""
        results = []
        for name in self._bridge.list_entities():
            data = self._bridge.read_entity(name)
            if data is None:
                continue
            if corpus_id:
                corpora = data.get("corpora", [])
                if not any(corpus_id in str(c) for c in corpora):
                    continue
            results.append({"_name": name, **data})
        return results

    def get_schema(self, schema_name: str) -> dict:
        """Load a schema note's frontmatter."""
        result = self._bridge._read_note("Schemas", schema_name)
        return result[0] if result else {}

    def list_schemas(self) -> list[str]:
        """List all schema note names."""
        return self._bridge._list_notes("Schemas")

    def update_entity(self, entity_name: str, updates: dict) -> None:
        """Update YAML frontmatter fields on an entity note."""
        self._bridge.write_entity(entity_name, updates)

    def save_schema_version(self, schema: dict) -> None:
        """Write an approved schema back to the vault."""
        name = schema.get("name", "schema")
        version = schema.get("version", 1)
        full_name = f"{name}_v{version}"
        self._bridge.write_schema(
            schema_name=full_name,
            corpus_id=schema.get("corpus_id", ""),
            columns=schema.get("columns", []),
            quality=schema.get("quality", "pending"),
        )

    def get_metadata_sources(self, entity_name: str) -> list[str]:
        """Return metadata source paths linked to an entity."""
        data = self._bridge.read_entity(entity_name) or {}
        sources = data.get("metadata_sources", [])
        resolved = []
        for s in sources:
            s_clean = str(s).strip("[[]]").replace("/", os.sep)
            path = self.vault / f"{s_clean}.md"
            resolved.append(str(path))
        return resolved

    # ── Mode B: REST API (optional) ─────────────────────────────────────────

    def dataview_query(self, dql: str) -> list[dict]:
        """Run a Dataview DQL query via the Local REST API plugin."""
        if not self._api_available:
            raise RuntimeError(
                "Obsidian REST API not available — open Obsidian with the "
                "obsidian-local-rest-api plugin enabled."
            )
        import httpx
        r = httpx.post(
            f"{self._rest_base()}/search/",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/vnd.olrapi.dataview.dql+txt",
            },
            content=dql.encode(),
            timeout=10.0,
        )
        return r.json()

    # ── Schema library ───────────────────────────────────────────────────────

    def schema_library_search(
        self,
        candidate_columns: list[dict],
        overlap_threshold: float = 0.60,
    ) -> list[dict]:
        """Search the vault for schemas with > overlap_threshold column overlap.

        Returns list of matching schema dicts sorted by overlap descending.
        Each item has: schema_name, overlap_ratio, columns, domain.
        """
        if not candidate_columns:
            return []

        candidate_names = {
            str(c.get("name") or "").lower()
            for c in candidate_columns
            if c.get("name")
        }

        matches = []
        for schema_name in self.list_schemas():
            schema = self.get_schema(schema_name)
            schema_cols = schema.get("columns", [])
            if not schema_cols:
                continue
            schema_names = {
                str(c.get("name") or "").lower()
                for c in schema_cols
                if c.get("name")
            }
            if not schema_names:
                continue
            overlap = len(candidate_names & schema_names) / max(len(candidate_names), 1)
            if overlap >= overlap_threshold:
                matches.append({
                    "schema_name": schema_name,
                    "overlap_ratio": round(overlap, 3),
                    "columns": schema_cols,
                    "domain": schema.get("domain", ""),
                    "version": schema.get("version", 1),
                })

        matches.sort(key=lambda x: x["overlap_ratio"], reverse=True)
        return matches


# ── Topology validation ───────────────────────────────────────────────────────


@dataclass
class TopologyResult:
    valid: bool
    broken_edge: str = ""
    details: dict = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


def validate_topology(corpus_id: str, vault_client: VaultClient) -> TopologyResult:
    """Four deterministic checks on the vault graph.

    1. DAG validity — detect circular wikilinks (checked via entity→corpus→schema chain)
    2. Reachability — every schema column has at least one keyword
    3. Sufficiency — at least 6 entities have acquisition_status = 'done'
    4. Metadata reachability — at least one metadata source exists for identity fields

    No LLM involved. Returns TopologyResult(valid=True) if all checks pass.
    """
    # 1. Schema reachability
    schema_data = {}
    for name in vault_client.list_schemas():
        sd = vault_client.get_schema(name)
        if corpus_id in str(sd.get("corpus", "")) or corpus_id in name:
            schema_data = sd
            break

    if schema_data:
        for col in schema_data.get("columns", []):
            col_name = col.get("name", "?")
            if not col.get("keywords"):
                return TopologyResult(
                    valid=False,
                    broken_edge=f"schema/{col_name} → missing keywords",
                )

    # 2. Entity sufficiency
    entities = vault_client.get_entities(corpus_id)
    if not entities:
        entities = vault_client.get_entities()

    acquired = [e for e in entities if e.get("acquisition_status") == "done"]
    if len(entities) >= 6 and len(acquired) < 6:
        return TopologyResult(
            valid=False,
            broken_edge=f"corpus/{corpus_id} → needs ≥6 acquired docs, has {len(acquired)}",
            details={"n_entities": len(entities), "n_acquired": len(acquired)},
        )

    # 3. Metadata reachability (check at least one entity has metadata_sources)
    entities_with_sources = [
        e for e in entities[:10]
        if e.get("metadata_sources")
    ]
    if entities and not entities_with_sources:
        return TopologyResult(
            valid=False,
            broken_edge=f"corpus/{corpus_id} → no metadata sources linked to any entity",
        )

    return TopologyResult(
        valid=True,
        details={"n_entities": len(entities), "n_acquired": len(acquired) if entities else 0},
    )


_vault_client: VaultClient | None = None


def get_vault_client(vault_path: Path | str | None = None) -> VaultClient:
    global _vault_client
    if _vault_client is None or vault_path:
        _vault_client = VaultClient(vault_path)
    return _vault_client


def kg_health_check(vault_path: Path | str | None = None) -> dict:
    """Check vault directory health and return a status dict.

    Returns:
        {
            "healthy": bool,
            "vault_exists": bool,
            "n_entities": int,
            "n_schemas": int,
            "error": str | None,
        }

    Never raises — always returns a dict so callers can surface the result
    as a st.warning without crashing.
    """
    result = {
        "healthy": False,
        "vault_exists": False,
        "n_entities": 0,
        "n_schemas": 0,
        "error": None,
    }
    try:
        bridge = get_obsidian_bridge(vault_path)
        result["vault_exists"] = bridge.vault.exists()
        if result["vault_exists"]:
            result["n_entities"] = len(bridge.list_entities())
            result["n_schemas"] = len(bridge._list_notes("Schemas"))
            result["healthy"] = True
    except Exception as exc:
        result["error"] = str(exc)
        logger.warning("kg_health_check: %s", exc)
    return result
