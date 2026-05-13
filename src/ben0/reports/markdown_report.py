"""Markdown collection data health report generator."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from ben0.dashboard.metrics import calculate_metrics


def _recommendations(metrics: dict) -> list[str]:
    recommendations: list[str] = []
    critical = metrics["validation_issues_by_severity"].get("critical", 0)
    errors = metrics["validation_issues_by_severity"].get("error", 0)
    missing_provenance = metrics["validation_issues_by_type"].get("missing_provenance", 0)
    unknown_provenance = metrics["validation_issues_by_type"].get("unknown_provenance", 0)
    open_tickets = metrics["correction_tickets_by_status"].get("proposed", 0)

    if critical:
        recommendations.append(
            f"Prioritize curator review of {critical} critical validation issues before downstream exports or reporting."
        )
    if errors:
        recommendations.append(
            f"Address {errors} error-level issues to stabilize record integrity and reduce repeat ticket churn."
        )
    if missing_provenance or unknown_provenance:
        recommendations.append(
            "Focus provenance cleanup on accessions missing source context or carrying unknown origin codes."
        )
    if metrics["source_coverage_pct"] < 75:
        recommendations.append(
            "Improve linked source coverage so accession histories can be interpreted and cited more confidently."
        )
    if open_tickets:
        recommendations.append(
            f"Review the {open_tickets} proposed correction tickets and accept, defer, or reject them explicitly."
        )
    if not recommendations:
        recommendations.append("No urgent gaps stood out. Continue routine validation, ticket review, and provenance documentation.")
    return recommendations


def generate_markdown_report(session: Session, output_path: str | Path | None = None) -> str:
    """Generate the BEN-0 collection data health report."""
    metrics = calculate_metrics(session)
    min_year = metrics["date_range"]["min_year"] or "unknown"
    max_year = metrics["date_range"]["max_year"] or "unknown"
    issue_lines = metrics["top_validation_issues"][:10]
    recommendations = _recommendations(metrics)

    lines = [
        "# BEN-0 Collection Data Health Report",
        "",
        "## Collection Overview",
        f"- Accessions: **{metrics['total_accessions']}**",
        f"- Items: **{metrics['total_items']}**",
        f"- Taxa: **{metrics['total_taxa']}**",
        f"- Locations: **{metrics['total_locations']}**",
        f"- Accession date range: **{min_year}** to **{max_year}**",
        "",
        "## Provenance Profile",
        f"- Wild-derived accessions: **{metrics['provenance_breakdown'].get('wild', 0)}**",
        f"- Garden-origin accessions: **{metrics['provenance_breakdown'].get('garden', 0)}**",
        f"- Unknown provenance accessions: **{metrics['provenance_breakdown'].get('unknown', 0)}**",
        f"- Provenance coverage: **{metrics['provenance_coverage_pct']}%**",
        f"- Linked source coverage: **{metrics['source_coverage_pct']}%**",
        "",
        "## Data Quality Summary",
        f"- Critical issues: **{metrics['validation_issues_by_severity'].get('critical', 0)}**",
        f"- Error issues: **{metrics['validation_issues_by_severity'].get('error', 0)}**",
        f"- Warning issues: **{metrics['validation_issues_by_severity'].get('warning', 0)}**",
        f"- Info issues: **{metrics['validation_issues_by_severity'].get('info', 0)}**",
        "",
        "## Top 10 Validation Issues",
    ]
    lines.extend(f"- **{row['issue_type']}** — {row['count']}" for row in issue_lines)
    lines.extend(["", "## Correction Ticket Summary"])
    ticket_lines = [
        f"- **{status}** — {count}"
        for status, count in sorted(metrics["correction_tickets_by_status"].items())
    ]
    lines.extend(ticket_lines or ["- No correction tickets recorded."])
    lines.extend(["", "## Recommendations"])
    lines.extend(f"- {item}" for item in recommendations)
    lines.append("")

    markdown = "\n".join(lines)

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
    return markdown
