"""Deterministic validation rules for BEN-0."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
import re
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ben0.db.models import Accession, Event, Item, Provenance, SensitiveDataFlag, Taxon

ACCESSION_PATTERNS = (
    re.compile(r"^\d{4}[-.]\d+$", re.I),
    re.compile(r"^CDBG[-.]\d{4}[-.]\d+$", re.I),
    re.compile(r"^\d{2}[-.]\d+$", re.I),
    re.compile(r"^(TEMP|UNKNOWN)[-.]\d+$", re.I),
)
TERMINAL_EVENT_TYPES = {"dead", "removed", "transferred"}
LOCATION_EVENT_TYPES = {"planted", "relocated", "potted", "pricked_out", "received"}
SENSITIVE_LEVELS = {"restricted", "culturally_sensitive", "unknown"}
SUSPICIOUS_YEAR_MIN = 1800


@dataclass(slots=True)
class ValidationFinding:
    issue_type: str
    severity: str
    entity_type: str | None
    entity_id: str | None
    entity_label: str | None
    explanation: str
    evidence: str
    recommended_action: str
    requires_human_review: bool = True


def _parse_iso_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _entity_label_for_item(item: Item) -> str:
    return item.item_label or item.id


def _entity_label_for_accession(accession: Accession) -> str:
    return accession.accession_number or accession.id


def _format_date(raw: str | None) -> str:
    return raw or "[missing]"


def check_accession_number_integrity(session: Session) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    accessions = session.scalars(select(Accession)).all()

    seen: dict[str, list[Accession]] = {}
    for accession in accessions:
        label = _entity_label_for_accession(accession)
        raw = (accession.accession_number or "").strip()
        normalized = (accession.accession_number_normalized or raw).strip().upper()

        if not raw:
            findings.append(
                ValidationFinding(
                    issue_type="missing_accession_number",
                    severity="critical",
                    entity_type="accession",
                    entity_id=accession.id,
                    entity_label=label,
                    explanation="Accession record is missing its accession number.",
                    evidence=f"accession_id={accession.id}",
                    recommended_action="Populate the accession number from the authoritative register before using this record.",
                )
            )
            continue

        if not any(pattern.match(raw) for pattern in ACCESSION_PATTERNS):
            findings.append(
                ValidationFinding(
                    issue_type="invalid_accession_number",
                    severity="error",
                    entity_type="accession",
                    entity_id=accession.id,
                    entity_label=label,
                    explanation="Accession number does not match any known local format.",
                    evidence=f"accession_number={raw}; normalized={normalized or '[none]'}",
                    recommended_action="Review the raw accession label, correct typos, or document a new accepted format.",
                )
            )

        seen.setdefault(normalized or raw.upper(), []).append(accession)

    for normalized, dupes in seen.items():
        if len(dupes) < 2:
            continue
        labels = ", ".join(_entity_label_for_accession(acc) for acc in dupes)
        for accession in dupes:
            findings.append(
                ValidationFinding(
                    issue_type="duplicate_accession_number",
                    severity="critical",
                    entity_type="accession",
                    entity_id=accession.id,
                    entity_label=_entity_label_for_accession(accession),
                    explanation="Multiple accession records resolve to the same normalized accession number.",
                    evidence=f"normalized_accession_number={normalized}; duplicates={labels}",
                    recommended_action="Merge duplicates or disambiguate the accession numbering in source records.",
                )
            )

    return findings


def check_required_accession_fields(session: Session) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    accessions = session.scalars(
        select(Accession).options(
            selectinload(Accession.provenances),
            selectinload(Accession.items),
        )
    ).all()

    for accession in accessions:
        label = _entity_label_for_accession(accession)
        has_taxon = bool(accession.taxon_id or (accession.taxon_name_verbatim or "").strip())
        if not has_taxon:
            findings.append(
                ValidationFinding(
                    issue_type="missing_taxon_name",
                    severity="error",
                    entity_type="accession",
                    entity_id=accession.id,
                    entity_label=label,
                    explanation="Accession is missing a taxon assignment and verbatim taxon name.",
                    evidence=f"accession_number={label}",
                    recommended_action="Attach the accession to an existing taxon or capture the original taxon name for review.",
                )
            )

        if not accession.provenances:
            findings.append(
                ValidationFinding(
                    issue_type="missing_provenance",
                    severity="error",
                    entity_type="accession",
                    entity_id=accession.id,
                    entity_label=label,
                    explanation="Accession has no provenance record.",
                    evidence=f"accession_number={label}",
                    recommended_action="Create a provenance record or explicitly document that provenance is unknown.",
                )
            )
        else:
            for provenance in accession.provenances:
                if not provenance.source_id:
                    findings.append(
                        ValidationFinding(
                            issue_type="missing_source",
                            severity="warning",
                            entity_type="accession",
                            entity_id=accession.id,
                            entity_label=label,
                            explanation="Provenance record exists but has no linked source.",
                            evidence=f"accession_number={label}; provenance_id={provenance.id}; origin_code={provenance.origin_code or '[missing]'}",
                            recommended_action="Link the provenance to a source institution, collector, or explicit unknown-source record.",
                        )
                    )
                if (provenance.origin_code or "").strip().upper() in {"", "U", "UNKNOWN"}:
                    findings.append(
                        ValidationFinding(
                            issue_type="unknown_provenance",
                            severity="warning",
                            entity_type="accession",
                            entity_id=accession.id,
                            entity_label=label,
                            explanation="Provenance is recorded as unknown or left blank.",
                            evidence=f"accession_number={label}; provenance_id={provenance.id}; origin_code={provenance.origin_code or '[missing]'}",
                            recommended_action="Review accession paperwork and source ledgers to refine provenance if possible.",
                        )
                    )

        if not accession.items:
            findings.append(
                ValidationFinding(
                    issue_type="accession_with_no_items",
                    severity="warning",
                    entity_type="accession",
                    entity_id=accession.id,
                    entity_label=label,
                    explanation="Accession has no linked item records.",
                    evidence=f"accession_number={label}",
                    recommended_action="Confirm whether the accession was never itemized, all items were removed, or the linkage failed during import.",
                )
            )

    return findings


def check_item_status_consistency(session: Session) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    items = session.scalars(
        select(Item).options(
            selectinload(Item.events),
            selectinload(Item.accession),
        )
    ).all()

    for item in items:
        label = _entity_label_for_item(item)
        life_status = (item.life_status or "unknown").lower()

        if life_status == "living" and not item.current_location_id:
            findings.append(
                ValidationFinding(
                    issue_type="living_item_without_current_location",
                    severity="error",
                    entity_type="item",
                    entity_id=item.id,
                    entity_label=label,
                    explanation="Living item does not have a current location.",
                    evidence=f"item_label={label}; life_status={life_status}; current_location_id=[missing]",
                    recommended_action="Assign the current location or update the life status if the plant is no longer living in the collection.",
                )
            )

        if life_status in TERMINAL_EVENT_TYPES and item.is_current:
            findings.append(
                ValidationFinding(
                    issue_type="dead_item_marked_current",
                    severity="critical",
                    entity_type="item",
                    entity_id=item.id,
                    entity_label=label,
                    explanation="Item is marked current even though its life status is terminal.",
                    evidence=f"item_label={label}; life_status={life_status}; is_current={item.is_current}",
                    recommended_action="Set is_current to false or correct the life status after reviewing event history.",
                )
            )

        if not item.events:
            findings.append(
                ValidationFinding(
                    issue_type="item_without_event_history",
                    severity="warning",
                    entity_type="item",
                    entity_id=item.id,
                    entity_label=label,
                    explanation="Item has no event history.",
                    evidence=f"item_label={label}",
                    recommended_action="Add at least one acquisition, planting, or status event so the item's history is auditable.",
                )
            )
            continue

        dated_events = sorted(
            (
                (event, _parse_iso_date(event.event_date))
                for event in item.events
                if event.event_type
            ),
            key=lambda pair: (pair[1] or date.min, pair[0].created_at),
        )

        terminal_events = [
            (event, parsed)
            for event, parsed in dated_events
            if (event.event_type or "").lower() in TERMINAL_EVENT_TYPES
        ]
        if item.is_current and terminal_events:
            event, parsed = terminal_events[-1]
            findings.append(
                ValidationFinding(
                    issue_type="current_item_with_terminal_event",
                    severity="error",
                    entity_type="item",
                    entity_id=item.id,
                    entity_label=label,
                    explanation="Current item has a terminal event recorded in its history.",
                    evidence=f"item_label={label}; terminal_event={event.event_type}; terminal_event_date={_format_date(event.event_date)}",
                    recommended_action="Review whether the item should be non-current or whether the terminal event was entered in error.",
                )
            )

        active_locations = {
            event.location_id or event.location_verbatim
            for event, _ in dated_events
            if (event.event_type or "").lower() in LOCATION_EVENT_TYPES
            and (event.location_id or event.location_verbatim)
        }
        latest_location_date = max(
            (parsed for event, parsed in dated_events if (event.event_type or "").lower() in LOCATION_EVENT_TYPES and parsed),
            default=None,
        )
        latest_locations = {
            event.location_id or event.location_verbatim
            for event, parsed in dated_events
            if parsed == latest_location_date
            and (event.event_type or "").lower() in LOCATION_EVENT_TYPES
            and (event.location_id or event.location_verbatim)
        }
        if item.is_current and len(active_locations) > 1 and len(latest_locations) > 1:
            findings.append(
                ValidationFinding(
                    issue_type="item_with_multiple_current_locations",
                    severity="critical",
                    entity_type="item",
                    entity_id=item.id,
                    entity_label=label,
                    explanation="Item appears to have multiple competing current locations.",
                    evidence=f"item_label={label}; latest_location_candidates={sorted(latest_locations)}",
                    recommended_action="Confirm the authoritative current location and close or correct the conflicting location history.",
                )
            )

    return findings


def check_date_integrity(session: Session) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    today = date.today()
    accessions = session.scalars(select(Accession).options(selectinload(Accession.events), selectinload(Accession.items))).all()

    for accession in accessions:
        accession_date = _parse_iso_date(accession.accession_date)
        label = _entity_label_for_accession(accession)

        if accession.accession_date:
            if accession_date is None:
                findings.append(
                    ValidationFinding(
                        issue_type="impossible_or_unparsed_accession_date",
                        severity="warning",
                        entity_type="accession",
                        entity_id=accession.id,
                        entity_label=label,
                        explanation="Accession date could not be parsed into a valid ISO date.",
                        evidence=f"accession_number={label}; accession_date={accession.accession_date}",
                        recommended_action="Normalize the accession date to a real calendar date.",
                    )
                )
            elif accession_date.year < SUSPICIOUS_YEAR_MIN or accession_date > today:
                findings.append(
                    ValidationFinding(
                        issue_type="suspicious_accession_date",
                        severity="warning",
                        entity_type="accession",
                        entity_id=accession.id,
                        entity_label=label,
                        explanation="Accession date falls outside a plausible operating range.",
                        evidence=f"accession_number={label}; accession_date={accession.accession_date}",
                        recommended_action="Confirm the accession date against original paperwork or ledgers.",
                    )
                )

        for event in accession.events:
            if event.event_date and _parse_iso_date(event.event_date) is None:
                findings.append(
                    ValidationFinding(
                        issue_type="impossible_or_unparsed_event_date",
                        severity="warning",
                        entity_type="event",
                        entity_id=event.id,
                        entity_label=event.event_type or event.id,
                        explanation="Event date could not be parsed into a valid ISO date.",
                        evidence=f"event_id={event.id}; event_date={event.event_date}; verbatim={event.event_date_verbatim or '[missing]'}",
                        recommended_action="Correct the event date format or preserve the value only in verbatim notes.",
                    )
                )
                continue

            event_date = _parse_iso_date(event.event_date)
            if event_date and accession_date and event_date < accession_date:
                findings.append(
                    ValidationFinding(
                        issue_type="event_before_accession_date",
                        severity="error",
                        entity_type="event",
                        entity_id=event.id,
                        entity_label=event.event_type or event.id,
                        explanation="Event is dated before the accession date.",
                        evidence=f"accession_number={label}; accession_date={_format_date(accession.accession_date)}; event_date={_format_date(event.event_date)}; event_type={event.event_type}",
                        recommended_action="Verify the event date, accession date, or whether the event belongs to a different accession.",
                    )
                )
            if event_date and (event_date.year < SUSPICIOUS_YEAR_MIN or event_date > today):
                findings.append(
                    ValidationFinding(
                        issue_type="suspicious_event_date",
                        severity="warning",
                        entity_type="event",
                        entity_id=event.id,
                        entity_label=event.event_type or event.id,
                        explanation="Event date falls outside a plausible operating range.",
                        evidence=f"event_id={event.id}; event_date={_format_date(event.event_date)}; event_type={event.event_type}",
                        recommended_action="Review the source row for data-entry or parsing errors.",
                    )
                )

        for item in accession.items:
            for field_name, raw in (("planting_date", item.planting_date), ("death_date", item.death_date)):
                if not raw:
                    continue
                parsed = _parse_iso_date(raw)
                if parsed is None or parsed.year < SUSPICIOUS_YEAR_MIN or parsed > today:
                    findings.append(
                        ValidationFinding(
                            issue_type="suspicious_item_date",
                            severity="warning",
                            entity_type="item",
                            entity_id=item.id,
                            entity_label=_entity_label_for_item(item),
                            explanation=f"{field_name.replace('_', ' ').title()} is impossible or suspicious.",
                            evidence=f"item_label={_entity_label_for_item(item)}; {field_name}={raw}",
                            recommended_action="Check the item's date fields against event history and source records.",
                        )
                    )

    return findings


def check_sensitive_data_controls(session: Session) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    accessions = session.scalars(select(Accession).options(selectinload(Accession.sensitive_flags))).all()

    for accession in accessions:
        label = _entity_label_for_accession(accession)
        if accession.is_sensitive and not accession.sensitive_flags:
            findings.append(
                ValidationFinding(
                    issue_type="sensitive_record_missing_sharing_restriction",
                    severity="critical",
                    entity_type="accession",
                    entity_id=accession.id,
                    entity_label=label,
                    explanation="Accession is marked sensitive but has no explicit sharing restriction record.",
                    evidence=f"accession_number={label}; is_sensitive=True",
                    recommended_action="Create a SensitiveDataFlag describing sensitivity level, sharing rules, and rationale.",
                )
            )

        for flag in accession.sensitive_flags:
            if flag.sensitivity_level in SENSITIVE_LEVELS and flag.sharing_allowed == "allowed":
                findings.append(
                    ValidationFinding(
                        issue_type="public_export_candidate_with_sensitive_flag",
                        severity="critical",
                        entity_type="accession",
                        entity_id=accession.id,
                        entity_label=label,
                        explanation="Record has a sensitive flag but is currently marked as allowed for sharing.",
                        evidence=f"accession_number={label}; sensitivity_level={flag.sensitivity_level}; sharing_allowed={flag.sharing_allowed}",
                        recommended_action="Switch sharing to review_required or not_allowed before public export.",
                    )
                )

    orphan_flags = session.scalars(select(SensitiveDataFlag).where(SensitiveDataFlag.accession_id.is_(None))).all()
    for flag in orphan_flags:
        if flag.sensitivity_level in SENSITIVE_LEVELS and flag.sharing_allowed == "allowed":
            findings.append(
                ValidationFinding(
                    issue_type="public_export_candidate_with_sensitive_flag",
                    severity="error",
                    entity_type=flag.entity_type,
                    entity_id=flag.entity_id,
                    entity_label=f"{flag.entity_type}:{flag.entity_id}",
                    explanation="Sensitive flag allows sharing on a non-accession record that should likely be reviewed.",
                    evidence=f"flag_id={flag.id}; sensitivity_level={flag.sensitivity_level}; sharing_allowed={flag.sharing_allowed}",
                    recommended_action="Review the flag and ensure downstream exports do not expose restricted data.",
                )
            )

    return findings


def check_similar_unreconciled_taxa(session: Session) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    taxa = session.scalars(select(Taxon)).all()
    normalized = [
        (
            taxon,
            re.sub(r"[^a-z0-9]+", " ", taxon.scientific_name.lower()).strip(),
        )
        for taxon in taxa
        if taxon.scientific_name
    ]

    seen_pairs: set[tuple[str, str]] = set()
    for idx, (left, left_norm) in enumerate(normalized):
        for right, right_norm in normalized[idx + 1 :]:
            pair = tuple(sorted((left.id, right.id)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            if left.accepted_taxon_id == right.id or right.accepted_taxon_id == left.id:
                continue
            ratio = SequenceMatcher(None, left_norm, right_norm).ratio()
            if ratio < 0.88:
                continue
            if left_norm == right_norm:
                continue
            findings.append(
                ValidationFinding(
                    issue_type="similar_unreconciled_taxon_names",
                    severity="warning",
                    entity_type="taxon",
                    entity_id=left.id,
                    entity_label=left.scientific_name,
                    explanation="Taxon name is very similar to another unreconciled name in the dataset.",
                    evidence=f"left={left.scientific_name}; right={right.scientific_name}; similarity={ratio:.2f}",
                    recommended_action="Review whether these names are spelling variants, synonyms, or genuinely distinct taxa.",
                )
            )

    return findings


def run_all_rules(session: Session) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for rule in VALIDATION_RULES:
        findings.extend(rule(session))
    return findings


VALIDATION_RULES: tuple = (
    check_accession_number_integrity,
    check_required_accession_fields,
    check_item_status_consistency,
    check_date_integrity,
    check_sensitive_data_controls,
    check_similar_unreconciled_taxa,
)
