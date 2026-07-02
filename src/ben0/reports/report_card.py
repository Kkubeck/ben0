"""Collection Biodiversity Report Card for ben0."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
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
    sections: list[SectionScore] = field(default_factory=list)

    def overall_rating(self) -> str:
        ratings = [s.rating for s in self.sections]
        if any(r == "needs_attention" for r in ratings):
            return "needs_attention"
        if all(r == "strong" for r in ratings):
            return "strong"
        return "adequate"

    def to_dict(self) -> dict[str, Any]:
        return {
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

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


# ---------------------------------------------------------------------------
# Section 1: Taxonomic Diversity
# ---------------------------------------------------------------------------

def assess_taxonomic_diversity(session: Session) -> SectionScore:
    """Assess breadth of taxonomic coverage across families, genera, and species."""
    taxa = session.scalars(
        select(Taxon).options(selectinload(Taxon.accessions))
    ).all()

    families: Counter[str] = Counter()
    genera: Counter[str] = Counter()
    family_accession_count: Counter[str] = Counter()

    for taxon in taxa:
        fam = taxon.family or "Unknown"
        gen = taxon.genus or "Unknown"
        families[fam] += 1
        genera[gen] += 1
        acc_count = len(taxon.accessions)
        family_accession_count[fam] += acc_count

    total_taxa = len(taxa)
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

def assess_conservation_value(session: Session) -> SectionScore:
    """Assess the collection's contribution to ex situ conservation of at-risk taxa."""
    total_taxa = session.scalar(select(func.count()).select_from(Taxon)) or 0

    statuses = session.scalars(select(ConservationStatus)).all()

    assessed_taxon_ids: set[str] = set()
    by_status: Counter[str] = Counter()
    threatened_taxon_ids: set[str] = set()

    for cs in statuses:
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

def assess_provenance(session: Session) -> SectionScore:
    """Assess wild origin documentation, locality completeness, and collector records."""
    accessions = session.scalars(
        select(Accession).options(selectinload(Accession.provenances))
    ).all()
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

def assess_collection_security(session: Session) -> SectionScore:
    """Assess resilience of the living collection against accession and item loss."""
    # For each taxon, count living accessions (accessions that have at least one living item)
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
    vulnerable_taxa: list[tuple[str, int]] = []  # (scientific_name, threatened_status)

    for taxon in taxa:
        living_accession_ids: list[str] = []
        for acc in taxon.accessions:
            living_items = [
                it for it in acc.items
                if (it.life_status or "").strip().lower() in {"living", "alive", "current"}
            ]
            if living_items:
                living_accession_ids.append(acc.id)
                # Check single-item accessions
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
            # Flag if taxon has conservation value
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

def assess_collection_dynamics(session: Session) -> SectionScore:
    """Assess acquisition trends, living ratio, and collection age profile."""
    from ben0.dashboard.metrics import _extract_year, _normalize_item_status

    accessions = session.scalars(
        select(Accession).options(selectinload(Accession.items))
    ).all()
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

    # Growth trend: compare last 3 decades
    sorted_decades = sorted(decade_counter.keys())
    growth_trend = "stable"
    if len(sorted_decades) >= 3:
        recent = sorted_decades[-3:]
        counts = [decade_counter[d] for d in recent]
        if counts[-1] > counts[0] * 1.2:
            growth_trend = "increasing"
        elif counts[-1] < counts[0] * 0.8:
            growth_trend = "declining"

    item_status_counts = Counter(_normalize_item_status(it.life_status) for it in items)
    total_items = len(items)
    alive_count = item_status_counts.get("alive", 0)
    living_pct = round((alive_count / total_items) * 100, 1) if total_items else 0.0

    import statistics
    current_year = datetime.utcnow().year
    accession_ages = [current_year - y for y in accession_years if y <= current_year]
    median_accession_age_years = (
        round(statistics.median(accession_ages), 1) if accession_ages else None
    )

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

    return SectionScore(
        name="Collection Dynamics",
        rating=rating,
        metrics={
            "accessions_by_decade": accessions_by_decade,
            "growth_trend": growth_trend,
            "living_pct": living_pct,
            "median_accession_age_years": median_accession_age_years,
        },
        findings=findings,
    )


# ---------------------------------------------------------------------------
# Section 6: Climate Readiness (stub)
# ---------------------------------------------------------------------------

def assess_climate_readiness(session: Session) -> SectionScore:
    """Stub: climate resilience assessment requires external CAT or climate zone data."""
    # Check if any ConservationStatus records indicate climate-related assessment
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

def assess_nursery_pipeline(session: Session) -> SectionScore:
    """Assess propagation pipeline throughput and success rates from Event records."""
    propagation_types = list(_PROPAGATION_TYPES)
    planting_type = "planted"

    # Count events by type for all propagation-related events
    prop_events = session.scalars(
        select(Event).where(Event.event_type.in_(propagation_types + [planting_type]))
    ).all()

    event_type_counts: Counter[str] = Counter(e.event_type for e in prop_events)
    total_propagation_events = sum(
        event_type_counts.get(t, 0) for t in propagation_types
    )
    germination_events = event_type_counts.get("germinated", 0)
    sown_events = event_type_counts.get("sown", 0)
    planting_events = event_type_counts.get(planting_type, 0)

    # Accessions with both a propagation event AND a planting event
    prop_accession_ids: set[str] = set(
        e.accession_id for e in prop_events
        if e.event_type in _PROPAGATION_TYPES and e.accession_id
    )
    planted_accession_ids: set[str] = set(
        e.accession_id for e in prop_events
        if e.event_type == planting_type and e.accession_id
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
        findings.append(f"{planting_events} planting events recorded.")
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
            "planting_events": planting_events,
            "propagation_to_planting_count": propagation_to_planting_count,
            "success_rate_pct": success_rate_pct,
            "event_type_counts": dict(event_type_counts),
        },
        findings=findings,
    )


# ---------------------------------------------------------------------------
# Section 8: Data Integrity
# ---------------------------------------------------------------------------

def assess_data_integrity(session: Session) -> SectionScore:
    """Assess data quality using dashboard metrics (reused from calculate_metrics)."""
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

def generate_report_card(session: Session, garden_name: str = "Collection") -> ReportCard:
    """Generate a full biodiversity report card for the given session."""
    sections = [
        assess_taxonomic_diversity(session),
        assess_conservation_value(session),
        assess_provenance(session),
        assess_collection_security(session),
        assess_collection_dynamics(session),
        assess_climate_readiness(session),
        assess_nursery_pipeline(session),
        assess_data_integrity(session),
    ]
    return ReportCard(
        garden_name=garden_name,
        generated_at=datetime.utcnow().isoformat(timespec="seconds"),
        sections=sections,
    )


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
        "---",
        "",
    ]

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
