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


def build_initial_prompt(question: str, tool_names: list[str]) -> str:
    tools = ", ".join(tool_names)
    return (
        f"Available tools: {tools}\n"
        f"{TOOL_FORMAT_GUIDANCE}\n"
        f"{CITATION_GUIDANCE}\n"
        f"{UNCERTAINTY_GUIDANCE}\n"
        f"Question: {question}"
    )


def build_tool_result_prompt(
    question: str,
    tool_name: str,
    arguments: dict[str, Any],
    result: Any,
) -> str:
    return (
        f"Question: {question}\n"
        f"Tool used: {tool_name}\n"
        f"Tool arguments: {json.dumps(arguments, ensure_ascii=False, sort_keys=True)}\n"
        f"TOOL_RESULT:\n{json.dumps(result, ensure_ascii=False, indent=2, default=str)}\n"
        f"{CITATION_GUIDANCE}\n"
        "Respond with FINAL: ..."
    )
