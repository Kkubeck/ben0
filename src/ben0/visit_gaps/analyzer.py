"""
Core analysis logic for visit-gaps: classify events and locations, compute
per-item visit profiles, and roll up a full collection report.

Reuses ben0.db.models and ben0.db.session, no new persistence layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from ben0.db.models import Event, Item

from ben0.visit_gaps.constants import (
    AREA_RULES,
    TERMINAL_STATUSES,
    VISIT_EVENTS,
)

# A day-bucket boundary, in days, used both for the summary histogram and
# for the overdue_1yr/2yr/5yr counts below.
_SIX_MONTHS = 182
_ONE_YEAR = 365
_TWO_YEARS = 730
_FIVE_YEARS = 1825


# -----------------------------------------------------------------------------
# classify_event(event_type) consumes a BEN-0 Event.event_type string (or
# None) and produces one of three category labels: "visit", "non_visit", or
# "unknown".
#
# Interpretation: "visit" means a curator was physically present at the
# plant; "non_visit" means an administrative/process record; "unknown"
# means the event_type isn't in either constants table (a value BEN-0
# defines, like "labeled", that the institution hasn't classified, or a
# value not in BEN-0's documented vocabulary at all). Unknown events do
# NOT count as visits for gap-tracking purposes: a curator could not
# confirm "eyes on plant" from an unclassified status, so treating it as a
# visit would understate real gaps.
#
# Example: classify_event("observed") == "visit"
#          classify_event("sown") == "non_visit"
#          classify_event("frobnicated") == "unknown"
# -----------------------------------------------------------------------------
def classify_event(event_type: str | None) -> str:
    """Return 'visit', 'non_visit', or 'unknown' for a BEN-0 event_type."""
    if event_type is None:
        return "unknown"
    normalized = event_type.strip().lower()
    if normalized in VISIT_EVENTS:
        return "visit"
    from ben0.visit_gaps.constants import NON_VISIT_EVENTS

    if normalized in NON_VISIT_EVENTS:
        return "non_visit"
    return "unknown"


# -----------------------------------------------------------------------------
# is_terminal(event_type) consumes a BEN-0 Event.event_type string (or
# None) and produces a bool.
#
# Interpretation: True means this event_type, if it is the most recent
# visit event for an item, indicates the item is no longer alive in the
# collection (dead, not found, removed, or transferred out).
#
# Example: is_terminal("dead") == True
#          is_terminal("observed") == False
# -----------------------------------------------------------------------------
def is_terminal(event_type: str | None) -> bool:
    """Return True if this event type ends the item's collection life."""
    if event_type is None:
        return False
    return event_type.strip().lower() in TERMINAL_STATUSES


# -----------------------------------------------------------------------------
# classify_area(location_code) consumes a Location.location_code string
# (or None) and produces a (area_name, action) tuple, where action is
# "include" or "exclude".
#
# Interpretation: walks AREA_RULES in order, matching the location_code's
# prefix case-insensitively against each rule's prefix_list. The first
# matching rule wins. If location_code is None or empty, or no rule
# matches, the code is bucketed into "Other" with the raw code preserved
# in the area name as "Other ({location_code})" so unmapped codes are
# visible in reports rather than silently disappearing into a single
# undifferentiated bucket. A None/empty code becomes "Other (unknown)".
# The "Other" bucket's action is always "include" so unmapped beds still
# surface in the report.
#
# Example: classify_area("1A2") == ("Alpine", "include")
#          classify_area("8B") == ("Nursery", "exclude")
#          classify_area("ZZZ99") == ("Other (ZZZ99)", "include")
# -----------------------------------------------------------------------------
def classify_area(location_code: str | None) -> tuple[str, str]:
    """Return (area_name, 'include'|'exclude') for a location code.

    Unmapped codes fall into an "Other (<code>)" bucket with action
    "include", preserving the raw code so gaps in the area map are visible.
    """
    if not location_code:
        return ("Other (unknown)", "include")
    code_upper = location_code.strip().upper()
    for prefixes, area_name, action in AREA_RULES:
        for prefix in prefixes:
            if code_upper.startswith(prefix.upper()):
                return (area_name, action)
    return (f"Other ({location_code})", "include")


