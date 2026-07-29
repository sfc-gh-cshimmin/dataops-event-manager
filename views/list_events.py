"""List events with inline detail view and approve action."""

import streamlit as st
import pandas as pd
from api_client import DataOpsClient, DataOpsAPIError
from utils import format_datetime


def _render_event_detail(client: DataOpsClient, slug: str):
    """Render event details inline. Called after the selectbox."""
    try:
        event = client.get_event(slug)
    except DataOpsAPIError as e:
        st.error(f"Failed to fetch event `{slug}`: {e}")
        return

    # Track slugs approved this session so the button hides immediately
    approved_this_session = st.session_state.get("_list_approved_slugs", set())
    is_approved = event.get("is_approved", False) or slug in approved_this_session

    # Show approve result banner if one is waiting
    if st.session_state.get("_list_approve_result"):
        kind, msg = st.session_state.pop("_list_approve_result")
        (st.success if kind == "success" else st.error)(msg)

    # Header row: name + approval badge + approve button
    hcol1, hcol2, hcol3 = st.columns([4, 1, 1])
    with hcol1:
        st.subheader(event.get("name", slug))
        st.caption(f"Slug: `{slug}`")
    with hcol2:
        if is_approved:
            st.success("Approved")
        else:
            st.warning("Pending")
    with hcol3:
        if not is_approved:
            if st.button("✅ Approve", type="primary", key=f"approve_inline_{slug}"):
                st.session_state["_list_approve_pending"] = True
                st.session_state["_list_approve_slug"] = slug
                st.rerun()

    # Dates
    st.markdown("**Dates**")
    date_cols = st.columns(4)
    labels = ["Build Date", "Start Date", "End Date", "Decommission"]
    fields = ["build_date", "start_date", "end_date", "decommission_date"]
    for col, label, field in zip(date_cols, labels, fields):
        with col:
            st.metric(label, format_datetime(event.get(field)))

    # Configuration
    st.markdown("**Configuration**")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Pool Size", event.get("pool_size", "—"))
        st.caption(f"Edition: {event.get('snowflake_account_edition', '—')}")
    with c2:
        st.metric("Region", event.get("snowflake_account_region_group", "—"))
        st.caption(f"Express: {event.get('is_express', False)}")
    with c3:
        st.caption(f"Location: {event.get('location', '—')}")
        st.caption(f"Delivery: {event.get('delivery_format', '—')}")

    project_path = event.get("dataops_configure_project_path", "")
    if project_path:
        st.caption(f"Configure Project: `{project_path}`")

    # Accounts summary
    st.markdown("**Accounts**")
    try:
        accounts = client.get_all_event_accounts(slug)
        total = len(accounts)
        status_counts: dict[str, int] = {}
        for acc in accounts:
            s = acc.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1

        acc_cols = st.columns(max(len(status_counts) + 1, 1))
        with acc_cols[0]:
            st.metric("Total", total)
        for i, (s, count) in enumerate(sorted(status_counts.items()), 1):
            with acc_cols[i]:
                st.metric(s.replace("_", " ").title(), count)
    except DataOpsAPIError:
        st.info("Could not load accounts.")

    instructions = event.get("instructions", "")
    if instructions:
        with st.expander("Instructions (HTML)"):
            st.code(instructions, language="html")

    # Quick actions
    st.divider()
    act1, act2 = st.columns(2)
    with act1:
        if st.button("✏️ Edit this event", key=f"edit_{slug}"):
            st.session_state["selected_event_slug"] = slug
            st.session_state["nav_override"] = "Patch Event"
            st.rerun()
    with act2:
        if st.button("🗑️ Decommission an account", key=f"decomm_{slug}"):
            st.session_state["selected_event_slug"] = slug
            st.session_state["nav_override"] = "Decommission Account"
            st.rerun()


def render(client: DataOpsClient):
    st.header("📋 Manage Events")

    # Execute pending approve (must be before any early return)
    if st.session_state.get("_list_approve_pending"):
        _slug = st.session_state.pop("_list_approve_slug", "")
        st.session_state.pop("_list_approve_pending", None)
        try:
            client.approve_event(_slug)
            approved = st.session_state.get("_list_approved_slugs", set())
            approved.add(_slug)
            st.session_state["_list_approved_slugs"] = approved
            st.session_state["_list_approve_result"] = ("success", f"Event `{_slug}` approved!")
        except DataOpsAPIError as e:
            st.session_state["_list_approve_result"] = ("error", f"Approval failed: {e.body}")
        except Exception as e:
            st.session_state["_list_approve_result"] = ("error", str(e))
        st.rerun()

    search = st.text_input("Search events", placeholder="Search by slug, name, or location...")

    try:
        data = client.get_events(search=search or None)
    except DataOpsAPIError as e:
        st.error(f"Failed to fetch events: {e}")
        return

    if isinstance(data, dict):
        events = data.get("results", data.get("events", []))
    else:
        events = data if isinstance(data, list) else []

    if not events:
        st.info("No events found.")
        return

    st.caption(f"{len(events)} event(s) found")

    approved_this_session = st.session_state.get("_list_approved_slugs", set())
    rows = []
    for ev in events:
        slug_val = ev.get("slug", "")
        is_app = ev.get("is_approved", False) or slug_val in approved_this_session
        rows.append({
            "Slug": slug_val,
            "Name": ev.get("name", ""),
            "Start": (ev.get("start_date") or "")[:10],
            "End": (ev.get("end_date") or "")[:10],
            "Pool": ev.get("pool_size", ""),
            "Approved": "✅" if is_app else "⏳",
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    slugs = [ev.get("slug", "") for ev in events if ev.get("slug")]
    if not slugs:
        return

    st.divider()
    preselect = st.session_state.get("selected_event_slug", "")
    default_idx = slugs.index(preselect) if preselect in slugs else 0

    selected = st.selectbox(
        "Select an event:",
        slugs,
        index=default_idx,
        key="list_selected_slug",
    )

    if selected:
        st.session_state["selected_event_slug"] = selected
        st.divider()
        _render_event_detail(client, selected)
