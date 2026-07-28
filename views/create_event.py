"""Create event form."""

import streamlit as st
from datetime import date
from pathlib import Path
from api_client import DataOpsClient, DataOpsAPIError
from utils import validate_slug, parse_comma_list


EDITION_OPTIONS = ["ENTERPRISE", "STANDARD"]
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
    return {
        "slug":              qp.get("slug", ""),
        "name":              qp.get("name", ""),
        "start_date":        _parse_date_param(qp.get("start_date")),
        "end_date":          _parse_date_param(qp.get("end_date")),
        "decommission_date": _parse_date_param(qp.get("decommission_date")),
        "build_date":        _parse_date_param(qp.get("build_date")),
        "pool_size":         int(qp["pool_size"]) if qp.get("pool_size", "").isdigit() else 0,
        "attendee_email":    qp.get("attendee_email", ""),
        "attendee_name":     qp.get("attendee_name", ""),
        "region":            qp.get("region", "").lower(),
        "delivery_format":   qp.get("delivery_format", ""),
        "configure_project": qp.get("configure_project", ""),
    }


def render(client: DataOpsClient):
    st.header("➕ Create Event")

    prefill = _read_prefill()
    has_prefill = any([prefill["name"], prefill["slug"], prefill["start_date"]])

    if has_prefill:
        st.info(
            "ℹ️ Form pre-filled from HOL Analytics Dashboard. Review all fields before submitting.",
            icon="ℹ️",
        )

    if has_prefill and prefill["slug"]:
        # Auto-check slug availability when pre-filled from HOL tracker
        try:
            client.get_event(prefill["slug"])
            st.warning(
                f"⚠️ Slug `{prefill['slug']}` is already in use. "
                "Edit the Event Slug field below before submitting.",
            )
        except DataOpsAPIError as _e:
            if _e.status_code == 404:
                st.success(f"✅ Slug `{prefill['slug']}` is available.", icon="✅")
            # Other errors (auth, network) — silently skip
        except Exception:
            pass

    with st.form("create_event_form"):
        st.subheader("Required Fields")
        slug = st.text_input(
            "Event Slug*",
            value=prefill["slug"],
            help="Max 31 chars, lowercase, starts with a letter, alphanumerics and hyphens only",
        )
        decommission_date = st.date_input(
            "Decommission Date*",
            value=prefill["decommission_date"],
        )

        st.subheader("Event Details")
        name = st.text_input("Event Name", value=prefill["name"])
        location = st.text_input("Location", value="Virtual")
        delivery_format = st.text_input("Delivery Format", value=prefill["delivery_format"])

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

        configure_project = st.text_input(
            "DataOps Configure Project Path",
            value=prefill["configure_project"],
            help="e.g. snowflake/hands-on-labs/zero-to-snowflake-v-2",
        )
        if prefill["configure_project"] and "default-event-configuration-" in prefill["configure_project"]:
            st.caption(
                "Path pre-generated for a custom event. Fork the parent repo in GitLab "
                "before submitting."
            )
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
        return

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

    # Show summary
    st.divider()
    st.subheader("Creation Summary")

    display_payload = {k: v for k, v in payload.items() if k != "instructions"}
    st.json(display_payload)

    with st.expander("Instructions template (auto-injected)"):
        preview = payload["instructions"]
        st.code(preview[:500] + "..." if len(preview) > 500 else preview, language="html")

    # Confirmation
    st.warning("⚠️ This action creates a new live event. This cannot be undone easily.")

    if "create_confirmed" not in st.session_state:
        st.session_state["create_confirmed"] = False

    if st.button("🚀 Create Event", type="primary"):
        st.session_state["create_confirmed"] = True

    if st.session_state.get("create_confirmed"):
        st.session_state["create_confirmed"] = False
        with st.spinner("Creating event..."):
            try:
                result = client.create_event(slug, payload)
                st.success("Event created successfully!")
                st.markdown(f"- **Slug:** `{slug}`")
                st.markdown(f"- **URL:** https://snowflake.dataops.live/event-deployments/{slug}")
                st.session_state["selected_event_slug"] = slug
                if isinstance(result, dict):
                    st.json(result)
            except DataOpsAPIError as e:
                st.error(f"Failed to create event: {e}")
                st.code(e.body)
