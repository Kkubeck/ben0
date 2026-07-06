"""Collection Biodiversity Report Card for ben0."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ben0.dashboard.metrics import calculate_metrics, _WILD_CODES, _GARDEN_CODES
from ben0.db.models import (
    Accession,
    ConservationStatus,
    Event,
    Item,
    Location,
    Provenance,
    Taxon,
    ValidationIssue,
)
from ben0.reports.snapshot import CollectionSnapshot

_THREATENED_CODES = {"VU", "EN", "CR"}
_PROPAGATION_TYPES = {"sown", "germinated", "pricked_out", "potted"}


# ---------------------------------------------------------------------------
# Data definitions
# ---------------------------------------------------------------------------

@dataclass
class SectionScore:
    """Traffic-light score for one report card section."""

    name: str
    rating: str  # "strong" | "adequate" | "needs_attention"
    metrics: dict[str, Any]
    findings: list[str]


@dataclass
class ReportCard:
    """Complete report card across all sections."""

    garden_name: str
    generated_at: str
    temporal_context: dict[str, Any] | None = None
    sections: list[SectionScore] = field(default_factory=list)

    def overall_rating(self) -> str:
        ratings = [s.rating for s in self.sections]
        if any(r == "needs_attention" for r in ratings):
            return "needs_attention"
        if all(r == "strong" for r in ratings):
            return "strong"
        return "adequate"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "garden_name": self.garden_name,
            "generated_at": self.generated_at,
            "overall_rating": self.overall_rating(),
            "sections": [
                {
                    "name": s.name,
                    "rating": s.rating,
                    "metrics": s.metrics,
                    "findings": s.findings,
                }
                for s in self.sections
            ],
        }
        if self.temporal_context is not None:
            d["temporal"] = self.temporal_context
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


@dataclass
class SectionDelta:
    """Comparison delta for one section between two report cards."""

    name: str
    trend: str  # "improving" | "stable" | "declining"
    metric_deltas: dict[str, Any]


@dataclass
class ReportCardComparison:
    """Side-by-side comparison of two report cards."""

    card_a: ReportCard
    card_b: ReportCard
    label_a: str
    label_b: str
    deltas: list[SectionDelta]


# ---------------------------------------------------------------------------
# Section 1: Taxonomic Diversity
# ---------------------------------------------------------------------------

def assess_taxonomic_diversity(snapshot: CollectionSnapshot) -> SectionScore:
    """Assess breadth of taxonomic coverage across families, genera, and species."""
    session = snapshot.session

    alive_accession_ids = snapshot.alive_accession_ids()

    taxa = session.scalars(
        select(Taxon).options(selectinload(Taxon.accessions))
    ).all()

    families: Counter[str] = Counter()
    genera: Counter[str] = Counter()
    family_accession_count: Counter[str] = Counter()

    for taxon in taxa:
        fam = taxon.family or "Unknown"
        gen = taxon.genus or "Unknown"

        if snapshot.as_of is not None:
            acc_count = sum(
                1 for acc in taxon.accessions if acc.id in alive_accession_ids
            )
        else:
            acc_count = len(taxon.accessions)

        if acc_count == 0:
            continue

        families[fam] += 1
        genera[gen] += 1
        family_accession_count[fam] += acc_count

    total_taxa = len(families) + len(genera)  # approximate: actual taxon count below
    total_taxa = session.scalar(select(func.count()).select_from(Taxon)) or 0
    total_families = len(families)
    total_genera = len(genera)
    genera_per_family = round(total_genera / total_families, 1) if total_families else 0.0

    single_species_genera = sum(1 for count in genera.values() if count == 1)
    single_species_genera_pct = round(
        (single_species_genera / total_genera) * 100, 1
    ) if total_genera else 0.0

    top_5_families = [
        {"family": fam, "accession_count": count}
        for fam, count in family_accession_count.most_common(5)
    ]

    if total_families >= 50 and total_genera >= 150:
        rating = "strong"
    elif total_families < 20 or total_genera < 50:
        rating = "needs_attention"
    else:
        rating = "adequate"

    findings: list[str] = []
    if top_5_families:
        dominant = top_5_families[0]["family"]
        findings.append(
            f"Most represented family by accession count: {dominant} "
            f"({top_5_families[0]['accession_count']} accessions)."
        )
    findings.append(
        f"Collection spans {total_families} families and {total_genera} genera "
        f"({genera_per_family} genera per family on average)."
    )
    if single_species_genera_pct > 60:
        findings.append(
            f"{single_species_genera_pct}% of genera are represented by a single species, "
            "suggesting breadth-first sampling rather than depth."
        )

    return SectionScore(
        name="Taxonomic Diversity",
        rating=rating,
        metrics={
            "total_taxa": total_taxa,
            "total_families": total_families,
            "total_genera": total_genera,
            "genera_per_family": genera_per_family,
            "single_species_genera_pct": single_species_genera_pct,
            "top_5_families": top_5_families,
        },
        findings=findings,
    )


# ---------------------------------------------------------------------------
# Section 2: Conservation Value
# ---------------------------------------------------------------------------

def assess_conservation_value(snapshot: CollectionSnapshot) -> SectionScore:
    """Assess the collection's contribution to ex situ conservation of at-risk taxa."""
    session = snapshot.session

    if snapshot.as_of is not None:
        alive_acc_ids = snapshot.alive_accession_ids()
        alive_taxon_ids: set[str] = set()
        for acc in session.scalars(select(Accession)).all():
            if acc.id in alive_acc_ids and acc.taxon_id:
                alive_taxon_ids.add(acc.taxon_id)
        total_taxa = len(alive_taxon_ids)
    else:
        total_taxa = session.scalar(select(func.count()).select_from(Taxon)) or 0
        alive_taxon_ids = None  # type: ignore[assignment]

    statuses = session.scalars(select(ConservationStatus)).all()

    assessed_taxon_ids: set[str] = set()
    by_status: Counter[str] = Counter()
    threatened_taxon_ids: set[str] = set()

    for cs in statuses:
        if alive_taxon_ids is not None and cs.taxon_id not in alive_taxon_ids:
            continue
        assessed_taxon_ids.add(cs.taxon_id)
        code = (cs.status_code or "").upper()
        by_status[code] += 1
        if code in _THREATENED_CODES:
            threatened_taxon_ids.add(cs.taxon_id)

    total_assessed = len(assessed_taxon_ids)
    threatened_count = len(threatened_taxon_ids)
    unassessed_count = total_taxa - total_assessed
    threatened_pct = round((threatened_count / total_taxa) * 100, 1) if total_taxa else 0.0
    unassessed_pct = round((unassessed_count / total_taxa) * 100, 1) if total_taxa else 0.0

    if threatened_pct >= 10 and unassessed_pct < 50:
        rating = "strong"
    elif threatened_pct < 3:
        rating = "needs_attention"
    else:
        rating = "adequate"

    findings: list[str] = []
    findings.append(
        f"{threatened_count} taxa ({threatened_pct}%) carry a threatened status (VU, EN, or CR)."
    )
    if by_status:
        status_summary = ", ".join(
            f"{code}: {count}" for code, count in sorted(by_status.items())
        )
        findings.append(f"Status breakdown: {status_summary}.")
    if unassessed_pct > 30:
        findings.append(
            f"{unassessed_pct}% of taxa lack a formal conservation assessment. "
            "Consider cross-referencing with IUCN Red List or COSEWIC."
        )

    return SectionScore(
        name="Conservation Value",
        rating=rating,
        metrics={
            "total_assessed": total_assessed,
            "threatened_count": threatened_count,
            "threatened_pct": threatened_pct,
            "by_status": dict(by_status),
            "unassessed_pct": unassessed_pct,
        },
        findings=findings,
    )


