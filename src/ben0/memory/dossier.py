"""Dossier storage: create, read, append, and seed entity dossier markdown files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ben0.assistant.entity_detection import DetectedEntity
from ben0.db.models import Accession, Item, Location, Provenance, Taxon
from ben0.memory.tags import TAG_SET, assign_tags


# ---------------------------------------------------------------------------
# Data definitions
# ---------------------------------------------------------------------------

# DOSSIER_ROOT is the base directory for all dossier files.
DOSSIER_ROOT = Path("data/dossiers")


@dataclass
class DossierEntry:
    """A single learned-fact entry in a dossier.

    timestamp: ISO date string (YYYY-MM-DD)
    tags: list of 1-2 tag strings from TAG_SET
    text: the fact or observation
    source_session: optional session id that produced this entry
    """

    timestamp: str
    tags: list[str]
    text: str
    source_session: str | None = None

# Examples:
#   DossierEntry("2026-07-05", ["status", "location"], "3 of 12 items dead, all in bed D-42")
#   DossierEntry("2026-07-10", ["propagation"], "2 cuttings taken spring 2024, both failed", "sess-42")


@dataclass
class Dossier:
    """In-memory representation of a single entity's dossier file.

    entity_type: "taxon" | "accession" | "location"
    entity_id: canonical identifier (slug)
    canonical_name: human-readable name
    facts: list of fact strings (seeded from DB)
    learned: list of DossierEntry (accumulated from conversations)
    path: filesystem path to the .md file
    """

    entity_type: str
    entity_id: str
    canonical_name: str
    facts: list[str] = field(default_factory=list)
    learned: list[DossierEntry] = field(default_factory=list)
    path: Path = field(default_factory=lambda: Path())

# Examples:
#   Dossier("taxon", "acer-macrophyllum", "Acer macrophyllum",
#           ["Family: Sapindaceae", "12 accessions in collection"],
#           [DossierEntry("2026-07-05", ["status"], "3 of 12 items dead")])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _dossier_path(entity_type: str, entity_id: str) -> Path:
    return DOSSIER_ROOT / entity_type / f"{_slugify(entity_id)}.md"


def _today() -> str:
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# load_dossier
# ---------------------------------------------------------------------------


def load_dossier(entity_type: str, entity_id: str) -> Dossier:
    """Load a dossier from disk, or return an empty Dossier if the file doesn't exist."""
    path = _dossier_path(entity_type, entity_id)
    dossier = Dossier(
        entity_type=entity_type,
        entity_id=_slugify(entity_id),
        canonical_name=entity_id,
        path=path,
    )
    if not path.exists():
        return dossier

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Parse header metadata
    for line in lines:
        if line.startswith("canonical_name:"):
            dossier.canonical_name = line.split(":", 1)[1].strip()

    # Parse Facts section
    in_facts = False
    in_learned = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Facts"):
            in_facts = True
            in_learned = False
            continue
        if stripped.startswith("## Learned"):
            in_facts = False
            in_learned = True
            continue
        if stripped.startswith("## "):
            in_facts = False
            in_learned = False
            continue

        if in_facts and stripped.startswith("- "):
            dossier.facts.append(stripped[2:])

        if in_learned and stripped.startswith("- "):
            entry = _parse_learned_line(stripped[2:])
            if entry:
                dossier.learned.append(entry)

    return dossier


def _parse_learned_line(line: str) -> DossierEntry | None:
    """Parse a learned entry line like: [2026-07-05] [status, location] some text"""
    match = re.match(r"\[(\d{4}-\d{2}-\d{2})\]\s*\[([^\]]*)\]\s*(.*)", line)
    if not match:
        return None
    timestamp = match.group(1)
    tags = [t.strip() for t in match.group(2).split(",") if t.strip()]
    text = match.group(3)
    return DossierEntry(timestamp=timestamp, tags=tags, text=text)


# ---------------------------------------------------------------------------
# read_dossier
# ---------------------------------------------------------------------------


def read_dossier(entity_type: str, entity_id: str) -> str:
    """Return the raw markdown text of a dossier, or empty string if not found."""
    path = _dossier_path(entity_type, entity_id)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# _write_dossier
# ---------------------------------------------------------------------------


