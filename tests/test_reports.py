from __future__ import annotations

from pathlib import Path

from ben0.dashboard.metrics import calculate_metrics
from ben0.db.models import Accession, CorrectionTicket, Item, Location, Provenance, Taxon, ValidationIssue
from ben0.db.session import get_session, init_db, reset_singletons
from ben0.ingest.normalize import normalize_accession_number
from ben0.reports.markdown_report import generate_markdown_report


def _session_for(tmp_path: Path, name: str):
    db_url = f"sqlite:///{tmp_path / name}"
    reset_singletons()
    init_db(db_url)
    return db_url, get_session(db_url)


def _seed_collection(session) -> None:
    taxon = Taxon(scientific_name="Abies lasiocarpa", genus="Abies", species="lasiocarpa")
    location = Location(location_code="ALP1", location_name="Alpine Garden")
    session.add_all([taxon, location])
    session.flush()

    accession1 = Accession(
        accession_number="2005-0234",
        accession_number_normalized=normalize_accession_number("2005-0234"),
        taxon_id=taxon.id,
        taxon_name_verbatim="Abies lasiocarpa",
        accession_date="2005-03-12",
        accession_year=2005,
        notes="Wild provenance from Manning Park.",
    )
    accession2 = Accession(
        accession_number="1952-0001",
        accession_number_normalized=normalize_accession_number("1952-0001"),
        taxon_id=taxon.id,
        taxon_name_verbatim="Abies lasiocarpa",
        accession_date="1952-01-01",
        accession_year=1952,
    )
    session.add_all([accession1, accession2])
    session.flush()

    session.add_all(
        [
            Provenance(accession_id=accession1.id, origin_code="W", source_id=None),
            Provenance(accession_id=accession2.id, origin_code="G", source_id=None),
        ]
    )
    session.add_all(
        [
            Item(
                accession_id=accession1.id,
                item_number="01",
                item_label="2005-0234.01",
                current_location_id=location.id,
                life_status="living",
                is_current=True,
                planting_date="2006-05-20",
            ),
            Item(
                accession_id=accession2.id,
                item_number="01",
                item_label="1952-0001.01",
                life_status="dead",
                is_current=False,
                death_date="2010-06-15",
            ),
        ]
    )
    session.add(
        ValidationIssue(
            issue_type="missing_source",
            severity="warning",
            entity_type="accession",
            entity_id=accession1.id,
            entity_label=accession1.accession_number,
            explanation="Provenance exists without a linked source.",
            evidence="accession_number=2005-0234",
            recommended_action="Link the provenance to a source.",
        )
    )
    session.add(
        CorrectionTicket(
            title="Review missing source for 2005-0234",
            proposed_correction="Link provenance to an institution record.",
            affected_entity_type="accession",
            affected_entity_id=accession1.id,
            status="proposed",
        )
    )
    session.commit()


def test_report_contains_expected_sections(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "report-sections.db")
    try:
        _seed_collection(session)
        report = generate_markdown_report(session)
        assert "# BEN-0 Collection Data Health Report" in report
        assert "## Collection Overview" in report
        assert "## Provenance Profile" in report
        assert "## Data Quality Summary" in report
        assert "## Recommendations" in report
    finally:
        session.close()
        reset_singletons()


def test_metrics_calculation(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "report-metrics.db")
    try:
        _seed_collection(session)
        metrics = calculate_metrics(session)
        assert metrics["total_accessions"] == 2
        assert metrics["total_items"] == 2
        assert metrics["total_taxa"] == 1
        assert metrics["total_locations"] == 1
        assert metrics["provenance_breakdown"]["wild"] == 1
        assert metrics["provenance_breakdown"]["garden"] == 1
        assert metrics["provenance_coverage_pct"] == 100.0
        assert metrics["source_coverage_pct"] == 0.0
        assert metrics["validation_issues_by_severity"]["warning"] == 1
        assert metrics["correction_tickets_by_status"]["proposed"] == 1
    finally:
        session.close()
        reset_singletons()