# ---------------------------------------------------------------------------
# Section 3: Provenance & Documentation
# ---------------------------------------------------------------------------

def assess_provenance(snapshot: CollectionSnapshot) -> SectionScore:
    """Assess wild origin documentation, locality completeness, and collector records."""
    session = snapshot.session

    active_accession_ids: set[str] | None = None
    if snapshot.as_of is not None:
        active_accession_ids = {acc.id for acc in snapshot.active_accessions()}

    accessions = session.scalars(
        select(Accession).options(selectinload(Accession.provenances))
    ).all()

    if active_accession_ids is not None:
        accessions = [a for a in accessions if a.id in active_accession_ids]

    total = len(accessions)

    wild_count = 0
    garden_count = 0
    unknown_count = 0
    locality_filled = 0
    collector_filled = 0
    provenance_record_count = 0

    for acc in accessions:
        provs = acc.provenances
        if not provs:
            unknown_count += 1
            continue

        category = "unknown"
        for p in provs:
            origin = (p.origin_code or p.establishment_means or "").strip().upper()
            if origin in _WILD_CODES:
                category = "wild"
                break
            elif origin in _GARDEN_CODES:
                category = "garden"

        if category == "wild":
            wild_count += 1
        elif category == "garden":
            garden_count += 1
        else:
            unknown_count += 1

        for p in provs:
            provenance_record_count += 1
            if p.collection_locality:
                locality_filled += 1
            if p.collector:
                collector_filled += 1

    wild_pct = round((wild_count / total) * 100, 1) if total else 0.0
    garden_pct = round((garden_count / total) * 100, 1) if total else 0.0
    unknown_pct = round((unknown_count / total) * 100, 1) if total else 0.0
    locality_completeness_pct = round(
        (locality_filled / provenance_record_count) * 100, 1
    ) if provenance_record_count else 0.0
    collector_completeness_pct = round(
        (collector_filled / provenance_record_count) * 100, 1
    ) if provenance_record_count else 0.0

    if wild_pct >= 40 and unknown_pct < 15:
        rating = "strong"
    elif unknown_pct > 40:
        rating = "needs_attention"
    else:
        rating = "adequate"

    findings: list[str] = []
    findings.append(
        f"Wild-collected accessions: {wild_pct}% | Garden/cultivated: {garden_pct}% | Unknown: {unknown_pct}%."
    )
    if unknown_pct > 20:
        findings.append(
            f"{unknown_count} accessions ({unknown_pct}%) carry unknown provenance origin codes."
        )
    if locality_completeness_pct < 50 and provenance_record_count > 0:
        findings.append(
            f"Collection locality recorded in only {locality_completeness_pct}% of provenance records."
        )
    if collector_completeness_pct < 40 and provenance_record_count > 0:
        findings.append(
            f"Collector name recorded in only {collector_completeness_pct}% of provenance records."
        )

    return SectionScore(
        name="Provenance and Documentation",
        rating=rating,
        metrics={
            "wild_pct": wild_pct,
            "garden_pct": garden_pct,
            "unknown_pct": unknown_pct,
            "locality_completeness_pct": locality_completeness_pct,
            "collector_completeness_pct": collector_completeness_pct,
        },
        findings=findings,
    )


