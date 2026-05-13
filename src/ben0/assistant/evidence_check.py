from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ben0.rules.schema import RuleFile

_CITATION_RE = re.compile(r"\[([^\[\]\n]{1,200})\]")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
}

_STATUS_GROUPS = {
    "living": {"living", "active", "established", "in cultivation", "cultivated"},
    "dead": {"dead", "lost", "removed", "deaccessioned", "destroyed"},
    "propagation": {"preparation", "culturing", "success", "failure", "observed", "in propagation"},
    "unknown": {"unknown", "unspecified", "pending review"},
}

_RELIABILITY_SCORES = {
    "official": 1.0,
    "professional": 0.8,
    "informal": 0.5,
    "generated": 0.2,
}


@dataclass(slots=True)
class CitationReport:
    cited_ids: list[str]
    valid_ids: list[str]
    phantom_ids: list[str]
    uncited_evidence: list[str]
    coverage_ratio: float


@dataclass(slots=True)
class Conflict:
    topic: str
    lane_a_summary: str
    lane_b_summary: str
    chunk_ids: list[str]


@dataclass(slots=True)
class RuleViolation:
    rule_id: str
    rule_name: str
    violation_description: str


@dataclass(slots=True)
class ConfidenceLevel:
    level: str
    score: float
    reasons: list[str]


@dataclass(slots=True)
class VerificationResult:
    citation_report: CitationReport
    conflicts: list[Conflict]
    rule_violations: list[RuleViolation]
    confidence: ConfidenceLevel

    def format_appendix(self) -> str:
        lines = ["---", f"📊 Evidence Check: {self.confidence.level} confidence (score: {self.confidence.score:.2f})"]
        if (
            self.citation_report.phantom_ids
            or not self.citation_report.valid_ids
            or self.citation_report.uncited_evidence
        ):
            lines.append(
                f"✅ Citations: {len(self.citation_report.valid_ids)} valid, {len(self.citation_report.phantom_ids)} phantom"
            )
        if self.conflicts:
            summary = "; ".join(conflict.topic for conflict in self.conflicts[:2])
            if len(self.conflicts) > 2:
                summary = f"{summary}; +{len(self.conflicts) - 2} more"
            lines.append(f"⚠️ Conflicts: {summary}")
        if self.rule_violations:
            summary = "; ".join(violation.rule_name for violation in self.rule_violations[:2])
            if len(self.rule_violations) > 2:
                summary = f"{summary}; +{len(self.rule_violations) - 2} more"
            lines.append(f"⚠️ Rule violations: {summary}")
        return "\n".join(lines)


def verify_citations(answer: str, retrieved_chunks: list[dict[str, Any]]) -> CitationReport:
    cited_ids = list(dict.fromkeys(match.strip() for match in _CITATION_RE.findall(answer) if match.strip()))
    valid_tokens = _build_valid_citation_tokens(retrieved_chunks)
    valid_ids = [citation for citation in cited_ids if citation in valid_tokens]
    phantom_ids = [citation for citation in cited_ids if citation not in valid_tokens]

    uncited_evidence: list[str] = []
    for chunk in retrieved_chunks:
        chunk_token = _primary_chunk_token(chunk)
        if not chunk_token:
            continue
        aliases = _chunk_aliases(chunk)
        if not any(alias in cited_ids for alias in aliases):
            uncited_evidence.append(chunk_token)

    coverage_ratio = len(valid_ids) / max(len(cited_ids), 1)
    return CitationReport(
        cited_ids=cited_ids,
        valid_ids=valid_ids,
        phantom_ids=phantom_ids,
        uncited_evidence=list(dict.fromkeys(uncited_evidence)),
        coverage_ratio=coverage_ratio,
    )


def detect_conflicts(lane_a_results: list[dict[str, Any]], lane_b_results: list[dict[str, Any]]) -> list[Conflict]:
    if not lane_a_results or not lane_b_results:
        return []

    conflicts: list[Conflict] = []
    seen: set[tuple[str, str]] = set()
    for lane_a in lane_a_results:
        for lane_b in lane_b_results:
            if not _results_overlap(lane_a, lane_b):
                continue
            if not _looks_contradictory(lane_a, lane_b):
                continue
            chunk_ids = [token for token in (_primary_chunk_token(lane_a), _primary_chunk_token(lane_b)) if token]
            key = tuple(chunk_ids)
            if key in seen:
                continue
            seen.add(key)
            conflicts.append(
                Conflict(
                    topic=_conflict_topic(lane_a, lane_b),
                    lane_a_summary=_summarize_text(lane_a.get("text") or lane_a.get("snippet") or ""),
                    lane_b_summary=_summarize_text(lane_b.get("text") or lane_b.get("snippet") or ""),
                    chunk_ids=chunk_ids,
                )
            )
    return conflicts


