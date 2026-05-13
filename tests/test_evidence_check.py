from __future__ import annotations

from pathlib import Path

from ben0.assistant.critic import critique_answer
from ben0.assistant.evidence_check import (
    CitationReport,
    VerificationResult,
    check_rule_compliance,
    detect_conflicts,
    score_confidence,
    verify_citations,
)
from ben0.rules.schema import RuleFile


class _CriticAdapter:
    def __init__(self, response: str):
        self.response = response

    def generate(self, prompt: str, system: str | None = None) -> str:
        assert "Draft answer:" in prompt
        assert system and "evidence auditor" in system.lower()
        return self.response


def _status_rule() -> RuleFile:
    return RuleFile(
        id="status_groups",
        name="Status Group Mappings",
        description="Maps statuses to operational groups.",
        tags=["status"],
        domain="accession_management",
        content={
            "status_groups": {
                "living": ["Living accession", "Active"],
                "dead": ["Dead", "Lost"],
                "unknown": ["Unknown"],
            }
        },
        source_path=Path("status_groups.yaml"),
    )


def test_verify_citations_valid_and_phantom() -> None:
    retrieved = [
        {"chunk_id": "chunk-1", "citation": "document:alpha#chunk-1", "document_name": "alpha"},
        {"chunk_id": "chunk-2", "citation": "accession:abc", "document_name": "beta"},
    ]
    answer = "Supported by [document:alpha#chunk-1], [beta], and [ghost-id]."

    report = verify_citations(answer, retrieved)

    assert report.valid_ids == ["document:alpha#chunk-1", "beta"]
    assert report.phantom_ids == ["ghost-id"]
    assert report.uncited_evidence == []


def test_verify_citations_no_citations_and_coverage_ratio() -> None:
    retrieved = [{"chunk_id": "chunk-1", "citation": "document:alpha#chunk-1", "document_name": "alpha"}]

    report = verify_citations("No explicit citation here.", retrieved)

    assert report.cited_ids == []
    assert report.coverage_ratio == 0.0
    assert report.uncited_evidence == ["chunk-1"]


def test_detect_conflicts_when_lanes_agree() -> None:
    lane_a = [{"chunk_id": "a1", "accession_id": "acc-1", "text": "Accession acc-1 is living and active.", "lane": "A"}]
    lane_b = [{"chunk_id": "b1", "accession_id": "acc-1", "text": "Codex notes accession acc-1 remains living.", "lane": "B"}]

    assert detect_conflicts(lane_a, lane_b) == []


def test_detect_conflicts_when_lanes_disagree() -> None:
    lane_a = [{"chunk_id": "a1", "accession_id": "acc-1", "text": "Accession acc-1 is Living accession as of 2024-01-01.", "lane": "A"}]
    lane_b = [{"chunk_id": "b1", "accession_id": "acc-1", "text": "Codex says accession acc-1 is Dead as of 2024-01-01.", "lane": "B"}]

    conflicts = detect_conflicts(lane_a, lane_b)

    assert len(conflicts) == 1
    assert conflicts[0].topic == "accession id acc-1"
    assert conflicts[0].chunk_ids == ["a1", "b1"]


def test_detect_conflicts_empty_results() -> None:
    assert detect_conflicts([], []) == []
    assert detect_conflicts([{"chunk_id": "a1"}], []) == []


def test_check_rule_compliance_clean_answer_passes() -> None:
    violations = check_rule_compliance("This accession is in the living group because it is Active.", [_status_rule()])
    assert violations == []


def test_check_rule_compliance_wrong_status_category_fails() -> None:
    violations = check_rule_compliance("This accession is in the living group because it is Dead.", [_status_rule()])
    assert len(violations) == 1
    assert violations[0].rule_id == "status_groups"


