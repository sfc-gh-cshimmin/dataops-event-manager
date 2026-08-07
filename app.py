"""DataOps Event Manager — Streamlit app for managing DataOps.live events."""

import streamlit as st
from api_client import DataOpsClient, DataOpsAPIError
from snowflake_helpers import get_token, get_query_params

# Compatibility: older Streamlit (SiS) uses st.experimental_rerun()
if not hasattr(st, "rerun"):
    st.rerun = st.experimental_rerun

st.set_page_config(page_title="DataOps Event Manager", page_icon="📋", layout="wide")


def get_client() -> DataOpsClient:
    """Get an authenticated DataOps API client."""
    token = get_token()
    if not token:
        st.error("DataOps API token not configured. Check Snowflake Secret or st.secrets.")
        st.stop()
    return DataOpsClient(token)


NAV_OPTIONS = ["Manage Events", "Create Event", "Patch Event", "Decommission Account", "Admin"]

# Map ?page= param values to nav labels
_PAGE_PARAM_MAP = {
    "create": "Create Event",
    "view": "Manage Events",
    "list": "Manage Events",
    "patch": "Patch Event",
    "decommission": "Decommission Account",
    "admin": "Admin",
}


def main():
    # Sidebar
    st.sidebar.title("DataOps Event Manager")

    # Health check
    client = get_client()
    try:
        client.health_check()
        st.sidebar.success("API Connected", icon="✅")
    except (DataOpsAPIError, Exception) as e:
        st.sidebar.error(f"API Error: {e}", icon="❌")

    # Resolve default nav from query params (deep-link support)
    page_param = get_query_params().get("page", "")
    default_nav = _PAGE_PARAM_MAP.get(page_param, "Create Event")
    default_index = NAV_OPTIONS.index(default_nav) if default_nav in NAV_OPTIONS else 0

    # Navigation
    nav = st.sidebar.radio(
        "Navigation",
        NAV_OPTIONS,
        index=default_index,
        key="nav_radio",
    )

    # Event slug input (shared across views)
    st.sidebar.divider()
    slug = st.sidebar.text_input(
        "Event Slug",
        value=st.session_state.get("selected_event_slug", ""),
        help="Enter or select an event slug to work with",
    )
    if slug != st.session_state.get("selected_event_slug", ""):
        st.session_state["selected_event_slug"] = slug

    st.sidebar.divider()
    _COMMON_TZ = [
        "PST", "PDT", "MST", "MDT", "CST", "CDT", "EST", "EDT",
        "AKST", "AKDT", "HST",
        "GMT", "UTC",
        "BST", "CET", "CEST",
        "IST", "JST", "AEST", "AEDT", "NZST", "NZDT",
    ]
    _default_tz = st.session_state.get("creator_tz", "PDT")
    _tz_idx = _COMMON_TZ.index(_default_tz) if _default_tz in _COMMON_TZ else 1
    _creator_tz = st.sidebar.selectbox(
        "Your Timezone",
        _COMMON_TZ,
        index=_tz_idx,
        key="creator_tz",
        help="Your current timezone. Used to convert entered event times to UTC.",
    )

    # Route to views
    if nav == "Manage Events":
        from views.list_events import render
        render(client)
    elif nav == "Create Event":
        from views.create_event import render
        render(client)
    elif nav == "Patch Event":
        from views.patch_event import render
        render(client)
    elif nav == "Decommission Account":
        from views.decommission import render
        render(client)
    elif nav == "Admin":
        from views.admin import render
        render()


if __name__ == "__main__":
    main()
