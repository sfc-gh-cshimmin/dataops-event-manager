"""Create event form."""

import streamlit as st
import urllib.parse as _urlparse
import requests as _requests
from datetime import date, time, datetime, timezone, timedelta
from pathlib import Path
from api_client import DataOpsClient, DataOpsAPIError
from utils import validate_slug, parse_comma_list
from snowflake_helpers import get_token, load_fork_parents, get_query_params


# Common US timezone abbreviations → UTC offset hours
_TZ_OFFSETS = {
    "EST": -5, "EDT": -4, "ET": -5,
    "CST": -6, "CDT": -5, "CT": -6,
    "MST": -7, "MDT": -6, "MT": -7,
    "PST": -8, "PDT": -7, "PT": -8,
    "AKST": -9, "AKDT": -8,
    "HST": -10, "HAST": -10,
    "AST": -4, "ADT": -3,
    "UTC": 0, "GMT": 0,
    "CET": 1, "CEST": 2,
    "IST": 5,  # +5:30 approximated
    "JST": 9, "AEST": 10, "AEDT": 11,
    "NZST": 12, "NZDT": 13,
}


def _tz_offset_str(tz_abbrev: str) -> str:
    """Return an ISO offset string like '-05:00' for a timezone abbreviation."""
    if not tz_abbrev:
        return "+00:00"
    key = tz_abbrev.strip().upper()
    hours = _TZ_OFFSETS.get(key, 0)
    sign = "+" if hours >= 0 else "-"
    return f"{sign}{abs(hours):02d}:00"


def _format_datetime(d: date | None, t: time | None, tz_abbrev: str) -> str | None:
    """Combine date + time into an ISO datetime string offset for DataOps display.
    DataOps displays all datetimes in UTC+9 (JST), so we always encode with +09:00
    so that the time entered by the user is the time shown in DataOps.
    tz_abbrev is retained as a form field for reference but does not affect the API value.
    """
    if not d:
        return None
    t = t or time(0, 0)
    return f"{d.isoformat()}T{t.strftime('%H:%M:%S')}+09:00"


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


def _gitlab_add_member(token: str, project_path: str, email: str, access_level: int = 40) -> tuple[bool, str]:
    """Add a user (by email) to a GitLab project with the given access level (40 = Maintainer).
    Returns (success, message).
    """
    headers = {"PRIVATE-TOKEN": token}
    # Look up the user by email
    try:
        resp = _requests.get(
            f"{GITLAB_BASE}/users",
            headers=headers,
            params={"search": email},
            timeout=10,
        )
        users = resp.json() if resp.status_code == 200 else []
        # Find an exact email match
        user_id = next((u["id"] for u in users if u.get("public_email") == email or u.get("email") == email), None)
        if not user_id and users:
            user_id = users[0]["id"]  # fallback: first result
        if not user_id:
            return False, f"Could not find GitLab user for {email}."
    except Exception as e:
        return False, f"Error looking up user: {e}"

    # Add member to project
    try:
        _proj_encoded = _urlparse.quote(project_path, safe="")
        add_resp = _requests.post(
            f"{GITLAB_BASE}/projects/{_proj_encoded}/members",
            headers={**headers, "Content-Type": "application/json"},
            json={"user_id": user_id, "access_level": access_level},
            timeout=10,
        )
        if add_resp.status_code in (200, 201):
            return True, f"Added {email} as Maintainer."
        elif add_resp.status_code == 409:
            return True, f"{email} is already a member."
        else:
            body = add_resp.json()
            return False, f"Failed to add member (HTTP {add_resp.status_code}): {body.get('message', body)}"
    except Exception as e:
        return False, f"Error adding member: {e}"


EDITION_OPTIONS = ["ENTERPRISE", "BUSINESS_CRITICAL", "STANDARD"]
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
REGION_OPTIONS = [
    # AWS
    "aws_us_west_2", "aws_us_east_1", "aws_us_east_2",
    "aws_ca_central_1", "aws_sa_east_1",
    "aws_eu_west_1", "aws_eu_west_2", "aws_eu_west_3",
    "aws_eu_central_1", "aws_eu_central_2", "aws_eu_north_1",
    "aws_ap_northeast_1", "aws_ap_northeast_2", "aws_ap_northeast_3",
    "aws_ap_south_1", "aws_ap_southeast_1", "aws_ap_southeast_2", "aws_ap_southeast_3",
    # GCP
    "gcp_us_central1", "gcp_us_east4",
    "gcp_europe_west2", "gcp_europe_west3", "gcp_europe_west4",
    "gcp_me_central2",
    # Azure
    "azure_westus2", "azure_centralus", "azure_southcentralus", "azure_eastus2",
    "azure_canadacentral", "azure_mexicocentral",
    "azure_uksouth", "azure_northeurope", "azure_westeurope", "azure_switzerlandnorth",
    "azure_uaenorth", "azure_centralindia", "azure_japaneast",
    "azure_southeastasia", "azure_australiaeast",
]

