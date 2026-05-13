from __future__ import annotations

from pathlib import Path

from ben0.db.models import Accession, Event, Item, Location, Provenance, Taxon
from ben0.db.session import get_session, init_db, reset_singletons
from ben0.ingest.normalize import normalize_accession_number
from ben0.validation.rules import (
    check_accession_number_integrity,
    check_item_status_consistency,
    check_required_accession_fields,
    check_similar_unreconciled_taxa,
)


def _session_for(tmp_path: Path, name: str):
    db_url = f"sqlite:///{tmp_path / name}"
    reset_singletons()
    init_db(db_url)
    return db_url, get_session(db_url)


def test_missing_accession_number_detected(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "missing-accession.db")
    try:
        session.add(Accession(accession_number="", accession_number_normalized=None))
        session.commit()

        findings = check_accession_number_integrity(session)
        assert any(finding.issue_type == "missing_accession_number" for finding in findings)
    finally:
        session.close()
        reset_singletons()


def test_duplicate_accession_detected(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "duplicate-accession.db")
    try:
        session.add_all(
            [
                Accession(
                    accession_number="2005-0234",
                    accession_number_normalized=normalize_accession_number("2005-0234"),
                ),
                Accession(
                    accession_number="2005.0234",
                    accession_number_normalized=normalize_accession_number("2005.0234"),
                ),
            ]
        )
        session.commit()

        findings = check_accession_number_integrity(session)
        assert any(finding.issue_type == "duplicate_accession_number" for finding in findings)
    finally:
        session.close()
        reset_singletons()


def test_missing_provenance_detected(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "missing-provenance.db")
    try:
        accession = Accession(
            accession_number="2005-0234",
            accession_number_normalized=normalize_accession_number("2005-0234"),
            taxon_name_verbatim="Abies lasiocarpa",
        )
        session.add(accession)
        session.commit()

        findings = check_required_accession_fields(session)
        assert any(finding.issue_type == "missing_provenance" for finding in findings)
    finally:
        session.close()
        reset_singletons()


def test_living_item_without_location_detected(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "living-no-location.db")
    try:
        accession = Accession(
            accession_number="2005-0234",
            accession_number_normalized=normalize_accession_number("2005-0234"),
            taxon_name_verbatim="Abies lasiocarpa",
        )
        session.add(accession)
        session.flush()
        session.add(Provenance(accession_id=accession.id, origin_code="W"))
        item = Item(
            accession_id=accession.id,
            item_number="01",
            item_label="2005-0234.01",
            life_status="living",
            is_current=True,
        )
        session.add(item)
        session.flush()
        session.add(Event(accession_id=accession.id, item_id=item.id, event_type="planted", event_date="2006-05-20"))
        session.commit()

        findings = check_item_status_consistency(session)
        assert any(finding.issue_type == "living_item_without_current_location" for finding in findings)
    finally:
        session.close()
        reset_singletons()


def test_dead_item_marked_current_detected(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "dead-current.db")
    try:
        accession = Accession(
            accession_number="2005-0234",
            accession_number_normalized=normalize_accession_number("2005-0234"),
            taxon_name_verbatim="Abies lasiocarpa",
        )
        location = Location(location_code="ALP1", location_name="Alpine Garden")
        session.add_all([accession, location])
        session.flush()
        session.add(Provenance(accession_id=accession.id, origin_code="W"))
        item = Item(
            accession_id=accession.id,
            item_number="01",
            item_label="2005-0234.01",
            current_location_id=location.id,
            life_status="dead",
            is_current=True,
        )
        session.add(item)
        session.flush()
        session.add(Event(accession_id=accession.id, item_id=item.id, event_type="dead", event_date="2010-06-15"))
        session.commit()

        findings = check_item_status_consistency(session)
        assert any(finding.issue_type == "dead_item_marked_current" for finding in findings)
    finally:
        session.close()
        reset_singletons()


def test_similar_taxa_detected(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "similar-taxa.db")
    try:
        session.add_all(
            [
                Taxon(scientific_name="Abies lasiocarpa", genus="Abies", species="lasiocarpa"),
                Taxon(scientific_name="Abies lasiocarpo", genus="Abies", species="lasiocarpo"),
            ]
        )
        session.commit()

        findings = check_similar_unreconciled_taxa(session)
        assert any(finding.issue_type == "similar_unreconciled_taxon_names" for finding in findings)
    finally:
        session.close()
        reset_singletons()
