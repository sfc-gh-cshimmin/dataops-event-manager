"""Patch event form with before/after diff."""

import streamlit as st
from api_client import DataOpsClient, DataOpsAPIError
from utils import format_datetime, parse_comma_list


PATCHABLE_FIELDS = {
    "name":                         {"type": "string",  "label": "Event Name"},
    "location":                      {"type": "string",  "label": "Location"},
    "delivery_format":               {"type": "string",  "label": "Delivery Format"},
    "build_date":                    {"type": "date",    "label": "Build Date",          "get_key": "build_datetime"},
    "start_date":                    {"type": "date",    "label": "Start Date",          "get_key": "start_datetime"},
    "end_date":                      {"type": "date",    "label": "End Date",            "get_key": "end_datetime"},
    "decommission_date":             {"type": "date",    "label": "Decommission Date",   "get_key": "decommission_datetime"},
    "pool_size":                     {"type": "integer", "label": "Pool Size",           "get_key": "initial_pool_size"},
    "instructor_reconfigure":        {"type": "boolean", "label": "Instructor Reconfigure"},
    "is_express":                    {"type": "boolean", "label": "Express Mode"},
    "express_token_duration_hours":  {"type": "integer", "label": "Express Token Duration (hours)"},
    "allowed_email_domains":         {"type": "array",   "label": "Allowed Email Domains"},
}


def render(client: DataOpsClient):
    st.header("✏️ Patch Event")

    slug = st.session_state.get("selected_event_slug", "")
    if not slug:
        st.warning("Enter an event slug in the sidebar or select one from List Events.")
        return

    # Clear stale widget state when switching to a different event
    if st.session_state.get("_patch_last_slug") != slug:
        for field in PATCHABLE_FIELDS:
            st.session_state.pop(f"patch_{field}", None)
        st.session_state["_patch_last_slug"] = slug

    # Fetch current state via details endpoint (has all fields)
    try:
        current = client.get_event_details(slug)
    except DataOpsAPIError as e:
        st.error(f"Failed to fetch event: {e}")
        return

    st.info(f"Editing event: **{slug}** — {current.get('name', '')}")

    with st.form("patch_event_form"):
        new_values = {}

        for field, meta in PATCHABLE_FIELDS.items():
            current_val = current.get(meta.get("get_key", field))
            label = f"{meta['label']} (current: {_display_val(current_val, meta['type'])})"

            if meta["type"] == "string":
                new_values[field] = st.text_input(label, value=current_val or "", key=f"patch_{field}")
            elif meta["type"] == "text":
                new_values[field] = st.text_area(label, value=current_val or "", key=f"patch_{field}", height=100)
            elif meta["type"] == "date":
                # Show as text input for ISO datetime
                new_values[field] = st.text_input(
                    label, value=current_val or "", key=f"patch_{field}",
                    help="ISO datetime, e.g. 2026-08-01T00:00:00Z"
                )
            elif meta["type"] == "integer":
                new_values[field] = st.number_input(
                    label, value=int(current_val) if current_val else 0, step=1, key=f"patch_{field}"
                )
            elif meta["type"] == "boolean":
                new_values[field] = st.checkbox(label, value=bool(current_val), key=f"patch_{field}")
            elif meta["type"] == "array":
                current_list = current_val if isinstance(current_val, list) else []
                new_values[field] = st.text_input(
                    label, value=", ".join(current_list), key=f"patch_{field}",
                    help="Comma-separated values"
                )

        submitted = st.form_submit_button("Compute Changes", use_container_width=True)

    if not submitted and not st.session_state.get(f"_patch_changes_{slug}"):
        return

    if submitted:
        # Compute diff
        changes = {}
        for field, meta in PATCHABLE_FIELDS.items():
            current_val = current.get(meta.get("get_key", field))
            new_val = new_values[field]

            # Normalize for comparison
            if meta["type"] == "array":
                new_val = parse_comma_list(new_val) if isinstance(new_val, str) else new_val
                current_val = current_val if isinstance(current_val, list) else []
                if new_val != current_val:
                    changes[field] = new_val
            elif meta["type"] == "integer":
                new_int = int(new_val) if new_val else 0
                cur_int = int(current_val) if current_val else 0
                if new_int != cur_int:
                    changes[field] = new_int
            elif meta["type"] == "boolean":
                if bool(new_val) != bool(current_val):
                    changes[field] = bool(new_val)
            elif meta["type"] in ("string", "text", "date"):
                new_str = new_val.strip() if new_val else ""
                # Compare against the raw GET value (which may use _datetime suffix)
                raw_cur = current.get(meta.get("get_key", field))
                cur_str = str(raw_cur).strip() if raw_cur else ""
                if new_str != cur_str:
                    if new_str:
                        changes[field] = new_str
                    else:
                        changes[field] = None

        if not changes:
            st.info("No changes detected. All values match the current event state.")
            st.session_state.pop(f"_patch_changes_{slug}", None)
            return

        st.session_state[f"_patch_changes_{slug}"] = changes

    # Show persisted changes (survives the Apply Changes button click)
    changes = st.session_state.get(f"_patch_changes_{slug}", {})
    if not changes:
        return

    # Show before/after
    st.divider()
    st.subheader("Proposed Changes")
    for field, new_val in changes.items():
        current_val = current.get(meta.get("get_key", field) if (meta := PATCHABLE_FIELDS.get(field, {})) else field)
        col1, col2, col3 = st.columns([2, 3, 3])
        with col1:
            st.markdown(f"**{PATCHABLE_FIELDS[field]['label']}**")
        with col2:
            raw_cur = current.get(PATCHABLE_FIELDS[field].get("get_key", field))
            st.text(f"Before: {_display_val(raw_cur, PATCHABLE_FIELDS[field]['type'])}")
        with col3:
            st.text(f"After: {_display_val(new_val, PATCHABLE_FIELDS[field]['type'])}")

    # Confirmation
    st.warning("⚠️ This action modifies a live event.")

    _a1, _a2 = st.columns([1, 5])
    with _a1:
        if st.button("✅ Apply Changes", type="primary", use_container_width=True):
            with st.spinner("Patching event..."):
                try:
                    result = client.patch_event(slug, changes)
                    st.success("Event updated successfully!")
                    st.session_state.pop(f"_patch_changes_{slug}", None)
                    st.session_state.pop(f"_patch_last_slug", None)  # force field refresh on next open
                    if isinstance(result, dict):
                        st.json(result)
                except DataOpsAPIError as e:
                    st.error(f"Failed to patch event: {e}")
                    st.code(e.body)
    with _a2:
        if st.button("Cancel", use_container_width=True):
            st.session_state.pop(f"_patch_changes_{slug}", None)
            st.rerun()


def _display_val(val, field_type: str) -> str:
    if val is None:
        return "—"
    if field_type == "date":
        return format_datetime(val) if isinstance(val, str) else str(val)
    if field_type == "array":
        return ", ".join(val) if isinstance(val, list) else str(val)
    if field_type == "boolean":
        return "Yes" if val else "No"
    return str(val)
