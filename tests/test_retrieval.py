from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from ben0.db.models import Document
from ben0.db.session import get_session, init_db, reset_singletons
from ben0.retrieval.index import FTS_TABLE, build_index
from ben0.retrieval.search import search_index


def _session_for(tmp_path: Path, name: str):
    db_url = f"sqlite:///{tmp_path / name}"
    reset_singletons()
    init_db(db_url)
    return db_url, get_session(db_url)


def test_build_index_creates_chunks(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "retrieval-index.db")
    try:
        session.add(
            Document(
                filename="policy.txt",
                document_type="policy",
                title="Policy",
                full_text="Provenance records support evidence-based stewardship. " * 20,
                character_count=900,
            )
        )
        session.commit()

        count = build_index(session)
        stored = session.execute(text(f"SELECT COUNT(*) FROM {FTS_TABLE}")).scalar_one()
        assert count > 0
        assert stored == count
    finally:
        session.close()
        reset_singletons()


def test_search_returns_relevant_results(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "retrieval-search.db")
    try:
        session.add(
            Document(
                filename="scope.txt",
                document_type="policy",
                title="Scope",
                full_text="Wild provenance from Manning Park is a conservation priority for the living collection.",
                character_count=86,
            )
        )
        session.commit()

        build_index(session)
        results = search_index(session, "Manning provenance", limit=5)
        assert results
        assert results[0]["document_name"] == "scope.txt"
        assert "provenance" in (results[0]["snippet"] or "").lower()
    finally:
        session.close()
        reset_singletons()


def test_search_empty_query(tmp_path: Path):
    db_url, session = _session_for(tmp_path, "retrieval-empty.db")
    try:
        build_index(session)
        assert search_index(session, "", limit=5) == []
        assert search_index(session, "   ", limit=5) == []
    finally:
        session.close()
        reset_singletons()