# ---------------------------------------------------------------------------
# Section 4: Collection Security
# ---------------------------------------------------------------------------

def assess_collection_security(snapshot: CollectionSnapshot) -> SectionScore:
    """Assess resilience of the living collection against accession and item loss."""
    session = snapshot.session

    alive_items_set = {it.id for it in snapshot.alive_items()}

    taxa = session.scalars(
        select(Taxon).options(
            selectinload(Taxon.accessions).selectinload(Accession.items)
        )
    ).all()

    total_living_taxa = 0
    single_accession_taxa_count = 0
    all_accession_counts: list[int] = []
    single_item_accession_count = 0
    total_tracked_accessions = 0
    vulnerable_taxa: list[tuple[str, int]] = []

    for taxon in taxa:
        living_accession_ids: list[str] = []
        for acc in taxon.accessions:
            living_items = [it for it in acc.items if it.id in alive_items_set]
            if living_items:
                living_accession_ids.append(acc.id)
                total_tracked_accessions += 1
                if len(living_items) == 1:
                    single_item_accession_count += 1

        if not living_accession_ids:
            continue

        total_living_taxa += 1
        count = len(living_accession_ids)
        all_accession_counts.append(count)

        if count == 1:
            single_accession_taxa_count += 1
            if taxon.iucn_status and taxon.iucn_status.upper() in _THREATENED_CODES:
                vulnerable_taxa.append((taxon.scientific_name, 1))

    single_accession_pct = round(
        (single_accession_taxa_count / total_living_taxa) * 100, 1
    ) if total_living_taxa else 0.0
    mean_accessions_per_taxon = round(
        sum(all_accession_counts) / len(all_accession_counts), 2
    ) if all_accession_counts else 0.0
    single_item_accessions_pct = round(
        (single_item_accession_count / total_tracked_accessions) * 100, 1
    ) if total_tracked_accessions else 0.0

    if single_accession_pct < 30:
        rating = "strong"
    elif single_accession_pct > 60:
        rating = "needs_attention"
    else:
        rating = "adequate"

    findings: list[str] = []
    findings.append(
        f"{single_accession_taxa_count} of {total_living_taxa} living taxa "
        f"({single_accession_pct}%) are represented by a single accession."
    )
    if single_item_accessions_pct > 40:
        findings.append(
            f"{single_item_accessions_pct}% of living accessions contain only one item, "
            "leaving them vulnerable to single-plant loss."
        )
    if vulnerable_taxa:
        names = ", ".join(n for n, _ in vulnerable_taxa[:5])
        findings.append(
            f"Threatened taxa with single-accession coverage include: {names}."
        )

    return SectionScore(
        name="Collection Security",
        rating=rating,
        metrics={
            "total_living_taxa": total_living_taxa,
            "single_accession_taxa_count": single_accession_taxa_count,
            "single_accession_pct": single_accession_pct,
            "mean_accessions_per_taxon": mean_accessions_per_taxon,
            "single_item_accessions_pct": single_item_accessions_pct,
        },
        findings=findings,
    )


