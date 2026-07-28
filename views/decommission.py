"""Decommission account view."""

import streamlit as st
import pandas as pd
from api_client import DataOpsClient, DataOpsAPIError


def render(client: DataOpsClient):
    st.header("🗑️ Decommission Account")

    slug = st.session_state.get("selected_event_slug", "")
    if not slug:
        st.warning("Enter an event slug in the sidebar or select one from List Events.")
        return

    st.info(f"Event: **{slug}**")

    # Search accounts
    search = st.text_input("Search accounts", placeholder="Account locator, email, or ID...")

    if not search:
        st.caption("Enter a search term to find accounts within this event.")
        return

    try:
        data = client.get_event_accounts(slug, search=search, page_size=50)
    except DataOpsAPIError as e:
        st.error(f"Failed to search accounts: {e}")
        return

    # Normalize response
    if isinstance(data, dict):
        accounts = data.get("results", data.get("accounts", []))
    else:
        accounts = data

    if not accounts:
        st.warning(f"No accounts found matching '{search}'.")
        return

    st.caption(f"{len(accounts)} account(s) found")

    # Display accounts table
    rows = []
    for acc in accounts:
        rows.append({
            "ID": acc.get("id", ""),
            "Slug": acc.get("slug", ""),
            "Identifier": acc.get("snowflake_account_identifier", acc.get("identifier", "")),
            "Status": acc.get("status", ""),
            "Allocated To": acc.get("allocated_to", ""),
            "Allocated At": acc.get("allocated_at", ""),
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Select account to decommission
    account_options = {
        f"{acc.get('id')} — {acc.get('snowflake_account_identifier', acc.get('identifier', 'unknown'))} ({acc.get('status', '')})": acc
        for acc in accounts
    }

    selected_label = st.selectbox("Select account to decommission:", list(account_options.keys()))
    selected_account = account_options[selected_label]

    # Account details
    st.divider()
    st.subheader("Account Details")
    detail_cols = st.columns(3)
    with detail_cols[0]:
        st.text(f"ID: {selected_account.get('id')}")
        st.text(f"Slug: {selected_account.get('slug', '—')}")
    with detail_cols[1]:
        st.text(f"Identifier: {selected_account.get('snowflake_account_identifier', selected_account.get('identifier', '—'))}")
        st.text(f"Status: {selected_account.get('status', '—')}")
    with detail_cols[2]:
        st.text(f"Allocated To: {selected_account.get('allocated_to', '—')}")
        st.text(f"Allocated At: {selected_account.get('allocated_at', '—')}")

    # Confirmation
    st.divider()
    st.error(
        "⚠️ **Warning: This action tears down the Snowflake environment and cannot be reversed.** "
        "The account slot will remain allocated after decommission."
    )

    confirm_text = st.text_input(
        f"Type the account ID (`{selected_account.get('id')}`) to confirm:",
        key="decommission_confirm",
    )

    account_id = selected_account.get("id")
    if st.button("🗑️ Decommission Account", type="primary", disabled=(str(confirm_text) != str(account_id))):
        with st.spinner("Decommissioning account..."):
            try:
                result = client.decommission_account(slug, account_id, remain_allocated=True)
                st.success("Account decommissioned successfully!")
                if isinstance(result, dict):
                    st.json(result)
            except DataOpsAPIError as e:
                st.error(f"Failed to decommission account: {e}")
                st.code(e.body)
