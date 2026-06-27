"""Fast keyword matcher for authoritative rule files.

Designed with the HtDP recipe (see /knowledge/design-style-ethic/STYLE.md).
Data definitions live at the top; functions follow stub/purpose/template/body order.
"""

from __future__ import annotations

import re

from ben0.rules.schema import RuleFile

# =============================================================================
# DATA DEFINITIONS
# =============================================================================

# Query = str
# interp. a user's natural-language question, used to find relevant rule files.
#         Case and punctuation are not significant; only alphanumeric word
#         tokens are compared.
#
# Examples:
#   Q1 = ""
#   Q2 = "Which living collection status values count as active?"
#   Q3 = "irrigation pumps"


# Token = str
# interp. a single lowercased alphanumeric word extracted from text.
#         Always matches the regex [a-z0-9]+.
#
# Examples:
#   T1 = "status"
#   T2 = "7a"
#   T3 = "accession"


# TokenSet = set[Token]
# interp. the unique tokens present in a piece of text. Set semantics:
#         duplicates are collapsed; ordering is not meaningful.
#
# Examples:
#   TS0: set[str] = set()
#   TS1 = {"status", "active"}


# Score = int  # in range [0, ∞)
# interp. match strength of a rule against a query. Higher = stronger match.
#         Score of 0 means no overlap and the rule is excluded from results.


# ScoredRule = tuple[Score, RuleFile]
# interp. a rule paired with its computed match score for a given query.
#         Used as an intermediate value during ranking, never returned.


# A ranked match result is List[RuleFile] (arbitrary-sized).
# interp. rule files relevant to a query, sorted strongest match first,
#         capped at `max_rules`. Empty when nothing matched.


# =============================================================================
# IMPLEMENTATION
# =============================================================================

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    """Return the set of lowercased alphanumeric tokens in `text`.

    Signature: str -> TokenSet

    Examples:
      _tokenize("")                       == set()
      _tokenize("Hello, World!")          == {"hello", "world"}
      _tokenize("status STATUS Status")   == {"status"}
    """
    # Atomic-data template: derive directly from the input string.
    return set(_TOKEN_RE.findall(text.lower()))


def _score_rule(query_tokens: set[str], rule: RuleFile) -> int:
    """Score how strongly `rule` matches the given query tokens.

    Signature: TokenSet x RuleFile -> Score

    Scoring:
      +1 for each rule tag whose tokens are all present in the query
      +1 for each query token that also appears in the rule's name
      +1 for each query token that also appears in the rule's domain

    Examples:
      _score_rule(set(), any_rule)                          == 0
      _score_rule({"status"}, rule_named "status rules")    >= 1
    """
    # Compound-data template: RuleFile has fields tags, name, domain that
    # contribute to the score. Each field accessor appears once.
    score = 0

    # Arbitrary-sized sub-walk over rule.tags (list[str]).
    for tag in rule.tags:
        tag_tokens = _tokenize(tag)
        if tag_tokens and tag_tokens.issubset(query_tokens):
            score += 1

    score += len(query_tokens & _tokenize(rule.name))
    score += len(query_tokens & _tokenize(rule.domain))
    return score


def match_rules(query: str, rules: list[RuleFile], *, max_rules: int = 5) -> list[RuleFile]:
    """Return the top `max_rules` rules most relevant to `query`.

    Signature: Query x List[RuleFile] x int -> List[RuleFile]

    Results are ordered by score descending, ties broken by rule priority
    descending. Rules with a score of 0 are omitted entirely; the result
    list may be shorter than `max_rules` or empty.

    Examples:
      match_rules("anything", [])                          == []
      match_rules("totally unrelated query", [some_rule])  == []
      match_rules("status", [status_rule, date_rule])      == [status_rule]
      len(match_rules("status", many_rules, max_rules=3))  <= 3
    """
    # Arbitrary-sized template over `rules` with an accumulator of
    # ScoredRule tuples. Filtering (score > 0) happens during accumulation;
    # ranking and truncation happen after.
    query_tokens = _tokenize(query)
    scored: list[tuple[int, RuleFile]] = []

    for rule in rules:
        score = _score_rule(query_tokens, rule)
        if score > 0:
            scored.append((score, rule))

    scored.sort(key=lambda item: (item[0], item[1].priority), reverse=True)
    return [rule for _, rule in scored[:max_rules]]
