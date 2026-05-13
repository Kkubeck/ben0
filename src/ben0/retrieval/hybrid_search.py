"""Hybrid keyword + vector retrieval for BEN-0."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from sqlalchemy.orm import Session

from .embeddings import EmbeddingModel
from .search import search_index
from .vector_index import search_vector_index, vector_index_exists

logger = logging.getLogger(__name__)
RRF_K = 60


def hybrid_search(
    session: Session,
    query: str,
    vector_dir: Path,
    *,
    embedding_model: EmbeddingModel | None = None,
    limit: int = 10,
    fts_weight: float = 1.0,
    vector_weight: float = 1.0,
    reliability_tier: str | None = None,
    source_type: str | None = None,
    lane: str | None = None,
    document_type: str | None = None,
) -> list[dict]:
    """Hybrid search combining FTS5 keyword + vector semantic results via RRF."""
    fts_results = search_index(
        session,
        query,
        limit=limit * 2,
        reliability_tier=reliability_tier,
        source_type=source_type,
        lane=lane,
        document_type=document_type,
    )

    if not vector_index_exists(vector_dir):
        logger.warning("Vector index not found at %s; falling back to FTS5-only results.", vector_dir)
        return _fts_only_results(fts_results, limit)

    model = embedding_model or EmbeddingModel()
    try:
        query_embedding = model.embed_query(query)
        vector_results = search_vector_index(
            vector_dir,
            query_embedding,
            limit=limit * 2,
            reliability_tier=reliability_tier,
            source_type=source_type,
            lane=lane,
            document_type=document_type,
        )
    except (FileNotFoundError, ImportError) as exc:
        logger.warning("Vector search unavailable; falling back to FTS5-only results: %s", exc)
        return _fts_only_results(fts_results, limit)

    merged: dict[str, dict] = {}
    rrf_scores: defaultdict[str, float] = defaultdict(float)

    for rank, result in enumerate(fts_results):
        chunk_id = str(result["chunk_id"])
        merged[chunk_id] = dict(result)
        rrf_scores[chunk_id] += fts_weight * (1.0 / (RRF_K + rank + 1))

    for rank, result in enumerate(vector_results):
        chunk_id = str(result["chunk_id"])
        if chunk_id not in merged:
            merged[chunk_id] = dict(result)
        rrf_scores[chunk_id] += vector_weight * (1.0 / (RRF_K + rank + 1))

    ordered = sorted(merged.items(), key=lambda item: rrf_scores[item[0]], reverse=True)
    results: list[dict] = []
    for chunk_id, payload in ordered[:limit]:
        row = dict(payload)
        row.setdefault("snippet", None)
        row["rrf_score"] = rrf_scores[chunk_id]
        results.append(row)
    return results


def _fts_only_results(results: list[dict], limit: int) -> list[dict]:
    fallback: list[dict] = []
    for rank, result in enumerate(results[:limit]):
        row = dict(result)
        row["rrf_score"] = 1.0 / (RRF_K + rank + 1)
        fallback.append(row)
    return fallback
