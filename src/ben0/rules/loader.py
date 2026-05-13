"""Load and seed authoritative rule files."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ben0.rules.schema import RuleFile

logger = logging.getLogger(__name__)


def load_rule(path: Path) -> RuleFile:
    return RuleFile.from_yaml(path)


def load_rules(rules_dir: Path) -> list[RuleFile]:
    if not rules_dir.exists() or not rules_dir.is_dir():
        return []

    rules: list[RuleFile] = []
    for path in sorted(rules_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
            continue
        try:
            rules.append(load_rule(path))
        except Exception as exc:
            logger.warning("Skipping unreadable rule file %s: %s", path, exc)

    return sorted(rules, key=lambda rule: rule.priority, reverse=True)


def seed_rules(target_dir: Path) -> int:
    target_dir.mkdir(parents=True, exist_ok=True)
    seeds_dir = Path(__file__).parent / "seeds"
    seeded = 0

    for seed_path in sorted(seeds_dir.glob("*.y*ml")):
        destination = target_dir / seed_path.name
        if destination.exists():
            continue
        shutil.copy2(seed_path, destination)
        seeded += 1

    return seeded
