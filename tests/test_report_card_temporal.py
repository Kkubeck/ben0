"""Tests for temporal (snapshot / window / comparison) report card features.

Covers CollectionSnapshot query methods, generate_report_card temporal_context
output, compare_report_cards delta logic, and the three CLI parse helpers.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ben0.db.models import Accession, Base, Event, Item, Taxon
from ben0.reports.snapshot import CollectionSnapshot


# ---------------------------------------------------------------------------
# Fixture: in-memory DB with a small, precisely dated collection
# ---------------------------------------------------------------------------

def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _seed(session):
    """Populate a tiny collection with known temporal data.

    Timeline:
      taxon_a  Quercus robur   (family Fagaceae)
      taxon_b  Acer rubrum     (family Sapindaceae)

    Accessions:
      acc_old   2000-06-01  taxon_a   (old)
      acc_new   2022-03-15  taxon_b   (recently acquired)
      acc_noyear  no date   taxon_a   (conservative inclusion)

    Items:
      item_living   acc_old   is_current=True   life_status=living
      item_dead     acc_old   is_current=False  life_status=dead

    Events:
      ev_sown       item_living   sown        2022-01-10
      ev_germinated item_living   germinated  2022-04-20
      ev_dead       item_dead     dead        2021-06-30

    So at as_of=2021-12-31:
      - item_living: last event before 2021-12-31 is ev_dead... wait, ev_dead
        is on item_dead, not item_living. item_living has no event before
        2021-12-31 (sown is 2022). Falls back to is_current=True -> alive.
      - item_dead: last event before 2021-12-31 is ev_dead (dead) -> not alive.

    At as_of=2022-12-31:
      - item_living: last event is ev_germinated (germinated) -> alive.
      - item_dead: last event is ev_dead (dead) -> not alive.
    """
    taxon_a_id = str(uuid4())
    taxon_b_id = str(uuid4())
    session.add_all([
        Taxon(id=taxon_a_id, scientific_name="Quercus robur", family="Fagaceae", genus="Quercus"),
        Taxon(id=taxon_b_id, scientific_name="Acer rubrum", family="Sapindaceae", genus="Acer"),
    ])

    acc_old_id = str(uuid4())
    acc_new_id = str(uuid4())
    acc_noyear_id = str(uuid4())
    session.add_all([
        Accession(
            id=acc_old_id, accession_number="2000-0001",
            taxon_id=taxon_a_id, accession_date="2000-06-01", accession_year=2000,
        ),
        Accession(
            id=acc_new_id, accession_number="2022-0001",
            taxon_id=taxon_b_id, accession_date="2022-03-15", accession_year=2022,
        ),
        Accession(
            id=acc_noyear_id, accession_number="NOYEAR-001",
            taxon_id=taxon_a_id, accession_date=None, accession_year=None,
        ),
    ])

    item_living_id = str(uuid4())
    item_dead_id = str(uuid4())
    session.add_all([
        Item(
            id=item_living_id, accession_id=acc_old_id,
            item_label="2000-0001.01", life_status="living", is_current=True,
        ),
        Item(
            id=item_dead_id, accession_id=acc_old_id,
            item_label="2000-0001.02", life_status="dead", is_current=False,
        ),
    ])

    session.add_all([
        Event(
            id=str(uuid4()), item_id=item_living_id, accession_id=acc_old_id,
            event_type="sown", event_date="2022-01-10",
        ),
        Event(
            id=str(uuid4()), item_id=item_living_id, accession_id=acc_old_id,
            event_type="germinated", event_date="2022-04-20",
        ),
        Event(
            id=str(uuid4()), item_id=item_dead_id, accession_id=acc_old_id,
            event_type="dead", event_date="2021-06-30",
        ),
    ])

    session.commit()
    return {
        "taxon_a_id": taxon_a_id,
        "taxon_b_id": taxon_b_id,
        "acc_old_id": acc_old_id,
        "acc_new_id": acc_new_id,
        "acc_noyear_id": acc_noyear_id,
        "item_living_id": item_living_id,
        "item_dead_id": item_dead_id,
    }


@pytest.fixture
def db():
    """Yield (session, ids) and close on teardown."""
    session = _make_session()
    ids = _seed(session)
    yield session, ids
    session.close()


# ---------------------------------------------------------------------------
# 1. alive_items at a past date
# ---------------------------------------------------------------------------

class TestAliveItemsPastDate:
    def test_only_current_items_at_pre_event_date(self, db):
        """Before any events fire, is_current is the fallback for item_living."""
        session, ids = db
        snap = CollectionSnapshot(session=session, as_of=date(2021, 12, 31))
        alive = snap.alive_items()
        alive_ids = {it.id for it in alive}
        # item_living has no event before 2021-12-31 -> falls back to is_current=True
        assert ids["item_living_id"] in alive_ids
        # item_dead has a "dead" event on 2021-06-30 -> NOT alive
        assert ids["item_dead_id"] not in alive_ids

    def test_alive_after_germination_event(self, db):
        """After germination event, item_living is still alive (non-terminal)."""
        session, ids = db
        snap = CollectionSnapshot(session=session, as_of=date(2022, 12, 31))
        alive = snap.alive_items()
        alive_ids = {it.id for it in alive}
        assert ids["item_living_id"] in alive_ids
        assert ids["item_dead_id"] not in alive_ids


# ---------------------------------------------------------------------------
# 2. alive_items with no date returns is_current items
# ---------------------------------------------------------------------------

class TestAliveItemsNoDate:
    def test_returns_is_current_items_only(self, db):
        session, ids = db
        snap = CollectionSnapshot(session=session)
        alive = snap.alive_items()
        alive_ids = {it.id for it in alive}
        assert ids["item_living_id"] in alive_ids
        assert ids["item_dead_id"] not in alive_ids

    def test_count_matches_is_current(self, db):
        session, ids = db
        snap = CollectionSnapshot(session=session)
        alive = snap.alive_items()
        # Only one item has is_current=True in fixture
        assert len(alive) == 1


# ---------------------------------------------------------------------------
# 3. active_accessions filters by accession_year
# ---------------------------------------------------------------------------

class TestActiveAccessions:
    def test_excludes_accession_after_as_of(self, db):
        """acc_new (2022) should be excluded at as_of=2021-12-31."""
        session, ids = db
        snap = CollectionSnapshot(session=session, as_of=date(2021, 12, 31))
        active_ids = {acc.id for acc in snap.active_accessions()}
        assert ids["acc_new_id"] not in active_ids
        assert ids["acc_old_id"] in active_ids

    def test_includes_accession_in_year(self, db):
        """acc_new (2022) is included at as_of=2022-12-31."""
        session, ids = db
        snap = CollectionSnapshot(session=session, as_of=date(2022, 12, 31))
        active_ids = {acc.id for acc in snap.active_accessions()}
        assert ids["acc_new_id"] in active_ids
        assert ids["acc_old_id"] in active_ids

    def test_no_date_accession_always_included(self, db):
        """Accession with no date info is conservatively included."""
        session, ids = db
        snap = CollectionSnapshot(session=session, as_of=date(1990, 1, 1))
        active_ids = {acc.id for acc in snap.active_accessions()}
        assert ids["acc_noyear_id"] in active_ids

    def test_no_as_of_returns_all(self, db):
        session, ids = db
        snap = CollectionSnapshot(session=session)
        active = snap.active_accessions()
        assert len(active) == 3


# ---------------------------------------------------------------------------
# 4. acquired_accessions in a window
# ---------------------------------------------------------------------------

class TestAcquiredAccessions:
    def test_window_captures_new_accession(self, db):
        """acc_new (2022-03-15) falls in [2022-01-01, 2023-01-01)."""
        session, ids = db
        snap = CollectionSnapshot(
            session=session,
            period_start=date(2022, 1, 1),
            period_end=date(2023, 1, 1),
        )
        acquired_ids = {acc.id for acc in snap.acquired_accessions()}
        assert ids["acc_new_id"] in acquired_ids
        assert ids["acc_old_id"] not in acquired_ids

    def test_window_excludes_outside_range(self, db):
        """acc_old (2000) not in [2010-01-01, 2015-01-01)."""
        session, ids = db
        snap = CollectionSnapshot(
            session=session,
            period_start=date(2010, 1, 1),
            period_end=date(2015, 1, 1),
        )
        acquired = snap.acquired_accessions()
        acquired_ids = {acc.id for acc in acquired}
        assert ids["acc_old_id"] not in acquired_ids
        assert ids["acc_new_id"] not in acquired_ids

    def test_no_window_returns_empty(self, db):
        """Without a period, acquired_accessions returns empty list."""
        session, ids = db
        snap = CollectionSnapshot(session=session)
        assert snap.acquired_accessions() == []


# ---------------------------------------------------------------------------
# 5. lost_items in a window
# ---------------------------------------------------------------------------

class TestLostItems:
    def test_dead_event_in_window(self, db):
        """ev_dead (2021-06-30) is in [2021-01-01, 2022-01-01)."""
        session, ids = db
        snap = CollectionSnapshot(
            session=session,
            period_start=date(2021, 1, 1),
            period_end=date(2022, 1, 1),
        )
        lost = snap.lost_items()
        assert len(lost) == 1
        assert lost[0].event_type == "dead"

    def test_dead_event_outside_window(self, db):
        """ev_dead (2021-06-30) is NOT in [2022-01-01, 2023-01-01)."""
        session, ids = db
        snap = CollectionSnapshot(
            session=session,
            period_start=date(2022, 1, 1),
            period_end=date(2023, 1, 1),
        )
        lost = snap.lost_items()
        assert lost == []

    def test_no_window_returns_empty(self, db):
        session, ids = db
        snap = CollectionSnapshot(session=session)
        assert snap.lost_items() == []


# ---------------------------------------------------------------------------
# 6. propagation_events filtered by window
# ---------------------------------------------------------------------------

class TestPropagationEvents:
    def test_events_in_window(self, db):
        """ev_sown (2022-01-10) and ev_germinated (2022-04-20) are in 2022."""
        session, ids = db
        snap = CollectionSnapshot(
            session=session,
            period_start=date(2022, 1, 1),
            period_end=date(2023, 1, 1),
        )
        events = snap.propagation_events()
        event_types = {ev.event_type for ev in events}
        assert "sown" in event_types
        assert "germinated" in event_types

    def test_events_outside_window_excluded(self, db):
        """No propagation events exist in 2019."""
        session, ids = db
        snap = CollectionSnapshot(
            session=session,
            period_start=date(2019, 1, 1),
            period_end=date(2020, 1, 1),
        )
        events = snap.propagation_events()
        assert events == []

    def test_no_window_returns_all_propagation_events(self, db):
        """Without a period, all propagation events are returned."""
        session, ids = db
        snap = CollectionSnapshot(session=session)
        events = snap.propagation_events()
        # Fixture has sown + germinated = 2 propagation events
        assert len(events) == 2

    def test_outcome_filter(self, db):
        """Filter by specific outcome (sown only)."""
        session, ids = db
        snap = CollectionSnapshot(
            session=session,
            period_start=date(2022, 1, 1),
            period_end=date(2023, 1, 1),
        )
        sown_only = snap.propagation_events(outcome="sown")
        assert all(ev.event_type == "sown" for ev in sown_only)
        assert len(sown_only) == 1


# ---------------------------------------------------------------------------
# 7. generate_report_card with snapshot_date produces temporal_context
# ---------------------------------------------------------------------------

class TestGenerateReportCardSnapshot:
    def test_snapshot_temporal_context(self, db):
        from ben0.reports.report_card import generate_report_card

        session, ids = db
        card = generate_report_card(
            session,
            garden_name="Test Garden",
            snapshot_date=date(2022, 12, 31),
        )
        assert card.temporal_context is not None
        assert card.temporal_context["mode"] == "snapshot"
        assert card.temporal_context["as_of"] == "2022-12-31"

    def test_no_date_gives_no_temporal_context(self, db):
        from ben0.reports.report_card import generate_report_card

        session, ids = db
        card = generate_report_card(session, garden_name="Test Garden")
        assert card.temporal_context is None

    def test_card_has_expected_section_names(self, db):
        from ben0.reports.report_card import generate_report_card

        session, ids = db
        card = generate_report_card(
            session,
            garden_name="Test Garden",
            snapshot_date=date(2022, 12, 31),
        )
        section_names = {s.name for s in card.sections}
        assert "Taxonomic Diversity" in section_names
        assert "Collection Dynamics" in section_names
        assert "Nursery Pipeline" in section_names


# ---------------------------------------------------------------------------
# 8. generate_report_card with period produces temporal_context
# ---------------------------------------------------------------------------

class TestGenerateReportCardPeriod:
    def test_period_temporal_context(self, db):
        from ben0.reports.report_card import generate_report_card

        session, ids = db
        card = generate_report_card(
            session,
            garden_name="Test Garden",
            period_start=date(2022, 1, 1),
            period_end=date(2023, 1, 1),
        )
        assert card.temporal_context is not None
        assert card.temporal_context["mode"] == "window"
        assert card.temporal_context["period_start"] == "2022-01-01"
        assert card.temporal_context["period_end"] == "2023-01-01"

    def test_to_dict_includes_temporal_key(self, db):
        from ben0.reports.report_card import generate_report_card

        session, ids = db
        card = generate_report_card(
            session,
            garden_name="Test Garden",
            period_start=date(2022, 1, 1),
            period_end=date(2023, 1, 1),
        )
        d = card.to_dict()
        assert "temporal" in d
        assert d["temporal"]["mode"] == "window"


# ---------------------------------------------------------------------------
# 9. compare_report_cards produces SectionDelta entries with trends
# ---------------------------------------------------------------------------

class TestCompareReportCards:
    def test_returns_deltas_for_all_sections(self, db):
        from ben0.reports.report_card import compare_report_cards, generate_report_card

        session, ids = db
        card_a = generate_report_card(session, garden_name="Test Garden")
        card_b = generate_report_card(
            session,
            garden_name="Test Garden",
            snapshot_date=date(2022, 12, 31),
        )
        deltas = compare_report_cards(card_a, card_b)
        assert len(deltas) > 0
        section_names = {d.name for d in deltas}
        assert "Taxonomic Diversity" in section_names

    def test_delta_trend_values_are_valid(self, db):
        from ben0.reports.report_card import compare_report_cards, generate_report_card

        session, ids = db
        card_a = generate_report_card(session, garden_name="Test Garden")
        card_b = generate_report_card(session, garden_name="Test Garden")
        deltas = compare_report_cards(card_a, card_b)
        valid_trends = {"improving", "stable", "declining"}
        for delta in deltas:
            assert delta.trend in valid_trends

    def test_same_card_produces_stable_trend(self, db):
        """Comparing a card to itself should yield all stable trends."""
        from ben0.reports.report_card import compare_report_cards, generate_report_card

        session, ids = db
        card = generate_report_card(session, garden_name="Test Garden")
        deltas = compare_report_cards(card, card)
        for delta in deltas:
            assert delta.trend == "stable"

    def test_metric_deltas_contain_numeric_keys(self, db):
        from ben0.reports.report_card import compare_report_cards, generate_report_card

        session, ids = db
        card_a = generate_report_card(session, garden_name="Test Garden")
        card_b = generate_report_card(session, garden_name="Test Garden")
        deltas = compare_report_cards(card_a, card_b)
        # At least one section should have numeric metric deltas
        has_numeric = False
        for delta in deltas:
            for key, vals in delta.metric_deltas.items():
                if isinstance(vals, dict) and "delta" in vals:
                    has_numeric = True
                    break
        assert has_numeric


# ---------------------------------------------------------------------------
# 10. CLI _parse_period parses both formats
# ---------------------------------------------------------------------------

class TestParsePeriod:
    def test_year_only_format(self):
        from ben0.cli import _parse_period

        start, end = _parse_period("2015:2020")
        assert start == date(2015, 1, 1)
        assert end == date(2020, 12, 31)

    def test_full_date_format(self):
        from ben0.cli import _parse_period

        start, end = _parse_period("2015-03-01:2020-06-30")
        assert start == date(2015, 3, 1)
        assert end == date(2020, 6, 30)

    def test_mixed_year_and_date_format(self):
        """Year-only start with full date end is not directly supported; test pure forms."""
        from ben0.cli import _parse_period

        # Both year-only: verified above.
        # Both full-date: verified above.
        # Just ensure the separator is required.
        import click
        with pytest.raises((click.UsageError, SystemExit, Exception)):
            _parse_period("20152020")

    def test_invalid_year_raises(self):
        import click
        from ben0.cli import _parse_period

        with pytest.raises((click.UsageError, ValueError)):
            _parse_period("ABCD:2020")


# ---------------------------------------------------------------------------
# 11. CLI _parse_snapshot_date parses and rejects bad dates
# ---------------------------------------------------------------------------

class TestParseSnapshotDate:
    def test_valid_date(self):
        from ben0.cli import _parse_snapshot_date

        d = _parse_snapshot_date("2022-06-15")
        assert d == date(2022, 6, 15)

    def test_invalid_date_raises_usage_error(self):
        import click
        from ben0.cli import _parse_snapshot_date

        with pytest.raises(click.UsageError):
            _parse_snapshot_date("not-a-date")

    def test_partial_date_raises(self):
        import click
        from ben0.cli import _parse_snapshot_date

        with pytest.raises(click.UsageError):
            _parse_snapshot_date("2022-06")

    def test_nonsense_raises(self):
        import click
        from ben0.cli import _parse_snapshot_date

        with pytest.raises(click.UsageError):
            _parse_snapshot_date("2022/06/15")


# ---------------------------------------------------------------------------
# 12. CLI _parse_compare_arg handles both formats
# ---------------------------------------------------------------------------

class TestParseCompareArg:
    def test_date_format_returns_snapshot(self):
        from ben0.cli import _parse_compare_arg

        snap, ps, pe = _parse_compare_arg("2020-12-31")
        assert snap == date(2020, 12, 31)
        assert ps is None
        assert pe is None

    def test_period_format_returns_window(self):
        from ben0.cli import _parse_compare_arg

        snap, ps, pe = _parse_compare_arg("2015:2020")
        assert snap is None
        assert ps == date(2015, 1, 1)
        assert pe == date(2020, 12, 31)

    def test_full_date_period_returns_window(self):
        from ben0.cli import _parse_compare_arg

        snap, ps, pe = _parse_compare_arg("2015-01-01:2020-12-31")
        assert snap is None
        assert ps == date(2015, 1, 1)
        assert pe == date(2020, 12, 31)
