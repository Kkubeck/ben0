from __future__ import annotations

from pathlib import Path

from ben0.assistant.model_adapters import MockModelAdapter
from ben0.assistant.orchestrator import AssistantOrchestrator
from ben0.dashboard.metrics import calculate_metrics
from ben0.db.session import get_session, init_db, reset_singletons
from ben0.ingest.csv_ingest import ingest_all_csvs
from ben0.ingest.document_ingest import ingest_documents
from ben0.reports.markdown_report import generate_markdown_report
from ben0.retrieval.index import build_index
from ben0.synthetic.generate_dataset import generate_all
from ben0.validation.engine import run_validation


def test_phase78_report_and_assistant(tmp_path: Path):
    synthetic_dir = tmp_path / "synthetic"
    db_url = f"sqlite:///{tmp_path / 'ben0-phase78.db'}"

    reset_singletons()
    generate_all(synthetic_dir)
    init_db(db_url)
    ingest_all_csvs(synthetic_dir, db_url=db_url)
    ingest_documents(synthetic_dir / "documents", db_url=db_url)

    session = get_session(db_url)
    try:
        run_validation(session)
        build_index(session)

        metrics = calculate_metrics(session)
        assert metrics["total_accessions"] > 0
        assert "provenance_coverage_pct" in metrics

        report = generate_markdown_report(session)
        assert "BEN-0 Collection Data Health Report" in report
        assert "## Data Quality Summary" in report

        orchestrator = AssistantOrchestrator(
            adapter=MockModelAdapter(),
            session_factory=lambda: get_session(db_url),
        )
        answer = orchestrator.answer("which accessions have missing provenance?")
        assert "[accession:" in answer or "[validation_issue:" in answer
        assert "provenance" in answer.lower()
    finally:
        session.close()
        reset_singletons()
