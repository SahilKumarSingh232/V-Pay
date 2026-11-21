from typing import Any

import streamlit as st

from ..formatting import make_qr
from ..state import open_qr_scanner, set_page

def render_sidebar(user: dict[str, Any]) -> None:
    with st.sidebar:
        st.markdown("### :material/account_balance_wallet: VirtualPay")
        st.caption(f"{user['name']} · +91 {user['phone']}")
        st.divider()
        if st.button("Sign out", icon=":material/logout:", width="stretch"):
            st.session_state.auth_stage = "phone"
            st.session_state.pop("user_phone", None)
            st.session_state.camera_enabled = False
            st.rerun()


def render_overview(user: dict[str, Any], accounts: list[dict[str, Any]]) -> None:
    st.title("Home")
    st.caption("Your VirtualPay profile")
    profile_col, qr_col = st.columns([1.2, 1], vertical_alignment="center")
    with profile_col, st.container(border=True):
        st.markdown(f"### {user['name']}")
        st.write(f"Phone number  ·  +91 {user['phone']}")
        st.write(f"VirtualPay ID  ·  **{user['virtual_id']}**")
    with qr_col, st.container(border=True):
        st.markdown("**Your QR code**")
        st.image(make_qr("virtualpay://receive/" + user["virtual_id"]), alt="QR code for your VirtualPay ID")

    st.subheader("What would you like to do?")
    first_row = st.columns(2)
    first_row[0].button(
        "Account", icon=":material/account_balance:", width="stretch",
        on_click=set_page, args=("My accounts",),
    )
    first_row[1].button(
        "Transfer money", icon=":material/swap_horiz:", type="primary", width="stretch",
        on_click=set_page, args=("Transfer money",),
    )
    second_row = st.columns(2)
    second_row[0].button(
        "History", icon=":material/history:", width="stretch",
        on_click=set_page, args=("History",),
    )
    second_row[1].button(
        "Scan QR", icon=":material/qr_code_scanner:", width="stretch",
        on_click=open_qr_scanner,
    )
