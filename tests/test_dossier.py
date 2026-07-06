"""Tests for dossier storage and tag assignment."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ben0.assistant.entity_detection import DetectedEntity
from ben0.db.models import Accession, Base, Item, Location, Provenance, Taxon
from ben0.memory.dossier import (
    Dossier,
    DossierEntry,
    append_learned,
    load_dossier,
    read_dossier,
    seed_from_db,
)
from ben0.memory.tags import TAG_SET, assign_tags


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


# ---------------------------------------------------------------------------
# Tag assignment tests
# ---------------------------------------------------------------------------


class TestAssignTags:
    def test_status_and_location(self) -> None:
        tags = assign_tags({"life_status": "dead", "bed_code": "D-42"})
        assert tags == ["status", "location"]

    def test_provenance_from_collector(self) -> None:
        tags = assign_tags({"collector": "J. Smith"})
        assert tags == ["provenance"]

    def test_empty_fields_return_no_tags(self) -> None:
        assert assign_tags({}) == []

    def test_max_two_tags(self) -> None:
        tags = assign_tags(
            {"life_status": "dead", "bed_code": "D-42", "collector": "Smith"}
        )
        assert len(tags) <= 2

    def test_taxonomy_tag(self) -> None:
        tags = assign_tags({"scientific_name": "Acer macrophyllum", "family": "Sapindaceae"})
        assert tags == ["taxonomy"]

    def test_conservation_tag(self) -> None:
        tags = assign_tags({"iucn_status": "VU"})
        assert tags == ["conservation"]

    def test_document_ref_tag(self) -> None:
        tags = assign_tags({"document": "plan.pdf", "filename": "plan.pdf"})
        assert tags == ["document-ref"]

    def test_all_tags_in_tag_set(self) -> None:
        for fields, expected in [
            ({"life_status": "alive"}, "status"),
            ({"bed_code": "A-1"}, "location"),
            ({"collector": "X"}, "provenance"),
            ({"propagation": "cutting"}, "propagation"),
            ({"scientific_name": "X"}, "taxonomy"),
            ({"iucn_status": "LC"}, "conservation"),
            ({"document": "x.pdf"}, "document-ref"),
            ({"validation_issue": "missing"}, "validation"),
        ]:
            result = assign_tags(fields)
            assert result[0] == expected
            assert result[0] in TAG_SET


# ---------------------------------------------------------------------------
# Dossier create / read / append tests
# ---------------------------------------------------------------------------


class TestDossierCreateReadAppend:
    def test_load_nonexistent_returns_empty(self, tmp_path: Path) -> None:
        with patch("ben0.memory.dossier.DOSSIER_ROOT", tmp_path):
            d = load_dossier("taxon", "nonexistent")
            assert d.entity_type == "taxon"
            assert d.facts == []
            assert d.learned == []

    def test_create_and_read_roundtrip(self, tmp_path: Path) -> None:
        with patch("ben0.memory.dossier.DOSSIER_ROOT", tmp_path):
            d = Dossier(
                entity_type="taxon",
                entity_id="acer-macrophyllum",
                canonical_name="Acer macrophyllum",
                facts=["Family: Sapindaceae", "12 accessions in collection"],
                learned=[],
                path=tmp_path / "taxon" / "acer-macrophyllum.md",
            )
            append_learned(d, [])

            loaded = load_dossier("taxon", "acer-macrophyllum")
            assert loaded.canonical_name == "Acer macrophyllum"
            assert "Family: Sapindaceae" in loaded.facts
            assert "12 accessions in collection" in loaded.facts

    def test_append_learned_entries(self, tmp_path: Path) -> None:
        with patch("ben0.memory.dossier.DOSSIER_ROOT", tmp_path):
            d = Dossier(
                entity_type="taxon",
                entity_id="acer-macrophyllum",
                canonical_name="Acer macrophyllum",
                facts=["Family: Sapindaceae"],
                learned=[],
                path=tmp_path / "taxon" / "acer-macrophyllum.md",
            )
            entries = [
                DossierEntry("2026-07-05", ["status", "location"], "3 of 12 items dead, all in bed D-42"),
                DossierEntry("2026-07-10", ["propagation"], "2 cuttings taken spring 2024"),
            ]
            append_learned(d, entries)

            loaded = load_dossier("taxon", "acer-macrophyllum")
            assert len(loaded.learned) == 2
            assert loaded.learned[0].tags == ["status", "location"]
            assert "3 of 12 items dead" in loaded.learned[0].text
            assert loaded.learned[1].tags == ["propagation"]

    def test_read_dossier_returns_raw_markdown(self, tmp_path: Path) -> None:
        with patch("ben0.memory.dossier.DOSSIER_ROOT", tmp_path):
            d = Dossier(
                entity_type="taxon",
                entity_id="test-taxon",
                canonical_name="Test Taxon",
                facts=["A fact"],
                learned=[DossierEntry("2026-07-05", ["status"], "alive")],
                path=tmp_path / "taxon" / "test-taxon.md",
            )
            append_learned(d, [])

            raw = read_dossier("taxon", "test-taxon")
            assert "# Test Taxon" in raw
            assert "## Facts" in raw
            assert "## Learned" in raw
            assert "- A fact" in raw

    def test_read_dossier_nonexistent_returns_empty(self, tmp_path: Path) -> None:
        with patch("ben0.memory.dossier.DOSSIER_ROOT", tmp_path):
            assert read_dossier("taxon", "nope") == ""

    def test_multiple_appends_accumulate(self, tmp_path: Path) -> None:
        with patch("ben0.memory.dossier.DOSSIER_ROOT", tmp_path):
            d = Dossier(
                entity_type="accession",
                entity_id="1968-0042",
                canonical_name="1968-0042",
                facts=["Taxon: Acer macrophyllum"],
                learned=[],
                path=tmp_path / "accession" / "1968-0042.md",
            )
            append_learned(d, [DossierEntry("2026-07-05", ["status"], "alive")])
            append_learned(d, [DossierEntry("2026-07-06", ["location"], "moved to D-42")])

            loaded = load_dossier("accession", "1968-0042")
            assert len(loaded.learned) == 2


# ---------------------------------------------------------------------------
# Seed from DB tests
# ---------------------------------------------------------------------------


class TestSeedFromDb:
    def test_seed_taxon(self) -> None:
        session = _make_session()
        try:
            taxon = Taxon(id="t1", scientific_name="Acer macrophyllum", family="Sapindaceae")
            session.add(taxon)
            session.flush()
            acc = Accession(id="a1", accession_number="1968-0042", taxon_id="t1")
            session.add(acc)
            session.flush()
            session.add(Item(id="i1", accession_id="a1", life_status="living"))
            session.add(Item(id="i2", accession_id="a1", life_status="dead"))
            session.add(Provenance(id="p1", accession_id="a1", origin_code="W"))
            session.commit()

            entity = DetectedEntity("taxon", "t1", "Acer macrophyllum", "Acer macrophyllum")
            facts = seed_from_db(session, entity)

            assert any("Sapindaceae" in f for f in facts)
            assert any("1 accessions" in f for f in facts)
            assert any("2 items total" in f for f in facts)
            assert any("Wild-collected" in f for f in facts)
        finally:
            session.close()

    def test_seed_accession(self) -> None:
        session = _make_session()
        try:
            taxon = Taxon(id="t1", scientific_name="Acer macrophyllum", family="Sapindaceae")
            session.add(taxon)
            session.flush()
            acc = Accession(
                id="a1",
                accession_number="1968-0042",
                accession_number_normalized="1968-0042",
                taxon_id="t1",
                accession_date="1968-03-15",
            )
            session.add(acc)
            session.flush()
            session.add(Item(id="i1", accession_id="a1"))
            session.add(Provenance(id="p1", accession_id="a1", collector="J. Smith", origin_code="W"))
            session.commit()

            entity = DetectedEntity("accession", "1968-0042", "1968-0042", "1968-0042")
            facts = seed_from_db(session, entity)

            assert any("Acer macrophyllum" in f for f in facts)
            assert any("1968-03-15" in f for f in facts)
            assert any("J. Smith" in f for f in facts)
        finally:
            session.close()

    def test_seed_location(self) -> None:
        session = _make_session()
        try:
            loc = Location(id="loc1", location_code="D-42", location_name="Douglas Bed")
            session.add(loc)
            session.flush()
            acc = Accession(id="a1", accession_number="1968-0042")
            session.add(acc)
            session.flush()
            session.add(Item(id="i1", accession_id="a1", current_location_id="loc1"))
            session.commit()

            entity = DetectedEntity("location", "loc1", "D-42", "D-42")
            facts = seed_from_db(session, entity)

            assert any("Douglas Bed" in f for f in facts)
            assert any("1 items" in f for f in facts)
        finally:
            session.close()

    def test_seed_unknown_entity_type(self) -> None:
        session = _make_session()
        try:
            entity = DetectedEntity("unknown", "x", "X", "X")
            assert seed_from_db(session, entity) == []
        finally:
            session.close()

    def test_seed_missing_taxon(self) -> None:
        session = _make_session()
        try:
            entity = DetectedEntity("taxon", "nonexistent", "Nope", "Nope")
            assert seed_from_db(session, entity) == []
        finally:
            session.close()