def test_score_confidence_high_score_for_good_citations() -> None:
    report = CitationReport(
        cited_ids=["document:alpha#chunk-1"],
        valid_ids=["document:alpha#chunk-1"],
        phantom_ids=[],
        uncited_evidence=[],
        coverage_ratio=1.0,
    )
    retrieved = [{"chunk_id": "chunk-1", "citation": "document:alpha#chunk-1", "reliability_tier": "official"}]

    confidence = score_confidence(report, [], [], retrieved)

    assert confidence.level == "high"
    assert confidence.score >= 0.8


def test_score_confidence_low_score_for_phantoms_and_level_mapping() -> None:
    retrieved = [{"chunk_id": "chunk-1", "citation": "document:alpha#chunk-1", "reliability_tier": "informal"}]

    low_confidence = score_confidence(
        CitationReport(
            cited_ids=["document:alpha#chunk-1", "ghost-id"],
            valid_ids=["document:alpha#chunk-1"],
            phantom_ids=["ghost-id"],
            uncited_evidence=[],
            coverage_ratio=0.5,
        ),
        [],
        [],
        retrieved,
    )
    insufficient_confidence = score_confidence(
        CitationReport(
            cited_ids=[],
            valid_ids=[],
            phantom_ids=["ghost-1", "ghost-2"],
            uncited_evidence=["chunk-1"],
            coverage_ratio=0.0,
        ),
        [
            check_rule_compliance(
                "This accession is in the living group because it is Dead.",
                [_status_rule()],
            )[0]
        ],
        [detect_conflicts(
            [{"chunk_id": "a1", "accession_id": "acc-1", "text": "Accession acc-1 is living.", "lane": "A"}],
            [{"chunk_id": "b1", "accession_id": "acc-1", "text": "Accession acc-1 is Dead.", "lane": "B"}],
        )[0]],
        retrieved,
    )

    assert low_confidence.level == "low"
    assert 0.2 <= low_confidence.score < 0.5
    assert insufficient_confidence.level == "insufficient"
    assert insufficient_confidence.score < 0.2


def test_verification_result_format_appendix() -> None:
    verification = VerificationResult(
        citation_report=CitationReport(
            cited_ids=["document:alpha#chunk-1"],
            valid_ids=["document:alpha#chunk-1"],
            phantom_ids=["ghost-id"],
            uncited_evidence=[],
            coverage_ratio=1.0,
        ),
        conflicts=[],
        rule_violations=[],
        confidence=score_confidence(
            CitationReport(
                cited_ids=["document:alpha#chunk-1"],
                valid_ids=["document:alpha#chunk-1"],
                phantom_ids=[],
                uncited_evidence=[],
                coverage_ratio=1.0,
            ),
            [],
            [],
            [{"chunk_id": "chunk-1", "citation": "document:alpha#chunk-1", "reliability_tier": "official"}],
        ),
    )

    appendix = verification.format_appendix()

    assert appendix.startswith("---")
    assert "Evidence Check:" in appendix
    assert "Citations:" in appendix


def test_critique_answer_parses_structured_response() -> None:
    adapter = _CriticAdapter(
        "Assessment: partially_supported\nIssues:\n1. One claim lacks a citation.\nSuggestions:\n1. Add the missing citation."
    )

    critique = critique_answer(adapter, "Draft.", ["Evidence text"], [_status_rule()])

    assert critique.assessment == "partially_supported"
    assert critique.issues == ["One claim lacks a citation."]
    assert critique.suggestions == ["Add the missing citation."]


def test_critique_answer_handles_messy_response() -> None:
    adapter = _CriticAdapter(
        "SUPPORTED? no. assessment - unsupported\nIssues - unsupported claim; vague wording\nSuggestions - tighten wording; cite evidence 1"
    )

    critique = critique_answer(adapter, "Draft.", ["Evidence text"])

    assert critique.assessment == "unsupported"
    assert critique.issues == ["unsupported claim", "vague wording"]
    assert critique.suggestions == ["tighten wording", "cite evidence 1"]
