"""Bootstrap field registry entries from source CSV files."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import re

from ben0.ingest.encoding import read_csv_safe
from ben0.registry.schema import FieldEntry, FieldRegistry, TierName

# A ColumnScan accumulates observations for one deduplicated column across
# one or more CSV files.
@dataclass(slots=True)
class ColumnScan:
    column: str
    source_files: set[str] = field(default_factory=set)
    non_null_count: int = 0
    total_count: int = 0
    distinct_values: set[str] = field(default_factory=set)
    sample_values: list[str] = field(default_factory=list)
    bool_like: bool = True
    int_like: bool = True
    float_like: bool = True
    date_like: bool = True


_CORE_KEYWORDS = (
    "accno",
    "taxon",
    "item",
    "location",
    "provenance",
    "prop",
    "cites",
    "iucn",
    "conservation",
)
_NICHE_KEYWORDS = ("commonname_", "vernacular", "phonetic", "kana", "lang")
_SKIP_KEYWORDS = ("guid", "timestamp", "modifiedby", "createdby", "checksum")
_PROPAGATION_PREFIXES = {
    "PropComment",
    "PropContainer",
    "PropMedium",
    "PropTreatment",
    "PropQuantity",
    "PropEnvironment",
    "PropDuration",
    "PropFailure",
}
_DB_MAPPING_HINTS = {
    "AccNoFull": "accession.accession_number",
    "AccYear": "accession.accession_year",
    "RecDate": "accession.accession_date",
    "TaxonName": "taxon.scientific_name",
    "TaxonNameFull": "accession.taxon_name_verbatim",
    "Genus": "taxon.genus",
    "Species": "taxon.species",
    "Family": "taxon.family",
    "FamilyEx": "taxon.family",
    "Cultivar": "taxon.cultivar_name",
    "IUCNRedList": "taxon.iucn_status",
    "IUCNRedListCode": "taxon.iucn_status",
    "ContactNameFull": "source.source_name",
    "ContactCode": "source.source_code",
    "ProvenanceCode": "provenance.origin_code",
    "CollDate": "provenance.collection_date",
    "CollLocality": "provenance.collection_locality",
    "CollCountry": "provenance.collection_country",
    "CollCollector": "provenance.collector",
    "ItemAccNoFull": "item.item_label",
    "ItemStatus": "item.life_status",
    "ItemLocationCode": "location.location_code",
    "ItemLocationName": "location.location_name",
    "PlantingDate": "item.planting_date",
    "DeathDate": "item.death_date",
    "CITESCat": "accession.notes (packed)",
}
_WORD_OVERRIDES = {
    "acc": "accession",
    "no": "number",
    "taxon": "taxon",
    "item": "item",
    "rec": "received",
    "coll": "collection",
    "prop": "propagation",
    "loc": "location",
    "cites": "CITES",
    "iucn": "IUCN",
}


def bootstrap_registry(csv_paths: list[Path], *, source_format: str = "irisBG") -> FieldRegistry:
    scans = _scan_columns(csv_paths)
    fields = [_scan_to_entry(scan) for scan in scans]
    fields.sort(key=lambda entry: entry.column.lower())
    return FieldRegistry(source_format=source_format, fields=fields)


def _scan_columns(csv_paths: list[Path]) -> list[ColumnScan]:
    scans: dict[str, ColumnScan] = {}
    for csv_path in csv_paths:
        headers, rows = read_csv_safe(csv_path)
        for header in headers:
            scan = scans.setdefault(header, ColumnScan(column=header))
            scan.source_files.add(csv_path.name)
        for row in rows:
            for header in headers:
                scan = scans[header]
                value = str(row.get(header, "") or "").strip()
                scan.total_count += 1
                if not value:
                    continue
                scan.non_null_count += 1
                scan.distinct_values.add(value)
                if value not in scan.sample_values and len(scan.sample_values) < 5:
                    scan.sample_values.append(value)
                scan.bool_like = scan.bool_like and _looks_like_bool(value)
                scan.int_like = scan.int_like and _looks_like_int(value)
                scan.float_like = scan.float_like and _looks_like_float(value)
                scan.date_like = scan.date_like and _looks_like_date(value)
    return list(scans.values())


def _scan_to_entry(scan: ColumnScan) -> FieldEntry:
    null_rate = 1.0
    if scan.total_count:
        null_rate = 1 - (scan.non_null_count / scan.total_count)
    unique_rate = 0.0
    if scan.non_null_count:
        unique_rate = len(scan.distinct_values) / scan.non_null_count

    return FieldEntry(
        column=scan.column,
        source_file=", ".join(sorted(scan.source_files)),
        data_type=_infer_data_type(scan),
        description=_describe_column(scan.column),
        tier=_suggest_tier(scan.column),
        db_mapping=_infer_db_mapping(scan.column),
        sample_values=scan.sample_values,
        null_rate=null_rate,
        unique_rate=unique_rate,
        notes=_bootstrap_notes(scan),
    )


def _infer_data_type(scan: ColumnScan) -> str:
    if scan.non_null_count == 0:
        return "string"
    if scan.bool_like:
        return "boolean"
    if scan.int_like:
        return "integer"
    if scan.float_like:
        return "float"
    if scan.date_like:
        return "date"
    return "string"


def _suggest_tier(column: str) -> TierName:
    if column in _PROPAGATION_PREFIXES:
        return "core"
    lowered = column.lower()
    if any(keyword in lowered for keyword in _SKIP_KEYWORDS):
        return "skip"
    if any(keyword in lowered for keyword in ("cites", "iucn", "conservation")):
        return "core"
    if any(keyword in lowered for keyword in _CORE_KEYWORDS):
        return "core"
    if any(keyword in lowered for keyword in _NICHE_KEYWORDS):
        return "niche"
    if lowered.endswith("comment") or lowered.endswith("remarks"):
        return "useful"
    return "useful"


def _infer_db_mapping(column: str) -> str | None:
    if column in _DB_MAPPING_HINTS:
        return _DB_MAPPING_HINTS[column]
    lowered = column.lower()
    if lowered.startswith("item"):
        return "item.notes (unmapped)"
    if lowered.startswith("prop"):
        return "event.notes (packed)"
    if lowered.startswith("commonname"):
        return None
    return None


def _bootstrap_notes(scan: ColumnScan) -> str:
    notes: list[str] = []
    if len(scan.source_files) > 1:
        notes.append(f"Appears in multiple exports: {', '.join(sorted(scan.source_files))}.")
    mapping = _infer_db_mapping(scan.column)
    if mapping and "(packed)" in mapping:
        notes.append("Currently packed into notes instead of a dedicated column.")
    return " ".join(notes)


def _describe_column(column: str) -> str:
    if column in _DB_MAPPING_HINTS:
        descriptions = {
            "AccNoFull": "Full accession number used as the primary accession identifier.",
            "AccYear": "Year the accession was received or recorded.",
            "RecDate": "Date the accession was received.",
            "TaxonName": "Current scientific name recorded for the accession.",
            "TaxonNameFull": "Full verbatim taxon string from the source export.",
            "Genus": "Genus portion of the taxon name.",
            "Species": "Species epithet portion of the taxon name.",
            "Family": "Plant family assigned to the taxon.",
            "FamilyEx": "Plant family assigned to the taxon.",
            "Cultivar": "Cultivar name associated with the taxon.",
            "IUCNRedList": "IUCN Red List status for the taxon.",
            "IUCNRedListCode": "IUCN Red List status code for the taxon.",
            "ContactNameFull": "Source institution or donor name tied to the accession.",
            "ContactCode": "Source institution or donor code tied to the accession.",
            "ProvenanceCode": "Origin code for the accession provenance record.",
            "CollDate": "Collection date for wild or source material.",
            "CollLocality": "Collection locality for wild or source material.",
            "CollCountry": "Collection country for the provenance record.",
            "CollCollector": "Collector or collecting party for the provenance record.",
            "ItemAccNoFull": "Full item identifier, usually accession number plus item suffix.",
            "ItemStatus": "Current or historical life status of the item.",
            "ItemLocationCode": "Location code where the item is or was recorded.",
            "ItemLocationName": "Human-readable location name for the item.",
            "PlantingDate": "Date the item was planted.",
            "DeathDate": "Date the item was recorded as dead or removed.",
            "CITESCat": "CITES appendix or trade restriction category for the taxon.",
        }
        return descriptions[column]

    words = _split_identifier(column)
    if not words:
        return f"Source field {column} from the IrisBG export."
    phrase = " ".join(words)
    return f"Source field for {phrase} from the IrisBG export."


def _split_identifier(value: str) -> list[str]:
    raw_parts = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+", value)
    words: list[str] = []
    for part in raw_parts:
        lowered = part.lower()
        words.append(_WORD_OVERRIDES.get(lowered, lowered))
    return words


def _looks_like_bool(value: str) -> bool:
    return value.strip().lower() in {"0", "1", "true", "false", "yes", "no", "y", "n"}


def _looks_like_int(value: str) -> bool:
    return re.fullmatch(r"[+-]?\d+", value.strip()) is not None


def _looks_like_float(value: str) -> bool:
    return re.fullmatch(r"[+-]?(?:\d+\.\d+|\d+)", value.strip()) is not None


def _looks_like_date(value: str) -> bool:
    text = value.strip()
    return bool(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}", text)
        or re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", text)
        or re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", text)
    )