# -----------------------------------------------------------------------------
# _parse_event_date(event_date) consumes the raw Event.event_date string
# (or None) and produces a date or None.
#
# Interpretation: Event.event_date is a free-form String(20), not a real
# date column, so it may be a full ISO date ("2016-10-19"), a year-month
# ("2016-10"), a bare year ("2016"), malformed text, or missing entirely.
# This helper is defensive: any value it can't parse becomes None rather
# than raising, so one bad row doesn't crash the whole analysis.
#
# Example: _parse_event_date("2016-10-19") == date(2016, 10, 19)
#          _parse_event_date("2016-10") == date(2016, 10, 1)
#          _parse_event_date("garbage") == None
#          _parse_event_date(None) == None
# -----------------------------------------------------------------------------
def _parse_event_date(event_date: str | None) -> date | None:
    if not event_date:
        return None
    text = event_date.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


# -----------------------------------------------------------------------------
# ItemVisitProfile is a dataclass representing one item's full visit
# timeline summary.
#
# Interpretation: item_label/accession_number/taxon_name/area/location_code
# are display fields. is_living is derived from the LAST visit event's
# type (not Item.life_status, per the design's explicit constraint).
# last_visit_date/last_visit_type describe the most recent visit event,
# or (None, "") if the item has zero visit events. days_since_last_visit
# is the gap from that date to the report's as_of date, or -1 if there is
# no visit event to measure from (sentinel, since the field is typed int
# not int | None per the design spec's dataclass; -1 reads unambiguously
# as "not applicable" given every real value is >= 0).
# previous_interval_days is the gap between the two most recent visits,
# or None if fewer than 2 visits exist. visit_count counts only events
# classified as "visit". is_ghost and is_overdue are booleans per the
# design's ghost/overdue definitions.
#
# Example: an item planted once on 2020-01-01 and never visited again,
# evaluated as_of 2026-06-26 with threshold_days=365 and still living,
# produces is_ghost=True, is_overdue=False (ghosts are reported
# separately from overdue, per design notes), visit_count=1.
# -----------------------------------------------------------------------------
@dataclass
class ItemVisitProfile:
    item_label: str
    accession_number: str
    taxon_name: str
    area: str
    location_code: str
    is_living: bool
    last_visit_date: date | None
    last_visit_type: str
    days_since_last_visit: int
    previous_interval_days: int | None
    visit_count: int
    is_ghost: bool
    is_overdue: bool


# -----------------------------------------------------------------------------
# AreaSummary is a dataclass holding area-level rollup counts for the
# summary table view.
#
# Interpretation: total_items is every item in the area regardless of
# status. living/terminated partition total_items by is_living.
# visited_6mo/visited_1yr count living items whose days_since_last_visit
# falls in [0, 182] / [0, 365] respectively (these are cumulative-from-now
# buckets, not the exclusive histogram buckets used in format_table's
# <6mo/6-12m/1-2yr/2-5yr/>5yr columns, which are computed directly off
# the item profiles by the formatter). overdue_1yr/2yr/5yr count living
# items whose days_since_last_visit exceeds 365/730/1825 respectively.
# ghosts counts is_ghost items in the area.
#
# Example: an area with 10 living items, 6 of which haven't been visited
# in over a year, produces overdue_1yr=6.
# -----------------------------------------------------------------------------
@dataclass
class AreaSummary:
    area: str
    total_items: int
    living: int
    terminated: int
    visited_6mo: int
    visited_1yr: int
    overdue_1yr: int
    overdue_2yr: int
    overdue_5yr: int
    ghosts: int


