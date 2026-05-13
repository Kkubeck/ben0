"""Correction ticket helpers for BEN-0."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ben0.db.models import CorrectionTicket, ValidationIssue

CONFIDENCE_BY_SEVERITY = {
    "critical": "high",
    "error": "high",
    "warning": "medium",
    "info": "low",
}


def create_ticket_from_issue(session: Session, issue: ValidationIssue, *, created_by: str = "ben0") -> CorrectionTicket:
    existing = session.scalar(
        select(CorrectionTicket).where(CorrectionTicket.linked_validation_issue_id == issue.id)
    )
    if existing:
        return existing

    entity_label = issue.entity_label or issue.entity_id or "record"
    ticket = CorrectionTicket(
        title=f"Review {issue.issue_type.replace('_', ' ')} for {entity_label}",
        proposed_correction=issue.recommended_action or "Review and correct this record.",
        reason=issue.explanation,
        evidence=issue.evidence,
        affected_entity_type=issue.entity_type,
        affected_entity_id=issue.entity_id,
        affected_records_json=json.dumps(
            [{"entity_type": issue.entity_type, "entity_id": issue.entity_id, "entity_label": issue.entity_label}]
        ),
        confidence=CONFIDENCE_BY_SEVERITY.get(issue.severity, "medium"),
        linked_validation_issue_id=issue.id,
        created_by=created_by,
    )
    session.add(ticket)
    return ticket


def create_tickets_from_issues(
    session: Session,
    *,
    status: str = "open",
    issue_ids: list[str] | None = None,
    created_by: str = "ben0",
) -> list[CorrectionTicket]:
    stmt = select(ValidationIssue).where(ValidationIssue.status == status)
    if issue_ids:
        stmt = stmt.where(ValidationIssue.id.in_(issue_ids))
    issues = session.scalars(stmt.order_by(ValidationIssue.severity.desc(), ValidationIssue.detected_at)).all()

    tickets = [create_ticket_from_issue(session, issue, created_by=created_by) for issue in issues]
    session.commit()
    return tickets


def list_tickets(
    session: Session,
    *,
    status: str | None = None,
    entity_type: str | None = None,
) -> list[CorrectionTicket]:
    stmt = select(CorrectionTicket).order_by(CorrectionTicket.created_at.desc())
    if status:
        stmt = stmt.where(CorrectionTicket.status == status)
    if entity_type:
        stmt = stmt.where(CorrectionTicket.affected_entity_type == entity_type)
    return session.scalars(stmt).all()
