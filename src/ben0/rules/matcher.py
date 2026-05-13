"""Fast keyword matcher for authoritative rule files."""

from __future__ import annotations

import re

from ben0.rules.schema import RuleFile

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _score_rule(query_tokens: set[str], rule: RuleFile) -> int:
    score = 0

    for tag in rule.tags:
        tag_tokens = _tokenize(tag)
        if tag_tokens and tag_tokens.issubset(query_tokens):
            score += 1

    score += len(query_tokens & _tokenize(rule.name))
    score += len(query_tokens & _tokenize(rule.domain))
    return score


def match_rules(query: str, rules: list[RuleFile], *, max_rules: int = 5) -> list[RuleFile]:
    query_tokens = _tokenize(query)
    scored: list[tuple[int, RuleFile]] = []

    for rule in rules:
        score = _score_rule(query_tokens, rule)
        if score > 0:
            scored.append((score, rule))

    scored.sort(key=lambda item: (item[0], item[1].priority), reverse=True)
    return [rule for _, rule in scored[:max_rules]]
