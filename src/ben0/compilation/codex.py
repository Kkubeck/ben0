"""Codex entry storage helpers for generated retrieval knowledge."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class CodexEntry:
    topic_id: str
    title: str
    domain: str
    definition: str
    working_rule: str
    known_exceptions: str
    do_not_infer: str
    source_evidence: list[dict[str, str]]
    generated_by: str
    generated_on: str
    review_status: str
    pinned: bool

    def to_markdown(self) -> str:
        frontmatter = {
            "topic_id": self.topic_id,
            "title": self.title,
            "domain": self.domain,
            "generated_by": self.generated_by,
            "generated_on": self.generated_on,
            "review_status": self.review_status,
            "pinned": self.pinned,
            "source_chunk_ids": [item.get("chunk_id", "") for item in self.source_evidence if item.get("chunk_id")],
        }
        frontmatter_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()

        evidence_lines: list[str] = []
        for idx, item in enumerate(self.source_evidence, start=1):
            chunk_id = item.get("chunk_id", "unknown")
            summary = item.get("summary", "")
            evidence_lines.append(f"{idx}. `{chunk_id}` — {summary}".rstrip())
        if not evidence_lines:
            evidence_lines.append("- None recorded")

        body = [
            "## Definition",
            self.definition.strip() or "Insufficient evidence",
            "",
            "## Current Working Rule",
            self.working_rule.strip() or "Insufficient evidence",
            "",
            "## Known Exceptions",
            self.known_exceptions.strip() or "Insufficient evidence",
            "",
            "## Do Not Infer",
            self.do_not_infer.strip() or "Insufficient evidence",
            "",
            "## Source Evidence",
            *evidence_lines,
            "",
        ]
        return f"---\n{frontmatter_text}\n---\n\n" + "\n".join(body)

    @classmethod
    def from_markdown(cls, path: Path) -> "CodexEntry":
        raw = path.read_text(encoding="utf-8")
        frontmatter, body = _split_frontmatter(raw)
        data = yaml.safe_load(frontmatter) or {}
        sections = _parse_sections(body)
        return cls(
            topic_id=data.get("topic_id") or path.stem,
            title=data.get("title") or path.stem.replace("-", " ").title(),
            domain=data.get("domain") or "unknown",
            definition=sections.get("Definition", "Insufficient evidence"),
            working_rule=sections.get("Current Working Rule", "Insufficient evidence"),
            known_exceptions=sections.get("Known Exceptions", "Insufficient evidence"),
            do_not_infer=sections.get("Do Not Infer", "Insufficient evidence"),
            source_evidence=_parse_source_evidence(sections.get("Source Evidence", ""), data.get("source_chunk_ids") or []),
            generated_by=_as_text(data.get("generated_by")) or "unknown",
            generated_on=_as_text(data.get("generated_on")),
            review_status=_as_text(data.get("review_status")) or "unreviewed",
            pinned=bool(data.get("pinned", False)),
        )

    @staticmethod
    def is_pinned(path: Path) -> bool:
        try:
            raw = path.read_text(encoding="utf-8")
            frontmatter, _ = _split_frontmatter(raw)
            data = yaml.safe_load(frontmatter) or {}
            return bool(data.get("pinned", False))
        except Exception:
            return False


def _split_frontmatter(raw: str) -> tuple[str, str]:
    if not raw.startswith("---"):
        raise ValueError("Codex file is missing YAML frontmatter")

    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise ValueError("Codex file has malformed YAML frontmatter")
    return parts[1].strip(), parts[2].lstrip("\n")


def _parse_sections(body: str) -> dict[str, str]:
    headings = [
        "Definition",
        "Current Working Rule",
        "Known Exceptions",
        "Do Not Infer",
        "Source Evidence",
    ]
    result: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []

    for line in body.splitlines():
        normalized = line.strip()
        matched_heading = None
        for heading in headings:
            if normalized.lower() == f"## {heading}".lower() or normalized.lower() == heading.lower():
                matched_heading = heading
                break
        if matched_heading is not None:
            if current is not None:
                result[current] = "\n".join(buffer).strip()
            current = matched_heading
            buffer = []
            continue
        if current is not None:
            buffer.append(line)

    if current is not None:
        result[current] = "\n".join(buffer).strip()
    return result


def _parse_source_evidence(section_text: str, source_chunk_ids: list[str]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        stripped = stripped.lstrip("-*").strip()
        if stripped and stripped[0].isdigit() and "." in stripped:
            stripped = stripped.split(".", 1)[1].strip()
        chunk_id = ""
        summary = stripped
        if stripped.lower() == "none recorded":
            continue
        if stripped.startswith("`") and "`" in stripped[1:]:
            second_tick = stripped.find("`", 1)
            chunk_id = stripped[1:second_tick]
            summary = stripped[second_tick + 1 :].lstrip(" -—")
        elif "—" in stripped:
            left, right = stripped.split("—", 1)
            candidate = left.strip().strip("`")
            if candidate:
                chunk_id = candidate
                summary = right.strip()
        entries.append({"chunk_id": chunk_id, "summary": summary.strip()})

    if entries:
        return entries
    return [{"chunk_id": chunk_id, "summary": ""} for chunk_id in source_chunk_ids]


def _as_text(value: object) -> str:
    return "" if value is None else str(value)
