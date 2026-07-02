"""Natural-language-to-SQL conversion and safe query execution for ben0."""

from __future__ import annotations

import re
import threading
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

# ---------------------------------------------------------------------------
# Data definitions
# ---------------------------------------------------------------------------

# SchemaDescription : str
# Interpretation: a concise, LLM-friendly description of all visible tables
# and their columns, omitting sensitive_data_flag.
# Example: "Table: accession (garden acquisitions)\n  - id: VARCHAR (pk)\n  ..."

# SQLResult : list[dict[str, Any]]
# Interpretation: rows returned by a safe SELECT, keyed by column name.
# Example: [{"accession_number": "1984-0001", "taxon_name_verbatim": "Acer ..."}]

# ValidationResult : tuple[bool, str]
# Interpretation: (is_valid, error_message). error_message is "" when valid.
# Example: (True, "") or (False, "Statement must begin with SELECT or WITH.")

_TABLE_DESCRIPTIONS: dict[str, str] = {
    "accession": "garden acquisitions",
    "taxon": "taxonomic names",
    "item": "individual plants/material entities",
    "event": "history events for accessions/items",
    "provenance": "origin/source information for accessions",
    "location": "garden beds/sections/nursery zones",
    "source": "originating institutions/collectors",
    "document": "ingested text documents",
    "source_chunk": "chunked passages for retrieval",
    "conservation_status": "conservation assessments",
    "validation_issue": "data quality issues",
    "correction_ticket": "proposed corrections",
}

_EXCLUDED_TABLES = {"sensitive_data_flag"}

_DANGEROUS_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|PRAGMA|ATTACH)\b",
    re.IGNORECASE,
)

