"""Create event form."""

import streamlit as st
import urllib.parse as _urlparse
import requests as _requests
from datetime import date
from pathlib import Path
from api_client import DataOpsClient, DataOpsAPIError
from utils import validate_slug, parse_comma_list


GITLAB_BASE = "https://app.dataops.live/api/v4"


def _gitlab_fork(token: str, fork_parent_path: str, configure_project: str) -> tuple[bool, str, str]:
    """Fork fork_parent_path into configure_project's namespace with configure_project's slug.
    Returns (success, message, fork_url).
    """
    headers = {"PRIVATE-TOKEN": token}

    # Look up parent project ID
    try:
        resp = _requests.get(
            f"{GITLAB_BASE}/projects/{_urlparse.quote(fork_parent_path, safe='')}",
            headers=headers, timeout=10
        )
        if resp.status_code != 200:
            return False, f"Could not find parent project (HTTP {resp.status_code}).", ""
        parent_id = resp.json()["id"]
    except Exception as e:
        return False, f"Error looking up parent project: {e}", ""

    # Derive namespace and path from configure_project
    parts = configure_project.rstrip("/").split("/")
    fork_path = parts[-1]
    fork_namespace = "/".join(parts[:-1])
    fork_url = f"https://app.dataops.live/{configure_project}"

    # Fork it
    try:
        fork_resp = _requests.post(
            f"{GITLAB_BASE}/projects/{parent_id}/fork",
            headers={**headers, "Content-Type": "application/json"},
            json={"namespace_path": fork_namespace, "path": fork_path, "name": fork_path},
            timeout=30,
        )
        if fork_resp.status_code == 201:
            return True, "Fork created successfully.", fork_url
        elif fork_resp.status_code == 409:
            return True, "Fork already exists.", fork_url
        else:
            body = fork_resp.json()
            msg = body.get("message", str(body))
            return False, f"Fork failed (HTTP {fork_resp.status_code}): {msg}", ""
    except Exception as e:
        return False, f"Error creating fork: {e}", ""


DELIVERY_FORMAT_OPTIONS = ["HANDS_ON_LAB", "WORKSHOP", "TRAINING", "HACKATHON", "OTHER"]

_DELIVERY_FORMAT_MAP = {
    "hands on lab": "HANDS_ON_LAB",
    "hands-on-lab": "HANDS_ON_LAB",
    "virtual hands on lab": "HANDS_ON_LAB",
    "in person hands on lab": "HANDS_ON_LAB",
    "hol": "HANDS_ON_LAB",
    "workshop": "WORKSHOP",
    "training": "TRAINING",
    "hackathon": "HACKATHON",
    "hack": "HACKATHON",
}

def _map_delivery_format(raw: str) -> str:
    """Map a free-text EVENT_TYPE to a valid API delivery_format enum value."""
    if not raw:
        return "HANDS_ON_LAB"
    lower = raw.lower().strip()
    for key, val in _DELIVERY_FORMAT_MAP.items():
        if key in lower:
            return val
    if lower in [v.lower() for v in DELIVERY_FORMAT_OPTIONS]:
        return lower.upper()
    return "OTHER"
REGION_OPTIONS = ["aws_us_west_2", "aws_us_east_1", "aws_eu_west_1", "azure_eastus2", "gcp_us_central1"]


def load_default_instructions() -> str:
    template_path = Path(__file__).parent.parent / "templates" / "default-instructions.html"
    if template_path.exists():
        return template_path.read_text()
    return ""


