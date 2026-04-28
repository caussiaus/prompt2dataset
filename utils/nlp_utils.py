"""Lightweight NLP utilities — pure Python, no heavy dependency.

Covers:
  - Topic/intent classification (what kind of data the user wants)
  - Field data-type inference from a plain-English description
  - BM25 keyword generation from topic + schema (replaces hardcoded tariff terms)
  - Company-name normalisation + fuzzy matching against a name list

All logic is regex + difflib — no spaCy, NLTK, or sklearn needed.
Fast enough to run on every schema-design request without GPU involvement.
"""
from __future__ import annotations

import re
import string
from difflib import SequenceMatcher
from typing import Any

# ── Intent taxonomy ───────────────────────────────────────────────────────────
# Each tag maps to (regex, domain-specific expansion keywords).
# Classified tags drive BM25 query expansion and chunk-keyword generation.

_INTENT_TAXONOMY: dict[str, tuple[re.Pattern, list[str]]] = {
    "trade_tariff": (
        re.compile(
            r"tariff|import.dut|trade.war|sanction|embargo|customs.dut|supply.chain"
            r"|retaliatory|countervail|anti.dump|section.232|section.301|USMCA|CUSMA"
            r"|CETA|CPTPP|liberation.day|softwood|lumber.dut",
            re.I,
        ),
        ["tariff", "duty", "duties", "customs", "import", "USMCA", "retaliatory",
         "trade", "Section 232", "Section 301", "countervailing", "anti-dumping",
         "supply chain", "border tax", "trade war", "safeguard"],
    ),
    "financial_metrics": (
        re.compile(
            r"revenue|earnings|ebitda|net.income|margin|cash.flow|eps|return.on"
            r"|profit|loss|gross|operating|capex|free.cash|dividend|yield",
            re.I,
        ),
        ["revenue", "EBITDA", "net income", "margin", "cash flow", "earnings",
         "profitability", "operating income", "gross profit", "free cash flow"],
    ),
    "esg_climate": (
        re.compile(
            r"emission|carbon|ghg|climate|sustainab|scope.[123]|net.zero"
            r"|biodiversity|water|waste|renewable|decarbonization",
            re.I,
        ),
        ["emissions", "carbon", "GHG", "Scope 1", "Scope 2", "Scope 3",
         "climate risk", "net zero", "sustainability", "renewable energy"],
    ),
    "governance": (
        re.compile(
            r"board|director|executive|compensation|governance|audit.committee"
            r"|say.on.pay|independence|diversity|ceo|cfo|whistleblower",
            re.I,
        ),
        ["board of directors", "executive compensation", "audit committee",
         "governance", "independence", "CEO", "CFO", "diversity"],
    ),
    "risk_factors": (
        re.compile(
            r"\brisk\b|uncertaint|exposure|sensitiv|contingent|legal.proceed"
            r"|litigation|lawsuit|regulatory|compliance|penalty",
            re.I,
        ),
        ["risk", "uncertainty", "exposure", "litigation", "regulatory risk",
         "compliance", "contingent liability", "legal proceedings"],
    ),
    "operational": (
        re.compile(
            r"production|capacity|output|volume|throughput|headcount|employee"
            r"|plant|facility|fleet|unit.cost|efficiency",
            re.I,
        ),
        ["production", "capacity", "output", "volume", "throughput",
         "employees", "headcount", "unit cost", "efficiency"],
    ),
    "real_estate": (
        re.compile(
            r"occupancy|lease|rent|cap.rate|noi|ffo|properties|square.feet"
            r"|tenant|vacancy|development|zoning",
            re.I,
        ),
        ["occupancy", "lease", "NOI", "FFO", "cap rate", "rental", "vacancy",
         "properties", "square feet", "tenant"],
    ),
    "mining_resources": (
        re.compile(
            r"mineral|reserve|resource|grade|ore|pit|mine|gold|silver|copper"
            r"|lithium|nickel|zinc|cobalt|uranium|royalty",
            re.I,
        ),
        ["mineral", "reserve", "resource", "grade", "ore body", "mine",
         "gold", "silver", "copper", "lithium", "recovery"],
    ),
    "energy_oil_gas": (
        re.compile(
            r"barrel|boe|mboe|proved|probable|reservoir|upstream|downstream"
            r"|refinery|petrochemical|lng|pipeline|wellbore|netback",
            re.I,
        ),
        ["barrels", "BOE", "proved reserves", "production", "upstream",
         "downstream", "refinery", "LNG", "pipeline", "netback", "royalty"],
    ),
    "healthcare_pharma": (
        re.compile(
            r"clinical.trial|drug|therapeutic|patent|approval|FDA|Health.Canada"
            r"|patient|prescription|molecule|pipeline.stage",
            re.I,
        ),
        ["clinical trial", "drug", "therapeutic", "patent", "FDA approval",
         "pipeline", "patient", "prescription", "molecule"],
    ),
}

