"""Turn conversational interview answers into rule files."""

from __future__ import annotations

import re
from typing import Any

import yaml

from ben0.interview.questions import InterviewQuestion
from ben0.rules.schema import RuleFile


def parse_answer_to_rule(
    question: InterviewQuestion,
    answer: str,
    adapter: Any,
    context: str | None = None,
) -> RuleFile:
    """Parse a user's conversational answer into a structured RuleFile."""
    content: dict[str, Any]
    try:
        prompt = _build_parsing_prompt(question, answer, context)
        raw_output = adapter.generate(prompt, system=_PARSER_SYSTEM_PROMPT)
        yaml_text = _extract_yaml_block(raw_output)
        parsed = yaml.safe_load(yaml_text)
        if isinstance(parsed, dict):
            if isinstance(parsed.get("content"), dict):
                content = parsed["content"]
            else:
                content = parsed
        else:
            raise ValueError("Parser output was not a YAML mapping")
    except Exception:
        content = {"raw_answer": answer}

    return RuleFile(
        id=question.rule_id,
        name=question.title,
        description=f"Generated from institution interview: {question.title}",
        tags=list(question.rule_tags),
        domain=question.domain,
        priority=question.priority,
        pinned=False,
        content=content,
    )


_PARSER_SYSTEM_PROMPT = (
    "You convert botanical garden interview answers into structured YAML rules. "
    "Return only YAML. Use concise keys. Preserve important mappings, caveats, and exceptions."
)


def _build_parsing_prompt(question: InterviewQuestion, answer: str, context: str | None) -> str:
    context_block = context or "No additional data context was available."
    return (
        "Given this interview question and answer about a botanical garden's practices, "
        "extract the key rules and mappings into structured YAML format.\n\n"
        f"Question ID: {question.question_id}\n"
        f"Rule ID: {question.rule_id}\n"
        f"Rule domain: {question.domain}\n"
        f"Question title: {question.title}\n"
        f"Question prompt: {question.prompt_template}\n"
        f"Data context: {context_block}\n\n"
        f"Answer:\n{answer}\n\n"
        "Return YAML only. Output a mapping suitable for the rule file's content field."
    )


def _extract_yaml_block(text: str) -> str:
    match = re.search(r"```(?:yaml|yml)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip()