def check_rule_compliance(answer: str, matched_rules: list[RuleFile]) -> list[RuleViolation]:
    sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", answer) if segment.strip()]
    violations: list[RuleViolation] = []

    for rule in matched_rules:
        status_groups = _extract_status_groups(rule.content)
        if not status_groups:
            continue
        lowered_groups = {
            group_name.lower(): {str(term).lower() for term in terms}
            for group_name, terms in status_groups.items()
            if isinstance(terms, list)
        }
        for sentence in sentences:
            lowered_sentence = sentence.lower()
            for group_name, terms in lowered_groups.items():
                if not any(term in lowered_sentence for term in terms):
                    continue
                mentioned_groups = {
                    candidate
                    for candidate in lowered_groups
                    if re.search(rf"\b{re.escape(candidate)}\b", lowered_sentence)
                }
                for mentioned_group in mentioned_groups:
                    if mentioned_group == group_name:
                        continue
                    violations.append(
                        RuleViolation(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            violation_description=(
                                f"Answer associates {group_name} status terminology with the '{mentioned_group}' group: "
                                f"{sentence}"
                            ),
                        )
                    )
                    break
                else:
                    continue
                break
            else:
                continue
            break
    return violations


def score_confidence(
    citation_report: CitationReport,
    rule_violations: list[RuleViolation],
    conflicts: list[Conflict],
    retrieved_chunks: list[dict[str, Any]],
) -> ConfidenceLevel:
    reasons: list[str] = []
    score = 0.15

    coverage_component = 0.45 * citation_report.coverage_ratio
    score += coverage_component
    if citation_report.cited_ids:
        reasons.append(f"citation coverage is {citation_report.coverage_ratio:.2f}")
    else:
        reasons.append("answer does not include explicit evidence citations")
        score -= 0.1

    reliability = _average_reliability(citation_report.valid_ids, retrieved_chunks)
    score += 0.2 * reliability
    if citation_report.valid_ids:
        reasons.append(f"cited evidence averages {reliability:.2f} reliability")

    if not citation_report.phantom_ids:
        if citation_report.valid_ids:
            score += 0.15
            reasons.append("no phantom citations detected")
    else:
        phantom_penalty = min(0.45, 0.2 * len(citation_report.phantom_ids))
        score -= phantom_penalty
        reasons.append(f"found {len(citation_report.phantom_ids)} phantom citation(s)")

    if rule_violations:
        penalty = min(0.3, 0.15 * len(rule_violations))
        score -= penalty
        reasons.append(f"found {len(rule_violations)} rule violation(s)")
    else:
        score += 0.05
        reasons.append("no rule violations detected")

    if conflicts:
        penalty = min(0.2, 0.08 * len(conflicts))
        score -= penalty
        reasons.append(f"retrieved evidence contains {len(conflicts)} conflict(s)")
    else:
        score += 0.05
        reasons.append("retrieved evidence is internally consistent")

    score = max(0.0, min(1.0, score))
    if score >= 0.8:
        level = "high"
    elif score >= 0.5:
        level = "medium"
    elif score >= 0.2:
        level = "low"
    else:
        level = "insufficient"

    return ConfidenceLevel(level=level, score=score, reasons=reasons)


