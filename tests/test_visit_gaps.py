from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ben0.db.models import Accession, Event, Item, Location, Taxon
from ben0.db.session import get_session, init_db, reset_singletons
from ben0.visit_gaps.analyzer import (
    analyze_collection,
    analyze_item,
    classify_area,
    classify_event,
    is_terminal,
)
from ben0.visit_gaps.formatters import format_csv, format_json


def _session_for(tmp_path: Path, name: str):
    db_url = f"sqlite:///{tmp_path / name}"
    reset_singletons()
    init_db(db_url)
    return db_url, get_session(db_url)


def _make_event(event_type: str, event_date: str | None) -> Event:
    return Event(event_type=event_type, event_date=event_date)


def _make_item(events: list[Event], location_code: str | None = None) -> Item:
    item = Item(item_label="2007-0116.2")
    item.events = events
    accession = Accession(accession_number="2007-0116")
    taxon = Taxon(scientific_name="Acer circinatum")
    accession.taxon = taxon
    item.accession = accession
    if location_code is not None:
        location = Location(location_code=location_code)
        item.current_location = location
    return item


# -----------------------------------------------------------------------------
# classify_event
# -----------------------------------------------------------------------------

def test_classify_event_visit_entries():
    assert classify_event("observed") == "visit"
    assert classify_event("planted") == "visit"
    assert classify_event("not_found") == "visit"
    assert classify_event("dead") == "visit"
    assert classify_event("relocated") == "visit"
    assert classify_event("removed") == "visit"


def test_classify_event_non_visit_entries():
    assert classify_event("sown") == "non_visit"
    assert classify_event("received") == "non_visit"
    assert classify_event("potted") == "non_visit"


def test_classify_event_unknown_entries():
    assert classify_event("frobnicated") == "unknown"
    assert classify_event(None) == "unknown"
    assert classify_event("") == "unknown"


# -----------------------------------------------------------------------------
# classify_area
# -----------------------------------------------------------------------------

def test_classify_area_alpine():
    assert classify_area("1A2") == ("Alpine", "include")


def test_classify_area_asian():
    assert classify_area("3X14") == ("Asian", "include")


def test_classify_area_nursery_excluded():
    assert classify_area("8B") == ("Nursery", "exclude")


def test_classify_area_unmapped_other():
    area, action = classify_area("ZZZ99")
    assert area == "Other (ZZZ99)"
    assert action == "include"


def test_classify_area_none():
    area, action = classify_area(None)
    assert area == "Other (unknown)"
    assert action == "include"


# -----------------------------------------------------------------------------
# is_terminal
# -----------------------------------------------------------------------------

def test_is_terminal_true_cases():
    assert is_terminal("dead") is True
    assert is_terminal("not_found") is True
    assert is_terminal("removed") is True
    assert is_terminal("transferred") is True


def test_is_terminal_false_cases():
    assert is_terminal("observed") is False
    assert is_terminal("planted") is False
    assert is_terminal(None) is False


# -----------------------------------------------------------------------------
# analyze_item
# -----------------------------------------------------------------------------

def test_analyze_item_living_with_two_visits():
    events = [
        _make_event("planted", "2020-01-01"),
        _make_event("observed", "2024-01-01"),
    ]
    item = _make_item(events, location_code="1A2")
    profile = analyze_item(item, threshold_days=365, as_of=date(2026, 1, 1))

    assert profile.is_living is True
    assert profile.visit_count == 2
    assert profile.previous_interval_days == 1461
    assert profile.days_since_last_visit == 731
    assert profile.is_overdue is True
    assert profile.is_ghost is False
    assert profile.area == "Alpine"


def test_analyze_item_not_overdue():
    events = [
        _make_event("planted", "2020-01-01"),
        _make_event("observed", "2025-12-01"),
    ]
    item = _make_item(events)
    profile = analyze_item(item, threshold_days=365, as_of=date(2026, 1, 1))

    assert profile.is_overdue is False
    assert profile.days_since_last_visit == 31


def test_analyze_item_ghost():
    events = [_make_event("planted", "2020-01-01")]
    item = _make_item(events)
    profile = analyze_item(item, threshold_days=365, as_of=date(2026, 1, 1))

    assert profile.visit_count == 1
    assert profile.is_living is True
    assert profile.is_ghost is True
    # Ghosts are reported separately, not folded into overdue.
    assert profile.is_overdue is False


def test_analyze_item_terminated_not_overdue():
    events = [
        _make_event("planted", "2010-01-01"),
        _make_event("observed", "2012-01-01"),
        _make_event("dead", "2013-01-01"),
    ]
    item = _make_item(events)
    profile = analyze_item(item, threshold_days=365, as_of=date(2026, 1, 1))

    assert profile.is_living is False
    # Even though days_since_last_visit is huge, terminated items are never overdue.
    assert profile.is_overdue is False
    assert profile.days_since_last_visit > 4000


