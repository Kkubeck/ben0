"""Vector embedding index backed by LanceDB."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pyarrow as pa
from sqlalchemy.orm import Session

from .embeddings import EmbeddingModel
from .index import IndexEntry, _iter_entries

VECTOR_TABLE = "ben0_vectors"
RESULT_FIELDS = (
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
)


def build_vector_index(
    session: Session,
    vector_dir: Path,
    *,
    embedding_model: EmbeddingModel | None = None,
    reset: bool = True,
    batch_size: int = 256,
) -> int:
    """Build the LanceDB vector index from all indexed entries. Returns row count."""
    lancedb = _import_lancedb()
    model = embedding_model or EmbeddingModel()
    vector_dir.mkdir(parents=True, exist_ok=True)

    entries = list(_iter_entries(session))
    rows: list[dict[str, object]] = []
    for start in range(0, len(entries), batch_size):
        batch = entries[start : start + batch_size]
        vectors = model.embed_texts([entry.text for entry in batch])
        for entry, vector in zip(batch, vectors, strict=True):
            rows.append(_entry_row(entry, vector))

    db = lancedb.connect(str(vector_dir))
    if reset and vector_index_exists(vector_dir):
        db.drop_table(VECTOR_TABLE)

    if rows:
        db.create_table(VECTOR_TABLE, data=rows, mode="overwrite")
    else:
        db.create_table(VECTOR_TABLE, schema=_table_schema(model.dimension), mode="overwrite")

    return len(rows)


def search_vector_index(
    vector_dir: Path,
    query_embedding: list[float],
    *,
    limit: int = 10,
    reliability_tier: str | None = None,
    source_type: str | None = None,
    lane: str | None = None,
    document_type: str | None = None,
) -> list[dict]:
    """Search the vector index. Returns results matching search_index() metadata."""
    lancedb = _import_lancedb()
    if not vector_index_exists(vector_dir):
        raise FileNotFoundError(f"Vector index table '{VECTOR_TABLE}' was not found in {vector_dir}.")

    db = lancedb.connect(str(vector_dir))
    table = db.open_table(VECTOR_TABLE)
    query = table.search(query_embedding).metric("cosine")

    where_clause = _where_clause(
        reliability_tier=reliability_tier,
        source_type=source_type,
        lane=lane,
        document_type=document_type,
    )
    if where_clause:
        query = query.where(where_clause, prefilter=True)

    rows = query.limit(limit).to_list()
    results: list[dict[str, object]] = []
    for row in rows:
        distance = row.get("_distance")
        result = {field: row.get(field) for field in RESULT_FIELDS}
        result["score"] = None if distance is None else 1.0 - float(distance)
        results.append(result)
    return results


def vector_index_exists(vector_dir: Path) -> bool:
    """Return True when the LanceDB vector table exists."""
    try:
        lancedb = _import_lancedb()
    except ImportError:
        return False
    if not vector_dir.exists():
        return False
    db = lancedb.connect(str(vector_dir))
    return VECTOR_TABLE in set(db.list_tables().tables)


def _entry_row(entry: IndexEntry, vector: list[float]) -> dict[str, object]:
    row = asdict(entry)
    row["vector"] = [float(value) for value in vector]
    return row


def _table_schema(dimension: int) -> pa.Schema:
    return pa.schema(
        [
            pa.field("source_type", pa.string()),
            pa.field("source_record_id", pa.string()),
            pa.field("chunk_id", pa.string()),
            pa.field("document_name", pa.string()),
            pa.field("text", pa.string()),
            pa.field("accession_id", pa.string()),
            pa.field("item_id", pa.string()),
            pa.field("taxon_id", pa.string()),
            pa.field("document_type", pa.string()),
            pa.field("reliability_tier", pa.string()),
            pa.field("source_file_path", pa.string()),
            pa.field("date", pa.string()),
            pa.field("lane", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dimension)),
        ]
    )


def _where_clause(
    *,
    reliability_tier: str | None = None,
    source_type: str | None = None,
    lane: str | None = None,
    document_type: str | None = None,
) -> str | None:
    clauses: list[str] = []
    for field_name, value in {
        "reliability_tier": reliability_tier,
        "source_type": source_type,
        "lane": lane,
        "document_type": document_type,
    }.items():
        if value is not None:
            escaped = value.replace("'", "''")
            clauses.append(f"{field_name} = '{escaped}'")
    return " AND ".join(clauses) or None


def _import_lancedb():
    try:
        import lancedb
    except ImportError as exc:  # pragma: no cover - exercised in integration environments
        raise ImportError(
            "Vector search dependencies are not installed. Install with `pip install ben0[vectors]`."
        ) from exc
    return lancedb
