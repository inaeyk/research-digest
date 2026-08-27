"""Date coverage/status grid rendering for Streamlit pages."""

from __future__ import annotations

import calendar
from datetime import date

from research_digest.coverage import DateCoverageStatus

WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
STATUS_LEGEND: tuple[tuple[str, str], ...] = (
    ("Done", "Source covered"),
    ("Failed", "Source retrieval failed"),
    ("Partial", "Partial/incomplete source retrieval"),
    ("Empty", "Checked: no submissions"),
    ("Pending", "Pending/uncovered"),
    ("Sel", "Currently selected"),
)
_STATUS_CELL_LABELS: dict[str, str] = {
    "completed": "Done",
    "failed": "Failed",
    "partial": "Partial",
    "empty": "Empty",
    "pending": "Pending",
    "out_of_scope": "-",
}
_STATUS_ICONS: dict[str, str] = {
    "completed": ":material/check_circle:",
    "failed": ":material/error:",
    "partial": ":material/warning:",
    "empty": ":material/radio_button_unchecked:",
    "pending": ":material/pending:",
    "out_of_scope": "",
}


def month_bounds(anchor: date) -> tuple[date, date]:
    last_day = calendar.monthrange(anchor.year, anchor.month)[1]
    return date(anchor.year, anchor.month, 1), date(anchor.year, anchor.month, last_day)


def render_date_status_grid(
    *,
    statuses: tuple[DateCoverageStatus, ...],
    title: str,
) -> None:
    import streamlit as st

    if not statuses:
        return
    by_date = {status.source_date: status for status in statuses}
    first = statuses[0].source_date
    st.markdown(f"**{title}**")
    st.caption(
        "Legend: "
        + "; ".join(f"{name} = {label}" for name, label in STATUS_LEGEND)
    )
    header_cols = st.columns(7)
    for index, label in enumerate(WEEKDAY_LABELS):
        header_cols[index].caption(label)
    first_weekday = first.weekday()
    days = list(by_date)
    padded: list[date | None] = [None] * first_weekday + days
    while len(padded) % 7:
        padded.append(None)
    for row_start in range(0, len(padded), 7):
        cols = st.columns(7)
        for index, source_date in enumerate(padded[row_start : row_start + 7]):
            with cols[index].container(border=True):
                if source_date is None:
                    st.caption("-")
                    continue
                status = by_date[source_date]
                st.markdown(f"**{source_date.day}**")
                st.caption(date_status_cell_label(status))
    detail_rows = date_status_detail_rows(statuses)
    if detail_rows:
        with st.expander("Date status details", icon=":material/calendar_month:"):
            st.dataframe(detail_rows, hide_index=True, width="stretch")


def date_status_cell_label(status: DateCoverageStatus) -> str:
    """Return compact non-color-only text for a small calendar day cell."""

    label = _STATUS_CELL_LABELS.get(status.status, status.status.replace("_", " ").title())
    icon = _STATUS_ICONS.get(status.status, "")
    parts = [part for part in (icon, label) if part and label != "-"]
    if status.selected:
        parts.append("Sel")
    if not parts:
        return "-"
    return " ".join(parts)


def date_status_detail_rows(
    statuses: tuple[DateCoverageStatus, ...],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for status in statuses:
        if status.status == "out_of_scope" and not status.selected:
            continue
        rows.append(
            {
                "Date": status.source_date.isoformat(),
                "Selected": "yes" if status.selected else "",
                "Status": status.label,
                "Run": f"#{status.run_id}" if status.run_id is not None else "",
                "Retrieved": status.retrieved_count if status.retrieved_count is not None else "",
            }
        )
    return rows
