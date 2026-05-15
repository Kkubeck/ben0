"""Query the SQLite FTS5 retrieval index."""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from .index import FTS_TABLE

# FTS5 special characters that break MATCH syntax
_FTS5_SPECIAL = re.compile(r'["\*\(\)\{\}\[\]\^~<>\?:!@#$%&;,./\\]')


def _sanitize_fts5_query(raw: str) -> str:
    """Strip FTS5 metacharacters from a natural-language query.

    Keeps alphanumeric tokens and simple boolean words (AND/OR/NOT)
    that FTS5 understands. Everything else is removed or replaced
    with spaces so the query degrades to a bag-of-words match.
    """
    cleaned = _FTS5_SPECIAL.sub(' ', raw)
    # Collapse whitespace and strip
    return ' '.join(cleaned.split())


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

    cleaned_query = _sanitize_fts5_query(query or "")
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
