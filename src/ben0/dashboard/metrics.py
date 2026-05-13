"""Collection dashboard metrics for BEN-0."""

from __future__ import annotations

from collections import Counter
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ben0.db.models import (
    Accession,
    CorrectionTicket,
    Item,
    Location,
    Provenance,
    Taxon,
    ValidationIssue,
)

_WILD_CODES = {"W", "Z", "WILD", "WILDNATIVE"}
_GARDEN_CODES = {"G", "GARDEN", "CULTIVATED", "INTRODUCED"}


def _extract_year(raw: str | None, fallback: int | None = None) -> int | None:
    if fallback:
        return fallback
    if not raw:
        return None
    match = re.search(r"(18|19|20)\d{2}", raw)
    return int(match.group(0)) if match else None


def _normalize_item_status(raw: str | None) -> str:
    value = (raw or "unknown").strip().lower()
    if value in {"living", "alive", "current"}:
        return "alive"
    if value == "dead":
        return "dead"
    if value in {"removed", "transferred"}:
        return "removed"
    return "unknown"


def _classify_provenance(provenances: list[Provenance]) -> str:
    if not provenances:
        return "unknown"

    categories: set[str] = set()
    for provenance in provenances:
        origin = (provenance.origin_code or provenance.establishment_means or "").strip().upper()
        if origin in _WILD_CODES:
            categories.add("wild")
        elif origin in _GARDEN_CODES:
            categories.add("garden")
        else:
            categories.add("unknown")

    if "wild" in categories:
        return "wild"
    if "garden" in categories:
        return "garden"
    return "unknown"


def calculate_metrics(session: Session) -> dict[str, Any]:
    """Calculate collection accountability metrics from the database."""
    accessions = session.scalars(
        select(Accession).options(selectinload(Accession.provenances)).order_by(Accession.accession_number)
    ).all()
    items = session.scalars(select(Item).order_by(Item.item_label, Item.id)).all()
    issues = session.scalars(select(ValidationIssue).order_by(ValidationIssue.detected_at.desc())).all()
    tickets = session.scalars(select(CorrectionTicket).order_by(CorrectionTicket.created_at.desc())).all()

    total_taxa = session.scalar(select(func.count()).select_from(Taxon)) or 0
    total_locations = session.scalar(select(func.count()).select_from(Location)) or 0

    item_status_counts = Counter(_normalize_item_status(item.life_status) for item in items)
    provenance_breakdown = Counter(_classify_provenance(accession.provenances) for accession in accessions)
    issues_by_severity = Counter(issue.severity for issue in issues)
    issues_by_type = Counter(issue.issue_type for issue in issues)
    tickets_by_status = Counter(ticket.status for ticket in tickets)

    top_taxa_rows = (
        session.query(Taxon.id, Taxon.scientific_name, func.count(Item.id).label("item_count"))
        .join(Accession, Accession.taxon_id == Taxon.id)
        .join(Item, Item.accession_id == Accession.id)
        .group_by(Taxon.id, Taxon.scientific_name)
        .order_by(func.count(Item.id).desc(), Taxon.scientific_name)
        .limit(10)
        .all()
    )
    top_taxa_by_item_count = [
        {
            "taxon_id": taxon_id,
            "scientific_name": scientific_name,
            "item_count": item_count,
        }
        for taxon_id, scientific_name, item_count in top_taxa_rows
    ]

    timeline_counter: Counter[int] = Counter()
    years: list[int] = []
    provenance_covered = 0
    source_covered = 0
    for accession in accessions:
        year = _extract_year(accession.accession_date, accession.accession_year)
        if year:
            years.append(year)
            timeline_counter[year - (year % 10)] += 1
        if accession.provenances:
            provenance_covered += 1
        if any(provenance.source_id for provenance in accession.provenances):
            source_covered += 1

    total_accessions = len(accessions)
    timeline = [
        {"decade": decade, "label": f"{decade}s", "count": count}
        for decade, count in sorted(timeline_counter.items())
    ]

    recent_tickets = [
        {
            "id": ticket.id,
            "title": ticket.title,
            "status": ticket.status,
            "confidence": ticket.confidence,
            "affected_entity_type": ticket.affected_entity_type,
            "affected_entity_id": ticket.affected_entity_id,
            "created_at": ticket.created_at.isoformat(timespec="seconds"),
        }
        for ticket in tickets[:10]
    ]

    return {
        "total_accessions": total_accessions,
        "total_items": len(items),
        "total_taxa": total_taxa,
        "total_locations": total_locations,
        "items_by_status": {
            key: item_status_counts.get(key, 0)
            for key in ("alive", "dead", "unknown", "removed")
        },
        "provenance_breakdown": {
            key: provenance_breakdown.get(key, 0)
            for key in ("wild", "garden", "unknown")
        },
        "validation_issues_by_severity": dict(sorted(issues_by_severity.items())),
        "validation_issues_by_type": dict(issues_by_type.most_common()),
        "correction_tickets_by_status": dict(sorted(tickets_by_status.items())),
        "top_taxa_by_item_count": top_taxa_by_item_count,
        "collection_timeline": timeline,
        "provenance_coverage_pct": round((provenance_covered / total_accessions) * 100, 1)
        if total_accessions
        else 0.0,
        "source_coverage_pct": round((source_covered / total_accessions) * 100, 1)
        if total_accessions
        else 0.0,
        "date_range": {
            "min_year": min(years) if years else None,
            "max_year": max(years) if years else None,
        },
        "recent_correction_tickets": recent_tickets,
        "top_validation_issues": [
            {"issue_type": issue_type, "count": count}
            for issue_type, count in issues_by_type.most_common(10)
        ],
    }


def generate_dashboard_data(session: Session) -> dict[str, Any]:
    """Alias retained for assistant/dashboard consumers."""
    return calculate_metrics(session)
