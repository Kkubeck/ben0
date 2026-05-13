from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import select

from ben0.db.models import Accession, Item, Location, Provenance, Taxon
from ben0.db.session import get_session, init_db, reset_singletons
from ben0.ingest.csv_ingest import ingest_all_csvs
from ben0.ingest.iris_ingest import _parse_iris_date, _read_csv, ingest_iris_csvs
from ben0.synthetic.generate_dataset import generate_all


ACCESSION_HEADERS = [
    "AccNoFull",
    "AccYear",
    "AccComment",
    "TaxonName",
    "TaxonNameFull",
    "Genus",
    "Species",
    "Family",
    "FamilyEx",
    "ProvenanceCode",
    "Collector",
    "CollDate",
    "CountryName",
    "Locality",
    "ContactNameFull",
    "ContactCode",
    "IUCNRedListCode",
    "MaterialType",
    "RecDate",
    "RestrictPublish",
    "Cultivar",
    "InfraName1",
    "InfraType1",
    "CoordLatDD",
    "CoordLongDD",
    "Habitat",
]

ITEM_HEADERS = [
    "\ufeffCurrent",
    "AccNoFull",
    "ItemNo",
    "ItemAccNoFull",
    "ItemStatus",
    "ItemStatusCode",
    "ItemStatusDate",
    "ItemStatusDateFrom",
    "ItemStatusDateTo",
    "ItemLocationCode",
    "ItemLocationName",
    "ItemComment",
    "ItemCondition",
    "ItemStatusPerson",
    "ItemStatusType",
    "PropHistCode",
]


