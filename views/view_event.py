"""View event details."""

import streamlit as st
from api_client import DataOpsClient, DataOpsAPIError
from utils import format_datetime


def render(client: DataOpsClient):
    st.header("🔍 View Event Details")

    slug = st.session_state.get("selected_event_slug", "")
    if not slug:
        st.warning("Enter an event slug in the sidebar or select one from List Events.")
        return

    try:
        event = client.get_event(slug)
    except DataOpsAPIError as e:
        st.error(f"Failed to fetch event: {e}")
        return

    # Header
    col1, col2 = st.columns([3, 1])
    with col1:
        st.subheader(event.get("name", slug))
        st.caption(f"Slug: `{slug}`")
    with col2:
        approved = event.get("is_approved")
        if approved:
            st.success("Approved")
        else:
            st.warning("Pending Approval")

    # Dates
    st.divider()
    st.markdown("**Dates**")
    date_cols = st.columns(4)
    with date_cols[0]:
        st.metric("Build Date", format_datetime(event.get("build_date")))
    with date_cols[1]:
        st.metric("Start Date", format_datetime(event.get("start_date")))
    with date_cols[2]:
        st.metric("End Date", format_datetime(event.get("end_date")))
    with date_cols[3]:
        st.metric("Decommission", format_datetime(event.get("decommission_date")))

    # Configuration
    st.divider()
    st.markdown("**Configuration**")
    config_cols = st.columns(3)
    with config_cols[0]:
        st.metric("Pool Size", event.get("pool_size", "—"))
        st.text(f"Edition: {event.get('snowflake_account_edition', '—')}")
    with config_cols[1]:
        st.metric("Region", event.get("snowflake_account_region_group", "—"))
        st.text(f"Express: {event.get('is_express', False)}")
    with config_cols[2]:
        st.text(f"Location: {event.get('location', '—')}")
        st.text(f"Delivery: {event.get('delivery_format', '—')}")

    project_path = event.get("dataops_configure_project_path", "")
    if project_path:
        st.text(f"Configure Project: {project_path}")

    # Accounts summary
    st.divider()
    st.markdown("**Accounts**")
    try:
        accounts = client.get_all_event_accounts(slug)
        total = len(accounts)
        status_counts = {}
        for acc in accounts:
            status = acc.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        acc_cols = st.columns(len(status_counts) + 1)
        with acc_cols[0]:
            st.metric("Total", total)
        for i, (status, count) in enumerate(sorted(status_counts.items()), 1):
            with acc_cols[i]:
                st.metric(status.replace("_", " ").title(), count)
    except DataOpsAPIError:
        st.info("Could not load accounts.")

    # Instructions (expandable)
    instructions = event.get("instructions", "")
    if instructions:
        with st.expander("Instructions (HTML)"):
            st.code(instructions, language="html")

    # Quick actions
    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("✏️ Edit this event"):
            st.session_state["selected_event_slug"] = slug
            st.session_state["nav_override"] = "Patch Event"
            st.rerun()
    with col_b:
        if st.button("🗑️ Decommission an account"):
            st.session_state["selected_event_slug"] = slug
            st.session_state["nav_override"] = "Decommission Account"
            st.rerun()