# ── Stop-word list for key-term extraction ────────────────────────────────────
_STOP: frozenset[str] = frozenset(
    "the and for are with from that this have been were they their them will "
    "would could should about into over under also both each more most only "
    "very just such than then some any may can has had its how per yet what "
    "when where which been being itself those these does did was were all one "
    "two three four five six seven many other every either neither after "
    "before during while whether".split()
)

# ── Data-type inference signals ───────────────────────────────────────────────
_FLOAT_SIG = re.compile(
    r"\b(amount|dollar|million|billion|percent|rate|ratio|value|price|cost|"
    r"revenue|income|ebitda|margin|yield|return|gain|loss|fee|salary|wage|"
    r"metric|score|average|mean|median|proportion|share|fraction|weight)\b",
    re.I,
)
_INT_SIG = re.compile(
    r"\b(count|number|year|month|quarter|employees|headcount|shares|units|"
    r"properties|buildings|facilities|mines|wells|days|hours|periods)\b",
    re.I,
)
_BOOL_SIG = re.compile(
    r"\b(whether|presence|existence|disclosed|reported|mentioned|flagged|"
    r"indicates|signal|binary|yes.no|true.false|flag)\b",
    re.I,
)
_DATE_SIG = re.compile(
    r"\b(date|when|period|quarter|year|month|fiscal|anniversary|expiry"
    r"|maturity|effective|announced|closed|signed)\b",
    re.I,
)


# ── Public API ────────────────────────────────────────────────────────────────

def classify_topic(text: str) -> list[str]:
    """Return canonical intent tags for a topic/prompt string."""
    return [tag for tag, (pat, _) in _INTENT_TAXONOMY.items() if pat.search(text)]


def infer_data_type(description: str) -> str:
    """Infer the most likely data type from a plain-English field description.

    Priority: bool > date > float > int > str
    """
    if _BOOL_SIG.search(description):
        return "bool"
    if _DATE_SIG.search(description):
        return "date"
    if _FLOAT_SIG.search(description):
        return "float"
    if _INT_SIG.search(description):
        return "int"
    return "str"


def is_quantitative(description: str) -> bool:
    """True if the field is likely a number (float or int)."""
    return infer_data_type(description) in ("float", "int")


def extract_key_terms(text: str, max_terms: int = 25) -> list[str]:
    """Extract content words ≥ 4 chars, deduped, order-preserved."""
    tokens = re.findall(r"[a-zA-Z]{4,}", text.lower())
    seen: set[str] = set()
    result: list[str] = []
    for tok in tokens:
        if tok not in _STOP and tok not in seen:
            seen.add(tok)
            result.append(tok)
        if len(result) >= max_terms:
            break
    return result


def generate_field_keywords(description: str, topic: str = "", n: int = 15) -> list[str]:
    """BM25 query tokens for a single schema field.

    Combines key terms from the field description with topic-domain expansions.
    """
    terms = extract_key_terms(f"{description} {topic}", max_terms=n)
    return terms


def generate_corpus_keywords(topic: str, schema_cols: list[dict] | None = None) -> list[str]:
    """Generate BM25 keyword pool for the whole corpus topic.

    Used to build dynamic KEYWORD_RULES for the chunk-level pre-filter gate.
    Combines:
      1. Raw terms from the topic string
      2. Domain expansion from intent taxonomy
      3. Field-level description terms from schema_cols
    """
    base = extract_key_terms(topic, max_terms=20)

    # Intent-based expansion
    expansions: list[str] = []
    for tag in classify_topic(topic):
        _, kws = _INTENT_TAXONOMY[tag]
        expansions.extend(kws)

    # Schema-level terms (if available)
    field_terms: list[str] = []
    for col in (schema_cols or []):
        desc = col.get("description") or col.get("extraction_instruction") or ""
        field_terms += extract_key_terms(desc, max_terms=8)

    # Merge, dedup, prioritise
    seen: set[str] = set()
    merged: list[str] = []
    for term in base + expansions + field_terms:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            merged.append(term)
    return merged[:40]


