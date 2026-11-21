from typing import Any

import streamlit as st

from ..database import get_transactions

def show_transaction_table(phone: str, limit: int | None = None) -> None:
    frame = get_transactions(phone)
    if frame.empty:
        st.info("No transactions yet.")
        return
    if limit:
        frame = frame.head(limit)
    visible = frame[["Transaction", "Details", "Virtual account", "Date", "Amount", "Status"]]
    st.dataframe(visible, hide_index=True, alt="VirtualPay transaction history")


def render_activity(phone: str, accounts: list[dict[str, Any]]) -> None:
    st.title("History")
    st.write("Every payment and allocation, all in one place.")
    frame = get_transactions(phone)
    if frame.empty:
        st.info("No transactions yet.")
        return
    filters = st.columns([2, 1], vertical_alignment="bottom")
    with filters[0]:
        query = st.text_input("Search transactions", placeholder="Search by name, detail, or account")
    with filters[1]:
        account_filter = st.selectbox("Account", ["All accounts", "Main account"] + [a["name"] for a in accounts])
    if account_filter != "All accounts":
        frame = frame[frame["Virtual account"] == account_filter]
    if query.strip():
        searchable = frame[["Transaction", "Details", "Virtual account"]].astype(str).agg(" ".join, axis=1)
        frame = frame[searchable.str.contains(query.strip(), case=False, na=False)]
    visible = frame[["Transaction", "Details", "Virtual account", "Date", "Amount", "Status"]]
    st.dataframe(visible, hide_index=True, alt="Filtered VirtualPay transaction history")
