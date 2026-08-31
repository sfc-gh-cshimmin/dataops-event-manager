"""Account Health Monitor — identifies active events with unhealthy account pools."""

import streamlit as st
from datetime import datetime, timezone
from api_client import DataOpsClient, DataOpsAPIError

UNHEALTHY_STATUSES = {"error", "decommissioned"}


def _fetch_active_events(client: DataOpsClient) -> list[dict]:
    """Paginate through all events and return those that are active (approved + decomm in future)."""
    now = datetime.now(timezone.utc)
    active = []
    page = 1
    while True:
        try:
            data = client._get("/event_management/events-paginated", params={"page": page, "page_size": 100})
        except DataOpsAPIError:
            break
        events = data.get("events", [])
        if not events:
            break
        for ev in events:
            if ev.get("approval_status") != "APPROVED":
                continue
            if ev.get("organization_account") != "SFSEHOL-SFSEHOL_ADMIN":
                continue
            decomm = ev.get("decommission_datetime")
            end_dt_str = ev.get("end_datetime")
            if not decomm:
                continue
            try:
                dt = datetime.fromisoformat(decomm.replace("Z", "+00:00"))
                if dt <= now:
                    continue
                # Only include events before their end date
                if end_dt_str:
                    end_dt = datetime.fromisoformat(end_dt_str.replace("Z", "+00:00"))
                    if end_dt <= now:
                        continue
                active.append(ev)
            except (ValueError, TypeError):
                pass
        if page >= data.get("total_pages", 1):
            break
        page += 1
    return active


def _compute_health(client: DataOpsClient, events: list[dict]) -> list[dict]:
    """For each event, fetch all accounts and compute health metrics."""
    results = []
    for ev in events:
        slug = ev.get("slug", "")
        try:
            accounts = client.get_all_event_accounts(slug)
        except (DataOpsAPIError, Exception):
            accounts = []
        total = len(accounts)
        if total == 0:
            continue
        unhealthy = [a for a in accounts if a.get("status") in UNHEALTHY_STATUSES]
        unhealthy_count = len(unhealthy)
        if unhealthy_count == 0:
            continue
        error_count = sum(1 for a in unhealthy if a.get("status") == "error")
        decomm_count = sum(1 for a in unhealthy if a.get("status") == "decommissioned")
        healthy_count = total - unhealthy_count
        healthy_pct = round((healthy_count / total) * 100, 1)
        results.append({
            "slug": slug,
            "name": ev.get("name", slug),
            "total": total,
            "healthy": healthy_count,
            "unhealthy": unhealthy_count,
            "error_count": error_count,
            "decomm_count": decomm_count,
            "healthy_pct": healthy_pct,
            "pool_size": ev.get("initial_pool_size", 0),
            "decommission_datetime": ev.get("decommission_datetime", ""),
        })
    results.sort(key=lambda x: x["healthy_pct"])
    return results


def render(client: DataOpsClient):
    st.header("Account Health Monitor")
    st.caption("Identifies active events with errored or unexpectedly decommissioned accounts.")

    col_refresh, col_spacer = st.columns([1, 5])
    with col_refresh:
        if st.button("Refresh", type="primary", use_container_width=True, key="health_refresh_btn"):
            st.cache_data.clear()
            st.rerun()

    @st.cache_data(ttl=300, show_spinner=False)
    def _cached_health_check(_token: str) -> list[dict]:
        active = _fetch_active_events(client)
        return _compute_health(client, active)

    with st.spinner("Fetching account health data for active events..."):
        try:
            from snowflake_helpers import get_token
            _token = get_token()
        except Exception:
            _token = "default"
        health_data = _cached_health_check(_token)

    if not health_data:
        st.success("All active event pools are healthy — no errored or decommissioned accounts found.")
        return

    st.warning(f"{len(health_data)} event(s) with unhealthy accounts detected.")

    for ev in health_data:
        _pct = ev["healthy_pct"]
        if _pct < 90:
            _color = "red"
        elif _pct < 100:
            _color = "orange"
        else:
            _color = "green"

        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3, 2, 3, 2])
            with c1:
                st.markdown(f"**{ev['name']}**")
                st.caption(f"`{ev['slug']}`")
            with c2:
                parts = []
                if ev["error_count"]:
                    parts.append(f"{ev['error_count']} error")
                if ev["decomm_count"]:
                    parts.append(f"{ev['decomm_count']} decommissioned")
                st.markdown(f":{_color}[{', '.join(parts)}]")
                st.caption(f"{ev['healthy']}/{ev['total']} healthy ({ev['healthy_pct']}%)")
            with c3:
                st.progress(ev["healthy_pct"] / 100)
            with c4:
                _event_url = f"https://snowflake.dataops.live/event-deployments/{ev['slug']}"
                st.link_button("View in DataOps", _event_url, use_container_width=True)
