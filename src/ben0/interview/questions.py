"""Default question set for the institution interview."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class InterviewQuestion:
    question_id: str
    domain: str
    title: str
    data_query: str | None
    db_query: str | None
    prompt_template: str
    followup_prompt: str | None
    rule_id: str
    rule_tags: list[str]
    priority: int = 10


DEFAULT_QUESTIONS: list[InterviewQuestion] = [
    InterviewQuestion(
        question_id="status_codes",
        domain="schema",
        title="Status Codes and Groupings",
        data_query=None,
        db_query="distinct_statuses",
        prompt_template=(
            "I found these status values in your collection data: {context}. "
            "Can you explain what each means and how they group together? "
            "Which ones mean 'alive', which mean 'dead or gone', and which are propagation stages?"
        ),
        followup_prompt=(
            "Could you be a bit more specific about which exact values belong in each group, "
            "and mention any ambiguous or legacy statuses?"
        ),
        rule_id="interview_status_groups",
        rule_tags=["interview", "status", "schema"],
        priority=12,
    ),
    InterviewQuestion(
        question_id="provenance_practices",
        domain="schema",
        title="Provenance and Origin Codes",
        data_query=None,
        db_query="distinct_provenances",
        prompt_template=(
            "Your collection uses these provenance/origin codes: {context}. "
            "Can you explain what each code means? Are there any codes that are historical or no longer used?"
        ),
        followup_prompt=(
            "Please include any codes that changed meaning over time, and note whether any should now be mapped "
            "to a modern replacement."
        ),
        rule_id="interview_provenance",
        rule_tags=["interview", "provenance", "schema"],
        priority=12,
    ),
    InterviewQuestion(
        question_id="propagation_workflow",
        domain="workflow",
        title="Propagation Workflow",
        data_query=None,
        db_query="propagation_event_types",
        prompt_template=(
            "I see these propagation-related events in your records: {context}. "
            "Can you walk me through the typical propagation workflow from start to finish? "
            "What's the expected sequence?"
        ),
        followup_prompt=(
            "Could you lay out the usual sequence step by step, including common branching points or exceptions?"
        ),
        rule_id="interview_propagation_workflow",
        rule_tags=["interview", "propagation", "workflow"],
        priority=11,
    ),
    InterviewQuestion(
        question_id="recording_history",
        domain="history",
        title="Recording History and System Changes",
        data_query=None,
        db_query="date_range_summary",
        prompt_template=(
            "Your records span from {context}. Have there been any major changes in how data was recorded over the years? "
            "Any system migrations, policy changes, or known gaps I should be aware of?"
        ),
        followup_prompt=(
            "Please mention approximate date ranges for major changes if you can, plus any especially unreliable periods."
        ),
        rule_id="interview_recording_history",
        rule_tags=["interview", "history", "recording"],
        priority=10,
    ),
    InterviewQuestion(
        question_id="location_system",
        domain="schema",
        title="Location Coding System",
        data_query=None,
        db_query="distinct_locations",
        prompt_template=(
            "I found these garden locations in your data: {context}. Can you explain the naming/coding system? "
            "Are any of these locations retired, renamed, or seasonal?"
        ),
        followup_prompt=(
            "If there are parent-child relationships, aliases, or retired codes that should map forward, please spell those out."
        ),
        rule_id="interview_locations",
        rule_tags=["interview", "locations", "schema"],
        priority=11,
    ),
    InterviewQuestion(
        question_id="collection_focus",
        domain="collection_profile",
        title="Collection Focus and Mandate",
        data_query=None,
        db_query="taxonomic_summary",
        prompt_template=(
            "Your collection has {context}. What is the garden's collection focus or mandate? "
            "Are there particular taxonomic groups, geographic regions, or conservation priorities that define your collection?"
        ),
        followup_prompt=(
            "Could you note any formal priorities versus informal strengths, and anything that should not be over-interpreted from the raw counts?"
        ),
        rule_id="interview_collection_focus",
        rule_tags=["interview", "collection-profile", "mandate"],
        priority=10,
    ),
    InterviewQuestion(
        question_id="data_quirks",
        domain="history",
        title="Known Data Quirks",
        data_query="data quality issues",
        db_query=None,
        prompt_template=(
            "Based on what I've seen so far, are there any known data quality issues, encoding problems, or historical artifacts "
            "in your records that I should know about? For example: dates in unusual formats, fields used differently over time, "
            "bulk imports that introduced errors?"
        ),
        followup_prompt=(
            "Please mention specific fields or eras if possible, plus any quirks that look wrong at first but are actually intentional."
        ),
        rule_id="interview_data_quirks",
        rule_tags=["interview", "data-quality", "history"],
        priority=10,
    ),
    InterviewQuestion(
        question_id="sensitive_data",
        domain="schema",
        title="Sensitive Data Handling",
        data_query=None,
        db_query=None,
        prompt_template=(
            "Does your collection include any sensitive data categories I should be careful with? "
            "For example: precise locations of rare species, Indigenous-associated knowledge, donor privacy, permit restrictions?"
        ),
        followup_prompt=(
            "If yes, please describe what should be restricted, generalized, or reviewed by a human before sharing."
        ),
        rule_id="interview_sensitive_data",
        rule_tags=["interview", "sensitive-data", "schema"],
        priority=12,
    ),
]
