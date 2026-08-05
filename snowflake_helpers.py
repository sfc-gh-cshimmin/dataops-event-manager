"""Helpers for Snowflake integration — works in SiS and falls back to st.secrets for local dev."""

import streamlit as st


def get_query_params() -> dict:
    """Get URL query params as a flat dict, compatible with old and new Streamlit."""
    try:
        # Streamlit >= 1.30
        return st.query_params
    except AttributeError:
        # Older Streamlit (SiS) — returns dict of lists
        raw = st.experimental_get_query_params()
        return {k: v[0] if v else "" for k, v in raw.items()}


def rerun():
    """Rerun the app, compatible with old and new Streamlit."""
    try:
        st.rerun()
    except AttributeError:
        st.experimental_rerun()


def get_token() -> str:
    """Get the DataOps API token. Checks container runtime (st.secrets), warehouse runtime (_snowflake), then local dev."""
    # Container runtime: secrets mapped via snowflake.yml are in st.secrets
    if "DATAOPS_PAT" in st.secrets:
        return st.secrets["DATAOPS_PAT"]
    # Warehouse runtime: use _snowflake module
    try:
        import _snowflake
        return _snowflake.get_generic_secret_string("DATAOPS_PAT")
    except (ImportError, Exception):
        pass
    # Local dev fallback: .streamlit/secrets.toml with DATAOPS_API_TOKEN key
    return st.secrets.get("DATAOPS_API_TOKEN", "")


def get_session():
    """Get the Snowpark session (SiS only). Returns None in local dev."""
    try:
        from snowflake.snowpark.context import get_active_session
        return get_active_session()
    except Exception:
        return None


@st.cache_data(ttl=60)
def load_fork_parents() -> list[dict]:
    """Load fork parents from Snowflake table (SiS) or return hardcoded defaults (local dev)."""
    session = get_session()
    if session:
        rows = session.sql(
            "SELECT ID, LABEL, PATH, SORT_ORDER "
            "FROM INTERNAL_DATA.DATAOPS_EVENTS.DATAOPS_FORK_PARENTS "
            "ORDER BY SORT_ORDER, ID"
        ).collect()
        return [{"id": r["ID"], "label": r["LABEL"], "path": r["PATH"], "sort_order": r["SORT_ORDER"]} for r in rows]
    # Fallback for local dev
    return [
        {"id": 1, "label": "Default Event Configuration", "path": "snowflake/hands-on-lab-drafts/default-event-configuration", "sort_order": 10},
        {"id": 2, "label": "Zero to Snowflake", "path": "snowflake/hands-on-labs/zero-to-snowflake-v-2", "sort_order": 20},
        {"id": 3, "label": "Intro to Cortex Code (CLI + SPCS)", "path": "snowflake/hands-on-labs/intro-to-cortex-code-cli-with-spcs-native-app", "sort_order": 30},
        {"id": 4, "label": "Intro to Cortex Code", "path": "snowflake/hands-on-labs/intro-to-cortex-code", "sort_order": 40},
        {"id": 5, "label": "AI Assistant for FSI (AI/SQL + SI)", "path": "snowflake/hands-on-labs/build-an-ai-assistant-for-fsi-using-aisql-and-snowflake-intelligence", "sort_order": 50},
        {"id": 6, "label": "Cortex AI SQL HOL Pack", "path": "snowflake/hands-on-labs/snowflake-cortex-aisql-hol-pack", "sort_order": 60},
    ]


def save_fork_parent(label: str, path: str, sort_order: int = 100) -> bool:
    """Add a fork parent to the Snowflake table. Returns True on success."""
    session = get_session()
    if not session:
        return False
    session.sql(
        f"INSERT INTO INTERNAL_DATA.DATAOPS_EVENTS.DATAOPS_FORK_PARENTS (LABEL, PATH, SORT_ORDER) "
        f"VALUES ('{label}', '{path}', {sort_order})"
    ).collect()
    load_fork_parents.clear()
    return True


def delete_fork_parent(row_id: int) -> bool:
    """Delete a fork parent by ID. Returns True on success."""
    session = get_session()
    if not session:
        return False
    session.sql(f"DELETE FROM INTERNAL_DATA.DATAOPS_EVENTS.DATAOPS_FORK_PARENTS WHERE ID = {row_id}").collect()
    load_fork_parents.clear()
    return True
