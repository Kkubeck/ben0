"""Streamlit dashboard for BEN-0."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from ben0.dashboard.metrics import calculate_metrics
from ben0.db.session import get_session
from ben0.retrieval.search import search_index

APP_PATH = str(Path(__file__).resolve())


def _pie_chart(data: dict[str, int], title: str) -> None:
    frame = pd.DataFrame(
        [{"category": key, "count": value} for key, value in data.items() if value]
    )
    if frame.empty:
        st.info(f"No data available for {title.lower()}.")
        return
    st.vega_lite_chart(
        frame,
        {
            "mark": {"type": "arc", "outerRadius": 110},
            "encoding": {
                "theta": {"field": "count", "type": "quantitative"},
                "color": {"field": "category", "type": "nominal"},
                "tooltip": [
                    {"field": "category", "type": "nominal"},
                    {"field": "count", "type": "quantitative"},
                ],
            },
            "title": title,
        },
        use_container_width=True,
    )


def _bar_chart(data: dict[str, int], title: str, x_label: str = "category") -> None:
    frame = pd.DataFrame(
        [{x_label: key, "count": value} for key, value in data.items() if value]
    )
    if frame.empty:
        st.info(f"No data available for {title.lower()}.")
        return
    st.vega_lite_chart(
        frame,
        {
            "mark": "bar",
            "encoding": {
                "x": {"field": x_label, "type": "nominal", "sort": "-y"},
                "y": {"field": "count", "type": "quantitative"},
                "tooltip": [
                    {"field": x_label, "type": "nominal"},
                    {"field": "count", "type": "quantitative"},
                ],
            },
            "title": title,
        },
        use_container_width=True,
    )


def main() -> None:
    st.set_page_config(page_title="BEN-0 Dashboard", layout="wide")
    st.title("BEN-0 Collection Dashboard")

    session = get_session()
    try:
        metrics = calculate_metrics(session)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Accessions", metrics["total_accessions"])
        col2.metric("Items", metrics["total_items"])
        col3.metric("Taxa", metrics["total_taxa"])
        col4.metric("Locations", metrics["total_locations"])

        left, right = st.columns(2)
        with left:
            _bar_chart(metrics["validation_issues_by_type"], "Validation Issues by Type", x_label="issue_type")
            _bar_chart(metrics["items_by_status"], "Items by Status", x_label="status")
        with right:
            _pie_chart(metrics["validation_issues_by_severity"], "Validation Issues by Severity")
            _pie_chart(metrics["provenance_breakdown"], "Provenance Profile")

        timeline = pd.DataFrame(metrics["collection_timeline"])
        st.subheader("Collection Timeline")
        if timeline.empty:
            st.info("No accession years available yet.")
        else:
            st.line_chart(timeline.set_index("label")["count"])

        st.subheader("Recent Correction Tickets")
        recent = pd.DataFrame(metrics["recent_correction_tickets"])
        if recent.empty:
            st.info("No correction tickets yet.")
        else:
            st.dataframe(recent, use_container_width=True, hide_index=True)

        st.subheader("Search Collection Notes and Documents")
        query = st.text_input("FTS5 search query")
        if query:
            results = search_index(session, query, limit=10)
            if not results:
                st.warning("No search results.")
            else:
                for result in results:
                    with st.container(border=True):
                        st.markdown(f"**{result['document_name']}**  ")
                        st.caption(
                            f"chunk={result['chunk_id']} accession={result.get('accession_id') or '-'} item={result.get('item_id') or '-'} taxon={result.get('taxon_id') or '-'}"
                        )
                        st.write(result["snippet"])
    finally:
        session.close()


if __name__ == "__main__":
    main()