# -----------------------------------------------------------------------------
# CollectionVisitReport is a dataclass holding the full output of
# analyze_collection: area rollups plus item-level lists for drill-down.
#
# Interpretation: area_summaries maps area name to its AreaSummary.
# overdue_items and ghost_items are ItemVisitProfile lists for direct
# display (overdue_items sorted by days_since_last_visit descending).
# all_items holds every ItemVisitProfile considered, living or not, so
# CSV/JSON export can produce one row per item without re-running the
# analysis; this field is not in the design spec's literal dataclass
# listing but is needed because format_csv must emit "one row per item"
# and the spec's report alone (just overdue + ghosts) cannot reconstruct
# that without re-querying the DB. total_living/total_overdue/total_ghosts
# are collection-wide counts.
#
# Example: a 2-area collection of 100 items where 12 are overdue and 3 are
# ghosts produces total_living + total_terminated == 100 (terminated
# count derivable by summing AreaSummary.terminated), total_overdue=12,
# total_ghosts=3.
# -----------------------------------------------------------------------------
@dataclass
class CollectionVisitReport:
    generated_at: datetime
    threshold_days: int
    area_summaries: dict[str, "AreaSummary"]
    overdue_items: list[ItemVisitProfile]
    ghost_items: list[ItemVisitProfile]
    total_living: int
    total_overdue: int
    total_ghosts: int
    all_items: list[ItemVisitProfile] = field(default_factory=list)


# -----------------------------------------------------------------------------
# YearActivity is a dataclass holding one area's, one year's worth of
# event-category counts, for the --year-activity report.
#
# Interpretation: year is the calendar year of event_date. observed_count
# counts events classified "visit" with event_type "observed" (or any
# IrisBG label that maps to "observed", e.g. "Present"/"Inspected").
# planted_count counts "planted" events. dead_count counts "dead" events.
# removed_count counts "removed" or "transferred" events (both end an
# item's life via departure from the collection, as distinct from death).
# other_visit_count counts visit events that are none of the above
# (not_found, relocated, divided, assessed). non_visit_count counts
# administrative events. total_count is the sum of all of the above.
#
# Example: a year with 40 observed events, 5 planted, 2 dead, 1 removed,
# 0 other visits, 10 non-visit events produces total_count=58.
# -----------------------------------------------------------------------------
@dataclass
class YearActivity:
    year: int
    observed_count: int = 0
    planted_count: int = 0
    dead_count: int = 0
    removed_count: int = 0
    other_visit_count: int = 0
    non_visit_count: int = 0
    total_count: int = 0


