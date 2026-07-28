"""List and search events view."""

import streamlit as st
import pandas as pd
from api_client import DataOpsClient, DataOpsAPIError


def render(client: DataOpsClient):
    st.header("📋 List Events")

    search = st.text_input("Search events", placeholder="Search by slug, name, or location...")

    try:
        if search:
            data = client.get_events(search=search)
        else:
            data = client.get_events()
    except DataOpsAPIError as e:
        st.error(f"Failed to fetch events: {e}")
        return

    # Normalize response — may be a list or paginated dict
    if isinstance(data, dict):
        events = data.get("results", data.get("events", []))
    else:
        events = data

    if not events:
        st.info("No events found.")
        return

    st.caption(f"{len(events)} event(s) found")

    # Build display table
    rows = []
    for ev in events:
        rows.append({
            "Slug": ev.get("slug", ""),
            "Name": ev.get("name", ""),
            "Location": ev.get("location", ""),
            "Start Date": ev.get("start_date", ""),
            "End Date": ev.get("end_date", ""),
            "Pool Size": ev.get("pool_size", ""),
            "Approved": ev.get("is_approved", ""),
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Selection
    st.subheader("Select an Event")
    slugs = [ev.get("slug", "") for ev in events if ev.get("slug")]
    if slugs:
        selected = st.selectbox("Choose an event to work with:", slugs)
        if st.button("Select Event"):
            st.session_state["selected_event_slug"] = selected
            st.success(f"Selected: **{selected}**")
            st.rerun()
