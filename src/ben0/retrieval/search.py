"""Query the SQLite FTS5 retrieval index."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from .index import FTS_TABLE


def search_index(
    session: Session,
    query: str,
    *,
    limit: int = 10,
    reliability_tier: str | None = None,
    source_type: str | None = None,
    lane: str | None = None,
    document_type: str | None = None,
) -> list[dict[str, str | float | None]]:
    bind = session.get_bind()
    if bind.dialect.name != "sqlite":
        raise RuntimeError("The prototype retrieval index currently requires SQLite/FTS5.")

    cleaned_query = (query or "").strip()
    if not cleaned_query:
        return []

    where_clauses = [f"{FTS_TABLE} MATCH :query"]
    params: dict[str, str | int] = {"query": cleaned_query, "limit": limit}

    filter_map = {
        "reliability_tier": reliability_tier,
        "source_type": source_type,
        "lane": lane,
        "document_type": document_type,
    }
    for field_name, value in filter_map.items():
        if value is not None:
            where_clauses.append(f"{field_name} = :{field_name}")
            params[field_name] = value

    sql = text(
        f"""
        SELECT
            chunk_id,
            document_name,
            source_type,
            snippet({FTS_TABLE}, 0, '[', ']', ' … ', 18) AS snippet,
            text,
            accession_id,
            item_id,
            taxon_id,
            document_type,
            reliability_tier,
            source_file_path,
            date,
            lane,
            bm25({FTS_TABLE}) AS score
        FROM {FTS_TABLE}
        WHERE {' AND '.join(where_clauses)}
        ORDER BY score
        LIMIT :limit
        """
    )
    rows = session.execute(sql, params).mappings().all()
    return [dict(row) for row in rows]
