"""DataOps Event Manager — Streamlit app for managing DataOps.live events."""

import streamlit as st
from api_client import DataOpsClient, DataOpsAPIError

st.set_page_config(page_title="DataOps Event Manager", page_icon="📋", layout="wide")


def check_password() -> bool:
    """Show a password gate if APP_PASSWORD is configured."""
    app_password = st.secrets.get("APP_PASSWORD", "")
    if not app_password:
        return True

    if st.session_state.get("password_ok"):
        return True

    st.title("🔒 DataOps Event Manager")
    pwd = st.text_input("Enter app password:", type="password")
    if st.button("Login"):
        if pwd == app_password:
            st.session_state["password_ok"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


def get_client() -> DataOpsClient:
    """Get an authenticated DataOps API client from secrets."""
    token = st.secrets.get("DATAOPS_API_TOKEN", "")
    if not token:
        st.error("DATAOPS_API_TOKEN not configured in secrets.")
        st.stop()
    return DataOpsClient(token)


NAV_OPTIONS = ["List Events", "Create Event", "Patch Event", "Decommission Account"]

# Map ?page= param values to nav labels
_PAGE_PARAM_MAP = {
    "create": "Create Event",
    "view": "List Events",
    "list": "List Events",
    "patch": "Patch Event",
    "decommission": "Decommission Account",
}


def main():
    if not check_password():
        return

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
    page_param = st.query_params.get("page", "")
    default_nav = _PAGE_PARAM_MAP.get(page_param, "List Events")
    default_index = NAV_OPTIONS.index(default_nav)

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

    # Route to views
    if nav == "List Events":
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


if __name__ == "__main__":
    main()
