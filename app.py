"""VirtualPay Streamlit entry point. Run with `streamlit run app.py`."""

import streamlit as st

from virtualpay.database import (
    ensure_admin_profile,
    get_user,
    initialize_database,
    list_accounts,
    repair_legacy_internal_transfers,
)
from virtualpay.state import render_flash, set_page
from virtualpay.ui.accounts import render_accounts
from virtualpay.ui.auth import render_login
from virtualpay.ui.history import render_activity
from virtualpay.ui.home import render_overview, render_sidebar
from virtualpay.ui.transfer import render_transfer

st.set_page_config(page_title="VirtualPay", page_icon=":material/account_balance_wallet:", layout="centered")
initialize_database()
ensure_admin_profile()
repair_legacy_internal_transfers()

if "auth_stage" not in st.session_state:
    st.session_state.auth_stage = "phone"

if st.session_state.auth_stage != "signed_in":
    render_login()
else:
    user = get_user(st.session_state.user_phone)
    if user is None:
        st.session_state.auth_stage = "phone"
        st.rerun()
    accounts = list_accounts(user["phone"])
    render_sidebar(user)
    page = st.session_state.get("nav_page", "Overview")
    if page != "Overview":
        st.button("Home", icon=":material/arrow_back:", on_click=set_page, args=("Overview",))
    if page != "Transfer money":
        st.session_state.camera_enabled = False
    render_flash()
    if page == "Overview":
        render_overview(user, accounts)
    elif page == "My accounts":
        render_accounts(user, accounts)
    elif page == "Transfer money":
        render_transfer(user, accounts)
    elif page == "History":
        render_activity(user["phone"], accounts)
