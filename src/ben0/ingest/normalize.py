"""Normalization helpers for ingest pipeline."""

from __future__ import annotations

import re
from datetime import date, datetime


_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%Y",
]


def parse_date(raw: str | None) -> str | None:
    """Parse a date string to ISO YYYY-MM-DD, or return None."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.date().isoformat()
        except ValueError:
            continue
    # Try year-only
    m = re.match(r"^(\d{4})$", raw)
    if m:
        return f"{m.group(1)}-01-01"
    return None


def parse_year(raw: str | None) -> int | None:
    """Extract a 4-digit year from a date string or year string."""
    if not raw or not raw.strip():
        return None
    m = re.search(r"\b(1[89]\d\d|20\d\d)\b", raw.strip())
    if m:
        return int(m.group(1))
    return None


_ACC_YEAR_SEQ = re.compile(r"^(\d{4})[.\-](\d+)$")
_CDBG_FORMAT = re.compile(r"^CDBG[.\-](\d{4})[.\-](\d+)$", re.I)
_SHORT_FORMAT = re.compile(r"^(\d{2})[.\-](\d+)$")


def normalize_accession_number(raw: str | None) -> str | None:
    """Normalize accession number to a canonical form."""
    if not raw or not raw.strip():
        return None
    s = raw.strip().upper()

    # CDBG-YYYY-NNN → CDBG-YYYY-NNN
    m = _CDBG_FORMAT.match(s)
    if m:
        return f"CDBG-{m.group(1)}-{m.group(2).zfill(3)}"

    # YYYY-NNNN or YYYY.NNNN → YYYY-NNNN
    m = _ACC_YEAR_SEQ.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(4)}"

    # YY-NNN (e.g. 87-113) — keep as-is but zero-pad seq
    m = _SHORT_FORMAT.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(3)}"

    return s


def clean_str(value: str | None) -> str | None:
    """Strip whitespace; return None if empty."""
    if value is None:
        return None
    v = str(value).strip()
    return v if v else None


def clean_int(value) -> int | None:
    """Parse integer, return None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