def test_analyze_item_zero_events():
    item = _make_item([])
    profile = analyze_item(item, threshold_days=365, as_of=date(2026, 1, 1))

    assert profile.visit_count == 0
    assert profile.is_living is False
    assert profile.is_ghost is False
    assert profile.is_overdue is False
    assert profile.last_visit_date is None
    assert profile.days_since_last_visit == -1


# -----------------------------------------------------------------------------
# analyze_collection
# -----------------------------------------------------------------------------

def test_analyze_collection_end_to_end(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "visit-gaps.db")
    try:
        taxon = Taxon(scientific_name="Acer circinatum")
        session.add(taxon)
        session.commit()

        alpine_loc = Location(location_code="1A1")
        asian_loc = Location(location_code="3A1")
        session.add_all([alpine_loc, asian_loc])
        session.commit()

        acc1 = Accession(accession_number="2020-0001", taxon_id=taxon.id)
        acc2 = Accession(accession_number="2020-0002", taxon_id=taxon.id)
        acc3 = Accession(accession_number="2020-0003", taxon_id=taxon.id)
        session.add_all([acc1, acc2, acc3])
        session.commit()

        # Alpine, overdue living item.
        item1 = Item(
            item_label="2020-0001.1",
            accession_id=acc1.id,
            current_location_id=alpine_loc.id,
        )
        # Alpine, ghost item.
        item2 = Item(
            item_label="2020-0002.1",
            accession_id=acc2.id,
            current_location_id=alpine_loc.id,
        )
        # Asian, recently visited living item.
        item3 = Item(
            item_label="2020-0003.1",
            accession_id=acc3.id,
            current_location_id=asian_loc.id,
        )
        session.add_all([item1, item2, item3])
        session.commit()

        session.add_all(
            [
                Event(item_id=item1.id, event_type="planted", event_date="2015-01-01"),
                Event(item_id=item1.id, event_type="observed", event_date="2016-01-01"),
                Event(item_id=item2.id, event_type="planted", event_date="2024-01-01"),
                Event(item_id=item3.id, event_type="planted", event_date="2025-01-01"),
                Event(item_id=item3.id, event_type="observed", event_date="2026-06-01"),
            ]
        )
        session.commit()

        report = analyze_collection(
            session, threshold_days=365, as_of=date(2026, 6, 26)
        )

        assert "Alpine" in report.area_summaries
        assert "Asian" in report.area_summaries
        assert report.area_summaries["Alpine"].total_items == 2
        assert report.area_summaries["Alpine"].ghosts == 1
        assert report.area_summaries["Asian"].total_items == 1
        assert report.total_ghosts == 1
        assert report.total_overdue == 1
        assert report.overdue_items[0].item_label == "2020-0001.1"
        assert report.ghost_items[0].item_label == "2020-0002.1"

        filtered = analyze_collection(
            session,
            threshold_days=365,
            area_filter="Alpine",
            as_of=date(2026, 6, 26),
        )
        assert list(filtered.area_summaries.keys()) == ["Alpine"]
        assert filtered.total_living + sum(
            summary.terminated for summary in filtered.area_summaries.values()
        ) == 2
    finally:
        session.close()
        reset_singletons()


# -----------------------------------------------------------------------------
# formatters
# -----------------------------------------------------------------------------

def test_format_json_round_trips(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "visit-gaps-json.db")
    try:
        loc = Location(location_code="1A1")
        session.add(loc)
        session.commit()

        acc = Accession(accession_number="2020-0001")
        session.add(acc)
        session.commit()

        item = Item(item_label="2020-0001.1", accession_id=acc.id, current_location_id=loc.id)
        session.add(item)
        session.commit()

        session.add(Event(item_id=item.id, event_type="planted", event_date="2020-01-01"))
        session.commit()

        report = analyze_collection(session, as_of=date(2026, 6, 26))
        rendered = format_json(report)
        parsed = json.loads(rendered)

        assert "area_summaries" in parsed
        assert "overdue_items" in parsed
        assert "ghost_items" in parsed
        assert "all_items" in parsed
        assert parsed["total_ghosts"] == 1
    finally:
        session.close()
        reset_singletons()


def test_format_csv_has_header_and_rows(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "visit-gaps-csv.db")
    try:
        loc = Location(location_code="1A1")
        session.add(loc)
        session.commit()

        acc = Accession(accession_number="2020-0001")
        session.add(acc)
        session.commit()

        item = Item(item_label="2020-0001.1", accession_id=acc.id, current_location_id=loc.id)
        session.add(item)
        session.commit()

        session.add(Event(item_id=item.id, event_type="planted", event_date="2020-01-01"))
        session.commit()

        report = analyze_collection(session, as_of=date(2026, 6, 26))
        rendered = format_csv(report)
        lines = rendered.strip().splitlines()

        assert "item_label" in lines[0]
        assert len(lines) == 2
    finally:
        session.close()
        reset_singletons()
