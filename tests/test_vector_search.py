from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path

import pytest

from ben0.db.models import Accession, Document, Event, Item, Source, SourceChunk
from ben0.db.session import get_session, init_db, reset_singletons
from ben0.retrieval.embeddings import EmbeddingModel
from ben0.retrieval.hybrid_search import hybrid_search
from ben0.retrieval.index import build_index
from ben0.retrieval.vector_index import VECTOR_TABLE, build_vector_index, search_vector_index

LANCEDB_AVAILABLE = importlib.util.find_spec("lancedb") is not None


class MockEmbeddingModel:
    def __init__(self, dimension: int = 8):
        self._dimension = dimension
        self._keywords = [
            "cedar",
            "manning",
            "policy",
            "nursery",
            "source",
            "display",
            "exchange",
            "staff",
        ]

    @property
    def dimension(self) -> int:
        return self._dimension

    def _embed(self, text: str) -> list[float]:
        lowered = text.lower()
        values = [1.0 if keyword in lowered else 0.0 for keyword in self._keywords]
        if len(values) < self._dimension:
            values.extend([0.0] * (self._dimension - len(values)))
        return values[: self._dimension]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return self._embed(query)


def _session_for(tmp_path: Path, name: str):
    db_url = f"sqlite:///{tmp_path / name}"
    reset_singletons()
    init_db(db_url)
    return get_session(db_url)


def _seed_records(session):
    accession = Accession(
        accession_number="2005-0234",
        accession_date="2005-03-12",
        notes="Cedar accession note from Manning Park.",
        source_file="/imports/accessions.csv",
    )
    session.add(accession)
    session.flush()

    item = Item(
        accession_id=accession.id,
        item_label="2005-0234.01",
        planting_date="2006-04-01",
        notes="Cedar item note in nursery bed.",
        source_file="/imports/items.csv",
    )
    session.add(item)
    session.flush()

    document = Document(
        filename="policy.txt",
        document_type="policy",
        title="Policy",
        full_text="Cedar policy guidance for the living collection.",
        character_count=48,
        source_file="/imports/policy.txt",
    )
    session.add(document)
    session.flush()

    session.add(
        SourceChunk(
            document_id=document.id,
            chunk_index=0,
            chunk_text="Cedar policy guidance for the living collection.",
            char_start=0,
            char_end=48,
            linked_accession_id=accession.id,
        )
    )

    event = Event(
        accession_id=accession.id,
        item_id=item.id,
        event_type="planted",
        event_date="2006-05-01",
        notes="Cedar planted by staff for display bed.",
        source_file="/imports/events.csv",
    )
    source = Source(
        source_name="Exchange Program",
        notes="Cedar source note from exchange memo.",
        source_file="/imports/sources.csv",
    )
    session.add_all([event, source])
    session.commit()


def test_embedding_model_embed_texts_and_dimension(monkeypatch):
    class FakeTextEmbedding:
        def __init__(self, model_name: str, cache_dir: str | None = None):
            self.model_name = model_name
            self.cache_dir = cache_dir

        def embed(self, texts):
            for index, _text in enumerate(texts, start=1):
                yield [float(index)] * 8

        def query_embed(self, texts):
            for _text in texts:
                yield [0.5] * 8

    monkeypatch.setitem(sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=FakeTextEmbedding))

    model = EmbeddingModel(cache_dir=Path("/tmp/embeddings"))
    vectors = model.embed_texts(["alpha", "beta"])

    assert len(vectors) == 2
    assert all(len(vector) == 8 for vector in vectors)
    assert model.dimension == 8
    assert vectors[0] != vectors[1]


def test_embedding_model_embed_query(monkeypatch):
    class FakeTextEmbedding:
        def __init__(self, model_name: str, cache_dir: str | None = None):
            pass

        def embed(self, texts):
            for _text in texts:
                yield [1.0] * 4

        def query_embed(self, texts):
            for _text in texts:
                yield [0.25, 0.5, 0.75, 1.0]

    monkeypatch.setitem(sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=FakeTextEmbedding))

    model = EmbeddingModel()
    assert model.embed_query("cedar policy") == [0.25, 0.5, 0.75, 1.0]


