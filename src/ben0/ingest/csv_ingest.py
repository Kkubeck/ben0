"""Ingest synthetic CSVs into the BEN-0 database."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from ben0.db.models import (
    Accession,
    ConservationStatus,
    Event,
    Item,
    Location,
    Provenance,
    Source,
    Taxon,
)
from ben0.db.session import get_session
from ben0.ingest.normalize import clean_int, clean_str, normalize_accession_number, parse_date, parse_year


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _val(row: dict, *keys: str) -> str | None:
    for k in keys:
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


# ---------------------------------------------------------------------------
# Per-table ingest functions
# ---------------------------------------------------------------------------

def ingest_taxa(path: Path, session) -> dict[str, str]:
    """Returns mapping scientific_name → taxon.id."""
    name_to_id: dict[str, str] = {}
    rows = _read_csv(path)
    source_file = str(path)

    for row_num, row in enumerate(rows, start=2):
        sci_name = clean_str(_val(row, "scientific_name"))
        if not sci_name:
            continue
        if sci_name in name_to_id:
            continue  # dedup by name

        taxon = Taxon(
            scientific_name=sci_name,
            genus=clean_str(_val(row, "genus")),
            species=clean_str(_val(row, "species")),
            family=clean_str(_val(row, "family")),
            taxon_rank=clean_str(_val(row, "taxon_rank")),
            iucn_status=clean_str(_val(row, "iucn_status")),
            is_synonym=_val(row, "is_synonym", "synonym") in ("True", "true", "1", "yes"),
            source_file=source_file,
            source_row=row_num,
        )
        session.add(taxon)
        session.flush()
        name_to_id[sci_name] = taxon.id

    return name_to_id


def ingest_locations(path: Path, session) -> dict[str, str]:
    """Returns mapping location_code → location.id."""
    code_to_id: dict[str, str] = {}
    rows = _read_csv(path)
    source_file = str(path)

    for row_num, row in enumerate(rows, start=2):
        code = clean_str(_val(row, "code", "location_code"))
        if not code or code in code_to_id:
            continue

        loc = Location(
            location_code=code,
            location_name=clean_str(_val(row, "name", "location_name")),
            description=clean_str(_val(row, "description")),
            source_file=source_file,
            source_row=row_num,
        )
        session.add(loc)
        session.flush()
        code_to_id[code] = loc.id

    return code_to_id


def ingest_sources(path: Path, session) -> dict[str, str]:
    """Returns mapping institution_name → source.id."""
    name_to_id: dict[str, str] = {}
    rows = _read_csv(path)
    source_file = str(path)

    for row_num, row in enumerate(rows, start=2):
        name = clean_str(_val(row, "institution_name", "source_name"))
        if not name or name in name_to_id:
            continue

        src = Source(
            source_name=name,
            source_type=clean_str(_val(row, "source_type")),
            contact=clean_str(_val(row, "contact")),
            notes=clean_str(_val(row, "description", "notes")),
            source_file=source_file,
            source_row=row_num,
        )
        session.add(src)
        session.flush()
        name_to_id[name] = src.id

    return name_to_id


def ingest_accessions(
    path: Path,
    session,
    taxon_map: dict[str, str],
    source_map: dict[str, str],
) -> dict[str, str]:
    """Returns mapping accession_number → accession.id (last seen wins for dupes)."""
    acc_to_id: dict[str, str] = {}
    rows = _read_csv(path)
    source_file = str(path)

    for row_num, row in enumerate(rows, start=2):
        raw_num = clean_str(_val(row, "accession_number"))
        if not raw_num:
            continue

        taxon_name = clean_str(_val(row, "taxon_scientific_name", "taxon_name"))
        taxon_id = taxon_map.get(taxon_name) if taxon_name else None

        acc_date_raw = _val(row, "accession_date")
        acc_date = parse_date(acc_date_raw)
        acc_year = parse_year(acc_date_raw or raw_num)

        acc = Accession(
            accession_number=raw_num,
            accession_number_normalized=normalize_accession_number(raw_num),
            taxon_id=taxon_id,
            taxon_name_verbatim=taxon_name,
            accession_date=acc_date,
            accession_year=acc_year,
            notes=clean_str(_val(row, "notes")),
            source_file=source_file,
            source_row=row_num,
        )
        session.add(acc)
        session.flush()
        acc_to_id[raw_num] = acc.id

        # Provenance record
        prov_code = clean_str(_val(row, "provenance_code"))
        src_desc = clean_str(_val(row, "source_description"))
        src_id = source_map.get(src_desc) if src_desc else None

        if prov_code or src_id:
            prov = Provenance(
                accession_id=acc.id,
                source_id=src_id,
                origin_code=prov_code,
                source_file=source_file,
                source_row=row_num,
            )
            session.add(prov)

    return acc_to_id


def ingest_items(
    path: Path,
    session,
    acc_to_id: dict[str, str],
    loc_to_id: dict[str, str],
) -> dict[tuple[str, str], str]:
    """Returns mapping (accession_number, suffix) → item.id."""
    item_map: dict[tuple[str, str], str] = {}
    rows = _read_csv(path)
    source_file = str(path)

    for row_num, row in enumerate(rows, start=2):
        raw_num = clean_str(_val(row, "accession_number"))
        suffix = clean_str(_val(row, "item_suffix", "item_number")) or "01"
        acc_id = acc_to_id.get(raw_num) if raw_num else None
        if not acc_id:
            continue

        loc_code = clean_str(_val(row, "current_location_code", "location_code"))
        loc_id = loc_to_id.get(loc_code) if loc_code else None

        life_status = clean_str(_val(row, "life_status")) or "unknown"
        planting_date = parse_date(_val(row, "planting_date"))
        removal_date = parse_date(_val(row, "removal_date"))

        item_label = f"{raw_num}.{suffix}" if raw_num else None

        item = Item(
            accession_id=acc_id,
            item_number=suffix,
            item_label=item_label,
            current_location_id=loc_id,
            life_status=life_status,
            is_current=life_status not in ("dead", "removed"),
            planting_date=planting_date,
            death_date=removal_date if life_status == "dead" else None,
            notes=clean_str(_val(row, "notes")),
            source_file=source_file,
            source_row=row_num,
        )
        session.add(item)
        session.flush()
        if raw_num:
            item_map[(raw_num, suffix)] = item.id

    return item_map


def ingest_events(
    path: Path,
    session,
    acc_to_id: dict[str, str],
    item_map: dict[tuple[str, str], str],
    loc_to_id: dict[str, str],
) -> int:
    rows = _read_csv(path)
    source_file = str(path)
    count = 0

    for row_num, row in enumerate(rows, start=2):
        raw_num = clean_str(_val(row, "accession_number"))
        suffix = clean_str(_val(row, "item_suffix")) or "01"
        acc_id = acc_to_id.get(raw_num) if raw_num else None
        item_id = item_map.get((raw_num, suffix)) if raw_num else None

        loc_code = clean_str(_val(row, "location_code"))
        loc_id = loc_to_id.get(loc_code) if loc_code else None

        event_date_raw = _val(row, "event_date")
        event_date = parse_date(event_date_raw)

        evt = Event(
            accession_id=acc_id,
            item_id=item_id,
            event_type=clean_str(_val(row, "event_type")),
            event_date=event_date,
            event_date_verbatim=event_date_raw,
            location_id=loc_id,
            location_verbatim=loc_code,
            notes=clean_str(_val(row, "notes")),
            source_file=source_file,
            source_row=row_num,
        )
        session.add(evt)
        count += 1

    return count


def ingest_conservation_status(
    path: Path, session, taxon_map: dict[str, str]
) -> int:
    rows = _read_csv(path)
    source_file = str(path)
    count = 0

    for row_num, row in enumerate(rows, start=2):
        taxon_name = clean_str(_val(row, "taxon_name", "scientific_name"))
        taxon_id = taxon_map.get(taxon_name) if taxon_name else None
        if not taxon_id:
            continue

        raw_date = _val(row, "assessment_date")
        year = parse_year(raw_date) if raw_date else None

        cs = ConservationStatus(
            taxon_id=taxon_id,
            authority=clean_str(_val(row, "status_source", "authority")),
            status_code=clean_str(_val(row, "conservation_status", "status_code")),
            assessment_year=year,
            source_file=source_file,
            source_row=row_num,
        )
        session.add(cs)
        count += 1

    return count


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def ingest_all_csvs(synthetic_dir: Path, db_url: str | None = None) -> dict[str, int]:
    counts: dict[str, int] = {}
    session = get_session(db_url)
    try:
        taxa_path = synthetic_dir / "taxa.csv"
        loc_path = synthetic_dir / "locations.csv"
        src_path = synthetic_dir / "sources.csv"
        acc_path = synthetic_dir / "accessions.csv"
        items_path = synthetic_dir / "items.csv"
        events_path = synthetic_dir / "events.csv"
        cs_path = synthetic_dir / "conservation_status.csv"

        taxon_map: dict[str, str] = {}
        if taxa_path.exists():
            taxon_map = ingest_taxa(taxa_path, session)
            counts["taxa"] = len(taxon_map)

        loc_map: dict[str, str] = {}
        if loc_path.exists():
            loc_map = ingest_locations(loc_path, session)
            counts["locations"] = len(loc_map)

        src_map: dict[str, str] = {}
        if src_path.exists():
            src_map = ingest_sources(src_path, session)
            counts["sources"] = len(src_map)

        acc_map: dict[str, str] = {}
        if acc_path.exists():
            acc_map = ingest_accessions(acc_path, session, taxon_map, src_map)
            counts["accessions"] = len(acc_map)

        item_map: dict[tuple[str, str], str] = {}
        if items_path.exists():
            item_map = ingest_items(items_path, session, acc_map, loc_map)
            counts["items"] = len(item_map)

        if events_path.exists():
            counts["events"] = ingest_events(events_path, session, acc_map, item_map, loc_map)

        if cs_path.exists():
            counts["conservation_statuses"] = ingest_conservation_status(cs_path, session, taxon_map)

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return counts
