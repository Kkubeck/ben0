from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ben0.assistant.entity_detection import detect_accessions, detect_entities, detect_locations, detect_taxa
from ben0.db.models import Base, Location, Taxon


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def test_detect_accessions_normalizes_variants() -> None:
    matches = detect_accessions("Tell me about accession 12345.678.90 and 1984-23.")

    assert [(match.entity_type, match.entity_id) for match in matches] == [
        ("accession", "12345-678-90"),
        ("accession", "1984-0023"),
    ]


def test_detect_taxa_matches_scientific_name_case_insensitively() -> None:
    session = _make_session()
    try:
        session.add(Taxon(id="taxon-1", scientific_name="Acer macrophyllum", family="Sapindaceae"))
        session.commit()

        matches = detect_taxa(session, "Do you have acer macrophyllum in the collection?")

        assert [(match.entity_type, match.entity_id, match.canonical_name) for match in matches] == [
            ("taxon", "taxon-1", "Acer macrophyllum"),
        ]
    finally:
        session.close()


def test_detect_locations_matches_codes_and_aliases() -> None:
    session = _make_session()
    try:
        session.add(
            Location(
                id="loc-1",
                location_code="D-42",
                aliases=json.dumps(["42D", "D42"]),
                location_name="Douglas Bed",
            )
        )
        session.commit()

        direct_matches = detect_locations(session, "What is planted in D-42?")
        alias_matches = detect_locations(session, "What is planted in 42D?")

        assert [(match.entity_type, match.entity_id, match.canonical_name) for match in direct_matches] == [
            ("location", "loc-1", "D-42"),
        ]
        assert [(match.entity_type, match.entity_id, match.canonical_name) for match in alias_matches] == [
            ("location", "loc-1", "D-42"),
        ]
    finally:
        session.close()


def test_detect_entities_combines_unique_matches() -> None:
    session = _make_session()
    try:
        session.add_all(
            [
                Taxon(id="taxon-1", scientific_name="Acer macrophyllum", family="Sapindaceae"),
                Location(id="loc-1", location_code="ALP1", location_name="Alpine Garden"),
            ]
        )
        session.commit()

        matches = detect_entities(
            session,
            "Compare Acer macrophyllum in ALP1 with accession 1984-23 and accession 1984-0023.",
        )

        assert [(match.entity_type, match.canonical_name) for match in matches] == [
            ("accession", "1984-0023"),
            ("taxon", "Acer macrophyllum"),
            ("location", "ALP1"),
        ]
    finally:
        session.close()
