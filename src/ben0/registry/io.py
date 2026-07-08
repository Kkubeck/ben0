"""Read, write, and merge field registry YAML files."""

from __future__ import annotations

from pathlib import Path

from ben0.registry.schema import FieldEntry, FieldRegistry


def registry_path_for_garden(garden_root: Path) -> Path:
    return garden_root / "field_registry.yaml"


def load_registry(path: Path) -> FieldRegistry | None:
    if not path.exists():
        return None
    return FieldRegistry.from_yaml(path)


def save_registry(path: Path, registry: FieldRegistry) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(registry.to_yaml(), encoding="utf-8")


def merge_registry(existing: FieldRegistry | None, fresh: FieldRegistry) -> FieldRegistry:
    if existing is None:
        return fresh

    existing_by_column = {entry.column: entry for entry in existing.fields}
    fresh_by_column = {entry.column: entry for entry in fresh.fields}
    merged_fields: list[FieldEntry] = []

    for column in sorted(fresh_by_column):
        fresh_entry = fresh_by_column[column]
        prior = existing_by_column.get(column)
        if prior is None:
            merged_fields.append(fresh_entry)
            continue
        merged_fields.append(
            FieldEntry(
                column=fresh_entry.column,
                source_file=fresh_entry.source_file,
                data_type=fresh_entry.data_type,
                description=prior.description or fresh_entry.description,
                tier=prior.tier,
                db_mapping=prior.db_mapping if prior.db_mapping is not None else fresh_entry.db_mapping,
                sample_values=fresh_entry.sample_values,
                null_rate=fresh_entry.null_rate,
                unique_rate=fresh_entry.unique_rate,
                notes=prior.notes or fresh_entry.notes,
                missing=False,
            )
        )

    for column in sorted(existing_by_column):
        if column in fresh_by_column:
            continue
        prior = existing_by_column[column]
        merged_fields.append(
            FieldEntry(
                column=prior.column,
                source_file=prior.source_file,
                data_type=prior.data_type,
                description=prior.description,
                tier=prior.tier,
                db_mapping=prior.db_mapping,
                sample_values=prior.sample_values,
                null_rate=prior.null_rate,
                unique_rate=prior.unique_rate,
                notes=_append_missing_note(prior.notes),
                missing=True,
            )
        )

    merged_fields.sort(key=lambda entry: entry.column.lower())
    return FieldRegistry(
        version=fresh.version,
        source_format=fresh.source_format,
        generated_at=fresh.generated_at,
        reviewed=existing.reviewed,
        fields=merged_fields,
        source_path=existing.source_path,
    )


def _append_missing_note(notes: str) -> str:
    marker = "Missing from latest CSV scan."
    if marker in notes:
        return notes
    if not notes:
        return marker
    return f"{notes} {marker}"
