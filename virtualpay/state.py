from typing import Any

import streamlit as st

def set_page(page: str) -> None:
    st.session_state.nav_page = page
    if page == "My accounts":
        st.session_state.account_page_view = "menu"
        st.session_state.pop("selected_account_id", None)


def open_qr_scanner() -> None:
    st.session_state.nav_page = "Transfer money"
    st.session_state.camera_enabled = True


def set_flash(message: str, kind: str = "success") -> None:
    st.session_state.flash_message = {"message": message, "kind": kind}


def render_flash() -> None:
    flash = st.session_state.pop("flash_message", None)
    if not flash:
        return
    if flash["kind"] == "error":
        st.toast(flash["message"], icon="⚠️")
    else:
        st.toast(flash["message"], icon="✅")


def authenticate(phone: str) -> None:
    st.session_state.user_phone = phone
    st.session_state.auth_stage = "signed_in"
    st.session_state.nav_page = "Overview"