def _write_iris_fixture(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)

    accession_rows = [
        [
            "1952-0001",
            "1952",
            "",
            "Ilex crenata",
            "Ilex crenata Thunb.",
            "Ilex",
            "crenata",
            "Aquifoliaceae",
            "Aquifoliaceae",
            "G",
            "",
            "",
            "",
            "",
            "Buildings & Grounds (ex Physical Plant)",
            "PHYSICAL PLANT",
            "",
            "plant",
            "1/1/1952",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
        [
            "2005-0234",
            "2005",
            "From seed exchange",
            "Abies lasiocarpa",
            "Abies lasiocarpa (Hook.) Nutt.",
            "Abies",
            "lasiocarpa",
            "Pinaceae",
            "Pinaceae",
            "W",
            "J. Smith",
            "6/15/2004",
            "Canada",
            "Manning Park",
            "Royal Botanic Gardens Kew",
            "RBGK",
            "LC",
            "seed",
            "3/12/2005",
            "1",
            "",
            "",
            "",
            "49.12",
            "-120.78",
            "Subalpine forest",
        ],
    ]

    item_rows = [
        [
            ">>>",
            "1952-0001",
            "1",
            "1952-0001.01",
            "Planted",
            "P",
            "1/1/1952",
            "1/1/1952",
            "12/31/9999",
            "5A",
            "North Nitobe Memorial Garden",
            "",
            "",
            "admin",
            "Existing",
            "",
        ],
        [
            "",
            "1952-0001",
            "2",
            "1952-0001.02",
            "Dead",
            "D",
            "6/15/2010",
            "6/15/2010",
            "6/15/2010",
            "3B",
            "Asian Garden",
            "",
            "Poor",
            "curator1",
            "Historical",
            "",
        ],
        [
            ">>>",
            "2005-0234",
            "1",
            "2005-0234.01",
            "Planted",
            "P",
            "5/20/2006",
            "5/20/2006",
            "12/31/9999",
            "ALP1",
            "Alpine Garden",
            "Strong growth",
            "Good",
            "admin",
            "Existing",
            "S",
        ],
    ]

    with (data_dir / "accession_history.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(ACCESSION_HEADERS)
        writer.writerows(accession_rows)

    with (data_dir / "accession_item_history.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(ITEM_HEADERS)
        writer.writerows(item_rows)


def test_synthetic_ingest_end_to_end(tmp_path: Path):
    synthetic_dir = tmp_path / "synthetic"
    db_url = f"sqlite:///{tmp_path / 'synthetic.db'}"

    reset_singletons()
    generate_all(synthetic_dir)
    init_db(db_url)
    counts = ingest_all_csvs(synthetic_dir, db_url=db_url)

    session = get_session(db_url)
    try:
        assert counts["taxa"] > 0
        assert counts["accessions"] > 0
        assert len(session.scalars(select(Taxon)).all()) == counts["taxa"]
        assert len(session.scalars(select(Accession)).all()) >= counts["accessions"]
    finally:
        session.close()
        reset_singletons()


def test_iris_ingest_creates_taxa(tmp_path: Path):
    data_dir = tmp_path / "iris"
    db_url = f"sqlite:///{tmp_path / 'iris-taxa.db'}"

    _write_iris_fixture(data_dir)
    reset_singletons()
    init_db(db_url)
    counts = ingest_iris_csvs(data_dir, db_url=db_url)

    session = get_session(db_url)
    try:
        taxa = session.scalars(select(Taxon).order_by(Taxon.scientific_name)).all()
        assert counts["taxa"] == 2
        assert [taxon.scientific_name for taxon in taxa] == ["Abies lasiocarpa", "Ilex crenata"]
    finally:
        session.close()
        reset_singletons()


def test_iris_ingest_creates_accessions(tmp_path: Path):
    data_dir = tmp_path / "iris"
    db_url = f"sqlite:///{tmp_path / 'iris-accessions.db'}"

    _write_iris_fixture(data_dir)
    reset_singletons()
    init_db(db_url)
    ingest_iris_csvs(data_dir, db_url=db_url)

    session = get_session(db_url)
    try:
        accession = session.scalar(
            select(Accession).where(Accession.accession_number == "2005-0234")
        )
        provenance = session.scalar(
            select(Provenance).join(Accession).where(Accession.accession_number == "2005-0234")
        )
        assert accession is not None
        assert accession.accession_number_normalized == "2005-0234"
        assert accession.accession_date == "2005-03-12"
        assert accession.accession_year == 2005
        assert accession.is_sensitive is True
        assert "Accession comment: From seed exchange" in (accession.notes or "")
        assert provenance is not None
        assert provenance.origin_code == "W"
        assert provenance.collection_date == "2004-06-15"
        assert provenance.collection_country == "Canada"
        assert provenance.collection_locality == "Manning Park"
        assert "Coordinates: 49.12, -120.78" in (provenance.collection_notes or "")
    finally:
        session.close()
        reset_singletons()


def test_iris_ingest_creates_items(tmp_path: Path):
    data_dir = tmp_path / "iris"
    db_url = f"sqlite:///{tmp_path / 'iris-items.db'}"

    _write_iris_fixture(data_dir)
    reset_singletons()
    init_db(db_url)
    counts = ingest_iris_csvs(data_dir, db_url=db_url)

    session = get_session(db_url)
    try:
        item = session.scalar(select(Item).where(Item.item_label == "2005-0234.01"))
        locations = session.scalars(select(Location).order_by(Location.location_code)).all()
        assert counts["items"] == 3
        assert item is not None
        assert item.life_status == "living"
        assert item.is_current is True
        assert item.planting_date == "2006-05-20"
        assert item.current_location is not None
        assert item.current_location.location_code == "ALP1"
        assert [location.location_code for location in locations] == ["3B", "5A", "ALP1"]
    finally:
        session.close()
        reset_singletons()


def test_iris_bom_handling(tmp_path: Path):
    data_dir = tmp_path / "iris"
    _write_iris_fixture(data_dir)

    headers, rows, _ = _read_csv(data_dir / "accession_item_history.csv")

    assert headers[0] == "Current"
    assert "Current" in rows[0]
    assert "\ufeffCurrent" not in rows[0]


def test_iris_sentinel_dates(tmp_path: Path):
    data_dir = tmp_path / "iris"
    _write_iris_fixture(data_dir)

    assert _parse_iris_date("12/31/9999") is None
    assert _parse_iris_date("9999-12-31") is None


def test_iris_date_parsing(tmp_path: Path):
    data_dir = tmp_path / "iris"
    db_url = f"sqlite:///{tmp_path / 'iris-dates.db'}"

    _write_iris_fixture(data_dir)
    reset_singletons()
    init_db(db_url)
    ingest_iris_csvs(data_dir, db_url=db_url)

    session = get_session(db_url)
    try:
        accession = session.scalar(
            select(Accession).where(Accession.accession_number == "2005-0234")
        )
        item = session.scalar(select(Item).where(Item.item_label == "1952-0001.01"))
        provenance = session.scalar(
            select(Provenance).join(Accession).where(Accession.accession_number == "2005-0234")
        )
        assert accession is not None and accession.accession_date == "2005-03-12"
        assert item is not None and item.planting_date == "1952-01-01"
        assert provenance is not None and provenance.collection_date == "2004-06-15"
    finally:
        session.close()
        reset_singletons()


def test_iris_location_extraction(tmp_path: Path):
    data_dir = tmp_path / "iris"
    db_url = f"sqlite:///{tmp_path / 'iris-locations.db'}"

    _write_iris_fixture(data_dir)
    reset_singletons()
    init_db(db_url)
    counts = ingest_iris_csvs(data_dir, db_url=db_url)

    session = get_session(db_url)
    try:
        locations = session.scalars(select(Location).order_by(Location.location_code)).all()
        assert counts["locations"] == 3
        assert [(location.location_code, location.location_name) for location in locations] == [
            ("3B", "Asian Garden"),
            ("5A", "North Nitobe Memorial Garden"),
            ("ALP1", "Alpine Garden"),
        ]
    finally:
        session.close()
        reset_singletons()
