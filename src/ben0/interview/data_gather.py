"""Database summaries used to ground institution interview questions."""

from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ben0.db.models import Accession, Event, Item, Location, Provenance, Taxon

_PROPAGATION_KEYWORDS = {
    "sow",
    "sown",
    "sowing",
    "germinat",
    "prick",
    "pot",
    "plant",
    "cutting",
    "division",
    "propagat",
    "seed",
    "rooted",
    "transplant",
}


def gather_db_context(session: Session, db_query_key: str) -> str:
    """Run a predefined database summary query and format results as context text."""
    handlers = {
        "distinct_statuses": _distinct_statuses,
        "distinct_provenances": _distinct_provenances,
        "propagation_event_types": _propagation_event_types,
        "date_range_summary": _date_range_summary,
        "distinct_locations": _distinct_locations,
        "taxonomic_summary": _taxonomic_summary,
    }
    handler = handlers.get(db_query_key)
    if handler is None:
        raise ValueError(f"Unknown interview db_query key: {db_query_key}")
    return handler(session)


def _distinct_statuses(session: Session) -> str:
    item_rows = session.execute(
        select(Item.life_status, func.count(Item.id))
        .where(Item.life_status.is_not(None), Item.life_status != "")
        .group_by(Item.life_status)
        .order_by(func.count(Item.id).desc(), Item.life_status.asc())
    ).all()
    event_rows = session.execute(
        select(Event.event_type, func.count(Event.id))
        .where(Event.event_type.is_not(None), Event.event_type != "")
        .group_by(Event.event_type)
        .order_by(func.count(Event.id).desc(), Event.event_type.asc())
    ).all()

    if not item_rows and not event_rows:
        return "No data found for this category yet."

    parts: list[str] = []
    if item_rows:
        parts.append(f"Item life_status values: {_format_count_rows(item_rows)}")
    if event_rows:
        parts.append(f"Event types: {_format_count_rows(event_rows)}")
    return " ".join(parts)


def _distinct_provenances(session: Session) -> str:
    origin_rows = session.execute(
        select(Provenance.origin_code, func.count(Provenance.id))
        .where(Provenance.origin_code.is_not(None), Provenance.origin_code != "")
        .group_by(Provenance.origin_code)
        .order_by(func.count(Provenance.id).desc(), Provenance.origin_code.asc())
    ).all()
    establishment_rows = session.execute(
        select(Provenance.establishment_means, func.count(Provenance.id))
        .where(Provenance.establishment_means.is_not(None), Provenance.establishment_means != "")
        .group_by(Provenance.establishment_means)
        .order_by(func.count(Provenance.id).desc(), Provenance.establishment_means.asc())
    ).all()

    if not origin_rows and not establishment_rows:
        return "No data found for this category yet."

    parts: list[str] = []
    if origin_rows:
        parts.append(f"origin_code values: {_format_count_rows(origin_rows)}")
    if establishment_rows:
        parts.append(f"establishment_means values: {_format_count_rows(establishment_rows)}")
    return " ".join(parts)


def _propagation_event_types(session: Session) -> str:
    rows = session.execute(
        select(Event.event_type, func.count(Event.id))
        .where(Event.event_type.is_not(None), Event.event_type != "")
        .group_by(Event.event_type)
        .order_by(func.count(Event.id).desc(), Event.event_type.asc())
    ).all()
    if not rows:
        return "No data found for this category yet."

    filtered = [row for row in rows if _looks_like_propagation_event(row[0])]
    chosen = filtered or rows
    return f"Propagation-related event counts: {_format_count_rows(chosen)}"


def _date_range_summary(session: Session) -> str:
    accession_rows = session.execute(
        select(Accession.accession_date, Accession.accession_year)
        .where(
            (Accession.accession_date.is_not(None) & (Accession.accession_date != ""))
            | Accession.accession_year.is_not(None)
        )
    ).all()
    sentinel_count = session.scalar(
        select(func.count(Accession.id)).where(Accession.accession_date == "9999-12-31")
    ) or 0

    accession_dates: list[str] = []
    years: list[int] = []
    for accession_date, accession_year in accession_rows:
        if accession_date and accession_date != "9999-12-31":
            accession_dates.append(accession_date)
            if len(accession_date) >= 4 and accession_date[:4].isdigit():
                years.append(int(accession_date[:4]))
                continue
        if accession_year is not None:
            years.append(int(accession_year))

    earliest = min(accession_dates) if accession_dates else None
    latest = max(accession_dates) if accession_dates else None

    decade_counts = Counter((year // 10) * 10 for year in years if year < 9000)
    decade_text = ", ".join(f"{decade}s ({count})" for decade, count in sorted(decade_counts.items()))
    if not decade_text:
        decade_text = "no decade counts available"

    if earliest or latest or sentinel_count or decade_counts:
        start = earliest or "unknown"
        end = latest or "unknown"
        return (
            f"{start} to {end}; sentinel accession dates: {sentinel_count}; "
            f"records by decade: {decade_text}"
        )
    return "No data found for this category yet."


def _distinct_locations(session: Session) -> str:
    rows = session.execute(
        select(Location.location_code, Location.location_name, func.count(Item.id).label("item_count"))
        .outerjoin(Item, Item.current_location_id == Location.id)
        .where(Location.location_code.is_not(None), Location.location_code != "")
        .group_by(Location.id, Location.location_code, Location.location_name)
        .order_by(func.count(Item.id).desc(), Location.location_code.asc())
        .limit(30)
    ).all()

    if not rows:
        return "No data found for this category yet."

    formatted = []
    for code, name, count in rows:
        label = str(code)
        if name:
            label = f"{label} ({name})"
        formatted.append(f"{label}: {count}")
    return "Top locations by current item count: " + ", ".join(formatted)


def _taxonomic_summary(session: Session) -> str:
    family_count = session.scalar(
        select(func.count(func.distinct(Taxon.family))).where(Taxon.family.is_not(None), Taxon.family != "")
    ) or 0
    genus_count = session.scalar(
        select(func.count(func.distinct(Taxon.genus))).where(Taxon.genus.is_not(None), Taxon.genus != "")
    ) or 0
    species_count = session.scalar(
        select(func.count(func.distinct(Taxon.species))).where(Taxon.species.is_not(None), Taxon.species != "")
    ) or 0
    top_families = session.execute(
        select(Taxon.family, func.count(Accession.id))
        .join(Accession, Accession.taxon_id == Taxon.id)
        .where(Taxon.family.is_not(None), Taxon.family != "")
        .group_by(Taxon.family)
        .order_by(func.count(Accession.id).desc(), Taxon.family.asc())
        .limit(15)
    ).all()

    if not any([family_count, genus_count, species_count, top_families]):
        return "No data found for this category yet."

    family_text = _format_count_rows(top_families) if top_families else "none yet"
    return (
        f"{family_count} families, {genus_count} genera, and {species_count} species recorded. "
        f"Top families by accession count: {family_text}"
    )


def _format_count_rows(rows: list[tuple[object, int]] | list[tuple[object, object]]) -> str:
    formatted = []
    for value, count in rows:
        label = str(value) if value not in {None, ""} else "[blank]"
        formatted.append(f"{label} ({count})")
    return ", ".join(formatted)


def _looks_like_propagation_event(value: object) -> bool:
    text = str(value or "").lower()
    return any(keyword in text for keyword in _PROPAGATION_KEYWORDS)