def build_keyword_rules(topic: str, schema_cols: list[dict] | None = None) -> list[tuple]:
    """Build regex keyword rules from a corpus topic (replaces hardcoded KEYWORD_RULES).

    Returns list of (compiled_pattern, label) tuples compatible with
    the existing ``KEYWORD_RULES`` format in chunk_prompt.py.

    Uses a two-pass approach:
      1. Long-phrase patterns (specific compound terms, e.g. "supply chain disruption")
      2. Short single-word patterns (e.g. "tariff")
    """
    keywords = generate_corpus_keywords(topic, schema_cols)
    rules: list[tuple] = []
    seen_labels: set[str] = set()

    for kw in keywords:
        kw_clean = kw.strip()
        if not kw_clean or len(kw_clean) < 3:
            continue
        label = re.sub(r"\s+", "_", kw_clean.lower())[:30]
        if label in seen_labels:
            continue
        seen_labels.add(label)
        # Escape for regex, allow flexible whitespace between words
        escaped = re.escape(kw_clean).replace(r"\ ", r"[\s\-]?")
        try:
            pat = re.compile(rf"\b{escaped}\b", re.I)
            rules.append((pat, label))
        except re.error:
            continue

    return rules


# ── Company-name normalisation + fuzzy matching ───────────────────────────────

_CORP_SUFFIXES = re.compile(
    r"\b(inc\.?|corp\.?|ltd\.?|limited|llc\.?|lp\.?|plc\.?|company|co\.?|"
    r"group|holding|holdings|international|global|sa\.?|nv\.?|ag\.?|gmbh\.?)\b",
    re.I,
)
_PUNCT = re.compile(r"[^\w\s]")


def normalize_company_name(name: str) -> str:
    """Lowercase, strip legal suffixes and punctuation for comparison."""
    s = str(name).lower()
    s = _CORP_SUFFIXES.sub("", s)
    s = _PUNCT.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def match_company_name(
    query: str,
    candidates: list[str],
    threshold: float = 0.72,
) -> tuple[str | None, float]:
    """Fuzzy-match a company name against a list of canonical names.

    Returns (best_match, score) or (None, 0.0) if no match above threshold.
    Uses difflib SequenceMatcher (no external dependency).
    """
    q = normalize_company_name(query)
    if not q:
        return None, 0.0

    best_name: str | None = None
    best_score = 0.0
    for cand in candidates:
        c = normalize_company_name(cand)
        if not c:
            continue
        # Exact substring check (fast path)
        if q in c or c in q:
            ratio = 1.0
        else:
            ratio = SequenceMatcher(None, q, c).ratio()
        if ratio > best_score:
            best_score = ratio
            best_name = cand
        if best_score >= 0.99:
            break

    if best_score < threshold:
        return None, best_score
    return best_name, best_score


