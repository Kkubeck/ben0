"""Encoding detection and safe CSV reading for IrisBG exports."""

from __future__ import annotations

import csv
import io
from pathlib import Path

# Known IrisBG special characters that signal encoding issues:
# × (U+00D7) - hybrid symbol, appears as 0xD7 in Latin-1
# • (U+2022) - bullet, used in bed numbers
# · (U+00B7) - middle dot, used in bed numbers
# ° (U+00B0) - degree symbol, in coordinates

ENCODING_CHAIN = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]


def read_csv_safe(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read a CSV with automatic encoding detection.

    Tries encodings in order: UTF-8-SIG, UTF-8, CP1252, Latin-1.
    Returns (fieldnames, rows).
    """
    raw = path.read_bytes()

    text: str | None = None
    for enc in ENCODING_CHAIN:
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, ValueError):
            continue

    if text is None:
        text = raw.decode("utf-8", errors="replace")

    if text.startswith("\ufeff"):
        text = text[1:]

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = [_clean_header(name) for name in (reader.fieldnames or [])]
    reader.fieldnames = fieldnames

    rows: list[dict[str, str]] = []
    for row in reader:
        cleaned = {_clean_header(key): value for key, value in row.items()}
        rows.append(cleaned)

    return fieldnames, rows


def _clean_header(value: str | None) -> str:
    """Clean a CSV header value."""
    return str(value or "").replace("\ufeff", "").strip()