def _build_valid_citation_tokens(retrieved_chunks: list[dict[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for chunk in retrieved_chunks:
        tokens.update(_chunk_aliases(chunk))
    return {token for token in tokens if token}


def _chunk_aliases(chunk: dict[str, Any]) -> set[str]:
    aliases = {
        str(chunk.get("chunk_id") or "").strip(),
        str(chunk.get("citation") or "").strip(),
        str(chunk.get("document_name") or "").strip(),
    }
    for key in ("accession_id", "item_id", "taxon_id", "id"):
        value = chunk.get(key)
        if value:
            aliases.add(str(value).strip())
    return {alias for alias in aliases if alias}


def _primary_chunk_token(chunk: dict[str, Any]) -> str:
    for key in ("chunk_id", "citation", "document_name", "id"):
        value = chunk.get(key)
        if value:
            return str(value)
    return ""


def _tokenize(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(text.lower()) if len(token) > 2 and token not in _STOPWORDS}


def _results_overlap(lane_a: dict[str, Any], lane_b: dict[str, Any]) -> bool:
    for key in ("accession_id", "item_id", "taxon_id"):
        left = lane_a.get(key)
        right = lane_b.get(key)
        if left and right and left == right:
            return True
    left_tokens = _tokenize(str(lane_a.get("text") or lane_a.get("snippet") or lane_a.get("document_name") or ""))
    right_tokens = _tokenize(str(lane_b.get("text") or lane_b.get("snippet") or lane_b.get("document_name") or ""))
    return len(left_tokens & right_tokens) >= 2


def _looks_contradictory(lane_a: dict[str, Any], lane_b: dict[str, Any]) -> bool:
    text_a = str(lane_a.get("text") or lane_a.get("snippet") or "")
    text_b = str(lane_b.get("text") or lane_b.get("snippet") or "")

    status_a = _status_category(text_a)
    status_b = _status_category(text_b)
    if status_a and status_b and status_a != status_b:
        contradictory_pairs = {frozenset({"living", "dead"}), frozenset({"living", "unknown"}), frozenset({"dead", "propagation"})}
        if frozenset({status_a, status_b}) in contradictory_pairs:
            return True

    provenance_a = _provenance_category(text_a)
    provenance_b = _provenance_category(text_b)
    if provenance_a and provenance_b and provenance_a != provenance_b:
        return True

    dates_a = _DATE_RE.findall(text_a)
    dates_b = _DATE_RE.findall(text_b)
    shared_context = bool(
        {"accession", "event", "collected", "recorded", "updated"} & _tokenize(text_a) & _tokenize(text_b)
    )
    if shared_context and len(set(dates_a)) == 1 and len(set(dates_b)) == 1 and dates_a[0] != dates_b[0]:
        return True

    return False


def _status_category(text: str) -> str | None:
    lowered = text.lower()
    for category, terms in _STATUS_GROUPS.items():
        if any(term in lowered for term in terms):
            return category
    return None


def _provenance_category(text: str) -> str | None:
    lowered = text.lower()
    if "wild origin" in lowered or "wild collected" in lowered:
        return "wild"
    if "garden origin" in lowered or "cultivated" in lowered:
        return "garden"
    if "unknown origin" in lowered:
        return "unknown"
    return None


def _conflict_topic(lane_a: dict[str, Any], lane_b: dict[str, Any]) -> str:
    for key in ("accession_id", "item_id", "taxon_id"):
        left = lane_a.get(key)
        right = lane_b.get(key)
        if left and right and left == right:
            return f"{key.replace('_', ' ')} {left}"
    document_name = lane_a.get("document_name") or lane_b.get("document_name")
    if document_name:
        return str(document_name)
    overlap = sorted(_tokenize(str(lane_a.get("text") or "")) & _tokenize(str(lane_b.get("text") or "")))
    return " / ".join(overlap[:3]) if overlap else "retrieved evidence"


def _summarize_text(text: str, *, limit: int = 140) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1].rstrip()}…"


def _extract_status_groups(content: dict[str, Any]) -> dict[str, list[Any]]:
    status_groups = content.get("status_groups")
    if isinstance(status_groups, dict):
        return {
            str(name): value
            for name, value in status_groups.items()
            if isinstance(value, list)
        }
    return {}


def _average_reliability(valid_ids: list[str], retrieved_chunks: list[dict[str, Any]]) -> float:
    if not valid_ids:
        return 0.4
    scores: list[float] = []
    valid_set = set(valid_ids)
    for chunk in retrieved_chunks:
        if not (_chunk_aliases(chunk) & valid_set):
            continue
        tier = str(chunk.get("reliability_tier") or "").lower().strip()
        scores.append(_RELIABILITY_SCORES.get(tier, 0.6))
    return sum(scores) / len(scores) if scores else 0.4
