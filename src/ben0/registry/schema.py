"""Data definitions for field registry YAML files."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml

# A TierName ranks a source field by how often BEN-0 should expose it to tools.
# core means always visible, useful means topic-relevant, niche means explicit
# request only, skip means hidden unless reviewed directly.
TierName = Literal["core", "useful", "niche", "skip"]


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class FieldEntry:
    """A FieldEntry describes one deduplicated source column."""

    column: str
    source_file: str
    data_type: str
    description: str
    tier: TierName
    db_mapping: str | None
    sample_values: list[str] = field(default_factory=list)
    null_rate: float = 0.0
    unique_rate: float = 0.0
    notes: str = ""
    missing: bool = False

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "column": self.column,
            "source_file": self.source_file,
            "data_type": self.data_type,
            "description": self.description,
            "tier": self.tier,
            "db_mapping": self.db_mapping,
            "sample_values": self.sample_values,
            "null_rate": round(self.null_rate, 4),
            "unique_rate": round(self.unique_rate, 4),
            "notes": self.notes,
        }
        if self.missing:
            payload["missing"] = True
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "FieldEntry":
        return cls(
            column=str(data["column"]),
            source_file=str(data["source_file"]),
            data_type=str(data.get("data_type", "string")),
            description=str(data.get("description", "")),
            tier=_coerce_tier(data.get("tier")),
            db_mapping=_coerce_optional_str(data.get("db_mapping")),
            sample_values=[str(item) for item in data.get("sample_values", []) or []],
            null_rate=float(data.get("null_rate", 0.0)),
            unique_rate=float(data.get("unique_rate", 0.0)),
            notes=str(data.get("notes", "")),
            missing=bool(data.get("missing", False)),
        )


@dataclass(slots=True)
class FieldRegistry:
    """A FieldRegistry is the full YAML document for one garden."""

    version: int = 1
    source_format: str = "irisBG"
    generated_at: str = field(default_factory=_timestamp_now)
    reviewed: bool = False
    fields: list[FieldEntry] = field(default_factory=list)
    source_path: Path | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "source_format": self.source_format,
            "generated_at": self.generated_at,
            "reviewed": self.reviewed,
            "fields": [entry.to_dict() for entry in self.fields],
        }

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_yaml(cls, path: Path) -> "FieldRegistry":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Registry file {path} did not contain a YAML mapping")

        fields_raw = data.get("fields", [])
        if not isinstance(fields_raw, list):
            raise ValueError(f"Registry file {path} has invalid fields, expected a list")

        registry = cls(
            version=int(data.get("version", 1)),
            source_format=str(data.get("source_format", "irisBG")),
            generated_at=str(data.get("generated_at", _timestamp_now())),
            reviewed=bool(data.get("reviewed", False)),
            fields=[FieldEntry.from_dict(item) for item in fields_raw],
            source_path=path,
        )
        registry.fields.sort(key=lambda entry: entry.column.lower())
        return registry
def _coerce_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_tier(value: object) -> TierName:
    text = str(value or "useful").strip().lower()
    if text not in {"core", "useful", "niche", "skip"}:
        return "useful"
    return text  # type: ignore[return-value]
