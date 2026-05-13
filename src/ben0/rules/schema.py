"""Schema for authoritative YAML rule files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class RuleFile:
    id: str
    name: str
    description: str
    tags: list[str]
    domain: str
    priority: int = 10
    pinned: bool = False
    content: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None

    @classmethod
    def from_yaml(cls, path: Path) -> "RuleFile":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Rule file {path} did not contain a YAML mapping")

        missing = [key for key in ("id", "name", "description", "tags", "domain", "content") if key not in data]
        if missing:
            raise ValueError(f"Rule file {path} missing required fields: {', '.join(missing)}")

        tags = data["tags"]
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError(f"Rule file {path} has invalid tags; expected list[str]")

        content = data["content"]
        if not isinstance(content, dict):
            raise ValueError(f"Rule file {path} has invalid content; expected mapping")

        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            description=str(data["description"]),
            tags=tags,
            domain=str(data["domain"]),
            priority=int(data.get("priority", 10)),
            pinned=bool(data.get("pinned", False)),
            content=content,
            source_path=path,
        )

    def to_yaml(self) -> str:
        payload = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "domain": self.domain,
            "priority": self.priority,
            "pinned": self.pinned,
            "content": self.content,
        }
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
