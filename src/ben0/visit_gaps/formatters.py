"""
Output formatting for visit-gaps: plain-text tables, CSV, and JSON.

No tabulate dependency: the project does not already depend on it, so
these formatters use manual fixed-width f-string formatting instead of
adding a new dependency.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import json
from datetime import date, datetime

from ben0.visit_gaps.analyzer import (
    AreaSummary,
    CollectionVisitReport,
    ItemVisitProfile,
    YearActivity,
)

# Histogram bucket boundaries, in days, used by the summary table's
# <6mo/6-12m/1-2yr/2-5yr/>5yr columns. These are distinct from
# AreaSummary's cumulative visited_6mo/visited_1yr/overdue_* fields:
# the histogram buckets here are mutually exclusive ranges computed
# directly from the per-item profiles passed to format_table.
_SIX_MONTHS = 182
_ONE_YEAR = 365
_TWO_YEARS = 730
_FIVE_YEARS = 1825


def _years_str(days: int) -> str:
    """Render a day count as a short '9.7yr' / '45d' style string."""
    if days < 0:
        return "n/a"
    if days < 365:
        return f"{days}d"
    return f"{days / 365.25:.1f}yr"


# -----------------------------------------------------------------------------
# _histogram_bucket(days_since_last_visit) consumes an int (or -1 sentinel
# for "no visit") and produces one of the 5 bucket label strings used by
# the summary table's column headers.
#
# Interpretation: buckets are mutually exclusive day ranges:
# "<6mo" is [0, 182], "6-12m" is (182, 365], "1-2yr" is (365, 730],
# "2-5yr" is (730, 1825], ">5yr" is (1825, inf). A days value of -1
# (never visited) is treated as ">5yr", the most overdue bucket, since
# an item with zero visit events is the most extreme case of "not seen."
#
# Example: _histogram_bucket(40) == "<6mo"
#          _histogram_bucket(-1) == ">5yr"
# -----------------------------------------------------------------------------
def _histogram_bucket(days_since_last_visit: int) -> str:
    days = days_since_last_visit if days_since_last_visit >= 0 else _FIVE_YEARS + 1
    if days <= _SIX_MONTHS:
        return "<6mo"
    if days <= _ONE_YEAR:
        return "6-12m"
    if days <= _TWO_YEARS:
        return "1-2yr"
    if days <= _FIVE_YEARS:
        return "2-5yr"
    return ">5yr"


# -----------------------------------------------------------------------------
# format_table(report, summary) consumes a CollectionVisitReport and a
# bool, and produces a plain-text table string.
#
# Interpretation: when summary is True, produces the area-level summary
# table (one row per area plus a TOTAL row) with columns Area / Living /
# <6mo / 6-12m / 1-2yr / 2-5yr / >5yr / Ghosts / %Over, matching the
# design spec's example layout. When summary is False, produces the
# per-item detail table with columns Item / Area / Last Visit / Status /
# Prev Int / Current / Visits, one row per living item in report.all_items
# (terminated items are omitted from per-item detail by default, since
# the design's default view is about gaps in living collection
# stewardship; ghosts and overdue items both appear here since they are
# living).
#
# Example: format_table(report, summary=True) starts with a header row
# "Area                     Living   <6mo  6-12m  1-2yr  2-5yr   >5yr  Ghosts  %Over"
# followed by one line per area and a TOTAL line.
# -----------------------------------------------------------------------------
def format_table(report: CollectionVisitReport, summary: bool = False) -> str:
    """Render a CollectionVisitReport as a plain-text table."""
    if summary:
        return _format_summary_table(report)
    return _format_detail_table(report)


def _format_summary_table(report: CollectionVisitReport) -> str:
    header = (
        f"{'Area':<24} {'Living':>7} {'<6mo':>6} {'6-12m':>6} "
        f"{'1-2yr':>6} {'2-5yr':>6} {'>5yr':>6} {'Ghosts':>7} {'%Over':>6}"
    )
    lines = [header]

    totals = {
        "living": 0,
        "<6mo": 0,
        "6-12m": 0,
        "1-2yr": 0,
        "2-5yr": 0,
        ">5yr": 0,
        "ghosts": 0,
        "overdue": 0,
    }

    for area_name in sorted(report.area_summaries.keys()):
        area_summary: AreaSummary = report.area_summaries[area_name]
        bucket_counts = {key: 0 for key in ("<6mo", "6-12m", "1-2yr", "2-5yr", ">5yr")}
        overdue_count = 0
        for profile in report.all_items:
            if profile.area != area_name or not profile.is_living:
                continue
            bucket_counts[_histogram_bucket(profile.days_since_last_visit)] += 1
            if profile.is_overdue:
                overdue_count += 1

        pct_over = 0.0
        if area_summary.living:
            pct_over = 100.0 * overdue_count / area_summary.living

        lines.append(
            f"{area_name:<24} {area_summary.living:>7} "
            f"{bucket_counts['<6mo']:>6} {bucket_counts['6-12m']:>6} "
            f"{bucket_counts['1-2yr']:>6} {bucket_counts['2-5yr']:>6} "
            f"{bucket_counts['>5yr']:>6} {area_summary.ghosts:>7} "
            f"{pct_over:>5.0f}%"
        )

        totals["living"] += area_summary.living
        for key in ("<6mo", "6-12m", "1-2yr", "2-5yr", ">5yr"):
            totals[key] += bucket_counts[key]
        totals["ghosts"] += area_summary.ghosts
        totals["overdue"] += overdue_count

    total_pct_over = 0.0
    if totals["living"]:
        total_pct_over = 100.0 * totals["overdue"] / totals["living"]

    lines.append(
        f"{'TOTAL':<24} {totals['living']:>7} "
        f"{totals['<6mo']:>6} {totals['6-12m']:>6} "
        f"{totals['1-2yr']:>6} {totals['2-5yr']:>6} "
        f"{totals['>5yr']:>6} {totals['ghosts']:>7} "
        f"{total_pct_over:>5.0f}%"
    )
    return "\n".join(lines)


def _format_detail_table(report: CollectionVisitReport) -> str:
    header = (
        f"{'Item':<20} {'Area':<14} {'Last Visit':<11} {'Status':<10} "
        f"{'Prev Int':>9} {'Current':>8} {'Visits':>7}"
    )
    lines = [header]

    for profile in report.all_items:
        if not profile.is_living:
            continue
        last_visit_str = (
            profile.last_visit_date.isoformat() if profile.last_visit_date else "n/a"
        )
        prev_int_str = (
            _years_str(profile.previous_interval_days)
            if profile.previous_interval_days is not None
            else "n/a"
        )
        current_str = _years_str(profile.days_since_last_visit)

        lines.append(
            f"{profile.item_label:<20} {profile.area:<14} {last_visit_str:<11} "
            f"{profile.last_visit_type:<10} {prev_int_str:>9} {current_str:>8} "
            f"{profile.visit_count:>7}"
        )
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# format_csv(report) consumes a CollectionVisitReport and produces a CSV
# string with one row per item in report.all_items, columns matching
# every ItemVisitProfile field. all_items includes terminated items and
# ghosts and overdue items alike, so the CSV is a complete export, not a
# filtered view (filtering, e.g. --ghosts-only, is applied by the CLI
# before calling the formatter, on the list it passes in).
#
# Example: format_csv(report) for a 3-item collection produces a header
# row plus 3 data rows.
# -----------------------------------------------------------------------------
def format_csv(report: CollectionVisitReport) -> str:
    """Render report.all_items as CSV, one row per item."""
    buffer = io.StringIO()
    fieldnames = [field.name for field in dataclasses.fields(ItemVisitProfile)]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for profile in report.all_items:
        row = dataclasses.asdict(profile)
        if row["last_visit_date"] is not None:
            row["last_visit_date"] = row["last_visit_date"].isoformat()
        writer.writerow(row)
    return buffer.getvalue()


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


# -----------------------------------------------------------------------------
# format_json(report) consumes a CollectionVisitReport and produces a
# JSON string of the full report, dates and datetimes rendered as ISO
# strings.
#
# Example: json.loads(format_json(report)) is a dict with keys
# "generated_at", "threshold_days", "area_summaries", "overdue_items",
# "ghost_items", "total_living", "total_overdue", "total_ghosts",
# "all_items".
# -----------------------------------------------------------------------------
def format_json(report: CollectionVisitReport) -> str:
    """Serialize the full CollectionVisitReport as JSON."""
    return json.dumps(dataclasses.asdict(report), default=_json_default, indent=2)


# -----------------------------------------------------------------------------
# format_year_activity(activity, fmt) consumes the dict produced by
# analyzer.year_activity and a format string ("table" or "json"), and
# produces a rendered string.
#
# Interpretation: "table" renders one block per area, each block a small
# table of year rows with the YearActivity counts. "json" serializes the
# nested dict directly (area -> year -> YearActivity fields).
#
# Example: format_year_activity({"Alpine": {2023: YearActivity(year=2023,
# observed_count=3)}}, fmt="table") includes the substring "Alpine" and
# "2023" in its output.
# -----------------------------------------------------------------------------
def format_year_activity(activity: dict[str, dict[int, YearActivity]], fmt: str = "table") -> str:
    """Render the year_activity() result as a table or JSON string."""
    if fmt == "json":
        serializable = {
            area: {str(year): dataclasses.asdict(record) for year, record in years.items()}
            for area, years in activity.items()
        }
        return json.dumps(serializable, default=_json_default, indent=2)

    lines = []
    for area_name in sorted(activity.keys()):
        lines.append(f"== {area_name} ==")
        header = (
            f"{'Year':>6} {'Observed':>9} {'Planted':>8} {'Dead':>6} "
            f"{'Removed':>8} {'OtherVisit':>10} {'NonVisit':>9} {'Total':>7}"
        )
        lines.append(header)
        for year in sorted(activity[area_name].keys()):
            record = activity[area_name][year]
            lines.append(
                f"{record.year:>6} {record.observed_count:>9} {record.planted_count:>8} "
                f"{record.dead_count:>6} {record.removed_count:>8} "
                f"{record.other_visit_count:>10} {record.non_visit_count:>9} "
                f"{record.total_count:>7}"
            )
        lines.append("")
    return "\n".join(lines).rstrip()
