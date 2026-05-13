"""Basic sensitivity-aware export for BEN-0."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ben0.db.models import Accession

BLOCKED_LEVELS = {"restricted", "culturally_sensitive", "unknown"}
BLOCKED_SHARING = {"not_allowed", "review_required"}
LEVEL_PRIORITY = {
    "public": 0,
    "internal": 1,
    "unknown": 2,
    "restricted": 3,
    "culturally_sensitive": 4,
}


def export_accessions(session: Session, output_path: Path, *, include_sensitive: bool = False) -> dict[str, int | str]:
    accessions = session.scalars(
        select(Accession).options(
            selectinload(Accession.taxon),
            selectinload(Accession.items),
            selectinload(Accession.provenances),
            selectinload(Accession.sensitive_flags),
        ).order_by(Accession.accession_number)
    ).all()

    exported: list[dict] = []
    skipped = 0

    for accession in accessions:
        effective_level, effective_sharing = _effective_sensitivity(accession)
        if not include_sensitive and (
            effective_level in BLOCKED_LEVELS or effective_sharing in BLOCKED_SHARING
        ):
            skipped += 1
            continue

        exported.append(
            {
                "accession_id": accession.id,
                "accession_number": accession.accession_number,
                "accession_date": accession.accession_date,
                "taxon_name": accession.taxon.scientific_name if accession.taxon else accession.taxon_name_verbatim,
                "material_type": accession.material_type,
                "notes": accession.notes,
                "is_sensitive": accession.is_sensitive,
                "sensitivity_level": effective_level,
                "sharing_allowed": effective_sharing,
                "items": [
                    {
                        "item_id": item.id,
                        "item_label": item.item_label,
                        "life_status": item.life_status,
                        "current_location_id": item.current_location_id,
                    }
                    for item in accession.items
                ],
                "provenance": [
                    {
                        "provenance_id": provenance.id,
                        "origin_code": provenance.origin_code,
                        "source_id": provenance.source_id,
                        "collection_locality": provenance.collection_locality,
                        "information_withheld": provenance.information_withheld,
                    }
                    for provenance in accession.provenances
                ],
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(exported, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "exported": len(exported),
        "skipped": skipped,
        "path": str(output_path),
    }


def _effective_sensitivity(accession: Accession) -> tuple[str, str]:
    if accession.sensitive_flags:
        level = max(
            (flag.sensitivity_level for flag in accession.sensitive_flags),
            key=lambda value: LEVEL_PRIORITY.get(value, 1),
        )
        if any(flag.sharing_allowed == "not_allowed" for flag in accession.sensitive_flags):
            sharing = "not_allowed"
        elif any(flag.sharing_allowed == "review_required" for flag in accession.sensitive_flags):
            sharing = "review_required"
        else:
            sharing = "allowed"
        return level, sharing

    if accession.is_sensitive:
        return "unknown", "review_required"
    return "internal", "allowed"
