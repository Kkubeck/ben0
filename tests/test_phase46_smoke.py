from __future__ import annotations

import json
from pathlib import Path

from ben0.db.session import get_session, init_db, reset_singletons
from ben0.export.basic_export import export_accessions
from ben0.ingest.csv_ingest import ingest_all_csvs
from ben0.ingest.document_ingest import ingest_documents
from ben0.retrieval.index import build_index
from ben0.retrieval.search import search_index
from ben0.synthetic.generate_dataset import generate_all
from ben0.tickets.service import create_tickets_from_issues
from ben0.validation.engine import run_validation


def test_phase46_end_to_end(tmp_path: Path):
    synthetic_dir = tmp_path / "synthetic"
    db_url = f"sqlite:///{tmp_path / 'ben0-test.db'}"
    export_path = tmp_path / "export.json"

    reset_singletons()
    generate_all(synthetic_dir)
    init_db(db_url)
    ingest_all_csvs(synthetic_dir, db_url=db_url)
    ingest_documents(synthetic_dir / "documents", db_url=db_url)

    session = get_session(db_url)
    try:
        validation_summary = run_validation(session)
        assert validation_summary["total"] > 0

        indexed = build_index(session)
        assert indexed > 0

        results = search_index(session, "provenance", limit=5)
        assert results
        assert "chunk_id" in results[0]

        tickets = create_tickets_from_issues(session)
        assert tickets

        export_summary = export_accessions(session, export_path)
        assert export_summary["exported"] > 0
    finally:
        session.close()
        reset_singletons()

    exported = json.loads(export_path.read_text(encoding="utf-8"))
    assert exported
    assert "accession_number" in exported[0]
