"""Tool functions exposed to the BEN-0 assistant."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from ben0 import config
from ben0.assistant.text_to_sql import (
    execute_safe_query,
    format_sql_results,
    generate_schema_description,
    generate_sql,
)
from ben0.dashboard.metrics import calculate_metrics
from ben0.db.models import Accession, CorrectionTicket, Event, Item, Taxon, ValidationIssue, Provenance
from ben0.db.session import get_engine
from ben0.reports.markdown_report import generate_markdown_report
from ben0.retrieval.hybrid_search import hybrid_search
from ben0.retrieval.search import search_index
from ben0.tickets.service import create_ticket_from_issue


def _citation(prefix: str, record_id: str, suffix: str | None = None) -> str:
    value = f"{prefix}:{record_id}"
    return f"{value}#{suffix}" if suffix else value


def _parse_query_filters(query_or_filters: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(query_or_filters, dict):
        return dict(query_or_filters)
    query = query_or_filters.strip()
    lowered = query.lower()
    filters: dict[str, Any] = {"query": query}
    if "missing provenance" in lowered or "no provenance" in lowered:
        filters["missing_provenance"] = True
    if "unknown provenance" in lowered:
        filters["unknown_provenance"] = True
    return filters


def search_documents(session: Session, query: str, limit: int = 5, use_hybrid: bool = False) -> dict[str, Any]:
    if use_hybrid:
        results = hybrid_search(session, query, config._GARDEN_ROOT / "data" / "vector", limit=limit)
    else:
        results = search_index(session, query, limit=limit)
    return {
        "tool": "search_documents",
        "query": query,
        "results": [
            {
                "chunk_id": row["chunk_id"],
                "document_name": row["document_name"],
                "source_type": row.get("source_type"),
                "snippet": row.get("snippet") or row.get("text"),
                "text": row.get("text"),
                "accession_id": row.get("accession_id"),
                "item_id": row.get("item_id"),
                "taxon_id": row.get("taxon_id"),
                "score": row.get("score"),
                "document_type": row.get("document_type"),
                "reliability_tier": row.get("reliability_tier"),
                "source_file_path": row.get("source_file_path"),
                "date": row.get("date"),
                "lane": row.get("lane"),
                "citation": _citation("document", row["document_name"], row["chunk_id"]),
            }
            for row in results
        ],
    }


def search_records(session: Session, query_or_filters: str | dict[str, Any], limit: int = 10) -> dict[str, Any]:
    filters = _parse_query_filters(query_or_filters)
    accessions_stmt = select(Accession).options(selectinload(Accession.taxon), selectinload(Accession.provenances))

    if filters.get("missing_provenance"):
        accessions_stmt = (
            accessions_stmt.outerjoin(Provenance, Provenance.accession_id == Accession.id)
            .where(
                or_(
                    Provenance.id.is_(None),
                    Provenance.origin_code.is_(None),
                    Provenance.origin_code.in_(["", "U", "UNKNOWN"]),
                )
            )
            .distinct()
            .order_by(Accession.accession_number)
        )
        accessions = session.scalars(accessions_stmt.limit(limit)).all()
    elif filters.get("unknown_provenance"):
        accessions_stmt = (
            accessions_stmt.join(Provenance, Provenance.accession_id == Accession.id)
            .where(or_(Provenance.origin_code.is_(None), Provenance.origin_code.in_(["", "U", "UNKNOWN"])))
            .order_by(Accession.accession_number)
        )
        accessions = session.scalars(accessions_stmt.limit(limit)).all()
    else:
        query = f"%{filters.get('query', '').strip()}%"
        accessions = session.scalars(
            accessions_stmt.where(
                or_(
                    Accession.accession_number.ilike(query),
                    Accession.accession_number_normalized.ilike(query),
                    Accession.taxon_name_verbatim.ilike(query),
                )
            )
            .limit(limit)
        ).all()

    items_query = f"%{filters.get('query', '').strip()}%"
    items = session.scalars(
        select(Item).options(selectinload(Item.accession)).where(
            or_(Item.item_label.ilike(items_query), Item.item_number.ilike(items_query))
        ).limit(limit)
    ).all()
    taxa = session.scalars(
        select(Taxon).where(Taxon.scientific_name.ilike(items_query)).limit(limit)
    ).all()

    return {
        "tool": "search_records",
        "filters": filters,
        "accessions": [
            {
                "id": accession.id,
                "accession_number": accession.accession_number,
                "taxon": accession.taxon.scientific_name if accession.taxon else accession.taxon_name_verbatim,
                "accession_year": accession.accession_year,
                "provenance_count": len(accession.provenances),
                "citation": _citation("accession", accession.id),
            }
            for accession in accessions
        ],
        "items": [
            {
                "id": item.id,
                "item_label": item.item_label,
                "life_status": item.life_status,
                "accession_number": item.accession.accession_number if item.accession else None,
                "citation": _citation("item", item.id),
            }
            for item in items
        ],
        "taxa": [
            {
                "id": taxon.id,
                "scientific_name": taxon.scientific_name,
                "family": taxon.family,
                "citation": _citation("taxon", taxon.id),
            }
            for taxon in taxa
        ],
    }


def get_accession(session: Session, accession_id: str) -> dict[str, Any] | None:
    accession = session.scalar(
        select(Accession)
        .options(
            selectinload(Accession.items).selectinload(Item.events),
            selectinload(Accession.events),
            selectinload(Accession.provenances),
            selectinload(Accession.taxon),
        )
        .where(Accession.id == accession_id)
    )
    if not accession:
        return None
    return {
        "tool": "get_accession",
        "id": accession.id,
        "accession_number": accession.accession_number,
        "taxon": accession.taxon.scientific_name if accession.taxon else accession.taxon_name_verbatim,
        "accession_date": accession.accession_date,
        "items": [
            {
                "id": item.id,
                "item_label": item.item_label,
                "life_status": item.life_status,
                "event_count": len(item.events),
                "citation": _citation("item", item.id),
            }
            for item in accession.items
        ],
        "provenances": [
            {
                "id": provenance.id,
                "origin_code": provenance.origin_code,
                "source_id": provenance.source_id,
                "collection_locality": provenance.collection_locality,
                "citation": _citation("provenance", provenance.id),
            }
            for provenance in accession.provenances
        ],
        "events": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "event_date": event.event_date,
                "citation": _citation("event", event.id),
            }
            for event in accession.events
        ],
        "citation": _citation("accession", accession.id),
    }


def get_item(session: Session, item_id: str) -> dict[str, Any] | None:
    item = session.scalar(
        select(Item)
        .options(selectinload(Item.events), selectinload(Item.accession).selectinload(Accession.taxon))
        .where(Item.id == item_id)
    )
    if not item:
        return None
    return {
        "tool": "get_item",
        "id": item.id,
        "item_label": item.item_label,
        "life_status": item.life_status,
        "accession_number": item.accession.accession_number if item.accession else None,
        "taxon": item.accession.taxon.scientific_name if item.accession and item.accession.taxon else None,
        "events": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "event_date": event.event_date,
                "notes": event.notes,
                "citation": _citation("event", event.id),
            }
            for event in item.events
        ],
        "citation": _citation("item", item.id),
    }


def get_taxon(session: Session, taxon_id: str) -> dict[str, Any] | None:
    taxon = session.scalar(
        select(Taxon).options(selectinload(Taxon.accessions)).where(Taxon.id == taxon_id)
    )
    if not taxon:
        return None
    return {
        "tool": "get_taxon",
        "id": taxon.id,
        "scientific_name": taxon.scientific_name,
        "family": taxon.family,
        "accessions": [
            {
                "id": accession.id,
                "accession_number": accession.accession_number,
                "citation": _citation("accession", accession.id),
            }
            for accession in taxon.accessions[:20]
        ],
        "citation": _citation("taxon", taxon.id),
    }


def list_validation_issues(session: Session, filters: dict[str, Any] | None = None, **kwargs) -> dict[str, Any]:
    filters = {**(filters or {}), **kwargs}
    stmt = select(ValidationIssue).order_by(ValidationIssue.detected_at.desc())
    if filters.get("issue_type"):
        stmt = stmt.where(ValidationIssue.issue_type == filters["issue_type"])
    if filters.get("severity"):
        stmt = stmt.where(ValidationIssue.severity == filters["severity"])
    if filters.get("entity_type"):
        stmt = stmt.where(ValidationIssue.entity_type == filters["entity_type"])
    if filters.get("entity_id"):
        stmt = stmt.where(ValidationIssue.entity_id == filters["entity_id"])
    if filters.get("status"):
        stmt = stmt.where(ValidationIssue.status == filters["status"])
    limit = int(filters.get("limit", 20))
    issues = session.scalars(stmt.limit(limit)).all()
    return {
        "tool": "list_validation_issues",
        "filters": filters,
        "issues": [
            {
                "id": issue.id,
                "issue_type": issue.issue_type,
                "severity": issue.severity,
                "entity_type": issue.entity_type,
                "entity_id": issue.entity_id,
                "entity_label": issue.entity_label,
                "explanation": issue.explanation,
                "recommended_action": issue.recommended_action,
                "citation": _citation("validation_issue", issue.id),
            }
            for issue in issues
        ],
    }


def create_correction_ticket(
    session: Session,
    *,
    title: str | None = None,
    proposed_correction: str | None = None,
    reason: str | None = None,
    evidence: str | None = None,
    affected_entity_type: str | None = None,
    affected_entity_id: str | None = None,
    confidence: str = "medium",
    linked_validation_issue_id: str | None = None,
    created_by: str = "assistant",
) -> dict[str, Any]:
    if linked_validation_issue_id:
        issue = session.get(ValidationIssue, linked_validation_issue_id)
        if not issue:
            raise ValueError(f"Validation issue {linked_validation_issue_id} was not found.")
        ticket = create_ticket_from_issue(session, issue, created_by=created_by)
    else:
        ticket = CorrectionTicket(
            title=title or "Assistant-proposed correction",
            proposed_correction=proposed_correction or "Review this record.",
            reason=reason,
            evidence=evidence,
            affected_entity_type=affected_entity_type,
            affected_entity_id=affected_entity_id,
            affected_records_json=json.dumps(
                [
                    {
                        "entity_type": affected_entity_type,
                        "entity_id": affected_entity_id,
                    }
                ]
            ),
            confidence=confidence,
            created_by=created_by,
        )
        session.add(ticket)
    session.commit()
    return {
        "tool": "create_correction_ticket",
        "ticket": {
            "id": ticket.id,
            "title": ticket.title,
            "status": ticket.status,
            "citation": _citation("ticket", ticket.id),
        },
    }


def summarize_collection(session: Session) -> dict[str, Any]:
    metrics = calculate_metrics(session)
    return {
        "tool": "summarize_collection",
        "summary": {
            "total_accessions": metrics["total_accessions"],
            "total_items": metrics["total_items"],
            "total_taxa": metrics["total_taxa"],
            "total_locations": metrics["total_locations"],
            "provenance_coverage_pct": metrics["provenance_coverage_pct"],
            "source_coverage_pct": metrics["source_coverage_pct"],
        },
        "citation": "collection_summary:metrics",
    }


def generate_data_quality_report(session: Session, output_path: str | Path | None = None) -> dict[str, Any]:
    report = generate_markdown_report(session, output_path=output_path)
    return {
        "tool": "generate_data_quality_report",
        "output_path": str(output_path) if output_path else None,
        "preview": report[:1000],
        "citation": "report:markdown",
    }


def query_database(session: Session, adapter: Any, question: str, rules: list[str] | None = None) -> dict[str, Any]:
    """Convert a natural-language question to SQL, execute it, and return results."""
    engine = get_engine()
    schema = generate_schema_description(engine)
    sql = generate_sql(adapter, question, schema, rules=rules)
    results = execute_safe_query(engine, sql)
    return format_sql_results(results, question, sql)


def build_tool_registry(session: Session, adapter: Any = None) -> dict[str, Any]:
    registry = {
        "search_documents": lambda **kwargs: search_documents(session, **kwargs),
        "search_records": lambda **kwargs: search_records(
            session,
            kwargs.pop("query_or_filters", kwargs.pop("query", "")),
            **kwargs,
        ),
        "get_accession": lambda **kwargs: get_accession(session, **kwargs),
        "get_item": lambda **kwargs: get_item(session, **kwargs),
        "get_taxon": lambda **kwargs: get_taxon(session, **kwargs),
        "list_validation_issues": lambda **kwargs: list_validation_issues(session, **kwargs),
        "create_correction_ticket": lambda **kwargs: create_correction_ticket(session, **kwargs),
        "summarize_collection": lambda **kwargs: summarize_collection(session),
        "generate_data_quality_report": lambda **kwargs: generate_data_quality_report(session, **kwargs),
        "generate_dashboard_data": lambda **kwargs: {"tool": "generate_dashboard_data", "data": calculate_metrics(session)},
    }
    if adapter is not None:
        registry["query_database"] = lambda **kwargs: query_database(
            session, adapter, kwargs.pop("question", kwargs.pop("query", "")), kwargs.get("rules"),
        )
    return registry