REGION_LABELS = {
    "aws_us_west_2":        "US West (Oregon) — aws_us_west_2",
    "aws_us_east_1":        "US East (N. Virginia) — aws_us_east_1",
    "aws_us_east_2":        "US East (Ohio) — aws_us_east_2",
    "aws_ca_central_1":     "Canada (Central) — aws_ca_central_1",
    "aws_sa_east_1":        "South America (São Paulo) — aws_sa_east_1",
    "aws_eu_west_1":        "EU (Ireland) — aws_eu_west_1",
    "aws_eu_west_2":        "EU (London) — aws_eu_west_2",
    "aws_eu_west_3":        "EU (Paris) — aws_eu_west_3",
    "aws_eu_central_1":     "EU (Frankfurt) — aws_eu_central_1",
    "aws_eu_central_2":     "EU (Zurich) — aws_eu_central_2",
    "aws_eu_north_1":       "EU (Stockholm) — aws_eu_north_1",
    "aws_ap_northeast_1":   "Asia Pacific (Tokyo) — aws_ap_northeast_1",
    "aws_ap_northeast_2":   "Asia Pacific (Seoul) — aws_ap_northeast_2",
    "aws_ap_northeast_3":   "Asia Pacific (Osaka) — aws_ap_northeast_3",
    "aws_ap_south_1":       "Asia Pacific (Mumbai) — aws_ap_south_1",
    "aws_ap_southeast_1":   "Asia Pacific (Singapore) — aws_ap_southeast_1",
    "aws_ap_southeast_2":   "Asia Pacific (Sydney) — aws_ap_southeast_2",
    "aws_ap_southeast_3":   "Asia Pacific (Jakarta) — aws_ap_southeast_3",
    "gcp_us_central1":      "GCP US Central (Iowa) — gcp_us_central1",
    "gcp_us_east4":         "GCP US East (N. Virginia) — gcp_us_east4",
    "gcp_europe_west2":     "GCP Europe West (London) — gcp_europe_west2",
    "gcp_europe_west3":     "GCP Europe West (Frankfurt) — gcp_europe_west3",
    "gcp_europe_west4":     "GCP Europe West (Netherlands) — gcp_europe_west4",
    "gcp_me_central2":      "GCP Middle East (Dammam) — gcp_me_central2",
    "azure_westus2":        "Azure West US 2 (Washington) — azure_westus2",
    "azure_centralus":      "Azure Central US (Iowa) — azure_centralus",
    "azure_southcentralus": "Azure South Central US (Texas) — azure_southcentralus",
    "azure_eastus2":        "Azure East US 2 (Virginia) — azure_eastus2",
    "azure_canadacentral":  "Azure Canada Central (Toronto) — azure_canadacentral",
    "azure_mexicocentral":  "Azure Mexico Central (Mexico City) — azure_mexicocentral",
    "azure_uksouth":        "Azure UK South (London) — azure_uksouth",
    "azure_northeurope":    "Azure North Europe (Ireland) — azure_northeurope",
    "azure_westeurope":     "Azure West Europe (Netherlands) — azure_westeurope",
    "azure_switzerlandnorth": "Azure Switzerland North (Zurich) — azure_switzerlandnorth",
    "azure_uaenorth":       "Azure UAE North (Dubai) — azure_uaenorth",
    "azure_centralindia":   "Azure Central India (Pune) — azure_centralindia",
    "azure_japaneast":      "Azure Japan East (Tokyo) — azure_japaneast",
    "azure_southeastasia":  "Azure Southeast Asia (Singapore) — azure_southeastasia",
    "azure_australiaeast":  "Azure Australia East (New South Wales) — azure_australiaeast",
}


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
    """Read pre-fill values from pasted JSON (session state) or URL query parameters."""
    # Check for pasted JSON first
    raw_json = st.session_state.get("_pasted_event_json", "")
    if raw_json:
        try:
            import json
            data = json.loads(raw_json)
            if isinstance(data, dict):
                _end = _parse_date_param(data.get("end_date"))
                _decomm = _parse_date_param(data.get("decommission_date")) or (_end + timedelta(days=2) if _end else None)
                return {
                    "slug":              data.get("slug", ""),
                    "name":              data.get("name", ""),
                    "start_date":        _parse_date_param(data.get("start_date")),
                    "end_date":          _end,
                    "decommission_date": _decomm,
                    "build_date":        _parse_date_param(data.get("build_date")),
                    "pool_size":         int(data["pool_size"]) if str(data.get("pool_size", "")).isdigit() else 0,
                    "attendee_email":    data.get("attendee_email", ""),
                    "attendee_name":     data.get("attendee_name", ""),
                    "region":            data.get("region", "").lower().replace("-", "_"),
                    "delivery_format":   _map_delivery_format(data.get("delivery_format", "")),
                    "configure_project": data.get("configure_project", ""),
                    "fork_parent":       data.get("fork_parent", ""),
                    "timezone":          data.get("timezone", ""),
                }
        except Exception:
            pass

    # Fallback: read from URL query params
    qp = get_query_params()
    _end = _parse_date_param(qp.get("end_date"))
    _decomm = _parse_date_param(qp.get("decommission_date")) or (_end + timedelta(days=2) if _end else None)
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
        "region":            qp.get("region", "").lower().replace("-", "_"),
        "delivery_format": _map_delivery_format(qp.get("delivery_format", "")),
        "configure_project": qp.get("configure_project", ""),
        "fork_parent":       qp.get("fork_parent", ""),
        "salesforce_id":     qp.get("salesforce_id", ""),
        "timezone":          qp.get("timezone", ""),
    }