# -----------------------------------------------------------------------------
# analyze_item(item, threshold_days, as_of) consumes an Item ORM object
# (whose .events relationship supplies the visit history), an int
# threshold in days, and an optional as_of date, and produces an
# ItemVisitProfile.
#
# Interpretation: events are sorted by parsed date (events with
# unparseable/missing dates sort last and are still classified, but
# cannot become "last visit" unless they are the only event). is_living
# comes from whether the LAST visit event (by date) is terminal, per the
# design's explicit constraint to use event history, not
# Item.life_status. If there are zero visit events at all, is_living is
# False (conservative default: we have no evidence the item is alive)
# and days_since_last_visit is -1 (sentinel, no visit to measure from).
# is_ghost requires exactly one visit event total, that event's type is
# "planted" (which covers both "Planted" and "Replanted - Same Seed
# Source" per the IrisBG mapping table, since both map to BEN-0
# event_type "planted"), and is_living is True. is_overdue requires
# is_living, not is_ghost, and days_since_last_visit > threshold_days
# (False whenever there's no visit to measure, since days_since_last_visit
# is the -1 sentinel in that case, which never exceeds a positive
# threshold; also always False for ghosts, since the design explicitly
# treats ghosts as a separate problem category from overdue items, not a
# subset of them).
#
# Example: an item with visits [planted 2020-01-01, observed 2024-01-01],
# evaluated as_of date(2026, 1, 1) with threshold_days=365, produces
# days_since_last_visit=730, previous_interval_days=1461, is_overdue=True
# (if living), is_ghost=False (2 visits, not 1).
# -----------------------------------------------------------------------------
def analyze_item(
    item: Item,
    threshold_days: int = 365,
    as_of: date | None = None,
) -> ItemVisitProfile:
    """Compute the visit timeline summary for a single item.

    Pulls events from item.events. as_of defaults to today's date if not
    given, so callers can inject a fixed date for deterministic tests.
    """
    if as_of is None:
        as_of = date.today()

    accession = item.accession
    taxon_name = ""
    accession_number = ""
    if accession is not None:
        accession_number = accession.accession_number or ""
        if accession.taxon is not None and accession.taxon.scientific_name:
            taxon_name = accession.taxon.scientific_name
        elif accession.taxon_name_verbatim:
            taxon_name = accession.taxon_name_verbatim

    location_code = ""
    if item.current_location is not None:
        location_code = item.current_location.location_code or ""
    area, _action = classify_area(location_code or None)

    events: list[Event] = list(item.events or [])

    def _sort_key(event: Event) -> tuple[int, date]:
        parsed = _parse_event_date(event.event_date)
        if parsed is None:
            return (1, date.min)
        return (0, parsed)

    events_sorted = sorted(events, key=_sort_key)

    visit_events: list[tuple[date | None, str]] = []
    for event in events_sorted:
        category = classify_event(event.event_type)
        if category == "visit":
            visit_events.append((_parse_event_date(event.event_date), event.event_type or ""))

    visit_count = len(visit_events)

    if visit_count == 0:
        return ItemVisitProfile(
            item_label=item.item_label or "",
            accession_number=accession_number,
            taxon_name=taxon_name,
            area=area,
            location_code=location_code,
            is_living=False,
            last_visit_date=None,
            last_visit_type="",
            days_since_last_visit=-1,
            previous_interval_days=None,
            visit_count=0,
            is_ghost=False,
            is_overdue=False,
        )

    last_visit_date, last_visit_type = visit_events[-1]
    is_living = not is_terminal(last_visit_type)

    if last_visit_date is None:
        days_since_last_visit = -1
    else:
        days_since_last_visit = (as_of - last_visit_date).days

    previous_interval_days: int | None = None
    if visit_count >= 2:
        prev_date, _prev_type = visit_events[-2]
        if prev_date is not None and last_visit_date is not None:
            previous_interval_days = (last_visit_date - prev_date).days

    is_ghost = (
        visit_count == 1
        and last_visit_type.strip().lower() == "planted"
        and is_living
    )

    # Ghosts are reported as a distinct data-hygiene problem (per the
    # design's "Ghost items are reported separately... because they
    # represent a different problem... than items that were actively
    # managed but have gone stale"), so a ghost is never also counted as
    # overdue even if its days_since_last_visit exceeds the threshold.
    is_overdue = is_living and not is_ghost and days_since_last_visit > threshold_days

    return ItemVisitProfile(
        item_label=item.item_label or "",
        accession_number=accession_number,
        taxon_name=taxon_name,
        area=area,
        location_code=location_code,
        is_living=is_living,
        last_visit_date=last_visit_date,
        last_visit_type=last_visit_type,
        days_since_last_visit=days_since_last_visit,
        previous_interval_days=previous_interval_days,
        visit_count=visit_count,
        is_ghost=is_ghost,
        is_overdue=is_overdue,
    )


