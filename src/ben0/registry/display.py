"""Formatting helpers for field registry CLI output."""

from __future__ import annotations

from collections import Counter

from ben0.registry.schema import FieldEntry, FieldRegistry, TierName


def filter_fields(registry: FieldRegistry, tier: TierName | None = None) -> list[FieldEntry]:
    fields = registry.fields
    if tier is not None:
        fields = [entry for entry in fields if entry.tier == tier]
    return sorted(fields, key=lambda entry: entry.column.lower())


def format_registry(registry: FieldRegistry, *, tier: TierName | None = None, show_stats: bool = False) -> str:
    lines: list[str] = []
    for entry in filter_fields(registry, tier=tier):
        base = f"{entry.column} [{entry.tier}] {entry.data_type} :: {entry.description}"
        if entry.missing:
            base += " (missing)"
        lines.append(base)
        lines.append(f"  source: {entry.source_file}")
        lines.append(f"  db: {entry.db_mapping or '-'}")
        if entry.sample_values:
            lines.append(f"  samples: {', '.join(entry.sample_values)}")
        if show_stats:
            lines.append(
                f"  stats: null_rate={entry.null_rate:.2f} unique_rate={entry.unique_rate:.2f}"
            )
        if entry.notes:
            lines.append(f"  notes: {entry.notes}")
    return "\n".join(lines)


def format_registry_stats(registry: FieldRegistry) -> str:
    counts = Counter(entry.tier for entry in registry.fields)
    total = len(registry.fields)
    return (
        f"fields={total} "
        f"core={counts.get('core', 0)} "
        f"useful={counts.get('useful', 0)} "
        f"niche={counts.get('niche', 0)} "
        f"skip={counts.get('skip', 0)}"
    )