def _write_dossier(dossier: Dossier) -> None:
    """Serialize a Dossier to its markdown file on disk."""
    dossier.path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append(f"# {dossier.canonical_name}")
    lines.append("")
    lines.append(f"entity_type: {dossier.entity_type}")
    lines.append(f"entity_id: {dossier.entity_id}")
    lines.append(f"canonical_name: {dossier.canonical_name}")
    lines.append(f"last_updated: {_today()}")
    lines.append("")

    lines.append("## Facts (seeded from DB on first encounter)")
    lines.append("")
    for fact in dossier.facts:
        lines.append(f"- {fact}")
    lines.append("")

    lines.append("## Learned (accumulated from conversations)")
    lines.append("")
    for entry in dossier.learned:
        tag_str = ", ".join(entry.tags)
        lines.append(f"- [{entry.timestamp}] [{tag_str}] {entry.text}")
    lines.append("")

    dossier.path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# seed_from_db
# ---------------------------------------------------------------------------


def seed_from_db(session: Session, entity: DetectedEntity) -> list[str]:
    """Query the database and return seed facts for an entity's dossier.

    Does not write to disk. Returns a list of fact strings.
    """
    if entity.entity_type == "taxon":
        return _seed_taxon(session, entity)
    if entity.entity_type == "accession":
        return _seed_accession(session, entity)
    if entity.entity_type == "location":
        return _seed_location(session, entity)
    return []


def _seed_taxon(session: Session, entity: DetectedEntity) -> list[str]:
    taxon = session.get(Taxon, entity.entity_id)
    if not taxon:
        return []

    facts: list[str] = []
    if taxon.family:
        facts.append(f"Family: {taxon.family}")

    acc_count = session.scalar(
        select(func.count(Accession.id)).where(Accession.taxon_id == taxon.id)
    )
    if acc_count:
        facts.append(f"{acc_count} accessions in collection")

    item_count = session.scalar(
        select(func.count(Item.id)).join(Accession).where(Accession.taxon_id == taxon.id)
    )
    dead_count = session.scalar(
        select(func.count(Item.id))
        .join(Accession)
        .where(Accession.taxon_id == taxon.id, Item.life_status == "dead")
    )
    if item_count:
        facts.append(f"{item_count} items total, {dead_count or 0} dead")

    wild_count = session.scalar(
        select(func.count(Provenance.id))
        .join(Accession)
        .where(Accession.taxon_id == taxon.id, Provenance.origin_code == "W")
    )
    if wild_count:
        facts.append(f"Wild-collected: {wild_count} of {acc_count}")

    if taxon.iucn_status:
        facts.append(f"IUCN status: {taxon.iucn_status}")

    return facts


def _seed_accession(session: Session, entity: DetectedEntity) -> list[str]:
    acc = session.scalar(
        select(Accession).where(
            Accession.accession_number_normalized == entity.entity_id
        )
    )
    if not acc:
        return []

    facts: list[str] = []
    if acc.taxon:
        facts.append(f"Taxon: {acc.taxon.scientific_name}")
    if acc.accession_date:
        facts.append(f"Accession date: {acc.accession_date}")

    item_count = session.scalar(
        select(func.count(Item.id)).where(Item.accession_id == acc.id)
    )
    if item_count:
        facts.append(f"{item_count} items")

    provs = session.scalars(
        select(Provenance).where(Provenance.accession_id == acc.id)
    ).all()
    for prov in provs:
        if prov.collector:
            facts.append(f"Collector: {prov.collector}")
        if prov.origin_code:
            facts.append(f"Origin: {prov.origin_code}")

    return facts


def _seed_location(session: Session, entity: DetectedEntity) -> list[str]:
    loc = session.get(Location, entity.entity_id)
    if not loc:
        return []

    facts: list[str] = []
    if loc.location_name:
        facts.append(f"Name: {loc.location_name}")

    item_count = session.scalar(
        select(func.count(Item.id)).where(Item.current_location_id == loc.id)
    )
    if item_count:
        facts.append(f"{item_count} items currently planted")

    return facts


# ---------------------------------------------------------------------------
# append_learned
# ---------------------------------------------------------------------------


def append_learned(dossier: Dossier, entries: list[DossierEntry]) -> None:
    """Append learned entries to a dossier and write to disk."""
    dossier.learned.extend(entries)
    _write_dossier(dossier)