# ---------------------------------------------------------------------------
# Section 5: Collection Dynamics
# ---------------------------------------------------------------------------

def assess_collection_dynamics(snapshot: CollectionSnapshot) -> SectionScore:
    """Assess acquisition trends, living ratio, and collection age profile."""
    from ben0.dashboard.metrics import _extract_year, _normalize_item_status

    session = snapshot.session

    accessions = snapshot.active_accessions()
    alive_items_set = {it.id for it in snapshot.alive_items()}
    items = session.scalars(select(Item)).all()

    decade_counter: Counter[int] = Counter()
    accession_years: list[int] = []

    for acc in accessions:
        year = _extract_year(acc.accession_date, acc.accession_year)
        if year:
            accession_years.append(year)
            decade_counter[year - (year % 10)] += 1

    accessions_by_decade = {
        f"{decade}s": count for decade, count in sorted(decade_counter.items())
    }

    sorted_decades = sorted(decade_counter.keys())
    growth_trend = "stable"
    if len(sorted_decades) >= 3:
        recent = sorted_decades[-3:]
        counts = [decade_counter[d] for d in recent]
        if counts[-1] > counts[0] * 1.2:
            growth_trend = "increasing"
        elif counts[-1] < counts[0] * 0.8:
            growth_trend = "declining"

    if snapshot.as_of is not None:
        alive_count = len(alive_items_set)
        total_items = len(items)
    else:
        item_status_counts = Counter(_normalize_item_status(it.life_status) for it in items)
        total_items = len(items)
        alive_count = item_status_counts.get("alive", 0)

    living_pct = round((alive_count / total_items) * 100, 1) if total_items else 0.0

    import statistics
    ref_year = snapshot.as_of.year if snapshot.as_of else datetime.utcnow().year
    accession_ages = [ref_year - y for y in accession_years if y <= ref_year]
    median_accession_age_years = (
        round(statistics.median(accession_ages), 1) if accession_ages else None
    )

    window_metrics: dict[str, Any] = {}
    if snapshot.period_start is not None and snapshot.period_end is not None:
        acquired = snapshot.acquired_accessions()
        lost = snapshot.lost_items()
        window_metrics["acquired_in_period"] = len(acquired)
        window_metrics["lost_in_period"] = len(lost)
        window_metrics["net_change"] = len(acquired) - len(lost)

    if growth_trend == "increasing" and living_pct >= 60:
        rating = "strong"
    elif growth_trend == "declining" or living_pct < 40:
        rating = "needs_attention"
    else:
        rating = "adequate"

    findings: list[str] = []
    findings.append(
        f"Acquisition trend over the last three recorded decades: {growth_trend}."
    )
    findings.append(
        f"{living_pct}% of tracked items are currently living "
        f"(alive: {alive_count} of {total_items} total items)."
    )
    if median_accession_age_years is not None:
        findings.append(
            f"Median accession age: {median_accession_age_years} years."
        )
    if window_metrics:
        findings.append(
            f"Window [{snapshot.period_start} to {snapshot.period_end}): "
            f"{window_metrics.get('acquired_in_period', 0)} acquired, "
            f"{window_metrics.get('lost_in_period', 0)} lost, "
            f"net {window_metrics.get('net_change', 0):+d}."
        )

    metrics: dict[str, Any] = {
        "accessions_by_decade": accessions_by_decade,
        "growth_trend": growth_trend,
        "living_pct": living_pct,
        "median_accession_age_years": median_accession_age_years,
    }
    metrics.update(window_metrics)

    return SectionScore(
        name="Collection Dynamics",
        rating=rating,
        metrics=metrics,
        findings=findings,
    )


