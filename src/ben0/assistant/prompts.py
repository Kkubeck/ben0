"""Prompt templates for the BEN-0 assistant."""

from __future__ import annotations

import json
from typing import Any

TOOL_FORMAT_GUIDANCE = """
You may either answer directly or request exactly one tool.

Tool call format:
TOOL_CALL <tool_name> <json arguments>

Final answer format:
FINAL: <answer with citations in square brackets>

If evidence is incomplete, say so explicitly.
""".strip()

CITATION_GUIDANCE = (
    "Always cite collection evidence using square-bracket citations such as "
    "[accession:1234], [validation_issue:abcd], or [document:filename#chunk]."
)

UNCERTAINTY_GUIDANCE = (
    "Use cautious language when evidence is incomplete: for example, 'The available records suggest...' "
    "or 'I could not confirm this from the indexed sources.'"
)


def build_initial_prompt(
    question: str,
    tool_names: list[str],
    recent_conversation: str = "",
) -> str:
    parts = [
        f"Available tools: {', '.join(tool_names)}",
        TOOL_FORMAT_GUIDANCE,
        CITATION_GUIDANCE,
        UNCERTAINTY_GUIDANCE,
    ]
    if recent_conversation:
        parts.append(recent_conversation)
    parts.append(f"Question: {question}")
    return "\n\n".join(parts)


def build_hybrid_prompt(
    question: str,
    tool_names: list[str],
    sql_result: dict[str, Any] | None = None,
    doc_result: dict[str, Any] | None = None,
    routing_hint: str = "",
    recent_conversation: str = "",
) -> str:
    parts = [f"Available tools: {', '.join(tool_names)}"]
    parts.append(TOOL_FORMAT_GUIDANCE)
    parts.append(CITATION_GUIDANCE)
    parts.append(UNCERTAINTY_GUIDANCE)
    if recent_conversation:
        parts.append(recent_conversation)

    if sql_result:
        sql_summary = json.dumps(sql_result, ensure_ascii=False, indent=2, default=str)
        parts.append(f"Pre-fetched SQL results:\n{sql_summary}")

    if doc_result:
        doc_summary = json.dumps(doc_result, ensure_ascii=False, indent=2, default=str)
        parts.append(f"Pre-fetched document context:\n{doc_summary}")

    if routing_hint:
        parts.append(f"Routing hint: {routing_hint}")

    parts.append(
        "You have been given both structured data (SQL) and document context above. "
        "Synthesize these into a comprehensive answer. Use the SQL results for quantitative "
        "claims and the document context for narrative explanation. You may still use tools "
        "for follow-up queries if needed."
    )
    parts.append(f"Question: {question}")
    return "\n\n".join(parts)


def build_tool_result_prompt(
    question: str,
    tool_name: str,
    arguments: dict[str, Any],
    result: Any,
    recent_conversation: str = "",
) -> str:
    parts = []
    if recent_conversation:
        parts.append(recent_conversation)
    parts.append(
        f"Question: {question}\n"
        f"Tool used: {tool_name}\n"
        f"Tool arguments: {json.dumps(arguments, ensure_ascii=False, sort_keys=True)}\n"
        f"TOOL_RESULT:\n{json.dumps(result, ensure_ascii=False, indent=2, default=str)}"
    )
    parts.append(CITATION_GUIDANCE)
    parts.append("Respond with FINAL: ...")
    return "\n\n".join(parts)
