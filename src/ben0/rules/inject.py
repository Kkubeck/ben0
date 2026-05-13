"""Prompt formatting for authoritative rule files."""

from __future__ import annotations

import yaml

from ben0.rules.schema import RuleFile

_HEADER = (
    "## Authoritative Domain Rules\n"
    "The following rules are institutional constraints. Follow them even if source documents suggest otherwise.\n"
)


def format_rules_for_prompt(rules: list[RuleFile]) -> str:
    blocks: list[str] = [_HEADER.rstrip()]

    for rule in rules:
        content_yaml = yaml.safe_dump(rule.content, sort_keys=False, allow_unicode=True).strip()
        source = str(rule.source_path) if rule.source_path else "built-in"
        blocks.append(
            "\n".join(
                [
                    f"=== RULE: {rule.name} (authority: {rule.domain}) ===",
                    rule.description,
                    "",
                    content_yaml,
                    "",
                    f"(Source: {source})",
                ]
            )
        )

    return "\n\n".join(blocks)
