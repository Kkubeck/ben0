from __future__ import annotations

import re
from dataclasses import dataclass

from ben0.rules.inject import format_rules_for_prompt
from ben0.rules.schema import RuleFile

_CRITIC_SYSTEM_PROMPT = (
    "You are an evidence auditor for a botanical garden collection system. "
    "Your job is to check whether an answer is supported by the provided evidence."
)
_VALID_ASSESSMENTS = {
    "supported",
    "partially_supported",
    "unsupported",
    "insufficient_evidence",
}


@dataclass(slots=True)
class CritiqueResult:
    assessment: str
    issues: list[str]
    suggestions: list[str]
    raw_output: str


def critique_answer(
    adapter,
    draft_answer: str,
    evidence_texts: list[str],
    matched_rules: list[RuleFile] | None = None,
) -> CritiqueResult:
    evidence_block = "\n\n".join(
        f"Evidence {idx}:\n{text.strip()}" for idx, text in enumerate(evidence_texts, start=1) if text.strip()
    ) or "No evidence provided."
    rules_block = format_rules_for_prompt(matched_rules or []) if matched_rules else "No matched rules."
    prompt = (
        "Draft answer:\n"
        f"{draft_answer.strip()}\n\n"
        "Evidence:\n"
        f"{evidence_block}\n\n"
        "Matched rules:\n"
        f"{rules_block}\n\n"
        "Respond in this format:\n"
        "Assessment: <supported|partially_supported|unsupported|insufficient_evidence>\n"
        "Issues:\n"
        "1. ...\n"
        "Suggestions:\n"
        "1. ..."
    )
    raw_output = adapter.generate(prompt, system=_CRITIC_SYSTEM_PROMPT).strip()
    assessment = _parse_assessment(raw_output)
    issues = _parse_section_items(raw_output, "issues")
    suggestions = _parse_section_items(raw_output, "suggestions")
    return CritiqueResult(
        assessment=assessment,
        issues=issues,
        suggestions=suggestions,
        raw_output=raw_output,
    )


def _parse_assessment(raw_output: str) -> str:
    match = re.search(
        r"assessment\s*[:\-]\s*(supported|partially_supported|unsupported|insufficient_evidence)",
        raw_output,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).lower()
    lowered = raw_output.lower()
    for assessment in _VALID_ASSESSMENTS:
        if assessment in lowered:
            return assessment
    return "insufficient_evidence"


def _parse_section_items(raw_output: str, section_name: str) -> list[str]:
    header_pattern = rf"{section_name}\s*[:\-]?"
    next_headers = "|".join(name for name in ("assessment", "issues", "suggestions") if name != section_name)
    match = re.search(
        rf"{header_pattern}(.*?)(?=\n\s*(?:{next_headers})\s*[:\-]|\Z)",
        raw_output,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []
    block = match.group(1).strip()
    if not block:
        return []

    items: list[str] = []
    for line in block.splitlines():
        cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
        if not cleaned:
            continue
        parts = [part.strip() for part in cleaned.split(";") if part.strip()]
        items.extend(parts or [cleaned])
    if items:
        return items

    chunks = [chunk.strip() for chunk in re.split(r";|\n", block) if chunk.strip()]
    return chunks
