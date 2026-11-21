import streamlit as st

from ..config import BANKS, OTP_DEMO
from ..database import create_user, get_user
from ..formatting import pin_digest
from ..state import authenticate

def render_login() -> None:
    left, right = st.columns([1.2, 1], gap="large", vertical_alignment="center")
    with left:
        st.markdown("### :material/account_balance_wallet: VirtualPay")
        st.title("Your money, in its place.")
        st.write(
            "Organize one bank balance into purpose-led virtual accounts. "
            "Keep the flexibility of one account with the clarity of many."
        )
        st.caption("One linked bank · Budgets that make sense · You stay in control")

    with right, st.container(border=True):
        stage = st.session_state.auth_stage
        if stage == "phone":
            st.subheader("Welcome to VirtualPay")
            st.caption("Enter your phone number to get started.")
            phone = st.text_input("Mobile number", placeholder="10-digit phone number")
            submitted = st.button("Continue", type="primary", width="stretch")
            if submitted:
                cleaned = phone.strip()
                if not cleaned.isdigit() or len(cleaned) != 10:
                    st.error("Enter a valid 10-digit mobile number.")
                else:
                    st.session_state.pending_phone = cleaned
                    st.session_state.auth_stage = "otp"
                    st.rerun()

        elif stage == "otp":
            st.subheader("Verify your number")
            st.caption(f"Enter the one-time code for +91 {st.session_state.pending_phone}.")
            st.info(f"Demo mode: use **{OTP_DEMO}**. No SMS is sent.")
            otp = st.text_input("One-time code", placeholder="6-digit code")
            submitted = st.button("Verify", type="primary", width="stretch")
            if submitted:
                phone = st.session_state.pending_phone
                if otp != OTP_DEMO:
                    st.error(f"That demo code is incorrect. Use {OTP_DEMO}.")
                elif get_user(phone):
                    st.session_state.auth_stage = "pin"
                    st.rerun()
                else:
                    st.session_state.auth_stage = "register"
                    st.rerun()
            if st.button("Change phone number", icon=":material/arrow_back:"):
                st.session_state.auth_stage = "phone"
                st.rerun()

        elif stage == "register":
            st.subheader("Make it yours")
            st.caption("Create a demo profile and link a sample bank account.")
            name = st.text_input("Full name", placeholder="Your name")
            bank = st.selectbox("Bank", BANKS)
            last4 = st.text_input("Last 4 digits of account", placeholder="2841")
            pin = st.text_input("Create demo payment PIN", type="password")
            st.caption("Use a made-up PIN. Never enter your real bank or UPI PIN.")
            submitted = st.button("Create my account", type="primary", width="stretch")
            if submitted:
                if not name.strip():
                    st.error("Enter your name.")
                elif not last4.isdigit() or len(last4) != 4:
                    st.error("Enter the last 4 digits of the demo account.")
                elif not pin.isdigit() or len(pin) not in (4, 5, 6):
                    st.error("Use a 4–6 digit demo PIN.")
                else:
                    create_user(st.session_state.pending_phone, name, bank, last4, pin, 0)
                    authenticate(st.session_state.pending_phone)
                    st.rerun()

        elif stage == "pin":
            st.subheader("Welcome back")
            st.caption("Enter your demo payment PIN to continue.")
            pin = st.text_input("Demo payment PIN", type="password")
            submitted = st.button("Sign in", type="primary", width="stretch")
            if submitted:
                user = get_user(st.session_state.pending_phone)
                if user and pin_digest(pin) == user["pin_hash"]:
                    authenticate(st.session_state.pending_phone)
                    st.rerun()
                st.error("That demo PIN does not match.")

    st.caption("VirtualPay is a local concept prototype. It does not connect to banks or send payments.")
