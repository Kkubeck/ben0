"""Query classification and routing for the ben0 assistant."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ben0.assistant.text_to_sql import classify_query

# ---------------------------------------------------------------------------
# Data definitions
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class QueryPlan:
    """A routing decision for an incoming question.

    query_type: "sql" | "rag" | "hybrid"
    specificity: "specific" | "medium" | "broad"
    compression_level: 0 (raw chunks) | 1 (cluster summaries) | 2 (topic summaries)
    routing_hint: str -- human-readable hint for the orchestrator prompt
    """

    query_type: str
    specificity: str
    compression_level: int
    routing_hint: str


# QueryPlan example (specific sql):
#   QueryPlan(
#       query_type="sql",
#       specificity="specific",
#       compression_level=0,
#       routing_hint="This question appears quantitative. Consider using query_database.",
#   )

# QueryPlan example (broad rag):
#   QueryPlan(
#       query_type="rag",
#       specificity="broad",
#       compression_level=2,
#       routing_hint="This is a broad question. Use topic-level summaries for context.",
#   )

# Accession number pattern: digits-digits (e.g. 1984-0023 or 19840023)
_ACCESSION_NUMBER_RE = re.compile(r"\b\d{4}[-]\d{3,6}\b|\b\d{7,10}\b")

# Capitalized binomial: genus (>=4 chars, not a common sentence-start word) + species (>=4 chars).
# Requires genus to be at least 4 letters so "The X" and "Describe X" don't match.
_BINOMIAL_RE = re.compile(r"\b[A-Z][a-z]{3,}\s+[a-z]{4,}\b")

_BROAD_SIGNALS = re.compile(
    r"\b(the collection|overall|summary|priorities|trends|in general|at large)\b",
    re.IGNORECASE,
)

_SPECIFICITY_HINTS = {
    "specific": 0,
    "medium": 1,
    "broad": 2,
}

_ROUTING_HINTS: dict[tuple[str, str], str] = {
    ("sql", "specific"): (
        "This question appears quantitative and refers to a specific record. "
        "Consider using query_database with a targeted WHERE clause."
    ),
    ("sql", "medium"): (
        "This question appears quantitative. Consider using query_database."
    ),
    ("sql", "broad"): (
        "This is a broad quantitative question. "
        "Consider using query_database with aggregation."
    ),
    ("rag", "specific"): (
        "This question asks for narrative detail about a specific entity. "
        "Use raw document chunks (compression_level 0)."
    ),
    ("rag", "medium"): (
        "This question seeks explanation or description. "
        "Use cluster-level summaries for context."
    ),
    ("rag", "broad"): (
        "This is a broad question. Use topic-level summaries for context."
    ),
    ("hybrid", "specific"): (
        "This question needs both structured data and document context for a specific entity. "
        "Run query_database first, then search documents."
    ),
    ("hybrid", "medium"): (
        "This question needs both structured data and document context. "
        "Use query_database and cluster-level document summaries."
    ),
    ("hybrid", "broad"): (
        "This is a broad question requiring both data and narrative. "
        "Use topic-level document summaries alongside an aggregation query."
    ),
}


# ---------------------------------------------------------------------------
# classify_specificity
# ---------------------------------------------------------------------------


def classify_specificity(question: str) -> str:
    """Return 'specific', 'medium', or 'broad' based on identifiers and scope signals."""
    if _ACCESSION_NUMBER_RE.search(question) or _BINOMIAL_RE.search(question):
        return "specific"

    lower = question.lower()
    single_entity_words = (r"\bthis\b", r"\bthat\b", r"\ba single\b", r"\bone \b")
    if any(re.search(w, lower) for w in single_entity_words):
        return "specific"

    if _BROAD_SIGNALS.search(question):
        return "broad"

    return "medium"


# ---------------------------------------------------------------------------
# route_query
# ---------------------------------------------------------------------------


def route_query(question: str) -> QueryPlan:
    """Classify a question and return a QueryPlan routing decision."""
    query_type = classify_query(question)
    specificity = classify_specificity(question)
    compression_level = _SPECIFICITY_HINTS[specificity]
    routing_hint = _ROUTING_HINTS.get(
        (query_type, specificity),
        "Route this question using the best available tool.",
    )
    return QueryPlan(
        query_type=query_type,
        specificity=specificity,
        compression_level=compression_level,
        routing_hint=routing_hint,
    )
