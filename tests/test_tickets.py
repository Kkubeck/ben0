from __future__ import annotations

from pathlib import Path

from ben0.db.models import ValidationIssue
from ben0.db.session import get_session, init_db, reset_singletons
from ben0.tickets.service import create_tickets_from_issues, list_tickets


def _session_for(tmp_path: Path, name: str):
    db_url = f"sqlite:///{tmp_path / name}"
    reset_singletons()
    init_db(db_url)
    return db_url, get_session(db_url)


def test_create_tickets_from_issues(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "tickets-create.db")
    try:
        session.add_all(
            [
                ValidationIssue(
                    issue_type="missing_provenance",
                    severity="error",
                    entity_type="accession",
                    entity_id="acc-1",
                    entity_label="2005-0234",
                    explanation="Accession has no provenance.",
                    evidence="accession_number=2005-0234",
                    recommended_action="Create a provenance record.",
                ),
                ValidationIssue(
                    issue_type="dead_item_marked_current",
                    severity="critical",
                    entity_type="item",
                    entity_id="item-1",
                    entity_label="2005-0234.01",
                    explanation="Dead item is marked current.",
                    evidence="item_label=2005-0234.01",
                    recommended_action="Mark the item non-current.",
                ),
            ]
        )
        session.commit()

        tickets = create_tickets_from_issues(session)
        assert len(tickets) == 2
        assert all(ticket.linked_validation_issue_id for ticket in tickets)
        assert {ticket.confidence for ticket in tickets} == {"high"}
    finally:
        session.close()
        reset_singletons()


def test_ticket_status_filtering(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "tickets-filter.db")
    try:
        session.add(
            ValidationIssue(
                issue_type="missing_provenance",
                severity="warning",
                entity_type="accession",
                entity_id="acc-1",
                entity_label="2005-0234",
                explanation="Accession has unknown provenance.",
                evidence="accession_number=2005-0234",
                recommended_action="Review the accession file.",
            )
        )
        session.commit()

        tickets = create_tickets_from_issues(session)
        tickets[0].status = "accepted"
        session.commit()

        accepted = list_tickets(session, status="accepted")
        proposed = list_tickets(session, status="proposed")
        assert len(accepted) == 1
        assert accepted[0].status == "accepted"
        assert proposed == []
    finally:
        session.close()
        reset_singletons()
