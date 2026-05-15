"""Ingest IrisBG CSV exports into the BEN-0 database."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ben0.db.models import Accession, Event, Item, Location, Provenance, Source, Taxon
from ben0.db.session import get_session
from ben0.ingest.encoding import read_csv_safe
from ben0.ingest.normalize import (
    clean_int,
    clean_location_code,
    clean_str,
    normalize_accession_number,
    parse_date,
    parse_year,
)

ACCESSION_FILENAME = "accession_history.csv"
ITEM_FILENAME = "accession_item_history.csv"
_SENTINEL_DATES = {"12/31/9999", "9999-12-31", "9999/12/31"}

_REQUIRED_ACCESSION_HEADERS = {"AccNoFull", "TaxonName", "AccYear"}
_REQUIRED_ITEM_HEADERS = {"AccNoFull", "ItemAccNoFull", "ItemStatus"}

_ORIGIN_MAP = {
    "W": "wild",
    "Z": "wildNative",
    "G": "cultivated",
    "U": "unknown",
}

_STATUS_MAP = {
    "P": ("living", "planted"),
    "PLANTED": ("living", "planted"),
    "D": ("dead", "dead"),
    "DEAD": ("dead", "dead"),
    "R": ("removed", "removed"),
    "REMOVED": ("removed", "removed"),
}


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]], dict[int, int]]:
    fieldnames, rows = read_csv_safe(path)
    row_numbers = {idx: idx + 2 for idx in range(len(rows))}
    return fieldnames, rows, row_numbers


def _val(row: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _truthy(value: str | None) -> bool:
    normalized = (value or "").strip().lower()
    return normalized in {"1", "true", "yes", "y", "t", ">>>"}


def _parse_iris_date(raw: str | None) -> str | None:
    value = clean_str(raw)
    if not value or value in _SENTINEL_DATES:
        return None
    if "/" in value:
        try:
            return datetime.strptime(value, "%m/%d/%Y").date().isoformat()
        except ValueError:
            pass
    return parse_date(value)


def _date_sort_key(raw: str | None, row_num: int) -> tuple[str, int]:
    parsed = _parse_iris_date(raw) or ""
    return parsed, row_num


def _origin_code(value: str | None) -> str:
    return (clean_str(value) or "U").upper()


def _establishment_means(origin_code: str | None) -> str:
    return _ORIGIN_MAP.get((origin_code or "U").upper(), "unknown")


def _life_status(status_code: str | None, status_name: str | None) -> str:
    normalized_code = (status_code or "").strip().upper()
    if normalized_code in _STATUS_MAP:
        return _STATUS_MAP[normalized_code][0]

    normalized_name = (status_name or "").strip().upper()
    if normalized_name in _STATUS_MAP:
        return _STATUS_MAP[normalized_name][0]

    lowered = (status_name or "").strip().lower()
    if lowered in {"living", "alive", "current", "existing"}:
        return "living"
    if lowered in {"dead", "removed"}:
        return lowered
    return "unknown"


def _event_type(status_code: str | None, status_name: str | None) -> str:
    normalized_code = (status_code or "").strip().upper()
    if normalized_code in _STATUS_MAP:
        return _STATUS_MAP[normalized_code][1]

    normalized_name = (status_name or "").strip().upper()
    if normalized_name in _STATUS_MAP:
        return _STATUS_MAP[normalized_name][1]

    return (clean_str(status_name) or "status_update").strip().lower().replace(" ", "_")


def _join_notes(*parts: tuple[str, str | None]) -> str | None:
    chunks: list[str] = []
    for label, value in parts:
        cleaned = clean_str(value)
        if cleaned:
            if label:
                chunks.append(f"{label}: {cleaned}")
            else:
                chunks.append(cleaned)
    if not chunks:
        return None
    return "\n".join(chunks)


def _detect_iris_headers(data_dir: Path) -> None:
    accession_path = data_dir / ACCESSION_FILENAME
    item_path = data_dir / ITEM_FILENAME
    if not accession_path.exists() or not item_path.exists():
        raise FileNotFoundError(
            f"Expected {ACCESSION_FILENAME} and {ITEM_FILENAME} in {data_dir}."
        )

    accession_headers, _, _ = _read_csv(accession_path)
    item_headers, _, _ = _read_csv(item_path)
    if not _REQUIRED_ACCESSION_HEADERS.issubset(set(accession_headers)):
        raise ValueError(f"{ACCESSION_FILENAME} does not look like an IrisBG accession export.")
    if not _REQUIRED_ITEM_HEADERS.issubset(set(item_headers)):
        raise ValueError(f"{ITEM_FILENAME} does not look like an IrisBG item export.")


def ingest_iris_csvs(data_dir: Path, db_url: str | None = None) -> dict[str, int]:
    """Ingest paired IrisBG accession and item history CSVs."""
    _detect_iris_headers(data_dir)

    accession_path = data_dir / ACCESSION_FILENAME
    item_path = data_dir / ITEM_FILENAME
    accession_headers, accession_rows, accession_row_numbers = _read_csv(accession_path)
    item_headers, item_rows, item_row_numbers = _read_csv(item_path)
    del accession_headers, item_headers

    counts: dict[str, int] = {}
    session = get_session(db_url)
    try:
        taxon_map: dict[str, str] = {}
        for idx, row in enumerate(accession_rows):
            scientific_name = clean_str(_val(row, "TaxonName"))
            if not scientific_name or scientific_name in taxon_map:
                continue

            source_row = accession_row_numbers[idx]
            family = clean_str(_val(row, "FamilyEx", "Family"))
            infra_rank = clean_str(_val(row, "InfraType1", "InfraType2"))
            infra_epithet = clean_str(_val(row, "InfraName1", "InfraName2"))
            cultivar = clean_str(_val(row, "Cultivar", "CultivarGroup"))
            taxon_rank = infra_rank or ("cultivar" if cultivar else "species")

            taxon = Taxon(
                scientific_name=scientific_name,
                genus=clean_str(_val(row, "Genus")),
                species=clean_str(_val(row, "Species")),
                family=family,
                infraspecific_rank=infra_rank,
                infraspecific_epithet=infra_epithet,
                cultivar_name=cultivar,
                taxon_rank=taxon_rank,
                iucn_status=clean_str(_val(row, "IUCNRedListCode", "IUCNRedList")),
                source_file=str(accession_path),
                source_row=source_row,
            )
            session.add(taxon)
            session.flush()
            taxon_map[scientific_name] = taxon.id
        counts["taxa"] = len(taxon_map)

        location_map: dict[str, str] = {}
        for idx, row in enumerate(item_rows):
            raw_location_code = clean_str(_val(row, "ItemLocationCode"))
            location_code = clean_location_code(raw_location_code)
            if not location_code or location_code in location_map:
                continue
            source_row = item_row_numbers[idx]
            location = Location(
                location_code=location_code,
                location_name=clean_str(_val(row, "ItemLocationName")),
                notes=(
                    _join_notes(("Raw location code", raw_location_code))
                    if raw_location_code and raw_location_code != location_code
                    else None
                ),
                source_file=str(item_path),
                source_row=source_row,
            )
            session.add(location)
            session.flush()
            location_map[location_code] = location.id
        counts["locations"] = len(location_map)

        source_map: dict[str, str] = {}
        for idx, row in enumerate(accession_rows):
            source_name = clean_str(_val(row, "ContactNameFull"))
            source_code = clean_str(_val(row, "ContactCode"))
            source_key = source_code or (source_name or "").lower()
            if not source_key or source_key in source_map:
                continue
            source_row = accession_row_numbers[idx]
            source = Source(
                source_code=source_code,
                source_name=source_name,
                source_type="institution",
                notes=_join_notes(("Contact code", source_code)) if source_code and not source_name else None,
                source_file=str(accession_path),
                source_row=source_row,
            )
            session.add(source)
            session.flush()
            source_map[source_key] = source.id
        counts["sources"] = len(source_map)

        accession_map: dict[str, str] = {}
        for idx, row in enumerate(accession_rows):
            accession_number = clean_str(_val(row, "AccNoFull"))
            if not accession_number:
                continue
            source_row = accession_row_numbers[idx]
            scientific_name = clean_str(_val(row, "TaxonName"))
            origin_code = _origin_code(_val(row, "ProvenanceCode"))
            source_name = clean_str(_val(row, "ContactNameFull"))
            source_code = clean_str(_val(row, "ContactCode"))
            source_key = source_code or (source_name or "").lower()

            accession_notes = _join_notes(
                ("Accession comment", _val(row, "AccComment")),
                ("Taxon name full", _val(row, "TaxonNameFull")),
                ("Determination taxon", _val(row, "DetTaxonName")),
                ("Determination date", _val(row, "DetDate")),
                ("Determination type", _val(row, "DetType")),
                ("Register date", _val(row, "RegisterDate")),
                ("Registered by", _val(row, "RegisterName")),
                ("CITES", _val(row, "CITESCat")),
            )

            accession = Accession(
                accession_number=accession_number,
                accession_number_normalized=normalize_accession_number(accession_number),
                taxon_id=taxon_map.get(scientific_name) if scientific_name else None,
                taxon_name_verbatim=clean_str(_val(row, "TaxonNameFull", "TaxonName")),
                accession_date=_parse_iris_date(_val(row, "RecDate")),
                accession_year=clean_int(_val(row, "AccYear")) or parse_year(_val(row, "RecDate")) or parse_year(accession_number),
                material_type=clean_str(_val(row, "MaterialType")),
                notes=accession_notes,
                is_sensitive=_truthy(_val(row, "RestrictPublish")) or _truthy(_val(row, "TaxonRestrictPublish")),
                source_file=str(accession_path),
                source_row=source_row,
            )
            session.add(accession)
            session.flush()
            accession_map[accession_number] = accession.id

            provenance_notes = _join_notes(
                ("Coordinates", ", ".join(part for part in [clean_str(_val(row, "CoordLatDD")), clean_str(_val(row, "CoordLongDD"))] if part) or None),
                ("Habitat", _val(row, "Habitat")),
            )
            provenance = Provenance(
                accession_id=accession.id,
                source_id=source_map.get(source_key),
                origin_code=origin_code,
                establishment_means=_establishment_means(origin_code),
                collection_country=clean_str(_val(row, "CountryName")),
                collection_locality=clean_str(_val(row, "LocalityFull", "Locality")),
                collection_date=_parse_iris_date(_val(row, "CollDate")),
                collector=clean_str(_val(row, "Collector")),
                collection_notes=provenance_notes,
                source_file=str(accession_path),
                source_row=source_row,
            )
            session.add(provenance)
        counts["accessions"] = len(accession_map)

        item_histories: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for idx, row in enumerate(item_rows):
            accession_number = clean_str(_val(row, "AccNoFull"))
            item_number = clean_str(_val(row, "ItemNo"))
            if not item_number:
                # Extract from ItemAccNoFull (e.g. "1952-0001.01" → "01")
                item_acc = clean_str(_val(row, "ItemAccNoFull")) or ""
                if "." in item_acc:
                    item_number = item_acc.rsplit(".", 1)[1]
            if not accession_number or not item_number:
                continue
            accession_id = accession_map.get(accession_number)
            if not accession_id:
                continue

            source_row = item_row_numbers[idx]
            raw_location_code = clean_str(_val(row, "ItemLocationCode"))
            location_code = clean_location_code(raw_location_code)
            normalized = {
                "accession_number": accession_number,
                "accession_id": accession_id,
                "item_number": item_number,
                "item_label": clean_str(_val(row, "ItemAccNoFull")) or f"{accession_number}.{str(item_number).zfill(2)}",
                "life_status": _life_status(_val(row, "ItemStatusCode"), _val(row, "ItemStatus")),
                "event_type": _event_type(_val(row, "ItemStatusCode"), _val(row, "ItemStatus")),
                "event_date": _parse_iris_date(_val(row, "ItemStatusDate", "ItemStatusDateFrom")),
                "event_date_verbatim": _val(row, "ItemStatusDate", "ItemStatusDateFrom"),
                "status_to": _parse_iris_date(_val(row, "ItemStatusDateTo")),
                "location_code": location_code,
                "location_code_raw": raw_location_code,
                "location_id": location_map.get(location_code) if location_code else None,
                "location_name": clean_str(_val(row, "ItemLocationName")),
                "notes": _join_notes(
                    ("Item comment", _val(row, "ItemComment")),
                    ("Condition", _val(row, "ItemCondition")),
                    ("Status type", _val(row, "ItemStatusType")),
                ),
                "operator": clean_str(_val(row, "ItemStatusPerson")),
                "propagation_notes": _join_notes(
                    ("Propagation history code", _val(row, "PropHistCode")),
                    ("Propagation comment", _val(row, "PropComment")),
                    ("Propagation container", _val(row, "PropContainer")),
                    ("Propagation medium", _val(row, "PropMedium")),
                    ("Propagation treatment", _val(row, "PropTreatment")),
                    ("Propagation quantity", _val(row, "PropQuantity")),
                ),
                "is_current_row": _truthy(_val(row, "Current"))
                or (clean_str(_val(row, "ItemStatusType")) or "").lower() == "existing"
                or clean_str(_val(row, "ItemStatusDateTo")) in _SENTINEL_DATES,
                "source_row": source_row,
            }
            item_histories[(accession_number, item_number)].append(normalized)

        item_map: dict[tuple[str, str], str] = {}
        for key, history in item_histories.items():
            accession_number, item_number = key
            history.sort(key=lambda row: _date_sort_key(row["event_date_verbatim"], row["source_row"]))
            current_rows = [row for row in history if row["is_current_row"]]
            representative = current_rows[-1] if current_rows else history[-1]
            life_status = representative["life_status"]
            if life_status == "unknown" and history:
                life_status = history[-1]["life_status"]

            planting_dates = [
                row["event_date"]
                for row in history
                if row["event_type"] == "planted" and row["event_date"]
            ]
            death_dates = [
                row["event_date"]
                for row in history
                if row["life_status"] == "dead" and row["event_date"]
            ]
            notes = "\n\n".join(
                part for part in dict.fromkeys(row["notes"] for row in history if row["notes"]).keys()
            ) or None
            is_current = bool(representative["is_current_row"] and life_status not in {"dead", "removed"})

            item = Item(
                accession_id=representative["accession_id"],
                item_number=item_number,
                item_label=representative["item_label"],
                current_location_id=representative["location_id"] if is_current else None,
                life_status=life_status,
                is_current=is_current,
                planting_date=min(planting_dates) if planting_dates else None,
                death_date=max(death_dates) if death_dates else None,
                notes=notes,
                source_file=str(item_path),
                source_row=representative["source_row"],
            )
            session.add(item)
            session.flush()
            item_map[key] = item.id
        counts["items"] = len(item_map)

        event_count = 0
        for history in item_histories.values():
            for row in history:
                event = Event(
                    accession_id=row["accession_id"],
                    item_id=item_map[(row["accession_number"], row["item_number"])],
                    event_type=row["event_type"],
                    event_date=row["event_date"],
                    event_date_verbatim=row["event_date_verbatim"],
                    location_id=row["location_id"],
                    location_verbatim=row["location_code_raw"] or row["location_code"] or row["location_name"],
                    operator=row["operator"],
                    notes=row["notes"],
                    source_file=str(item_path),
                    source_row=row["source_row"],
                )
                session.add(event)
                event_count += 1

                if row["propagation_notes"]:
                    propagation_event = Event(
                        accession_id=row["accession_id"],
                        item_id=item_map[(row["accession_number"], row["item_number"])],
                        event_type="propagation",
                        event_date=row["event_date"],
                        event_date_verbatim=row["event_date_verbatim"],
                        location_id=row["location_id"],
                        location_verbatim=row["location_code"] or row["location_name"],
                        operator=row["operator"],
                        notes=row["propagation_notes"],
                        source_file=str(item_path),
                        source_row=row["source_row"],
                    )
                    session.add(propagation_event)
                    event_count += 1
        counts["events"] = event_count

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return counts
