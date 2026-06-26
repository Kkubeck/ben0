"""
Visit-gaps: curator visit frequency analysis for BEN-0.

Public API re-exported here so callers can do:

    from ben0.visit_gaps import analyze_collection

See docs/visit-gaps-design.md for the full design spec.
"""

from __future__ import annotations

from ben0.visit_gaps.analyzer import (
    AreaSummary,
    CollectionVisitReport,
    ItemVisitProfile,
    YearActivity,
    analyze_collection,
    analyze_item,
    classify_area,
    classify_event,
    is_terminal,
    year_activity,
)
from ben0.visit_gaps.constants import (
    AREA_RULES,
    NON_VISIT_EVENTS,
    TERMINAL_STATUSES,
    VISIT_EVENTS,
)
from ben0.visit_gaps.formatters import (
    format_csv,
    format_json,
    format_table,
    format_year_activity,
)

__all__ = [
    "AreaSummary",
    "CollectionVisitReport",
    "ItemVisitProfile",
    "YearActivity",
    "analyze_collection",
    "analyze_item",
    "classify_area",
    "classify_event",
    "is_terminal",
    "year_activity",
    "AREA_RULES",
    "NON_VISIT_EVENTS",
    "TERMINAL_STATUSES",
    "VISIT_EVENTS",
    "format_csv",
    "format_json",
    "format_table",
    "format_year_activity",
]
