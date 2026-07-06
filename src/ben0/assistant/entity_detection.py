"""Rule-based botanical entity detection for assistant questions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ben0.db.models import Location, Taxon
from ben0.ingest.normalize import clean_location_code, normalize_accession_number


# ---------------------------------------------------------------------------
# Data definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DetectedEntity:
    """A botanical entity identified in a user question.

    entity_type: "accession" | "taxon" | "location"
    entity_id: canonical identifier for downstream lookup
    canonical_name: human-readable canonical label
    matched_text: original text span matched in the question
    """

    entity_type: str
    entity_id: str
    canonical_name: str
    matched_text: str


# A DetectionList is a list[DetectedEntity].
# Interpretation: each entry describes one unique entity detected in a question.
# Examples:
#   [DetectedEntity("accession", "1984-0023", "1984-0023", "1984-23")]
#   [DetectedEntity("taxon", "taxon-1", "Acer macrophyllum", "acer macrophyllum")]


# accession_text is a string from the user's question.
# Interpretation: accession_text may appear in normalized or lightly variant forms.
# Examples:
#   "12345-678-90"
#   "1984-23"
_ACCESSION_PATTERN = re.compile(r"\b\d{4,5}(?:[-.]\d{1,4})(?:[-.]\d{1,4})?\b")


# entity_text is a taxon or location name/code.
# Interpretation: entity_text should match as a standalone phrase, not inside a longer token.
# Example:
#   "Acer macrophyllum"
#   "D-42"
_NON_WORD_BOUNDARY = r"(?<![A-Za-z0-9]){text}(?![A-Za-z0-9])"


# ---------------------------------------------------------------------------
# detect_entities
# ---------------------------------------------------------------------------


def detect_entities(session: Session, question: str) -> list[DetectedEntity]:
    """Return the accession, taxon, and location entities mentioned in question."""
    entities = []
    entities.extend(detect_accessions(question))
    entities.extend(detect_taxa(session, question))
    entities.extend(detect_locations(session, question))
    return _dedupe_entities(entities)


def detect_accessions(question: str) -> list[DetectedEntity]:
    """Return accession-like identifiers mentioned in question."""
    matches: list[DetectedEntity] = []
    for match_text in _ACCESSION_PATTERN.findall(question):
        canonical = normalize_accession_number(match_text.replace(".", "-"))
        if not canonical:
            continue
        matches.append(
            DetectedEntity(
                entity_type="accession",
                entity_id=canonical,
                canonical_name=canonical,
                matched_text=match_text,
            )
        )
    return _dedupe_entities(matches)


def detect_taxa(session: Session, question: str) -> list[DetectedEntity]:
    """Return taxon records whose scientific names are mentioned in question."""
    question_lower = question.lower()
    taxa = session.scalars(select(Taxon).where(Taxon.scientific_name.is_not(None))).all()
    matches: list[DetectedEntity] = []

    for taxon in sorted(taxa, key=lambda row: len(row.scientific_name or ""), reverse=True):
        scientific_name = (taxon.scientific_name or "").strip()
        if not scientific_name:
            continue
        if not _contains_phrase(question_lower, scientific_name.lower()):
            continue
        matches.append(
            DetectedEntity(
                entity_type="taxon",
                entity_id=taxon.id,
                canonical_name=scientific_name,
                matched_text=scientific_name,
            )
        )
    return _dedupe_entities(matches)


def detect_locations(session: Session, question: str) -> list[DetectedEntity]:
    """Return location records whose codes or aliases are mentioned in question."""
    question_upper = question.upper()
    locations = session.scalars(select(Location).where(Location.location_code.is_not(None))).all()
    matches: list[DetectedEntity] = []

    for location in locations:
        candidates = [location.location_code]
        candidates.extend(_load_aliases(location.aliases))
        seen_candidates = {candidate for candidate in candidates if candidate}
        for candidate in seen_candidates:
            cleaned = clean_location_code(candidate)
            if not cleaned:
                continue
            if not _contains_phrase(question_upper, cleaned.upper()):
                continue
            matches.append(
                DetectedEntity(
                    entity_type="location",
                    entity_id=location.id,
                    canonical_name=location.location_code,
                    matched_text=candidate,
                )
            )
            break
    return _dedupe_entities(matches)


def _contains_phrase(haystack: str, needle: str) -> bool:
    """Return whether needle appears as a standalone phrase in haystack."""
    pattern = _NON_WORD_BOUNDARY.format(text=re.escape(needle))
    return re.search(pattern, haystack, re.IGNORECASE) is not None


def _load_aliases(raw_aliases: str | None) -> list[str]:
    """Decode Location.aliases JSON safely."""
    if not raw_aliases:
        return []
    try:
        payload = json.loads(raw_aliases)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [str(value) for value in payload if str(value).strip()]


def _dedupe_entities(entities: list[DetectedEntity]) -> list[DetectedEntity]:
    """Return entities in first-seen order, removing duplicate type/id pairs."""
    deduped: list[DetectedEntity] = []
    seen: set[tuple[str, str]] = set()
    for entity in entities:
        marker = (entity.entity_type, entity.entity_id)
        if marker in seen:
            continue
        deduped.append(entity)
        seen.add(marker)
    return deduped