# ---------------------------------------------------------------------------
# Section 6: Climate Readiness (stub)
# ---------------------------------------------------------------------------

def assess_climate_readiness(snapshot: CollectionSnapshot) -> SectionScore:
    """Stub: climate resilience assessment requires external CAT or climate zone data."""
    session = snapshot.session

    climate_count = session.scalar(
        select(func.count()).select_from(ConservationStatus).where(
            ConservationStatus.notes.ilike("%climate%")
        )
    ) or 0

    data_available = climate_count > 0

    findings: list[str] = [
        "No climate assessment data available in the current database.",
        "Consider running a BGCI Climate Adaptation Tool (CAT) analysis to score "
        "collection resilience against projected range shifts.",
    ]
    if data_available:
        findings = [
            f"{climate_count} conservation status records reference climate context.",
            "Full CAT integration is not yet implemented. Manual review recommended.",
        ]

    return SectionScore(
        name="Climate Readiness",
        rating="needs_attention",
        metrics={
            "data_available": data_available,
            "assessed_taxa_count": climate_count,
        },
        findings=findings,
    )


# ---------------------------------------------------------------------------
# Section 7: Nursery Pipeline
# ---------------------------------------------------------------------------

def assess_nursery_pipeline(snapshot: CollectionSnapshot) -> SectionScore:
    """Assess propagation pipeline throughput and success rates from Event records."""
    planting_type = "planted"

    prop_events = snapshot.propagation_events()
    planting_events_list = snapshot.session.scalars(
        select(Event).where(Event.event_type == planting_type)
    ).all()

    if snapshot.period_start is not None and snapshot.period_end is not None:
        from ben0.reports.snapshot import _parse_date
        filtered: list[Event] = []
        for ev in planting_events_list:
            pd = _parse_date(ev.event_date)
            if pd is not None and snapshot.period_start <= pd < snapshot.period_end:
                filtered.append(ev)
        planting_events_list = filtered

    event_type_counts: Counter[str] = Counter(e.event_type for e in prop_events)
    total_propagation_events = len(prop_events)
    germination_events = event_type_counts.get("germinated", 0)
    sown_events = event_type_counts.get("sown", 0)
    planting_events_count = len(planting_events_list)

    prop_accession_ids: set[str] = set(
        e.accession_id for e in prop_events if e.accession_id
    )
    planted_accession_ids: set[str] = set(
        e.accession_id for e in planting_events_list if e.accession_id
    )
    propagation_to_planting_count = len(prop_accession_ids & planted_accession_ids)

    success_rate_pct: float | None = None
    if sown_events > 0 and germination_events > 0:
        success_rate_pct = round((germination_events / sown_events) * 100, 1)

    if total_propagation_events == 0:
        rating = "needs_attention"
    elif success_rate_pct is not None and success_rate_pct > 50:
        rating = "strong"
    else:
        rating = "adequate"

    findings: list[str] = []
    if total_propagation_events == 0:
        findings.append(
            "No propagation events (sown, germinated, pricked_out, potted) found in the database. "
            "Pipeline records may not have been imported."
        )
    else:
        findings.append(
            f"{total_propagation_events} propagation events recorded "
            f"({sown_events} sown, {germination_events} germinated, "
            f"{event_type_counts.get('pricked_out', 0)} pricked out, "
            f"{event_type_counts.get('potted', 0)} potted)."
        )
        findings.append(f"{planting_events_count} planting events recorded.")
        if propagation_to_planting_count:
            findings.append(
                f"{propagation_to_planting_count} accessions have both propagation and planting records "
                "(trackable pipeline trajectory)."
            )
        if success_rate_pct is not None:
            findings.append(f"Germination success rate: {success_rate_pct}% (germinated / sown events).")

    return SectionScore(
        name="Nursery Pipeline",
        rating=rating,
        metrics={
            "total_propagation_events": total_propagation_events,
            "germination_events": germination_events,
            "sown_events": sown_events,
            "planting_events": planting_events_count,
            "propagation_to_planting_count": propagation_to_planting_count,
            "success_rate_pct": success_rate_pct,
            "event_type_counts": dict(event_type_counts),
        },
        findings=findings,
    )


# ---------------------------------------------------------------------------
# Section 8: Data Integrity
# ---------------------------------------------------------------------------

