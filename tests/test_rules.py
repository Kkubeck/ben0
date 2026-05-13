from __future__ import annotations

from pathlib import Path

from ben0.rules.inject import format_rules_for_prompt
from ben0.rules.loader import load_rules, seed_rules
from ben0.rules.matcher import match_rules
from ben0.rules.schema import RuleFile


def _write_rule(path: Path, *, rule_id: str, name: str, tags: list[str], domain: str, priority: int = 10, content: dict | None = None) -> None:
    content = content or {"example": {"value": rule_id}}
    rule = RuleFile(
        id=rule_id,
        name=name,
        description=f"Description for {name}",
        tags=tags,
        domain=domain,
        priority=priority,
        content=content,
    )
    path.write_text(rule.to_yaml(), encoding="utf-8")


def test_rulefile_from_yaml_parses_fields(tmp_path: Path):
    rule_path = tmp_path / "status.yaml"
    _write_rule(
        rule_path,
        rule_id="status_groups",
        name="Status Group Mappings",
        tags=["status", "accession"],
        domain="accession_management",
        priority=14,
        content={"status_groups": {"living": ["Living accession"]}},
    )

    rule = RuleFile.from_yaml(rule_path)

    assert rule.id == "status_groups"
    assert rule.name == "Status Group Mappings"
    assert rule.tags == ["status", "accession"]
    assert rule.priority == 14
    assert rule.content["status_groups"]["living"] == ["Living accession"]
    assert rule.source_path == rule_path


def test_load_rules_reads_yaml_and_sorts_by_priority(tmp_path: Path):
    _write_rule(tmp_path / "low.yaml", rule_id="low", name="Low", tags=["alpha"], domain="records", priority=5)
    _write_rule(tmp_path / "high.yml", rule_id="high", name="High", tags=["beta"], domain="records", priority=15)
    (tmp_path / "broken.yaml").write_text("id: [unterminated", encoding="utf-8")

    rules = load_rules(tmp_path)

    assert [rule.id for rule in rules] == ["high", "low"]


def test_load_rules_missing_directory_returns_empty_list(tmp_path: Path):
    assert load_rules(tmp_path / "missing") == []


def test_match_rules_matches_tags_and_returns_empty_for_non_matches():
    status_rule = RuleFile(
        id="status",
        name="Status Rule",
        description="status mapping",
        tags=["status", "living collection"],
        domain="accession_management",
        content={"status": "living"},
    )
    date_rule = RuleFile(
        id="dates",
        name="Date Rule",
        description="date parsing",
        tags=["date", "legacy"],
        domain="records_management",
        content={"dates": True},
    )

    matched = match_rules("Which living collection status values count as active?", [status_rule, date_rule])
    unmatched = match_rules("Tell me about irrigation pumps", [status_rule, date_rule])

    assert [rule.id for rule in matched] == ["status"]
    assert unmatched == []


def test_match_rules_respects_max_rules_limit():
    rules = [
        RuleFile(
            id=f"rule-{idx}",
            name=f"Status Rule {idx}",
            description="desc",
            tags=["status"],
            domain="accession_management",
            priority=idx,
            content={"idx": idx},
        )
        for idx in range(6)
    ]

    matched = match_rules("status", rules, max_rules=3)

    assert len(matched) == 3
    assert [rule.priority for rule in matched] == [5, 4, 3]


def test_match_rules_sorts_by_score_then_priority():
    high_score = RuleFile(
        id="high-score",
        name="Status Provenance Rule",
        description="desc",
        tags=["status", "provenance"],
        domain="accession_management",
        priority=1,
        content={"a": 1},
    )
    high_priority = RuleFile(
        id="high-priority",
        name="Status Rule",
        description="desc",
        tags=["status"],
        domain="accession_management",
        priority=50,
        content={"b": 2},
    )

    matched = match_rules("status provenance accession management", [high_priority, high_score])

    assert [rule.id for rule in matched] == ["high-score", "high-priority"]


def test_format_rules_for_prompt_contains_header_names_and_content():
    rule = RuleFile(
        id="status",
        name="Status Group Mappings",
        description="How statuses map",
        tags=["status"],
        domain="accession_management",
        content={"status_groups": {"living": ["Living accession"]}},
        source_path=Path("/tmp/status_groups.yaml"),
    )

    formatted = format_rules_for_prompt([rule])

    assert formatted.startswith("## Authoritative Domain Rules")
    assert "=== RULE: Status Group Mappings (authority: accession_management) ===" in formatted
    assert "status_groups:" in formatted
    assert "Living accession" in formatted
    assert "(Source: /tmp/status_groups.yaml)" in formatted


def test_seed_rules_seeds_empty_dir_without_overwriting_existing(tmp_path: Path):
    seeded_first = seed_rules(tmp_path)
    assert seeded_first >= 4

    status_path = tmp_path / "status_groups.yaml"
    original = status_path.read_text(encoding="utf-8")
    status_path.write_text("custom: keep-me\n", encoding="utf-8")

    seeded_second = seed_rules(tmp_path)

    assert seeded_second == 0
    assert status_path.read_text(encoding="utf-8") == "custom: keep-me\n"
    assert original != "custom: keep-me\n"
