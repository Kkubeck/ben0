from __future__ import annotations

from pathlib import Path

from ben0.registry.bootstrap import bootstrap_registry
from ben0.registry.display import filter_fields, format_registry
from ben0.registry.io import load_registry, merge_registry, save_registry
from ben0.registry.schema import FieldEntry, FieldRegistry


def _write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    lines = [",".join(headers)]
    lines.extend(",".join(row) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_registry_yaml_round_trip(tmp_path: Path):
    registry = FieldRegistry(
        reviewed=True,
        fields=[
            FieldEntry(
                column="AccNoFull",
                source_file="accession_history.csv",
                data_type="string",
                description="Full accession number.",
                tier="core",
                db_mapping="accession.accession_number",
                sample_values=["1952-0001"],
                null_rate=0.0,
                unique_rate=1.0,
                notes="Reviewed by curator.",
            )
        ],
    )
    path = tmp_path / "field_registry.yaml"

    save_registry(path, registry)
    loaded = load_registry(path)

    assert loaded is not None
    assert loaded.reviewed is True
    assert loaded.fields[0].column == "AccNoFull"
    assert loaded.fields[0].db_mapping == "accession.accession_number"
    assert loaded.fields[0].sample_values == ["1952-0001"]


def test_bootstrap_registry_from_sample_csvs_deduplicates_columns(tmp_path: Path):
    accession_csv = tmp_path / "accession_history.csv"
    item_csv = tmp_path / "accession_item_history.csv"
    _write_csv(
        accession_csv,
        ["AccNoFull", "PropTreatment", "CITESCat", "CommonName_ja"],
        [
            ["1952-0001", "Cold stratification", "Appendix II", ""],
            ["2024-0156", "", "", "イチョウ"],
        ],
    )
    _write_csv(
        item_csv,
        ["AccNoFull", "ItemAccNoFull", "ItemStatus"],
        [
            ["1952-0001", "1952-0001.01", "living"],
            ["2024-0156", "2024-0156.01", "dead"],
        ],
    )

    registry = bootstrap_registry([accession_csv, item_csv])
    by_column = {entry.column: entry for entry in registry.fields}

    assert by_column["AccNoFull"].source_file == "accession_history.csv, accession_item_history.csv"
    assert by_column["AccNoFull"].tier == "core"
    assert by_column["AccNoFull"].db_mapping == "accession.accession_number"
    assert by_column["PropTreatment"].tier == "core"
    assert by_column["PropTreatment"].notes.startswith("Currently packed into notes")
    assert by_column["CITESCat"].tier == "core"
    assert by_column["CommonName_ja"].tier == "niche"
    assert by_column["ItemStatus"].data_type == "string"


def test_merge_registry_preserves_reviewed_metadata_and_flags_missing_columns():
    existing = FieldRegistry(
        reviewed=True,
        fields=[
            FieldEntry(
                column="AccNoFull",
                source_file="accession_history.csv",
                data_type="string",
                description="Human reviewed description.",
                tier="useful",
                db_mapping="accession.accession_number",
                sample_values=["old"],
                null_rate=0.1,
                unique_rate=0.9,
                notes="Keep this note.",
            ),
            FieldEntry(
                column="LegacyField",
                source_file="accession_history.csv",
                data_type="string",
                description="Legacy only.",
                tier="niche",
                db_mapping=None,
                sample_values=["legacy"],
                null_rate=0.5,
                unique_rate=0.2,
                notes="Old export setting.",
            ),
        ],
    )
    fresh = FieldRegistry(
        fields=[
            FieldEntry(
                column="AccNoFull",
                source_file="accession_history.csv, accession_item_history.csv",
                data_type="string",
                description="Auto description.",
                tier="core",
                db_mapping="accession.accession_number",
                sample_values=["1952-0001"],
                null_rate=0.0,
                unique_rate=1.0,
                notes="Auto note.",
            ),
            FieldEntry(
                column="NewField",
                source_file="accession_history.csv",
                data_type="integer",
                description="New field.",
                tier="useful",
                db_mapping=None,
                sample_values=["3"],
                null_rate=0.25,
                unique_rate=0.5,
                notes="",
            ),
        ]
    )

    merged = merge_registry(existing, fresh)
    by_column = {entry.column: entry for entry in merged.fields}

    assert merged.reviewed is True
    assert by_column["AccNoFull"].description == "Human reviewed description."
    assert by_column["AccNoFull"].tier == "useful"
    assert by_column["AccNoFull"].notes == "Keep this note."
    assert by_column["AccNoFull"].sample_values == ["1952-0001"]
    assert by_column["LegacyField"].missing is True
    assert "Missing from latest CSV scan." in by_column["LegacyField"].notes
    assert by_column["NewField"].description == "New field."


def test_filter_and_format_registry_by_tier():
    registry = FieldRegistry(
        fields=[
            FieldEntry("AccNoFull", "accession_history.csv", "string", "Accession number.", "core", "accession.accession_number"),
            FieldEntry("CommonName_ja", "accession_history.csv", "string", "Japanese common name.", "niche", None),
        ]
    )

    filtered = filter_fields(registry, tier="core")
    rendered = format_registry(registry, tier="core", show_stats=True)

    assert [entry.column for entry in filtered] == ["AccNoFull"]
    assert "AccNoFull [core] string" in rendered
    assert "CommonName_ja" not in rendered
    assert "stats: null_rate=0.00 unique_rate=0.00" in rendered