def assess_data_integrity(snapshot: CollectionSnapshot) -> SectionScore:
    """Assess data quality using dashboard metrics (reused from calculate_metrics)."""
    session = snapshot.session
    metrics = calculate_metrics(session)

    issues_by_sev = metrics["validation_issues_by_severity"]
    critical = issues_by_sev.get("critical", 0)
    error = issues_by_sev.get("error", 0)
    warning = issues_by_sev.get("warning", 0)
    open_tickets = metrics["correction_tickets_by_status"].get("proposed", 0)
    provenance_coverage_pct = metrics["provenance_coverage_pct"]
    source_coverage_pct = metrics["source_coverage_pct"]

    if critical == 0 and error < 5:
        rating = "strong"
    elif critical > 0 or error > 20:
        rating = "needs_attention"
    else:
        rating = "adequate"

    findings: list[str] = []
    if critical:
        findings.append(f"{critical} critical validation issues require immediate curator attention.")
    if error:
        findings.append(f"{error} error-level issues are degrading record integrity.")
    if warning:
        findings.append(f"{warning} warnings flagged for review.")
    if open_tickets:
        findings.append(f"{open_tickets} proposed correction tickets are awaiting review.")

    top_issues = metrics.get("top_validation_issues", [])
    if top_issues:
        top = top_issues[0]
        findings.append(
            f"Most common issue type: {top['issue_type']} ({top['count']} occurrences)."
        )

    if not findings:
        findings.append("No outstanding validation issues or open tickets detected.")

    return SectionScore(
        name="Data Integrity",
        rating=rating,
        metrics={
            "critical_issues": critical,
            "error_issues": error,
            "warning_issues": warning,
            "provenance_coverage_pct": provenance_coverage_pct,
            "source_coverage_pct": source_coverage_pct,
            "open_tickets": open_tickets,
        },
        findings=findings,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_report_card(
    session: Session,
    garden_name: str = "Collection",
    snapshot_date: date | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> ReportCard:
    """Generate a full biodiversity report card for the given session.

    Pass snapshot_date for point-in-time reconstruction.
    Pass period_start and period_end for window mode.
    Omit all three for current-state mode (backward compatible).
    """
    snapshot = CollectionSnapshot(
        session=session,
        as_of=snapshot_date,
        period_start=period_start,
        period_end=period_end,
    )

    temporal_context: dict[str, Any] | None = None
    if snapshot_date is not None:
        temporal_context = {"mode": "snapshot", "as_of": str(snapshot_date)}
    elif period_start is not None or period_end is not None:
        temporal_context = {
            "mode": "window",
            "period_start": str(period_start) if period_start else None,
            "period_end": str(period_end) if period_end else None,
        }

    sections = [
        assess_taxonomic_diversity(snapshot),
        assess_conservation_value(snapshot),
        assess_provenance(snapshot),
        assess_collection_security(snapshot),
        assess_collection_dynamics(snapshot),
        assess_climate_readiness(snapshot),
        assess_nursery_pipeline(snapshot),
        assess_data_integrity(snapshot),
    ]
    return ReportCard(
        garden_name=garden_name,
        generated_at=datetime.utcnow().isoformat(timespec="seconds"),
        temporal_context=temporal_context,
        sections=sections,
    )


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

_RATING_NUMERIC = {"strong": 2, "adequate": 1, "needs_attention": 0}


def compare_report_cards(a: ReportCard, b: ReportCard) -> list[SectionDelta]:
    """Compare two cards section-by-section and produce SectionDelta entries."""
    deltas: list[SectionDelta] = []
    sections_b = {s.name: s for s in b.sections}

    for sec_a in a.sections:
        sec_b = sections_b.get(sec_a.name)
        if sec_b is None:
            continue

        rating_a = _RATING_NUMERIC.get(sec_a.rating, 1)
        rating_b = _RATING_NUMERIC.get(sec_b.rating, 1)
        diff = rating_b - rating_a

        if diff > 0:
            trend = "improving"
        elif diff < 0:
            trend = "declining"
        else:
            trend = "stable"

        metric_deltas: dict[str, Any] = {}
        for key, val_a in sec_a.metrics.items():
            val_b = sec_b.metrics.get(key)
            if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
                delta = val_b - val_a
                pct_change: float | None = None
                if val_a != 0:
                    pct_change = round((delta / abs(val_a)) * 100, 1)
                metric_deltas[key] = {
                    "a": val_a,
                    "b": val_b,
                    "delta": round(delta, 4) if isinstance(delta, float) else delta,
                    "pct_change": pct_change,
                }

        deltas.append(SectionDelta(name=sec_a.name, trend=trend, metric_deltas=metric_deltas))

    return deltas


def render_comparison_markdown(comparison: ReportCardComparison) -> str:
    """Render a side-by-side comparison of two report cards as Markdown."""
    lines: list[str] = [
        f"# Report Card Comparison: {comparison.card_a.garden_name}",
        "",
        f"| | {comparison.label_a} | {comparison.label_b} | Trend |",
        "|-|---|---|---|",
        f"| **Overall** | {comparison.card_a.overall_rating()} | {comparison.card_b.overall_rating()} | |",
        "",
    ]

    delta_by_name = {d.name: d for d in comparison.deltas}

    for sec_a, sec_b in zip(comparison.card_a.sections, comparison.card_b.sections):
        delta = delta_by_name.get(sec_a.name)
        trend_sym = {"improving": "+", "declining": "-", "stable": "~"}.get(
            delta.trend if delta else "stable", "~"
        )
        lines.append(f"## {sec_a.name}")
        lines.append("")
        lines.append(
            f"| Metric | {comparison.label_a} | {comparison.label_b} | Delta |"
        )
        lines.append("|---|---|---|---|")
        lines.append(
            f"| Rating | {sec_a.rating} | {sec_b.rating} | {trend_sym} |"
        )

        if delta:
            for metric_key, vals in delta.metric_deltas.items():
                a_val = vals.get("a", "")
                b_val = vals.get("b", "")
                d_val = vals.get("delta", "")
                if isinstance(d_val, float):
                    d_str = f"{d_val:+.2f}"
                elif isinstance(d_val, int):
                    d_str = f"{d_val:+d}"
                else:
                    d_str = str(d_val)
                lines.append(f"| {metric_key} | {a_val} | {b_val} | {d_str} |")

        lines.append("")

        for finding in sec_a.findings:
            lines.append(f"- **{comparison.label_a}:** {finding}")
        for finding in sec_b.findings:
            lines.append(f"- **{comparison.label_b}:** {finding}")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

_RATING_ICONS = {
    "strong": "🟢",
    "adequate": "🟡",
    "needs_attention": "🔴",
}

_RATING_LABELS = {
    "strong": "Strong",
    "adequate": "Adequate",
    "needs_attention": "Needs Attention",
}


def render_markdown(card: ReportCard) -> str:
    """Render a ReportCard as a Markdown string."""
    overall = card.overall_rating()
    overall_icon = _RATING_ICONS[overall]
    overall_label = _RATING_LABELS[overall]

    lines: list[str] = [
        f"# Collection Biodiversity Report Card: {card.garden_name}",
        "",
        f"**Generated:** {card.generated_at}  ",
        f"**Overall Rating:** {overall_icon} {overall_label}",
        "",
    ]

    if card.temporal_context:
        mode = card.temporal_context.get("mode", "current")
        if mode == "snapshot":
            lines.append(f"**Snapshot date:** {card.temporal_context.get('as_of')}  ")
        elif mode == "window":
            lines.append(
                f"**Period:** {card.temporal_context.get('period_start')} to "
                f"{card.temporal_context.get('period_end')}  "
            )
        lines.append("")

    lines += ["---", ""]

    for section in card.sections:
        icon = _RATING_ICONS.get(section.rating, "⚪")
        label = _RATING_LABELS.get(section.rating, section.rating)
        lines.append(f"## {icon} {section.name} — {label}")
        lines.append("")

        if section.metrics:
            lines.append("**Metrics**")
            lines.append("")
            for key, value in section.metrics.items():
                if isinstance(value, list):
                    lines.append(f"- **{key}:**")
                    for item in value:
                        if isinstance(item, dict):
                            item_str = ", ".join(f"{k}: {v}" for k, v in item.items())
                            lines.append(f"  - {item_str}")
                        else:
                            lines.append(f"  - {item}")
                elif isinstance(value, dict):
                    lines.append(f"- **{key}:**")
                    for k, v in value.items():
                        lines.append(f"  - {k}: {v}")
                else:
                    lines.append(f"- **{key}:** {value}")
            lines.append("")

        if section.findings:
            lines.append("**Findings**")
            lines.append("")
            for finding in section.findings:
                lines.append(f"- {finding}")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)
