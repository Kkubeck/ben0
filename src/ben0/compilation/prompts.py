"""Prompt templates for codex compilation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractionTopic:
    topic_id: str
    title: str
    domain: str
    search_queries: list[str]
    extraction_prompt: str


def _prompt(question: str) -> str:
    return (
        f"You are compiling a BEN-0 codex entry. {question}\n\n"
        "Use only the evidence chunks below. Cite specific chunk IDs inline when possible. "
        "If a section cannot be supported by the evidence, write exactly 'Insufficient evidence'.\n\n"
        "Evidence:\n{evidence}\n\n"
        "Respond using exactly these sections:\n"
        "Definition\n"
        "Current Working Rule\n"
        "Known Exceptions\n"
        "Do Not Infer\n"
    )


DEFAULT_TOPICS = [
    ExtractionTopic(
        topic_id="status-code-ontology",
        title="Status Code Ontology",
        domain="schema",
        search_queries=["status codes", "life status", "living dead removed", "propagation status"],
        extraction_prompt=_prompt(
            "Read the evidence and explain what status codes exist in this collection, how the status system is defined, how codes are grouped in current practice, notable exceptions, and what users must not infer from a status value alone."
        ),
    ),
    ExtractionTopic(
        topic_id="propagation-workflow",
        title="Propagation Workflow",
        domain="workflow",
        search_queries=["propagation", "sowing germination", "culturing success failure", "nursery"],
        extraction_prompt=_prompt(
            "Read the evidence and describe the propagation workflow stages, including how material moves through nursery or propagation steps and how success or failure is interpreted in practice."
        ),
    ),
    ExtractionTopic(
        topic_id="accession-lifecycle",
        title="Accession Lifecycle",
        domain="workflow",
        search_queries=["accession received", "accession date", "accession lifecycle", "material type"],
        extraction_prompt=_prompt(
            "Read the evidence and describe the lifecycle of an accession from receipt through later management states, including current working interpretation rules, exceptions, and limits on inference."
        ),
    ),
    ExtractionTopic(
        topic_id="provenance-categories",
        title="Provenance Categories",
        domain="schema",
        search_queries=["provenance", "origin code", "wild collected", "garden origin", "establishment means"],
        extraction_prompt=_prompt(
            "Read the evidence and explain which provenance or origin categories are used, how they are interpreted in current practice, edge cases, and what should not be inferred from provenance fields alone."
        ),
    ),
    ExtractionTopic(
        topic_id="data-quality-history",
        title="Data Quality History",
        domain="history",
        search_queries=["data quality", "recording practice", "legacy data", "BGAS migration", "date format"],
        extraction_prompt=_prompt(
            "Read the evidence and summarize known data quality issues, historical recording changes, current working interpretation rules, notable exceptions, and unsafe inferences to avoid."
        ),
    ),
    ExtractionTopic(
        topic_id="taxonomic-coverage",
        title="Taxonomic Coverage",
        domain="collection_profile",
        search_queries=["family", "genus", "taxonomic coverage", "collection focus"],
        extraction_prompt=_prompt(
            "Read the evidence and summarize the taxonomic breadth and focus of the collection, including practical interpretation rules, known caveats, and unsupported inferences."
        ),
    ),
]
