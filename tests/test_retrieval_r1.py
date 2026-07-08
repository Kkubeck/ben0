from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from ben0.db.models import Accession, Document, Event, Item, Source, SourceChunk
from ben0.db.session import get_session, init_db, reset_singletons
from ben0.retrieval.index import FTS_TABLE, build_index
from ben0.retrieval.search import search_index


def _session_for(tmp_path: Path, name: str):
    db_url = f"sqlite:///{tmp_path / name}"
    reset_singletons()
    init_db(db_url)
    return db_url, get_session(db_url)


def _seed_records(session):
    accession = Accession(
        accession_number="2005-0234",
        accession_date="2005-03-12",
        notes="Cedar accession note from Manning Park.",
        source_file="/imports/accessions.csv",
    )
    session.add(accession)
    session.flush()

    item = Item(
        accession_id=accession.id,
        item_label="2005-0234.01",
        planting_date="2006-04-01",
        notes="Cedar item note in nursery bed.",
        source_file="/imports/items.csv",
    )
    session.add(item)
    session.flush()

    document = Document(
        filename="policy.txt",
        document_type="policy",
        title="Policy",
        full_text="Cedar policy guidance for the living collection.",
        character_count=48,
        source_file="/imports/policy.txt",
    )
    session.add(document)
    session.flush()

    session.add(
        SourceChunk(
            document_id=document.id,
            chunk_index=0,
            chunk_text="Cedar policy guidance for the living collection.",
            char_start=0,
            char_end=48,
            linked_accession_id=accession.id,
        )
    )

    event = Event(
        accession_id=accession.id,
        item_id=item.id,
        event_type="planted",
        event_date="2006-05-01",
        notes="Cedar planted by staff for display bed.",
        source_file="/imports/events.csv",
    )
    source = Source(
        source_name="Exchange Program",
        notes="Cedar source note from exchange memo.",
        source_file="/imports/sources.csv",
    )
    session.add_all([event, source])
    session.commit()

    return {
        "accession": accession,
        "item": item,
        "document": document,
        "event": event,
        "source": source,
    }


def test_build_index_populates_r1_metadata(tmp_path: Path):
    _, session = _session_for(tmp_path, "retrieval-r1-index.db")
    try:
        seeded = _seed_records(session)

        count = build_index(session)
        assert count >= 5

        rows = session.execute(
            text(
                f"""
                SELECT source_type, document_type, reliability_tier, source_file_path, date, lane
                FROM {FTS_TABLE}
                ORDER BY source_type
                """
            )
        ).mappings().all()

        by_source_type = {row["source_type"]: dict(row) for row in rows}
        expected_types = {"accession_note", "document_chunk", "event_note", "item_note"}
        assert expected_types <= set(by_source_type.keys())

        assert by_source_type["accession_note"]["document_type"] == "accession_record"
        assert by_source_type["accession_note"]["reliability_tier"] == "official"
        assert by_source_type["accession_note"]["source_file_path"] == "/imports/accessions.csv"
        assert by_source_type["accession_note"]["date"] == "2005-03-12"

        assert by_source_type["document_chunk"]["document_type"] == seeded["document"].document_type
        assert by_source_type["document_chunk"]["reliability_tier"] == "informal"
        assert by_source_type["document_chunk"]["source_file_path"] == "/imports/policy.txt"
        assert by_source_type["event_note"]["date"] == "2006-05-01"
        assert by_source_type["item_note"]["date"] == "2006-04-01"
        assert {"A", "B"} <= {row["lane"] for row in rows}
    finally:
        session.close()
        reset_singletons()



def test_search_returns_r1_metadata_fields(tmp_path: Path):
    _, session = _session_for(tmp_path, "retrieval-r1-search.db")
    try:
        _seed_records(session)
        build_index(session)

        results = search_index(session, "policy cedar", limit=5)
        assert results
        top = results[0]
        assert top["source_type"] == "document_chunk"
        assert top["document_type"] == "policy"
        assert top["reliability_tier"] == "informal"
        assert top["source_file_path"] == "/imports/policy.txt"
        assert top["lane"] == "A"
        assert "date" in top
    finally:
        session.close()
        reset_singletons()



def test_search_filters_by_reliability_tier(tmp_path: Path):
    _, session = _session_for(tmp_path, "retrieval-r1-tier.db")
    try:
        _seed_records(session)
        build_index(session)

        official = search_index(session, "cedar", reliability_tier="official", limit=10)
        professional = search_index(session, "cedar", reliability_tier="professional", limit=10)
        informal = search_index(session, "cedar", reliability_tier="informal", limit=10)

        assert {row["source_type"] for row in official} == {"accession_note", "item_note"}
        assert {row["source_type"] for row in professional} == {"event_note"}
        assert {row["source_type"] for row in informal} == {"document_chunk", "source_note"}
    finally:
        session.close()
        reset_singletons()



def test_search_filters_by_source_type_and_lane(tmp_path: Path):
    _, session = _session_for(tmp_path, "retrieval-r1-filters.db")
    try:
        _seed_records(session)
        build_index(session)

        event_results = search_index(session, "cedar", source_type="event_note", limit=10)
        assert len(event_results) == 1
        assert event_results[0]["source_type"] == "event_note"
        assert event_results[0]["document_type"] == "event_record"

        policy_results = search_index(session, "cedar", document_type="policy", lane="A", limit=10)
        assert len(policy_results) == 1
        assert policy_results[0]["source_type"] == "document_chunk"
        assert all(row["lane"] == "A" for row in search_index(session, "cedar", lane="A", limit=10))
    finally:
        session.close()
        reset_singletons()
