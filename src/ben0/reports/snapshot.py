"""CollectionSnapshot: date-filtered session wrapper for temporal report cards."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ben0.db.models import Accession, Event, Item
from ben0.visit_gaps.constants import TERMINAL_STATUSES

_PROPAGATION_TYPES = frozenset({"sown", "germinated", "pricked_out", "potted"})

_DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%Y-%m",
    "%Y",
]


def _parse_date(raw: str | None) -> date | None:
    """Try multiple date formats; return None on failure."""
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


@dataclass
class CollectionSnapshot:
    """Session wrapper that applies temporal filters to collection queries.

    Pass as_of for snapshot mode (state at a point in time).
    Pass period_start and period_end for window mode (events within a range).
    Both can be set together: as_of anchors alive counts, period_ anchors flows.
    """

    session: Session
    as_of: date | None = None
    period_start: date | None = None
    period_end: date | None = None

    # Cached results keyed by item_id for alive determination
    _item_last_event_cache: dict[str, Event | None] | None = field(
        default=None, repr=False, compare=False
    )

    def _last_events_by_item(self) -> dict[str, Event | None]:
        """Build a map from item_id to that item's last Event before as_of.

        Only events with a parseable date are considered. Events without a
        date are skipped (cannot be ordered).
        """
        if self._item_last_event_cache is not None:
            return self._item_last_event_cache

        events = self.session.scalars(
            select(Event).where(Event.item_id.is_not(None))
        ).all()

        # Group by item_id, filtering to events on or before as_of
        by_item: dict[str, list[tuple[date, Event]]] = {}
        for ev in events:
            parsed = _parse_date(ev.event_date)
            if parsed is None:
                continue
            if self.as_of is not None and parsed > self.as_of:
                continue
            by_item.setdefault(ev.item_id, []).append((parsed, ev))

        result: dict[str, Event | None] = {}
        for item_id, dated_events in by_item.items():
            dated_events.sort(key=lambda t: t[0])
            result[item_id] = dated_events[-1][1]

        self._item_last_event_cache = result
        return result

    def alive_items(self) -> list[Item]:
        """Items alive at as_of date.

        Alive = last event before as_of is NOT in TERMINAL_STATUSES.
        Falls back to Item.is_current when no events exist before as_of.
        When as_of is None, returns all items with is_current=True.
        """
        items = self.session.scalars(
            select(Item).options(selectinload(Item.events))
        ).all()

        if self.as_of is None:
            return [it for it in items if it.is_current]

        last_events = self._last_events_by_item()
        alive: list[Item] = []
        for item in items:
            ev = last_events.get(item.id)
            if ev is None:
                # No event history at as_of: fall back to is_current
                if item.is_current:
                    alive.append(item)
            elif (ev.event_type or "") not in TERMINAL_STATUSES:
                alive.append(item)
        return alive

    def alive_accession_ids(self) -> set[str]:
        """Accession IDs with at least one alive item."""
        return {it.accession_id for it in self.alive_items() if it.accession_id}

    def active_accessions(self) -> list[Accession]:
        """Accessions that existed at as_of (by accession_year / accession_date).

        When as_of is None, returns all accessions.
        Accessions with no date info are always included (conservative).
        """
        accessions = self.session.scalars(select(Accession)).all()
        if self.as_of is None:
            return list(accessions)

        result: list[Accession] = []
        for acc in accessions:
            yr = acc.accession_year
            parsed_date = _parse_date(acc.accession_date)
            if yr is None and parsed_date is None:
                # No date info: include conservatively
                result.append(acc)
                continue
            if parsed_date is not None and parsed_date <= self.as_of:
                result.append(acc)
            elif yr is not None and yr <= self.as_of.year:
                result.append(acc)
        return result

    def acquired_accessions(self) -> list[Accession]:
        """Accessions acquired within [period_start, period_end).

        Uses accession_date when parseable, falls back to accession_year.
        Returns empty list when no window is defined.
        """
        if self.period_start is None or self.period_end is None:
            return []

        accessions = self.session.scalars(select(Accession)).all()
        result: list[Accession] = []
        for acc in accessions:
            parsed_date = _parse_date(acc.accession_date)
            yr = acc.accession_year
            if parsed_date is not None:
                if self.period_start <= parsed_date < self.period_end:
                    result.append(acc)
            elif yr is not None:
                if self.period_start.year <= yr < self.period_end.year:
                    result.append(acc)
        return result

    def lost_items(self) -> list[Event]:
        """Terminal events (dead/removed/etc.) with event_date within the window.

        Returns empty list when no window is defined.
        """
        if self.period_start is None or self.period_end is None:
            return []

        events = self.session.scalars(
            select(Event).where(Event.event_type.in_(list(TERMINAL_STATUSES)))
        ).all()

        result: list[Event] = []
        for ev in events:
            parsed = _parse_date(ev.event_date)
            if parsed is None:
                continue
            if self.period_start <= parsed < self.period_end:
                result.append(ev)
        return result

    def propagation_events(self, outcome: str | None = None) -> list[Event]:
        """Propagation events within the window.

        outcome: if provided, filter to that specific event_type.
        When no window is defined, returns all propagation events (no date filter).
        """
        types = [outcome] if outcome else list(_PROPAGATION_TYPES)
        events = self.session.scalars(
            select(Event).where(Event.event_type.in_(types))
        ).all()

        if self.period_start is None or self.period_end is None:
            return list(events)

        result: list[Event] = []
        for ev in events:
            parsed = _parse_date(ev.event_date)
            if parsed is None:
                continue
            if self.period_start <= parsed < self.period_end:
                result.append(ev)
        return result
