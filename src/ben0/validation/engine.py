"""Validation engine orchestration for BEN-0."""

from __future__ import annotations

from collections import Counter

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ben0.db.models import ValidationIssue
from .rules import ValidationFinding, run_all_rules


def run_validation(session: Session, *, clear_existing: bool = True) -> dict[str, int]:
    """Run all validation rules, persist issues, and return summary counts."""
    if clear_existing:
        session.execute(delete(ValidationIssue))
        session.flush()

    findings = run_all_rules(session)
    issue_rows = [_to_issue(finding) for finding in findings]
    session.add_all(issue_rows)
    session.commit()

    summary = Counter(issue.severity for issue in issue_rows)
    summary["total"] = len(issue_rows)
    return dict(summary)


def _to_issue(finding: ValidationFinding) -> ValidationIssue:
    return ValidationIssue(
        issue_type=finding.issue_type,
        severity=finding.severity,
        entity_type=finding.entity_type,
        entity_id=finding.entity_id,
        entity_label=finding.entity_label,
        explanation=finding.explanation,
        evidence=finding.evidence,
        recommended_action=finding.recommended_action,
        requires_human_review=finding.requires_human_review,
    )


def list_validation_issues(session: Session, *, status: str | None = None, severity: str | None = None) -> list[ValidationIssue]:
    stmt = select(ValidationIssue).order_by(ValidationIssue.detected_at.desc(), ValidationIssue.severity.desc())
    if status:
        stmt = stmt.where(ValidationIssue.status == status)
    if severity:
        stmt = stmt.where(ValidationIssue.severity == severity)
    return session.scalars(stmt).all()