@pytest.mark.skipif(not LANCEDB_AVAILABLE, reason="lancedb is not installed")
def test_build_vector_index_creates_table(tmp_path: Path):
    import lancedb

    session = _session_for(tmp_path, "vector-index.db")
    try:
        _seed_records(session)
        count = build_vector_index(session, tmp_path / "vector", embedding_model=MockEmbeddingModel())
        db = lancedb.connect(str(tmp_path / "vector"))
        table = db.open_table(VECTOR_TABLE)
        schema_names = set(table.to_arrow().schema.names)

        assert count == 5
        assert {"chunk_id", "document_name", "vector", "lane", "reliability_tier"}.issubset(schema_names)
    finally:
        session.close()
        reset_singletons()


@pytest.mark.skipif(not LANCEDB_AVAILABLE, reason="lancedb is not installed")
def test_search_vector_index_returns_expected_fields(tmp_path: Path):
    session = _session_for(tmp_path, "vector-search.db")
    try:
        _seed_records(session)
        vector_dir = tmp_path / "vector"
        model = MockEmbeddingModel()
        build_vector_index(session, vector_dir, embedding_model=model)

        results = search_vector_index(vector_dir, model.embed_query("cedar policy"), limit=3)

        assert results
        expected = {
            "chunk_id",
            "document_name",
            "source_type",
            "text",
            "accession_id",
            "item_id",
            "taxon_id",
            "document_type",
            "reliability_tier",
            "source_file_path",
            "date",
            "lane",
            "score",
        }
        assert expected == set(results[0].keys())
    finally:
        session.close()
        reset_singletons()


@pytest.mark.skipif(not LANCEDB_AVAILABLE, reason="lancedb is not installed")
def test_search_vector_index_filters(tmp_path: Path):
    session = _session_for(tmp_path, "vector-filters.db")
    try:
        _seed_records(session)
        vector_dir = tmp_path / "vector"
        model = MockEmbeddingModel()
        build_vector_index(session, vector_dir, embedding_model=model)

        official = search_vector_index(
            vector_dir,
            model.embed_query("cedar"),
            limit=10,
            reliability_tier="official",
        )
        lane_a = search_vector_index(vector_dir, model.embed_query("cedar"), limit=10, lane="A")

        assert {row["source_type"] for row in official} == {"accession_note", "item_note"}
        assert lane_a and all(row["lane"] == "A" for row in lane_a)
    finally:
        session.close()
        reset_singletons()


@pytest.mark.skipif(not LANCEDB_AVAILABLE, reason="lancedb is not installed")
def test_hybrid_search_returns_rrf_scores(tmp_path: Path):
    session = _session_for(tmp_path, "hybrid-search.db")
    try:
        _seed_records(session)
        build_index(session)
        vector_dir = tmp_path / "vector"
        model = MockEmbeddingModel()
        build_vector_index(session, vector_dir, embedding_model=model)

        results = hybrid_search(session, "cedar policy", vector_dir, embedding_model=model, limit=3)

        assert results
        assert "rrf_score" in results[0]
        assert results[0]["rrf_score"] > 0
        assert all("snippet" in row for row in results)
    finally:
        session.close()
        reset_singletons()


def test_hybrid_search_graceful_fallback_without_vector_index(tmp_path: Path, caplog):
    session = _session_for(tmp_path, "hybrid-fallback.db")
    try:
        _seed_records(session)
        build_index(session)
        caplog.set_level(logging.WARNING)

        results = hybrid_search(session, "cedar policy", tmp_path / "missing-vector", limit=3)

        assert results
        assert all("rrf_score" in row for row in results)
        assert "falling back to FTS5-only" in caplog.text
    finally:
        session.close()
        reset_singletons()


@pytest.mark.skipif(not LANCEDB_AVAILABLE, reason="lancedb is not installed")
def test_vector_and_hybrid_results_have_consistent_keys(tmp_path: Path):
    session = _session_for(tmp_path, "vector-hybrid-keys.db")
    try:
        _seed_records(session)
        build_index(session)
        vector_dir = tmp_path / "vector"
        model = MockEmbeddingModel()
        build_vector_index(session, vector_dir, embedding_model=model)

        vector_results = search_vector_index(vector_dir, model.embed_query("cedar"), limit=2)
        hybrid_results = hybrid_search(session, "cedar", vector_dir, embedding_model=model, limit=2)

        assert len({frozenset(row.keys()) for row in vector_results}) == 1
        assert len({frozenset(row.keys()) for row in hybrid_results}) == 1
    finally:
        session.close()
        reset_singletons()