def draft_schema_from_prompt(
    topic: str,
    *,
    max_fields: int = 8,
) -> list[dict[str, Any]]:
    """Generate a first-pass schema draft using NLP only (no LLM).

    The LLM schema_node should refine this draft, not start from scratch.
    Produces fields that are:
      - Typed by data-type inference signals
      - Keyed to the domain vocabulary detected in the topic
      - Annotated with BM25 keywords for retrieval

    Returned schema is compatible with DatasetState['proposed_columns'].
    """
    tags = classify_topic(topic)
    kws = generate_corpus_keywords(topic)

    # Canonical field templates per intent tag
    FIELD_TEMPLATES: dict[str, list[dict]] = {
        "trade_tariff": [
            {"name": "tariff_mention", "type": "str",
             "description": "Direct quote from the document mentioning tariffs, import duties, or trade measures",
             "keywords": ["tariff", "duty", "duties", "import", "retaliatory", "USMCA"]},
            {"name": "affected_segment", "type": "str",
             "description": "Business segment, product line, or geography affected by the tariff",
             "keywords": ["segment", "division", "product", "region", "Canada", "US"]},
            {"name": "financial_impact", "type": "str",
             "description": "Quantified or estimated financial impact of the tariff ($ millions or % of revenue)",
             "keywords": ["million", "impact", "cost", "exposure", "revenue", "margin"]},
            {"name": "management_response", "type": "str",
             "description": "Actions taken or planned to mitigate tariff risk",
             "keywords": ["mitigate", "hedge", "diversify", "supplier", "response", "action"]},
        ],
        "financial_metrics": [
            {"name": "revenue", "type": "float",
             "description": "Total revenue or net revenue for the reported period",
             "keywords": ["revenue", "sales", "net revenue", "total revenue"]},
            {"name": "ebitda", "type": "float",
             "description": "EBITDA or adjusted EBITDA for the period",
             "keywords": ["EBITDA", "earnings before", "adjusted EBITDA"]},
            {"name": "net_income", "type": "float",
             "description": "Net income or net loss for the period",
             "keywords": ["net income", "net loss", "profit", "bottom line"]},
            {"name": "operating_margin", "type": "float",
             "description": "Operating margin as a percentage",
             "keywords": ["operating margin", "operating income", "margin"]},
        ],
        "esg_climate": [
            {"name": "ghg_emissions", "type": "float",
             "description": "Total GHG emissions (Scope 1+2 or combined) in tonnes CO2e",
             "keywords": ["GHG", "emissions", "Scope 1", "Scope 2", "CO2", "carbon"]},
            {"name": "emissions_target", "type": "str",
             "description": "Stated emissions reduction target or net-zero commitment",
             "keywords": ["target", "net zero", "reduction", "commitment", "2030", "2050"]},
            {"name": "climate_risk_disclosure", "type": "str",
             "description": "Quote describing material climate risks identified by management",
             "keywords": ["climate risk", "physical risk", "transition risk", "TCFD"]},
        ],
        "risk_factors": [
            {"name": "risk_description", "type": "str",
             "description": "Description of a material risk factor disclosed",
             "keywords": ["risk", "uncertainty", "material", "could", "may affect"]},
            {"name": "risk_category", "type": "str",
             "description": "Category of the risk (operational, regulatory, financial, climate, etc.)",
             "keywords": ["category", "type", "operational", "regulatory", "financial"]},
            {"name": "potential_impact", "type": "str",
             "description": "Potential financial or operational impact of the risk",
             "keywords": ["impact", "adverse", "material", "significant", "affect"]},
        ],
        "governance": [
            {"name": "board_composition", "type": "str",
             "description": "Number and diversity characteristics of the board",
             "keywords": ["board", "directors", "independent", "diversity", "women"]},
            {"name": "ceo_compensation", "type": "float",
             "description": "Total CEO compensation for the year",
             "keywords": ["CEO", "compensation", "salary", "bonus", "total pay"]},
        ],
        "operational": [
            {"name": "production_volume", "type": "float",
             "description": "Production or output volume for the period",
             "keywords": ["production", "output", "volume", "units", "throughput"]},
            {"name": "capacity_utilization", "type": "float",
             "description": "Capacity utilization rate (%)",
             "keywords": ["capacity", "utilization", "efficiency", "rate"]},
        ],
    }

    fields: list[dict] = []
    seen_names: set[str] = set()

    for tag in tags:
        for template in FIELD_TEMPLATES.get(tag, []):
            if template["name"] not in seen_names and len(fields) < max_fields:
                seen_names.add(template["name"])
                fields.append({**template, "default": None})

    # If no tag matched, generate generic quote + context + impact fields
    if not fields:
        fields = [
            {
                "name": "relevant_passage",
                "type": "str",
                "description": f"Direct quote from the document relevant to: {topic[:80]}",
                "keywords": kws[:8],
                "default": None,
            },
            {
                "name": "context",
                "type": "str",
                "description": "Context or background for the passage (who, what, when, where)",
                "keywords": ["context", "background", "related", "mentions"],
                "default": None,
            },
            {
                "name": "quantitative_value",
                "type": "str",
                "description": "Any numeric value, metric, or financial figure mentioned",
                "keywords": ["million", "percent", "value", "amount", "figure"],
                "default": None,
            },
        ]

    return fields[:max_fields]