_SQL_BLOCK_RE = re.compile(r"```sql\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_BARE_SELECT_RE = re.compile(r"((?:WITH|SELECT)\s+.*)", re.DOTALL | re.IGNORECASE)

# Keywords that signal aggregation or comparison, routing to sql.
_SQL_SIGNALS = re.compile(
    r"\b(how many|count|total|average|percentage|proportion|number of"
    r"|more than|fewer than|most|least|between"
    r"|list all|which \w+ have|show me all \w+ where)\b",
    re.IGNORECASE,
)

# Keywords that signal narrative/document questions, routing to rag.
_RAG_SIGNALS = re.compile(
    r"\b(why|explain|describe|tell me about|document|policy|procedure)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# generate_schema_description
# ---------------------------------------------------------------------------

def generate_schema_description(engine: Engine) -> str:
    """Return a concise LLM-friendly schema description, excluding sensitive tables."""
    insp = inspect(engine)
    table_names = [t for t in insp.get_table_names() if t not in _EXCLUDED_TABLES]

    lines: list[str] = []
    for table in sorted(table_names):
        human = _TABLE_DESCRIPTIONS.get(table, "")
        header = f"Table: {table} ({human})" if human else f"Table: {table}"
        lines.append(header)

        columns = insp.get_columns(table)
        pk_cols = set(insp.get_pk_constraint(table).get("constrained_columns", []))
        fk_map: dict[str, str] = {}
        for fk in insp.get_foreign_keys(table):
            for col in fk["constrained_columns"]:
                ref_table = fk["referred_table"]
                ref_cols = fk.get("referred_columns", [])
                ref_col = ref_cols[0] if ref_cols else "id"
                fk_map[col] = f"{ref_table}.{ref_col}"

        for col in columns:
            col_name = col["name"]
            col_type = str(col["type"])
            tags: list[str] = []
            if col_name in pk_cols:
                tags.append("pk")
            if col_name in fk_map:
                tags.append(f"fk -> {fk_map[col_name]}")
            nullable = col.get("nullable", True)
            if not nullable and col_name not in pk_cols:
                tags.append("not null")
            tag_str = f" ({', '.join(tags)})" if tags else ""
            lines.append(f"  - {col_name}: {col_type}{tag_str}")

        lines.append("")

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# classify_query
# ---------------------------------------------------------------------------

def classify_query(question: str) -> str:
    """Return 'sql', 'rag', or 'hybrid' based on question content."""
    has_sql = bool(_SQL_SIGNALS.search(question))
    has_rag = bool(_RAG_SIGNALS.search(question))

    if has_sql and has_rag:
        return "hybrid"
    if has_sql:
        return "sql"
    if has_rag:
        return "rag"
    return "rag"


# ---------------------------------------------------------------------------
# generate_sql
# ---------------------------------------------------------------------------

def generate_sql(
    adapter: Any,
    question: str,
    schema: str,
    rules: list[str] | None = None,
) -> str:
    """Ask the LLM to convert a natural-language question to SQL and return the SQL string."""
    rules_block = ""
    if rules:
        formatted = "\n".join(f"- {r}" for r in rules)
        rules_block = f"\nBusiness rules to respect:\n{formatted}\n"

    system = (
        "You are a SQL assistant for a botanical garden database. "
        "Generate only SELECT queries. "
        "Always include LIMIT 100 unless a smaller limit is specified. "
        "Use proper JOIN syntax with ON clauses. "
        "Handle NULLs with IS NULL or COALESCE where appropriate. "
        "Return only the SQL, wrapped in a ```sql ... ``` code block."
    )

    prompt = (
        f"Database schema:\n{schema}\n"
        f"{rules_block}"
        f"\nQuestion: {question}\n"
        "Write a SQL SELECT query that answers this question."
    )

    response = adapter.generate(prompt, system=system)
    return _extract_sql(response)


def _extract_sql(response: str) -> str:
    """Pull the SQL statement out of the model response."""
    block_match = _SQL_BLOCK_RE.search(response)
    if block_match:
        return block_match.group(1).strip()

    bare_match = _BARE_SELECT_RE.search(response)
    if bare_match:
        return bare_match.group(1).strip()

    return response.strip()


# ---------------------------------------------------------------------------
# validate_sql
# ---------------------------------------------------------------------------

def validate_sql(sql: str) -> tuple[bool, str]:
    """Return (True, '') when sql is a safe SELECT, or (False, reason) otherwise."""
    if _DANGEROUS_KEYWORDS.search(sql):
        matched = _DANGEROUS_KEYWORDS.search(sql)
        keyword = matched.group(1).upper() if matched else "unknown"
        return False, f"Disallowed keyword: {keyword}."

    stripped = sql.strip()
    upper = stripped.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        return False, "Statement must begin with SELECT or WITH."

    return True, ""


# ---------------------------------------------------------------------------
# execute_safe_query
# ---------------------------------------------------------------------------

def execute_safe_query(
    engine: Engine,
    sql: str,
    limit: int = 100,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Validate, optionally add LIMIT, execute, and return rows as dicts."""
    is_valid, error = validate_sql(sql)
    if not is_valid:
        return []

    if not re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        sql = f"{sql.rstrip('; ')} LIMIT {limit}"

    result: list[dict[str, Any]] = []
    exc_holder: list[Exception] = []

    def _run() -> None:
        try:
            with engine.connect() as conn:
                rows = conn.execute(text(sql))
                keys = list(rows.keys())
                result.extend(dict(zip(keys, row)) for row in rows)
        except Exception as exc:
            exc_holder.append(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive() or exc_holder:
        return []

    return result


# ---------------------------------------------------------------------------
# format_sql_results
# ---------------------------------------------------------------------------

def format_sql_results(
    results: list[dict[str, Any]],
    question: str,
    sql: str,
) -> dict[str, Any]:
    """Wrap query results in the standard tool registry dict format."""
    annotated = []
    for i, row in enumerate(results[:100]):
        row_copy = dict(row)
        row_copy["citation"] = f"query_database:row_{i}"
        annotated.append(row_copy)
    return {
        "tool": "query_database",
        "question": question,
        "sql": sql,
        "row_count": len(results),
        "results": annotated,
        "citation": "query_database:sql",
    }
