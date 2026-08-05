"""Admin panel — manage fork parent repos."""

import streamlit as st
from snowflake_helpers import load_fork_parents, save_fork_parent, delete_fork_parent, get_session


def render():
    st.header("Admin")

    st.subheader("Fork Parent Repos")
    st.caption("These populate the 'Fork Parent Repo' dropdown on the Create Event form.")

    parents = load_fork_parents()

    for entry in parents:
        c1, c2, c3 = st.columns([2, 5, 1])
        c1.write(entry["label"])
        c2.code(entry["path"], language=None)
        if c3.button("Delete", key=f"del_{entry['id']}"):
            if delete_fork_parent(entry["id"]):
                st.rerun()
            else:
                st.warning("Delete only available in SiS (Snowflake-hosted) mode.")

    st.divider()
    st.subheader("Add Fork Parent")
    with st.form("add_fork_parent_form"):
        new_label = st.text_input("Display Name", placeholder="Zero to Snowflake")
        new_path = st.text_input(
            "GitLab Path",
            placeholder="snowflake/hands-on-labs/zero-to-snowflake-v-2",
            help="Path after https://app.dataops.live/",
        )
        new_order = st.number_input("Sort Order", value=100, step=10, help="Lower = appears earlier in the dropdown")
        if st.form_submit_button("Add", type="primary") and new_label.strip() and new_path.strip():
            if save_fork_parent(new_label.strip(), new_path.strip(), int(new_order)):
                st.success(f"Added: {new_label.strip()}")
                st.rerun()
            else:
                st.warning("Add only available in SiS (Snowflake-hosted) mode.")

    if not get_session():
        st.info("Running in local dev mode — fork parents are read-only (hardcoded fallback).")