def render(client: DataOpsClient):
    st.header("➕ Create Event")

    # Execute pending approve action
    if st.session_state.get("_approve_pending"):
        _approve_slug = st.session_state.pop("_approve_slug", "")
        st.session_state.pop("_approve_pending", None)
        try:
            client.approve_event(_approve_slug)
            if "_just_created" in st.session_state:
                st.session_state["_just_created"]["approved"] = True
        except DataOpsAPIError as _ae:
            if "_just_created" in st.session_state:
                st.session_state["_just_created"]["approve_error"] = str(_ae.body)
        except Exception as _ae:
            if "_just_created" in st.session_state:
                st.session_state["_just_created"]["approve_error"] = str(_ae)
        st.rerun()

    # Execute pending create action (must be before any early return)
    if st.session_state.get("_create_pending"):
        _payload = st.session_state.pop("_create_payload", {})
        _slug = st.session_state.pop("_create_slug", "")
        _instructor_emails = st.session_state.pop("_pending_instructors", [])
        st.session_state.pop("_create_pending", None)
        with st.spinner("Creating event..."):
            try:
                result = client.create_event(_slug, _payload)
                st.session_state["_just_created"] = {
                    "slug": _slug,
                    "name": _payload.get("name", _slug),
                    "event_url": f"https://snowflake.dataops.live/event-deployments/{_slug}",
                    "result": result,
                }
                st.session_state["selected_event_slug"] = _slug
            except DataOpsAPIError as e:
                st.error(f"Failed to create event: {e}")
                st.code(e.body)
                return
            except Exception as e:
                st.error(f"Unexpected error: {e}")
                return
        # Add instructors after successful event creation
        if _instructor_emails:
            try:
                client.add_instructors(_slug, _instructor_emails)
                st.session_state["_just_created"]["instructors_added"] = _instructor_emails
            except Exception as _ie:
                st.session_state["_just_created"]["instructor_error"] = str(_ie)
        st.rerun()

    # Show persistent success page after event creation
    if st.session_state.get("_just_created"):
        _jc = st.session_state["_just_created"]
        _slug = _jc["slug"]
        _event_name = _jc.get("name", _slug)
        _event_url = _jc["event_url"]
        st.success("✅ Event created successfully!")
        st.info(
            f"**Next step:** Copy the event URL below and paste it into the "
            f"**HOL URL** field for **{_event_name}** in the HOL Request Tracker."
        )
        _rc1, _rc2 = st.columns(2)
        with _rc1:
            st.markdown(f"**Slug:** `{_slug}`")
            st.markdown(f"**URL:** [{_event_url}]({_event_url})")
        with _rc2:
            if _jc.get("approved"):
                st.success(f"Event `{_slug}` approved!")
            elif _jc.get("approve_error"):
                st.error(f"Approval failed: {_jc['approve_error']}")
                if st.button("Retry Approve", type="primary", key="retry_approve_btn"):
                    _jc.pop("approve_error", None)
                    st.session_state["_approve_pending"] = True
                    st.session_state["_approve_slug"] = _slug
                    st.rerun()
            else:
                if st.button("✅ Approve Event", type="primary", key="approve_btn"):
                    st.session_state["_approve_pending"] = True
                    st.session_state["_approve_slug"] = _slug
                    st.rerun()
        if isinstance(_jc.get("result"), dict):
            with st.expander("API response", expanded=False):
                st.json(_jc["result"])
        # Instructor results
        if _jc.get("instructors_added"):
            st.success(f"✅ Instructors added: {', '.join(_jc['instructors_added'])}")
        elif _jc.get("instructor_error"):
            st.warning(f"⚠️ Event created but instructor assignment failed: {_jc['instructor_error']}")
        if st.button("Create Another Event", key="create_another_btn"):
            st.session_state.pop("_just_created", None)
            st.rerun()
        return

    # JSON fallback — hidden by default, shown via toggle
    if st.toggle("Use JSON fallback", key="show_json_fallback", value=bool(st.session_state.get("_pasted_event_json"))):
        _paste_val = st.text_area(
            "Paste JSON from HOL Tracker",
            value=st.session_state.get("_pasted_event_json", ""),
            height=120,
            key="_paste_input",
            placeholder='{"name": "...", "slug": "...", "start_date": "..."}',
            help="Copy the JSON from the HOL Request Tracker and paste here to pre-fill the form.",
        )
        if st.button("Load", key="load_json_btn"):
            st.session_state["_pasted_event_json"] = _paste_val
            st.rerun()

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

    # Configure Project section — all outside form so fork button can react immediately
    st.subheader("Configure Project")

    _prefill_fp = prefill["fork_parent"]
    _default_cp_mode = "Fork a repo" if _prefill_fp else "Set configure project"
    _cp_mode = st.radio(
        "Mode",
        ["Set configure project", "Fork a repo"],
        index=["Set configure project", "Fork a repo"].index(_default_cp_mode),
        horizontal=True,
        key="cp_mode_toggle",
        help="Set configure project = search and pick a repo directly.  Fork a repo = create a fork first.",
    )

    _fork_parent = None  # only set in Fork a repo mode
    _selected_group = "Published HOLs"  # default; overridden in Fork a repo mode

    if _cp_mode == "Set configure project":
        # Search GitLab to directly set configure project path (no fork created)
        _dc_col, _dc_btn = st.columns([4, 1])
        with _dc_col:
            _dc_search = st.text_input(
                "Search repos",
                key="dc_repo_search_input",
                placeholder="e.g. cortex, zero-to-snowflake, data-engineering",
                label_visibility="collapsed",
            )
        with _dc_btn:
            _dc_do_search = st.button("Search", key="dc_repo_search_btn", use_container_width=True)

        if _dc_do_search and _dc_search.strip():
            _token = get_token()
            _headers = {"PRIVATE-TOKEN": _token}
            _dc_results = []
            for _gid in ["snowflake"]:
                _page = 1
                while True:
                    try:
                        _resp = _requests.get(
                            f"{GITLAB_BASE}/groups/{_gid}/projects",
                            headers=_headers,
                            params={"search": _dc_search.strip(), "per_page": 100, "page": _page, "include_subgroups": "true"},
                            timeout=10,
                        )
                        if _resp.status_code != 200:
                            break
                        _page_results = _resp.json()
                        _dc_results += [p["path_with_namespace"] for p in _page_results]
                        if len(_page_results) < 100:
                            break
                        _page += 1
                    except Exception:
                        break
            _dc_results = [p for p in _dc_results if not p.startswith("snowflake/instances/")]

        _dc_results = st.session_state.get("_dc_search_results", [])
        if _dc_results:
            _dc_selected = st.selectbox(
                "Select repo",
                [None] + _dc_results,
                format_func=lambda x: "None" if x is None else x,
                key="dc_repo_select",
            )
            if _dc_selected:
                _uc1, _uc2 = st.columns([1, 3])
                with _uc1:
                    if st.button("Use this repo", key="dc_use_repo_btn", type="primary", use_container_width=True):
                        st.session_state["_cp_direct_path"] = _dc_selected
                        st.rerun()
                with _uc2:
                    st.caption(f"Sets configure project to `{_dc_selected}`")
        elif _dc_do_search:
            st.caption("No repos found. Try a different search term.")

        # In Set mode: init configure_project to prefill on first load only
        _cp_state_key = ("direct", None)
        if st.session_state.get("_cp_last_fork_parent") != _cp_state_key:
            st.session_state["configure_project_input"] = prefill["configure_project"]
            st.session_state["_cp_last_fork_parent"] = _cp_state_key

    else:  # Fork a repo mode — existing fork parent UI
        _fp_mode = st.radio(
            "Fork Parent",
            ["Common repos", "Search all repos"],
            horizontal=True,
            key="fp_mode_toggle",
            help="Common repos = curated list. Search = query all repos in the snowflake group and subgroups.",
        )

        if _fp_mode == "Common repos":
            _fork_parent_data = load_fork_parents()
            _fp_labels = ["None (standard deployment)"] + [fp["label"] for fp in _fork_parent_data]
            _fp_paths  = [None] + [fp["path"] for fp in _fork_parent_data]
            _default_fp_idx = 0
            if _prefill_fp:
                for _i, _p in enumerate(_fp_paths):
                    if _p == _prefill_fp:
                        _default_fp_idx = _i
                        break

            _selected_fp_label = st.selectbox(
                "Fork Parent Repo",
                _fp_labels,
                index=_default_fp_idx,
                key="cp_fork_parent",
                help="Repo to fork from.",
            )
            _fork_parent = _fp_paths[_fp_labels.index(_selected_fp_label)]

        else:  # Search all repos for fork parent
            _search_col, _btn_col = st.columns([4, 1])
            with _search_col:
                _repo_search = st.text_input(
                    "Search repos",
                    key="repo_search_input",
                    placeholder="e.g. cortex, zero-to-snowflake, data-engineering",
                    label_visibility="collapsed",
                )
            with _btn_col:
                _do_search = st.button("Search", key="repo_search_btn", use_container_width=True)

            if _do_search and _repo_search.strip():
                _token = get_token()
                _headers = {"PRIVATE-TOKEN": _token}
                _results = []
                for _gid in ["snowflake"]:
                    _page = 1
                    while True:
                        try:
                            _resp = _requests.get(
                                f"{GITLAB_BASE}/groups/{_gid}/projects",
                                headers=_headers,
                                params={"search": _repo_search.strip(), "per_page": 100, "page": _page, "include_subgroups": "true"},
                                timeout=10,
                            )
                            if _resp.status_code != 200:
                                break
                            _page_results = _resp.json()
                            _results += [p["path_with_namespace"] for p in _page_results]
                            if len(_page_results) < 100:
                                break
                            _page += 1
                        except Exception:
                            break
                st.session_state["_repo_search_results"] = [p for p in _results if not p.startswith("snowflake/instances/")] or []

            _search_results = st.session_state.get("_repo_search_results", [])
            if _search_results:
                _fork_parent = st.selectbox(
                    "Select repo",
                    [None] + _search_results,
                    format_func=lambda x: "None (standard deployment)" if x is None else x,
                    key="cp_fork_parent_search",
                )
            elif _do_search:
                st.caption("No repos found. Try a different search term.")
                _fork_parent = None
            else:
                _fork_parent = _prefill_fp or None

        # Destination group toggle — controls which namespace the fork lands in
        _group_default = "Drafts" if (_prefill_fp and "hands-on-lab-drafts" in _prefill_fp) else "Published HOLs"
        if "fork_group_toggle" not in st.session_state:
            st.session_state["fork_group_toggle"] = _group_default
        _selected_group = st.radio(
            "Destination Group",
            ["Drafts", "Published HOLs"],
            horizontal=True,
            key="fork_group_toggle",
            help="Drafts = hands-on-lab-drafts  |  Published HOLs = hands-on-labs",
        )
        _dest_namespace = "hands-on-lab-drafts" if _selected_group == "Drafts" else "hands-on-labs"

        # Auto-derive configure project path from fork parent + destination group + slug
        _slug_val = (st.session_state.get("slug_input") or prefill["slug"] or "").strip()
        _fork_parent_name = _fork_parent.split("/")[-1] if _fork_parent else ""
        if _fork_parent and _slug_val:
            _auto_cp = f"snowflake/{_dest_namespace}/{_fork_parent_name}-{_slug_val}"
        elif _fork_parent:
            _auto_cp = f"snowflake/{_dest_namespace}/{_fork_parent_name}"
        else:
            _auto_cp = prefill["configure_project"]

        _cp_state_key = (_fork_parent, _selected_group)
        if st.session_state.get("_cp_last_fork_parent") != _cp_state_key:
            st.session_state["configure_project_input"] = _auto_cp
            st.session_state["_cp_last_fork_parent"] = _cp_state_key

    # Apply direct repo selection (Set configure project mode) before widget renders
    if st.session_state.get("_cp_direct_path"):
        st.session_state["configure_project_input"] = st.session_state.pop("_cp_direct_path")

    # Apply standard fork success path before widget renders (avoids post-render mutation error)
    if st.session_state.get("_std_fork_success_path"):
        st.session_state["configure_project_input"] = st.session_state.pop("_std_fork_success_path")

    configure_project_val = st.text_input(
        "DataOps Configure Project Path",
        key="configure_project_input",
        help="e.g. snowflake/hands-on-labs/zero-to-snowflake-v-2 — auto-filled from fork parent + slug, editable.",
    )
    salesforce_id_val = st.text_input(
        "Salesforce Campaign ID",
        value=prefill["salesforce_id"],
        key="salesforce_id_input",
        help="Passed as DATAOPS_CATALOG_SALESFORCE_ID in extra_env_vars",
    )

    # Standard HOL fork toggle — only in Fork a repo mode, when no fork_parent from URL
    if _cp_mode == "Fork a repo" and configure_project_val and not _fork_parent:
        _std_fork_on = st.toggle(
            "Fork this repo for this event",
            key="std_fork_toggle",
            help="Creates a fork named {parent_repo}-{slug}. Choose a destination group below.",
        )
        if _std_fork_on:
            _slug_for_fork = (st.session_state.get("slug_input") or prefill["slug"] or "").strip()
            _cp_parts    = configure_project_val.rstrip("/").split("/")
            _cp_basename = _cp_parts[-1]
            _parent_ns   = "/".join(_cp_parts[:-1])

            _default_group = "Drafts" if "hands-on-lab-drafts" in _parent_ns else "Published HOLs"
            _std_dest_group = st.radio(
                "Destination Group",
                ["Drafts", "Published HOLs"],
                index=["Drafts", "Published HOLs"].index(_default_group),
                horizontal=True,
                key="std_fork_dest_group",
                help="Drafts = hands-on-lab-drafts  |  Published HOLs = hands-on-labs",
            )
            _std_dest_ns   = "snowflake/hands-on-lab-drafts" if _std_dest_group == "Drafts" else "snowflake/hands-on-labs"
            _suffix        = f"-{_slug_for_fork}" if _slug_for_fork else "-event"
            _std_fork_path = f"{_std_dest_ns}/{_cp_basename}{_suffix}"

            st.caption(f"Fork target: `{_std_fork_path}`")

            _std_fork_key   = f"fork_state_{_std_fork_path}"
            _std_fork_state = st.session_state.setdefault(_std_fork_key, None)
            _std_fork_status = None
            try:
                _token = get_token()
                _cr = _requests.get(
                    f"{GITLAB_BASE}/projects/{_urlparse.quote(_std_fork_path, safe='')}",
                    headers={"PRIVATE-TOKEN": _token},
                    timeout=5,
                )
                _std_fork_status = _cr.status_code
            except Exception:
                pass

            if _std_fork_state == "success":
                st.success(f"Fork created: [{_std_fork_path}](https://app.dataops.live/{_std_fork_path})")
            elif _std_fork_state == "exists" or _std_fork_status == 200:
                st.info(f"Fork already exists — [{_std_fork_path}](https://app.dataops.live/{_std_fork_path})")
            _mem_result = st.session_state.get(f"_fork_member_{_std_fork_path}")
            if _mem_result:
                st.caption(f"👤 {_mem_result}")
            elif isinstance(_std_fork_state, str) and _std_fork_state:
                st.error(_std_fork_state)

            if _std_fork_state not in ("success", "exists") and _std_fork_status != 200:
                _fc1, _fc2 = st.columns([1, 3])
                with _fc1:
                    if st.button("Create Fork", key="std_fork_btn", type="primary", use_container_width=True):
                        _token = get_token()
                        with st.spinner("Creating fork..."):
                            _ok, _msg, _ = _gitlab_fork(_token, configure_project_val, _std_fork_path)
                        if _ok:
                            st.session_state[_std_fork_key] = "exists" if "already exists" in _msg else "success"
                            st.session_state["_std_fork_success_path"] = _std_fork_path
                            if prefill.get("attendee_email"):
                                _mem_ok, _mem_msg = _gitlab_add_member(_token, _std_fork_path, prefill["attendee_email"])
                                st.session_state[f"_fork_member_{_std_fork_path}"] = _mem_msg
                        else:
                            st.session_state[_std_fork_key] = _msg
                        st.rerun()
                with _fc2:
                    st.caption(f"Forks `{configure_project_val}` → `{_std_fork_path}`")

    # Custom event fork button — only in Fork a repo mode, when fork_parent was passed via URL
    if _cp_mode == "Fork a repo" and _fork_parent and configure_project_val:
        _fork_key = f"fork_state_{configure_project_val}"
        if _fork_key not in st.session_state:
            st.session_state[_fork_key] = None
        _fork_state = st.session_state[_fork_key]
        _fork_url = f"https://app.dataops.live/{configure_project_val}"

        # Check whether this GitLab project already exists (live check, no cache)
        _cp_status = None
        if configure_project_val:
            try:
                _token = get_token()
                _cr = _requests.get(
                    f"{GITLAB_BASE}/projects/{_urlparse.quote(configure_project_val, safe='')}",
                    headers={"PRIVATE-TOKEN": _token},
                    timeout=5,
                )
                _cp_status = _cr.status_code
            except Exception:
                pass

        if _fork_state == "success":
            st.success(f"Fork created: [{configure_project_val}]({_fork_url})")
        elif _fork_state == "exists" or _cp_status == 200:
            st.info(f"Project already exists: [{configure_project_val}]({_fork_url}) — proceed with event form below.")
        _mem_result_custom = st.session_state.get(f"_fork_member_{configure_project_val}")
        if _mem_result_custom:
            st.caption(f"👤 {_mem_result_custom}")
        elif _cp_status == 404:
            st.success(f"✅ Fork path `{configure_project_val}` is available.")
        elif isinstance(_fork_state, str) and _fork_state:
            st.error(_fork_state)

        if _fork_state not in ("success", "exists") and _cp_status != 200:
            _fc1, _fc2 = st.columns([1, 3])
            with _fc1:
                if st.button("Create Fork", type="primary", key="create_fork_btn", use_container_width=True):
                    _token = get_token()
                    with st.spinner("Creating fork in GitLab..."):
                        _ok, _msg, _ = _gitlab_fork(_token, _fork_parent, configure_project_val)
                    if _ok and "already exists" in _msg:
                        st.session_state[_fork_key] = "exists"
                    elif _ok:
                        st.session_state[_fork_key] = "success"
                        if prefill.get("attendee_email"):
                            _mem_ok, _mem_msg = _gitlab_add_member(_token, configure_project_val, prefill["attendee_email"])
                            st.session_state[f"_fork_member_{configure_project_val}"] = _mem_msg
                    else:
                        st.session_state[_fork_key] = _msg
                    st.rerun()
            with _fc2:
                st.caption(f"Forks `{_fork_parent}` → `{configure_project_val}`")

    with st.form("create_event_form"):
        st.subheader("Required Fields")
        decomm_col1, decomm_col2 = st.columns(2)
        with decomm_col1:
            decommission_date = st.date_input(
                "Decommission Date*",
                value=prefill["decommission_date"],
            )
        with decomm_col2:
            decommission_time = st.time_input("Decomm Time", value=time(22, 0))
        st.subheader("Event Details")
        name = st.text_input("Event Name", value=prefill["name"])
        location = st.text_input("Location", value="Virtual")
        delivery_format = st.selectbox(
            "Delivery Format",
            DELIVERY_FORMAT_OPTIONS,
            index=DELIVERY_FORMAT_OPTIONS.index(prefill["delivery_format"])
                  if prefill["delivery_format"] in DELIVERY_FORMAT_OPTIONS else 0,
        )

        st.subheader("Dates & Times")
        _tz_val = prefill.get("timezone", "")
        event_timezone = st.text_input(
            "Timezone",
            value=_tz_val,
            help="Timezone abbreviation (e.g. EST, PST, UTC). Used to set time offsets on date fields.",
        )
        col1, col2, col3 = st.columns(3)
        with col1:
            build_date = st.date_input("Build Date", value=prefill["build_date"])
            build_time = st.time_input("Build Time", value=time(0, 0))
        with col2:
            start_date = st.date_input("Start Date", value=prefill["start_date"])
            start_time = st.time_input("Start Time", value=time(0, 0))
        with col3:
            end_date = st.date_input("End Date", value=prefill["end_date"])
            end_time = st.time_input("End Time", value=time(22, 0))

        st.subheader("Configuration")
        col_a, col_b = st.columns(2)
        with col_a:
            pool_size = st.number_input("Pool Size", min_value=0, value=prefill["pool_size"], step=1)
            edition = st.selectbox("Snowflake Edition", EDITION_OPTIONS, index=0)
            region = st.selectbox(
                "Region Group", REGION_OPTIONS,
                index=REGION_OPTIONS.index(prefill["region"]) if prefill["region"] in REGION_OPTIONS else 0,
                format_func=lambda r: REGION_LABELS.get(r, r),
                key="region_group",
            )
        with col_b:
            is_express = st.checkbox("Express Mode")
            express_hours = st.number_input(
                "Express Token Duration (hours)", min_value=1, value=24, step=1, disabled=not is_express
            )
            instructor_reconfigure = st.checkbox("Instructor Reconfigure")

        allowed_domains = st.text_input("Allowed Email Domains", help="Comma-separated, e.g. snowflake.com, acme.org")

        # Instructors section
        st.subheader("Instructors")
        if prefill["attendee_email"]:
            st.caption(f"Requestor will be added as instructor automatically: **{prefill['attendee_name']}** &lt;{prefill['attendee_email']}&gt;")
        additional_instructors_raw = st.text_input(
            "Additional Instructor Emails",
            placeholder="alice@snowflake.com, bob@snowflake.com",
            help="Comma-separated. Note: additional instructors from the LIFT ticket are not yet available automatically.",
        )

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
            st.subheader("Event Preview")
            _pc1, _pc2 = st.columns(2)
            with _pc1:
                if _p.get("name"): st.markdown(f"**Name:** {_p['name']}")
                if _p.get("slug"): st.markdown(f"**Slug:** `{_p['slug']}`")
                if _p.get("snowflake_account_region_group"): st.markdown(f"**Region:** `{_p['snowflake_account_region_group']}`")
                if _p.get("snowflake_account_edition"): st.markdown(f"**Edition:** {_p['snowflake_account_edition']}")
                if _p.get("delivery_format"): st.markdown(f"**Format:** {_p['delivery_format']}")
                if _p.get("pool_size"): st.markdown(f"**Pool Size:** {_p['pool_size']}")
            with _pc2:
                def _fmt_dt(iso: str) -> str:
                    try:
                        _dt = datetime.fromisoformat(iso)
                        return _dt.strftime("%b %d, %Y at %I:%M %p") + f" ({iso[-6:]})"
                    except Exception:
                        return iso
                if _p.get("build_date"): st.markdown(f"**Build Date:** {_fmt_dt(_p['build_date'])}")
                if _p.get("start_date"): st.markdown(f"**Start:** {_fmt_dt(_p['start_date'])}")
                if _p.get("end_date"): st.markdown(f"**End:** {_fmt_dt(_p['end_date'])}")
                if _p.get("decommission_date"): st.markdown(f"**Decomm:** {_fmt_dt(_p['decommission_date'])}")
            if _p.get("dataops_configure_project_path"):
                st.markdown(f"**Configure Project:** `{_p['dataops_configure_project_path']}`")
            with st.expander("Raw payload", expanded=False):
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
    _tz = event_timezone.strip() if event_timezone else ""
    payload = {
        "slug": slug,
        "decommission_date": _format_datetime(decommission_date, decommission_time, _tz),
    }

    if name:
        payload["name"] = name
    if location:
        payload["location"] = location
    if delivery_format:
        payload["delivery_format"] = delivery_format
    if build_date:
        payload["build_date"] = _format_datetime(build_date, build_time, _tz)
    if start_date:
        payload["start_date"] = _format_datetime(start_date, start_time, _tz)
    if end_date:
        payload["end_date"] = _format_datetime(end_date, end_time, _tz)
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

    # Salesforce Campaign ID → extra_env_vars
    salesforce_id = st.session_state.get("salesforce_id_input", "").strip()
    if salesforce_id:
        payload["extra_env_vars"] = {"DATAOPS_CATALOG_SALESFORCE_ID": salesforce_id}

    # Build instructor email list: requestor first, then any additional
    _instructor_emails = []
    if prefill["attendee_email"]:
        _instructor_emails.append(prefill["attendee_email"].strip())
    for _em in parse_comma_list(additional_instructors_raw):
        _em = _em.strip()
        if _em and _em not in _instructor_emails:
            _instructor_emails.append(_em)

    # Store payload for the confirm step (shown on next rerun via the early-return path above)
    st.session_state["_pending_payload"] = payload
    st.session_state["_pending_slug"] = slug
    st.session_state["_pending_instructors"] = _instructor_emails
    st.rerun()
