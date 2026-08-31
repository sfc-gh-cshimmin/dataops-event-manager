"""View event details."""

import streamlit as st
from datetime import datetime, timezone, timedelta
from api_client import DataOpsClient, DataOpsAPIError
from utils import format_datetime, generate_clone_slug


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
    col_a, col_b, col_c, col_d = st.columns(4)
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
    with col_c:
        if st.button("⛔ Decommission Event", type="primary"):
            st.session_state["_confirm_decomm_slug"] = slug
    with col_d:
        if st.button("📋 Clone Event"):
            st.session_state["_view_clone_source"] = slug

    # Clone confirmation
    if st.session_state.get("_view_clone_source") == slug:
        _clone_instr = st.checkbox("Carry over instructors", value=True, key="view_clone_instr")
        if st.button("Confirm Clone", type="primary", key="view_clone_confirm"):
            with st.spinner("Generating clone..."):
                _new_slug = generate_clone_slug(client, slug)
                _clone_data = {
                    "slug": _new_slug,
                    "name": event.get("name", ""),
                    "start_date": (event.get("start_datetime") or "")[:10],
                    "end_date": (event.get("end_datetime") or "")[:10],
                    "decommission_date": (event.get("decommission_datetime") or "")[:10],
                    "build_date": (event.get("build_datetime") or "")[:10],
                    "pool_size": str(event.get("initial_pool_size", 0)),
                    "region": event.get("snowflake_account_region_group", ""),
                    "edition": event.get("snowflake_account_edition", "ENTERPRISE"),
                    "configure_project": event.get("project", ""),
                    "instructors": [i.get("email", i) if isinstance(i, dict) else i for i in (event.get("instructors") or [])] if _clone_instr else [],
                }
                st.session_state["_clone_event_data"] = _clone_data
                st.session_state.pop("_view_clone_source", None)
                st.session_state["nav_override"] = "Create Event"
                st.rerun()

    if st.session_state.get("_confirm_decomm_slug") == slug:
        st.warning(
            f"⚠️ This will set the decommission date to **now** for `{slug}`. "
            "All accounts will begin decommissioning."
        )
        _dc1, _dc2, _ = st.columns([1, 1, 4])
        with _dc1:
            if st.button("Yes, Decommission", type="primary", key="decomm_confirm_btn"):
                # Send current time as UTC+9 (DataOps display timezone)
                _now_jst = datetime.now(timezone(timedelta(hours=9)))
                _decomm_str = _now_jst.strftime("%Y-%m-%dT%H:%M:%S+09:00")
                try:
                    client.patch_event(slug, {"decommission_date": _decomm_str})
                    st.success(f"Decommission date set to {_decomm_str}.")
                    st.session_state.pop("_confirm_decomm_slug", None)
                    st.rerun()
                except DataOpsAPIError as _de:
                    st.error(f"Failed: {_de}")
                except Exception as _de:
                    st.error(f"Unexpected error: {_de}")
        with _dc2:
            if st.button("Cancel", key="decomm_cancel_btn"):
                st.session_state.pop("_confirm_decomm_slug", None)
                st.rerun()