# -----------------------------------------------------------------------------
# analyze_collection(session, threshold_days, area_filter, as_of) queries
# every Item in the DB, builds an ItemVisitProfile for each, and rolls
# them up into a CollectionVisitReport.
#
# Interpretation: area_filter, when given, restricts the report to items
# whose classify_area(...) area name is an EXACT, case-sensitive match to
# area_filter (a design choice; exact match keeps area_filter unambiguous
# given the "Other (<code>)" bucket naming, rather than risking a
# substring match accidentally pulling in unrelated "Other (...)" rows).
# as_of defaults to today; passing a fixed date makes tests deterministic.
# Excluded areas (action "exclude" in AREA_RULES, e.g. Nursery) are still
# included in the report's area_summaries and all_items: AREA_RULES'
# "exclude" action is reserved for CLI/dashboard default-view filtering
# in a later integration phase (see design notes), not for analyze_collection
# itself, since the design's analyze_collection signature has no "action"
# concept; analyze_collection treats every Location as part of the
# collection by default unless area_filter excludes it explicitly.
#
# Example: a 2-area DB with 5 Alpine and 5 Asian items, called with
# area_filter="Alpine", returns a report whose area_summaries has only
# the "Alpine" key, and total_living/total_overdue/total_ghosts reflect
# only Alpine items.
# -----------------------------------------------------------------------------
def analyze_collection(
    session,
    threshold_days: int = 365,
    area_filter: str | None = None,
    as_of: date | None = None,
) -> CollectionVisitReport:
    """Run the full visit-gap analysis across the collection."""
    if as_of is None:
        as_of = date.today()

    items: list[Item] = session.query(Item).all()

    profiles: list[ItemVisitProfile] = []
    for item in items:
        profile = analyze_item(item, threshold_days=threshold_days, as_of=as_of)
        if area_filter is not None and profile.area != area_filter:
            continue
        profiles.append(profile)

    area_summaries: dict[str, AreaSummary] = {}
    for profile in profiles:
        summary = area_summaries.get(profile.area)
        if summary is None:
            summary = AreaSummary(
                area=profile.area,
                total_items=0,
                living=0,
                terminated=0,
                visited_6mo=0,
                visited_1yr=0,
                overdue_1yr=0,
                overdue_2yr=0,
                overdue_5yr=0,
                ghosts=0,
            )
            area_summaries[profile.area] = summary

        summary.total_items += 1
        if profile.is_living:
            summary.living += 1
            if 0 <= profile.days_since_last_visit <= _SIX_MONTHS:
                summary.visited_6mo += 1
            if 0 <= profile.days_since_last_visit <= _ONE_YEAR:
                summary.visited_1yr += 1
            if profile.days_since_last_visit > _ONE_YEAR:
                summary.overdue_1yr += 1
            if profile.days_since_last_visit > _TWO_YEARS:
                summary.overdue_2yr += 1
            if profile.days_since_last_visit > _FIVE_YEARS:
                summary.overdue_5yr += 1
        else:
            summary.terminated += 1
        if profile.is_ghost:
            summary.ghosts += 1

    ghost_items = [profile for profile in profiles if profile.is_ghost]
    overdue_items = [profile for profile in profiles if profile.is_overdue]
    overdue_items.sort(key=lambda profile: profile.days_since_last_visit, reverse=True)

    total_living = sum(1 for profile in profiles if profile.is_living)
    total_overdue = len(overdue_items)
    total_ghosts = len(ghost_items)

    return CollectionVisitReport(
        generated_at=datetime.now(),
        threshold_days=threshold_days,
        area_summaries=area_summaries,
        overdue_items=overdue_items,
        ghost_items=ghost_items,
        total_living=total_living,
        total_overdue=total_overdue,
        total_ghosts=total_ghosts,
        all_items=profiles,
    )


# -----------------------------------------------------------------------------
# year_activity(session, area_filter) queries every Event joined through
# Item -> Location for area classification, and produces a nested dict
# mapping area name -> year -> YearActivity.
#
# Interpretation: events with an unparseable or missing event_date are
# skipped (there is no year to bucket them into). area_filter behaves
# the same as in analyze_collection: exact match on the area name.
# Events not linked to an item (item_id is None, e.g. accession-level-only
# events) are skipped, since area is derived from the item's current
# location.
#
# Example: 3 "observed" events in 2023 and 1 "dead" event in 2024 for
# Alpine items produce
# result["Alpine"][2023].observed_count == 3 and
# result["Alpine"][2024].dead_count == 1.
# -----------------------------------------------------------------------------
def year_activity(
    session,
    area_filter: str | None = None,
) -> dict[str, dict[int, YearActivity]]:
    """Compute per-area, per-year counts of observations, plantings, deaths, etc."""
    items: list[Item] = session.query(Item).all()

    result: dict[str, dict[int, YearActivity]] = {}

    for item in items:
        location_code = None
        if item.current_location is not None:
            location_code = item.current_location.location_code
        area, _action = classify_area(location_code)

        if area_filter is not None and area != area_filter:
            continue

        for event in item.events or []:
            parsed = _parse_event_date(event.event_date)
            if parsed is None:
                continue
            year = parsed.year
            category = classify_event(event.event_type)
            event_type = (event.event_type or "").strip().lower()

            year_map = result.setdefault(area, {})
            activity = year_map.get(year)
            if activity is None:
                activity = YearActivity(year=year)
                year_map[year] = activity

            if category == "non_visit":
                activity.non_visit_count += 1
            elif category == "visit":
                if event_type == "observed":
                    activity.observed_count += 1
                elif event_type == "planted":
                    activity.planted_count += 1
                elif event_type == "dead":
                    activity.dead_count += 1
                elif event_type in ("removed", "transferred"):
                    activity.removed_count += 1
                else:
                    activity.other_visit_count += 1
            # "unknown" category events are not counted in any bucket,
            # consistent with classify_event's documented behavior.

            activity.total_count += 1

    return result
