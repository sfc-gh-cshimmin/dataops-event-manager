"""List events with inline detail view and approve action."""

import streamlit as st
import json
import pandas as pd
from datetime import datetime, timezone, timedelta
from api_client import DataOpsClient, DataOpsAPIError
from utils import format_datetime, generate_clone_slug


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
    act1, act2, act3, act4 = st.columns(4)
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
    with act3:
        if st.button("⛔ Decommission Event", type="primary", key=f"decomm_event_{slug}"):
            st.session_state["_list_confirm_decomm_slug"] = slug
    with act4:
        if st.button("📋 Clone Event", key=f"clone_{slug}"):
            st.session_state["_clone_source_slug"] = slug

    # Clone confirmation
    if st.session_state.get("_clone_source_slug") == slug:
        _clone_instr = st.checkbox("Carry over instructors", value=True, key=f"clone_instr_{slug}")
        if st.button("Confirm Clone", type="primary", key=f"clone_confirm_{slug}"):
            with st.spinner("Generating clone..."):
                _evt = client.get_event_details(slug)
                _new_slug = generate_clone_slug(client, slug)
                _clone_data = {
                    "slug": _new_slug,
                    "name": _evt.get("name", ""),
                    "start_date": (_evt.get("start_datetime") or "")[:10],
                    "end_date": (_evt.get("end_datetime") or "")[:10],
                    "decommission_date": (_evt.get("decommission_datetime") or "")[:10],
                    "build_date": (_evt.get("build_datetime") or "")[:10],
                    "pool_size": str(_evt.get("initial_pool_size", 0)),
                    "region": _evt.get("snowflake_account_region_group", ""),
                    "edition": _evt.get("snowflake_account_edition", "ENTERPRISE"),
                    "configure_project": _evt.get("project", ""),
                    "instructors": [i.get("email", i) if isinstance(i, dict) else i for i in (_evt.get("instructors") or [])] if _clone_instr else [],
                }
                st.session_state["_clone_event_data"] = _clone_data
                st.session_state.pop("_clone_source_slug", None)
                st.session_state["nav_override"] = "Create Event"
                st.rerun()

    if st.session_state.get("_list_confirm_decomm_slug") == slug:
        st.warning(
            f"⚠️ This will set the decommission date to **now** for `{slug}`. "
            "All accounts will begin decommissioning."
        )
        _dc1, _dc2, _ = st.columns([1, 1, 4])
        with _dc1:
            if st.button("Yes, Decommission", type="primary", key=f"decomm_event_confirm_{slug}"):
                st.session_state["_list_decomm_pending"] = True
                st.session_state["_list_decomm_slug"] = slug
                st.rerun()
        with _dc2:
            if st.button("Cancel", key=f"decomm_event_cancel_{slug}"):
                st.session_state.pop("_list_confirm_decomm_slug", None)
                st.rerun()


def render(client: DataOpsClient):
    st.header("📋 Manage Events")

    # Execute pending decommission (must be before any early return)
    if st.session_state.get("_list_decomm_pending"):
        _slug = st.session_state.pop("_list_decomm_slug", "")
        st.session_state.pop("_list_decomm_pending", None)
        st.session_state.pop("_list_confirm_decomm_slug", None)
        _now_jst = datetime.now(timezone(timedelta(hours=9)))
        _decomm_str = _now_jst.strftime("%Y-%m-%dT%H:%M:%S+09:00")
        try:
            client.patch_event(_slug, {"decommission_date": _decomm_str})
            st.success(f"Decommission date for `{_slug}` set to {_decomm_str}.")
        except DataOpsAPIError as _de:
            st.error(f"Decommission failed: {_de}")
        except Exception as _de:
            st.error(f"Unexpected error: {_de}")

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

    slugs = [ev.get("slug", "") for ev in events if ev.get("slug")]
    if not slugs:
        return

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