def _parse_date_param(value: str | None) -> date | None:
    """Parse an ISO date string (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ) to a date object."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _read_prefill() -> dict:
    """Read pre-fill values from URL query parameters."""
    qp = st.query_params
    from datetime import timedelta as _td
    _end = _parse_date_param(qp.get("end_date"))
    _decomm = _parse_date_param(qp.get("decommission_date")) or (_end + _td(days=2) if _end else None)
    return {
        "slug":              qp.get("slug", ""),
        "name":              qp.get("name", ""),
        "start_date":        _parse_date_param(qp.get("start_date")),
        "end_date":          _end,
        "decommission_date": _decomm,
        "build_date":        _parse_date_param(qp.get("build_date")),
        "pool_size":         int(qp["pool_size"]) if qp.get("pool_size", "").isdigit() else 0,
        "attendee_email":    qp.get("attendee_email", ""),
        "attendee_name":     qp.get("attendee_name", ""),
        "region":            qp.get("region", "").lower(),
        "delivery_format": _map_delivery_format(qp.get("delivery_format", "")),
        "configure_project": qp.get("configure_project", ""),
        "fork_parent":       qp.get("fork_parent", ""),
    }


def render(client: DataOpsClient):
    st.header("➕ Create Event")

    # Execute pending create action (must be before any early return)
    if st.session_state.get("_create_pending"):
        _payload = st.session_state.pop("_create_payload", {})
        _slug = st.session_state.pop("_create_slug", "")
        st.session_state.pop("_create_pending", None)
        with st.spinner("Creating event..."):
            try:
                result = client.create_event(_slug, _payload)
                st.success("Event created successfully!")
                st.markdown(f"- **Slug:** `{_slug}`")
                st.markdown(f"- **URL:** https://snowflake.dataops.live/event-deployments/{_slug}")
                st.session_state["selected_event_slug"] = _slug
                if isinstance(result, dict):
                    st.json(result)
            except DataOpsAPIError as e:
                st.error(f"Failed to create event: {e}")
                st.code(e.body)
            except Exception as e:
                st.error(f"Unexpected error: {e}")
        return

    prefill = _read_prefill()
    has_prefill = any([prefill["name"], prefill["slug"], prefill["start_date"]])

    if has_prefill:
        st.info(
            "ℹ️ Form pre-filled from HOL Analytics Dashboard. Review all fields before submitting.",
            icon="ℹ️",
        )

    # Fork Repository section — shown for custom/fork-type events
    # (Only shown when fork_parent is explicitly passed via URL)
    if False:  # Replaced by inline fork button near configure_project field below
        pass

    # Slug field lives outside the form so availability is checked on every keystroke
    st.subheader("Event Slug")
    slug = st.text_input(
        "Event Slug*",
        value=prefill["slug"].strip(),
        key="slug_input",
        help="Max 31 chars, lowercase, starts with a letter, alphanumerics and hyphens only.",
    )
    if slug:
        slug = slug.strip()
        slug_valid, slug_err = validate_slug(slug)
        if slug_valid:
            try:
                client.get_event(slug)
                event_url = f"https://snowflake.dataops.live/event-deployments/{slug}"
                st.warning(f"⚠️ Slug `{slug}` is already taken — this event likely already exists.")
                st.info(f"If the HOL URL is missing in the HOL Request Tracker, copy this: `{event_url}`")
            except DataOpsAPIError as _ce:
                if _ce.status_code == 404:
                    st.success(f"✅ Slug `{slug}` is available.")
            except Exception:
                pass
        else:
            st.caption(f"🔴 {slug_err}")

    # Configure Project Path — outside form so fork button can react immediately
    st.subheader("Configure Project")
    configure_project_val = st.text_input(
        "DataOps Configure Project Path",
        value=prefill["configure_project"],
        key="configure_project_input",
        help="e.g. snowflake/hands-on-labs/zero-to-snowflake-v-2",
    )

    # Detect fork-type path and show fork button
    _fork_parent = prefill["fork_parent"]
    if not _fork_parent and configure_project_val:
        import re as _re
        _m = _re.match(r'^(snowflake/hands-on-lab-drafts/[a-z0-9-]+)-[a-z0-9-]+$', configure_project_val)
        if _m:
            _fork_parent = _m.group(1)

    if _fork_parent and configure_project_val:
        _fork_key = f"fork_state_{configure_project_val}"
        if _fork_key not in st.session_state:
            st.session_state[_fork_key] = None
        _fork_state = st.session_state[_fork_key]
        _fork_url = f"https://app.dataops.live/{configure_project_val}"

        if _fork_state == "success":
            st.success(f"Fork created: [{configure_project_val}]({_fork_url})")
        elif _fork_state == "exists":
            st.info(f"Fork already exists: [{configure_project_val}]({_fork_url}) — proceed with form below.")
        elif isinstance(_fork_state, str) and _fork_state:
            st.error(_fork_state)

        if _fork_state not in ("success", "exists"):
            _fc1, _fc2 = st.columns([1, 3])
            with _fc1:
                if st.button("Create Fork", type="primary", key="create_fork_btn", use_container_width=True):
                    _token = st.secrets.get("DATAOPS_API_TOKEN", "")
                    with st.spinner("Creating fork in GitLab..."):
                        _ok, _msg, _ = _gitlab_fork(_token, _fork_parent, configure_project_val)
                    if _ok and "already exists" in _msg:
                        st.session_state[_fork_key] = "exists"
                    elif _ok:
                        st.session_state[_fork_key] = "success"
                    else:
                        st.session_state[_fork_key] = _msg
                    st.rerun()
            with _fc2:
                st.caption(f"Forks `{_fork_parent}` → `{configure_project_val}`")
    elif configure_project_val:
        st.caption("Standard HOL content — no fork needed.")

    with st.form("create_event_form"):
        st.subheader("Required Fields")
        decommission_date = st.date_input(
            "Decommission Date*",
            value=prefill["decommission_date"],
        )
        st.subheader("Event Details")
        name = st.text_input("Event Name", value=prefill["name"])
        location = st.text_input("Location", value="Virtual")
        delivery_format = st.selectbox(
            "Delivery Format",
            DELIVERY_FORMAT_OPTIONS,
            index=DELIVERY_FORMAT_OPTIONS.index(prefill["delivery_format"])
                  if prefill["delivery_format"] in DELIVERY_FORMAT_OPTIONS else 0,
        )

        st.subheader("Dates")
        col1, col2, col3 = st.columns(3)
        with col1:
            build_date = st.date_input("Build Date", value=prefill["build_date"])
        with col2:
            start_date = st.date_input("Start Date", value=prefill["start_date"])
        with col3:
            end_date = st.date_input("End Date", value=prefill["end_date"])

        st.subheader("Configuration")
        col_a, col_b = st.columns(2)
        with col_a:
            pool_size = st.number_input("Pool Size", min_value=0, value=prefill["pool_size"], step=1)
            edition = st.selectbox("Snowflake Edition", EDITION_OPTIONS, index=0)
            region = st.selectbox(
                "Region Group", REGION_OPTIONS,
                index=REGION_OPTIONS.index(prefill["region"]) if prefill["region"] in REGION_OPTIONS else 0,
                key="region_group",
            )
        with col_b:
            is_express = st.checkbox("Express Mode")
            express_hours = st.number_input(
                "Express Token Duration (hours)", min_value=1, value=24, step=1, disabled=not is_express
            )
            instructor_reconfigure = st.checkbox("Instructor Reconfigure")

        allowed_domains = st.text_input("Allowed Email Domains", help="Comma-separated, e.g. snowflake.com, acme.org")

        # Attendee pre-fill (shown read-only so user knows what will be submitted)
        if prefill["attendee_email"]:
            st.subheader("Requestor (Attendee)")
            st.caption(
                f"Will be added as attendee: **{prefill['attendee_name']}** "
                f"&lt;{prefill['attendee_email']}&gt;"
            )

        submitted = st.form_submit_button("Preview & Validate", use_container_width=True)

    if not submitted:
        # Show the summary and confirm button if payload is pending
        if st.session_state.get("_pending_payload"):
            _p = st.session_state["_pending_payload"]
            _s = st.session_state["_pending_slug"]
            st.divider()
            st.subheader("Creation Summary")
            st.json({k: v for k, v in _p.items() if k != "instructions"})
            st.warning("⚠️ This action creates a new live event. This cannot be undone easily.")
            if st.button("🚀 Create Event", type="primary", key="create_btn"):
                st.session_state["_create_pending"] = True
                st.session_state["_create_payload"] = _p
                st.session_state["_create_slug"] = _s
                st.session_state.pop("_pending_payload", None)
                st.session_state.pop("_pending_slug", None)
                st.rerun()
        return

    # Read configure_project from session state (field is outside the form)
    configure_project = st.session_state.get("configure_project_input", "").strip()
    # Validate slug
    valid, error = validate_slug(slug)
    if not valid:
        st.error(f"Slug validation failed: {error}")
        return

    # Build payload
    payload = {
        "slug": slug,
        "decommission_date": f"{decommission_date.isoformat()}T00:00:00Z",
    }

    if name:
        payload["name"] = name
    if location:
        payload["location"] = location
    if delivery_format:
        payload["delivery_format"] = delivery_format
    if build_date:
        payload["build_date"] = f"{build_date.isoformat()}T00:00:00Z"
    if start_date:
        payload["start_date"] = f"{start_date.isoformat()}T00:00:00Z"
    if end_date:
        payload["end_date"] = f"{end_date.isoformat()}T00:00:00Z"
    if pool_size > 0:
        payload["pool_size"] = pool_size
    if configure_project:
        payload["dataops_configure_project_path"] = configure_project
    if is_express:
        payload["is_express"] = True
        payload["express_token_duration_hours"] = express_hours
    if instructor_reconfigure:
        payload["instructor_reconfigure"] = True
    if allowed_domains:
        payload["allowed_email_domains"] = parse_comma_list(allowed_domains)
    if prefill["attendee_email"]:
        payload["attendees"] = [{
            "name":  prefill["attendee_name"] or prefill["attendee_email"],
            "email": prefill["attendee_email"],
            "role":  "attendee",
        }]

    # Hard-coded fields
    payload["snowflake_account_edition"] = edition
    payload["snowflake_account_region_group"] = region
    payload["organization_account_identifier"] = "SFSEHOL-SFSEHOL_ADMIN"
    payload["initial_pool_size"] = payload.get("pool_size", 0)
    payload["instructions"] = load_default_instructions()

    # Store payload for the confirm step (shown on next rerun via the early-return path above)
    st.session_state["_pending_payload"] = payload
    st.session_state["_pending_slug"] = slug
    st.rerun()
