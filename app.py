"""VirtualPay: a local, simulated virtual-account budgeting prototype."""

from __future__ import annotations

import hashlib
import io
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import qrcode
import streamlit as st
import numpy as np


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "virtualpay.db"
OTP_DEMO = "123456"
BANKS = ["State Bank of India", "HDFC Bank", "ICICI Bank", "Axis Bank", "Other bank"]
ADMIN_PHONE = "1223334444"
ADMIN_PIN = "282005"


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def initialize_database() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                phone TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                bank TEXT NOT NULL,
                last4 TEXT NOT NULL,
                bank_balance INTEGER NOT NULL DEFAULT 0,
                virtual_id TEXT NOT NULL UNIQUE,
                pin_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY,
                phone TEXT NOT NULL REFERENCES users(phone) ON DELETE CASCADE,
                name TEXT NOT NULL,
                emoji TEXT NOT NULL,
                description TEXT NOT NULL,
                balance INTEGER NOT NULL DEFAULT 0,
                budget INTEGER NOT NULL DEFAULT 1000,
                created_at TEXT NOT NULL,
                UNIQUE(phone, name)
            );
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL REFERENCES users(phone) ON DELETE CASCADE,
                name TEXT NOT NULL,
                detail TEXT NOT NULL,
                account_name TEXT NOT NULL,
                amount INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Completed'
            );
            CREATE TABLE IF NOT EXISTS recipients (
                recipient_id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL REFERENCES users(phone) ON DELETE CASCADE,
                recipient TEXT NOT NULL,
                recipient_name TEXT NOT NULL DEFAULT '',
                UNIQUE(phone, recipient)
            );
            CREATE TABLE IF NOT EXISTS transfer_receipts (
                source_transaction_id INTEGER PRIMARY KEY,
                recipient_phone TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        recipient_columns = {row[1] for row in db.execute("PRAGMA table_info(recipients)")}
        if "recipient_name" not in recipient_columns:
            db.execute("ALTER TABLE recipients ADD COLUMN recipient_name TEXT NOT NULL DEFAULT ''")


def Indian_money(value: int | float) -> str:
    """Format a rupee amount with Indian digit grouping."""
    number = int(round(value))
    sign = "−" if number < 0 else ""
    digits = str(abs(number))
    if len(digits) <= 3:
        grouped = digits
    else:
        grouped = digits[-3:]
        digits = digits[:-3]
        while digits:
            grouped = digits[-2:] + "," + grouped
            digits = digits[:-2]
    return f"{sign}₹{grouped}"


def pin_digest(pin: str) -> str:
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()


def get_user(phone: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
    return dict(row) if row else None


def find_virtualpay_recipient(value: str) -> dict[str, Any] | None:
    """Resolve an in-app recipient from a phone number or VirtualPay ID."""
    recipient = value.strip().removeprefix("virtualpay://receive/")
    with connect() as db:
        if recipient.upper().startswith("VP-"):
            row = db.execute(
                "SELECT * FROM users WHERE upper(virtual_id) = upper(?)", (recipient,)
            ).fetchone()
        else:
            digits = recipient.replace("+91", "").replace(" ", "").replace("-", "")
            if len(digits) != 10 or not digits.isdigit():
                return None
            row = db.execute("SELECT * FROM users WHERE phone = ?", (digits,)).fetchone()
    return dict(row) if row else None


def repair_legacy_internal_transfers() -> None:
    """Credit internal recipients for transfers recorded before incoming credits existed."""
    with connect() as db:
        pending = db.execute(
            """SELECT t.transaction_id, t.phone, t.detail, t.amount, t.created_at, u.name AS sender_name
               FROM transactions AS t
               JOIN users AS u ON u.phone = t.phone
               LEFT JOIN transfer_receipts AS r ON r.source_transaction_id = t.transaction_id
               WHERE t.amount < 0 AND t.detail LIKE 'Transfer to %'
                 AND r.source_transaction_id IS NULL
               ORDER BY t.transaction_id"""
        ).fetchall()
    for transfer in pending:
        recipient_value = transfer["detail"].removeprefix("Transfer to ")
        recipient_user = find_virtualpay_recipient(recipient_value)
        if recipient_user is None or recipient_user["phone"] == transfer["phone"]:
            continue
        received = -int(transfer["amount"])
        when = transfer["created_at"]
        with connect() as db:
            if not is_admin(recipient_user["phone"]):
                db.execute(
                    "UPDATE users SET bank_balance = bank_balance + ? WHERE phone = ?",
                    (received, recipient_user["phone"]),
                )
            db.execute(
                """INSERT INTO transactions(phone, name, detail, account_name, amount, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (recipient_user["phone"], "Money received", f"From {transfer['sender_name']}", "Main account", received, when),
            )
            db.execute(
                "INSERT INTO transfer_receipts(source_transaction_id, recipient_phone, created_at) VALUES (?, ?, ?)",
                (transfer["transaction_id"], recipient_user["phone"], datetime.now().isoformat(timespec="seconds")),
            )


def list_accounts(phone: str) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM accounts WHERE phone = ? ORDER BY created_at, name", (phone,)
        ).fetchall()
    return [dict(row) for row in rows]


def get_account(phone: str, account_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            "SELECT * FROM accounts WHERE phone = ? AND account_id = ?",
            (phone, account_id),
        ).fetchone()
    return dict(row) if row else None


def is_admin(phone: str) -> bool:
    return phone == ADMIN_PHONE


def available_to_allocate(phone: str) -> int | float:
    if is_admin(phone):
        return float("inf")
    user = get_user(phone)
    accounts = list_accounts(phone)
    return int(user["bank_balance"] - sum(a["balance"] for a in accounts))


def available_label(phone: str) -> str:
    available = available_to_allocate(phone)
    return "Unlimited" if is_admin(phone) else Indian_money(available)


def add_transaction(
    phone: str, name: str, detail: str, account_name: str, amount: int
) -> None:
    with connect() as db:
        db.execute(
            """INSERT INTO transactions(phone, name, detail, account_name, amount, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (phone, name, detail, account_name, amount, datetime.now().isoformat(timespec="seconds")),
        )


def create_user(phone: str, name: str, bank: str, last4: str, pin: str, bank_balance: int) -> None:
    virtual_id = "VP-" + secrets.token_hex(3).upper()
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as db:
        db.execute(
            """INSERT INTO users(phone, name, bank, last4, bank_balance, virtual_id, pin_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (phone, name.strip(), bank, last4, bank_balance, virtual_id, pin_digest(pin), now),
        )


def ensure_admin_profile() -> None:
    """Create or reserve the built-in Admin profile for this local demo."""
    with connect() as db:
        existing = db.execute("SELECT phone FROM users WHERE phone = ?", (ADMIN_PHONE,)).fetchone()
        if existing:
            db.execute(
                "UPDATE users SET name = ?, bank = ?, last4 = ?, pin_hash = ? WHERE phone = ?",
                ("Admin", "VirtualPay Demo", "0000", pin_digest(ADMIN_PIN), ADMIN_PHONE),
            )
        else:
            db.execute(
                """INSERT INTO users(phone, name, bank, last4, bank_balance, virtual_id, pin_hash, created_at)
                   VALUES (?, ?, ?, ?, 0, ?, ?, ?)""",
                (
                    ADMIN_PHONE,
                    "Admin",
                    "VirtualPay Demo",
                    "0000",
                    "VP-" + secrets.token_hex(3).upper(),
                    pin_digest(ADMIN_PIN),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )


def record_recipient(phone: str, recipient: str, name: str = "") -> None:
    with connect() as db:
        db.execute(
            """INSERT INTO recipients(phone, recipient, recipient_name) VALUES (?, ?, ?)
               ON CONFLICT(phone, recipient) DO UPDATE SET recipient_name =
               CASE WHEN excluded.recipient_name = '' THEN recipients.recipient_name
                    ELSE excluded.recipient_name END""",
            (phone, recipient, name.strip()),
        )


def list_recipients(phone: str) -> list[dict[str, str]]:
    with connect() as db:
        rows = db.execute(
            "SELECT recipient, recipient_name FROM recipients WHERE phone = ? ORDER BY recipient_id DESC LIMIT 5",
            (phone,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_transactions(phone: str) -> pd.DataFrame:
    with connect() as db:
        rows = db.execute(
            """SELECT name, detail, account_name, amount, created_at, status
               FROM transactions WHERE phone = ? ORDER BY created_at DESC, transaction_id DESC""",
            (phone,),
        ).fetchall()
    frame = pd.DataFrame([dict(row) for row in rows])
    if not frame.empty:
        frame["created_at"] = pd.to_datetime(frame["created_at"])
        frame["Date"] = frame["created_at"].dt.strftime("%d %b %Y, %I:%M %p")
        frame["Amount"] = frame["amount"].map(Indian_money)
        frame = frame.rename(
            columns={
                "name": "Transaction",
                "detail": "Details",
                "account_name": "Virtual account",
                "status": "Status",
            },
        )
    return frame


def make_qr(value: str) -> bytes:
    image = qrcode.make(value)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


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


st.set_page_config(page_title="VirtualPay", page_icon=":material/account_balance_wallet:", layout="centered")
initialize_database()
ensure_admin_profile()
repair_legacy_internal_transfers()

if "auth_stage" not in st.session_state:
    st.session_state.auth_stage = "phone"


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
            bank_balance = st.number_input(
                "Main account balance (demo)", min_value=0, step=1000, value=0,
                help="Starts at ₹0. Enter a sample balance if you want to try allocating money.",
            )
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
                    create_user(st.session_state.pending_phone, name, bank, last4, pin, int(bank_balance))
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

def select_account(account_id: str) -> None:
    st.session_state.selected_account_id = account_id
    st.session_state.account_action = "overview"
    st.session_state.account_page_view = "virtual"
    st.session_state.nav_page = "My accounts"


def open_new_account() -> None:
    st.session_state.pop("selected_account_id", None)
    st.session_state.account_page_view = "create_pin"


def open_main_account() -> None:
    st.session_state.pop("selected_account_id", None)
    st.session_state.account_page_view = "main_pin"


def show_main_account() -> None:
    st.session_state.pop("selected_account_id", None)
    st.session_state.account_page_view = "main"


def show_account_create_form() -> None:
    st.session_state.pop("selected_account_id", None)
    st.session_state.account_page_view = "create_form"


def back_to_main_account() -> None:
    st.session_state.pop("selected_account_id", None)
    st.session_state.account_page_view = "main"


def back_to_account_menu() -> None:
    st.session_state.pop("selected_account_id", None)
    st.session_state.account_page_view = "menu"


def set_account_action(action: str) -> None:
    st.session_state.account_action = action


def render_accounts(user: dict[str, Any], accounts: list[dict[str, Any]]) -> None:
    phone = user["phone"]
    view = st.session_state.get("account_page_view", "menu")
    st.title("Account")

    if view == "menu":
        st.caption("Choose an account option")
        options = st.columns(2, gap="large")
        options[0].button(
            "Main account",
            icon=":material/account_balance:",
            width="stretch",
            on_click=open_main_account,
        )
        options[1].button(
            "Create virtual account",
            icon=":material/add:",
            width="stretch",
            on_click=open_new_account,
        )
        return

    if view in {"main_pin", "create_pin"}:
        st.button("Back", icon=":material/arrow_back:", on_click=back_to_account_menu)
        if view == "main_pin":
            st.subheader("Main account")
            st.caption("Enter your payment PIN to view the main account balance.")
        else:
            st.subheader("Create virtual account")
            st.caption("Enter your payment PIN to continue to the account form.")
        pin = st.text_input("Payment PIN", type="password")
        submitted = st.button("Continue", type="primary", width="stretch")
        if submitted:
            if pin_digest(pin) != user["pin_hash"]:
                st.toast("The payment PIN is incorrect. No account details were changed.", icon="⚠️")
            elif view == "main_pin":
                show_main_account()
                st.rerun()
            else:
                show_account_create_form()
                st.rerun()
        return

    if view == "create_form":
        st.button("Back", icon=":material/arrow_back:", on_click=back_to_account_menu)
        st.subheader("Create virtual account")
        st.caption(f"Money available for allocation: {available_label(phone)}")
        name = st.text_input("Name of virtual account", placeholder="For example, Travel")
        amount = st.number_input("Amount to allocate", min_value=0, step=500, value=0)
        description = st.text_input("Purpose", placeholder="Optional")
        emoji = st.selectbox("Icon", ["🎯", "🏠", "🎓", "💪", "🎁", "🐾", "🛍️", "✈️"])
        submitted = st.button("Done", type="primary", width="stretch")
        if submitted:
            fresh_free = available_to_allocate(phone)
            if not name.strip():
                st.toast("Enter a name for this virtual account.", icon="⚠️")
            elif any(item["name"].casefold() == name.strip().casefold() for item in accounts):
                st.toast("An account with that name already exists.", icon="⚠️")
            elif amount > fresh_free:
                st.toast("The amount is greater than the money available for allocation.", icon="⚠️")
            else:
                account_id = secrets.token_hex(8)
                try:
                    with connect() as db:
                        db.execute(
                            """INSERT INTO accounts(account_id, phone, name, emoji, description,
                               balance, budget, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (account_id, phone, name.strip(), emoji, description.strip() or "VirtualPay budget", int(amount), max(int(amount), 1000), datetime.now().isoformat(timespec="seconds")),
                        )
                        if amount:
                            db.execute(
                                """INSERT INTO transactions(phone, name, detail, account_name, amount, created_at)
                                   VALUES (?, ?, ?, ?, ?, ?)""",
                                (phone, "Allocation added", "Starting allocation", name.strip(), int(amount), datetime.now().isoformat(timespec="seconds")),
                            )
                except sqlite3.Error:
                    st.toast("Virtual account creation failed. No account was created.", icon="⚠️")
                else:
                    st.session_state.selected_account_id = account_id
                    st.session_state.account_page_view = "virtual"
                    st.session_state.account_action = "overview"
                    set_flash(f"{name.strip()} virtual account created successfully.")
                    st.rerun()
        return

    if view not in {"main", "virtual"}:
        st.session_state.account_page_view = "menu"
        st.rerun()

    if view == "main":
        st.button("Back to account options", icon=":material/arrow_back:", on_click=back_to_account_menu)
    else:
        st.button("Back to main account", icon=":material/arrow_back:", on_click=back_to_main_account)

    free = available_to_allocate(phone)
    st.caption("Main account and virtual accounts")

    account_list_col, account_detail_col = st.columns([1, 1.2], gap="large")
    with account_list_col:
        with st.container(border=True):
            st.caption("MAIN ACCOUNT")
            st.markdown(f"**{user['bank']} ···· {user['last4']}**")
            st.metric("Money available for allocation", available_label(phone))
            total_balance = "Unlimited" if is_admin(phone) else Indian_money(user["bank_balance"])
            st.caption(f"Total bank balance: {total_balance}")

        st.subheader("Virtual accounts")
        if accounts:
            for item in accounts:
                with st.container(border=True):
                    st.markdown(f"**{item['emoji']} {item['name']}**")
                    cols = st.columns([1.2, 1])
                    cols[0].caption(f"Available · {Indian_money(item['balance'])}")
                    cols[1].button(
                        "Open account",
                        key=f"open_account_{item['account_id']}",
                        on_click=select_account,
                        args=(item["account_id"],),
                    )
        else:
            st.info("No virtual accounts yet. Create one to start setting money aside.")
    selected_id = st.session_state.get("selected_account_id")
    account = get_account(phone, selected_id) if selected_id else None
    with account_detail_col, st.container(border=True):
        if account is None:
            st.subheader("Main account")
            st.caption("Choose a virtual account from the list to manage it.")
        else:
            st.subheader(f"{account['emoji']} {account['name']}")
            st.metric("Available balance", Indian_money(account["balance"]))
            st.caption(f"Budget: {Indian_money(account['budget'])} · {account['description']}")

            with st.container(horizontal=True, horizontal_alignment="left", wrap=True):
                st.button("Add money", icon=":material/add:", on_click=set_account_action, args=("add",), key=f"add_action_{selected_id}")
                st.button("Withdraw", icon=":material/keyboard_return:", on_click=set_account_action, args=("withdraw",), key=f"withdraw_action_{selected_id}")
                st.button("Move allocation", icon=":material/swap_horiz:", on_click=set_account_action, args=("move",), key=f"move_action_{selected_id}")
                st.button("Rename / delete", icon=":material/more_horiz:", on_click=set_account_action, args=("manage",), key=f"manage_action_{selected_id}")

            action = st.session_state.get("account_action", "overview")
            if action == "add":
                st.divider()
                st.markdown("**Add money from the main account**")
                st.caption(f"Available to allocate: {available_label(phone)}")
                amount = st.number_input("Amount", min_value=1, step=500, key=f"add_amount_{selected_id}")
                pin = st.text_input("Payment PIN", type="password", key=f"add_pin_{selected_id}")
                submitted = st.button("Done", type="primary", width="stretch", key=f"add_submit_{selected_id}")
                if submitted:
                    current_free = available_to_allocate(phone)
                    if pin_digest(pin) != user["pin_hash"]:
                        st.toast("The payment PIN is incorrect. No money was moved.", icon="⚠️")
                    elif amount > current_free:
                        st.toast("There is not enough money available in the main account.", icon="⚠️")
                    else:
                        try:
                            with connect() as db:
                                result = db.execute(
                                    "UPDATE accounts SET balance = balance + ?, budget = MAX(budget, balance + ?) WHERE account_id = ? AND phone = ?",
                                    (amount, amount, selected_id, phone),
                                )
                                if result.rowcount != 1:
                                    raise sqlite3.IntegrityError("Virtual account was not found")
                                db.execute(
                                    """INSERT INTO transactions(phone, name, detail, account_name, amount, created_at)
                                       VALUES (?, ?, ?, ?, ?, ?)""",
                                    (phone, "Money added", "Allocation from main account", account["name"], int(amount), datetime.now().isoformat(timespec="seconds")),
                                )
                        except sqlite3.Error:
                            set_flash("Add money failed. No allocation was changed.", "error")
                        else:
                            set_flash(f"Added {Indian_money(amount)} to {account['name']} successfully.")
                        st.rerun()

            elif action == "withdraw":
                st.divider()
                st.markdown("**Withdraw to the main account's available balance**")
                amount = st.number_input("Amount", min_value=1, step=500, key=f"withdraw_amount_{selected_id}")
                pin = st.text_input("Payment PIN", type="password", key=f"withdraw_pin_{selected_id}")
                submitted = st.button("Done", type="primary", width="stretch", key=f"withdraw_submit_{selected_id}")
                if submitted:
                    if pin_digest(pin) != user["pin_hash"]:
                        st.toast("The payment PIN is incorrect. No money was moved.", icon="⚠️")
                    elif amount > account["balance"]:
                        st.toast("There is not enough money in this virtual account.", icon="⚠️")
                    else:
                        try:
                            with connect() as db:
                                result = db.execute(
                                    "UPDATE accounts SET balance = balance - ? WHERE account_id = ? AND phone = ? AND balance >= ?",
                                    (amount, selected_id, phone, amount),
                                )
                                if result.rowcount != 1:
                                    raise sqlite3.IntegrityError("Allocation changed before withdrawal")
                                db.execute(
                                    """INSERT INTO transactions(phone, name, detail, account_name, amount, created_at)
                                       VALUES (?, ?, ?, ?, ?, ?)""",
                                    (phone, "Money withdrawn", "Returned to main account", account["name"], int(amount), datetime.now().isoformat(timespec="seconds")),
                                )
                        except sqlite3.Error:
                            set_flash("Withdrawal failed. No allocation was changed.", "error")
                        else:
                            set_flash(f"Withdrew {Indian_money(amount)} from {account['name']} successfully.")
                        st.rerun()

            elif action == "move":
                destinations = [item for item in accounts if item["account_id"] != selected_id]
                st.divider()
                if not destinations:
                    st.info("Create another virtual account before moving an allocation.")
                else:
                    st.markdown("**Move money to another virtual account**")
                    target_id = st.selectbox(
                        "Destination account",
                        [item["account_id"] for item in destinations],
                        format_func=lambda value: next(item["name"] for item in destinations if item["account_id"] == value),
                    )
                    amount = st.number_input("Amount", min_value=1, step=500, key=f"move_amount_{selected_id}")
                    pin = st.text_input("Payment PIN", type="password", key=f"move_pin_{selected_id}")
                    submitted = st.button("Done", type="primary", width="stretch", key=f"move_submit_{selected_id}")
                    if submitted:
                        target = get_account(phone, target_id)
                        if pin_digest(pin) != user["pin_hash"]:
                            st.toast("The payment PIN is incorrect. No money was moved.", icon="⚠️")
                        elif amount > account["balance"]:
                            st.toast("There is not enough money in this virtual account.", icon="⚠️")
                        elif target is None:
                            st.toast("The destination account could not be found.", icon="⚠️")
                        else:
                            try:
                                with connect() as db:
                                    source_result = db.execute(
                                        "UPDATE accounts SET balance = balance - ? WHERE account_id = ? AND phone = ? AND balance >= ?",
                                        (amount, selected_id, phone, amount),
                                    )
                                    target_result = db.execute(
                                        "UPDATE accounts SET balance = balance + ?, budget = MAX(budget, balance + ?) WHERE account_id = ? AND phone = ?",
                                        (amount, amount, target_id, phone),
                                    )
                                    if source_result.rowcount != 1 or target_result.rowcount != 1:
                                        raise sqlite3.IntegrityError("An account changed before the move completed")
                                    db.execute(
                                        """INSERT INTO transactions(phone, name, detail, account_name, amount, created_at)
                                           VALUES (?, ?, ?, ?, ?, ?)""",
                                        (phone, "Money moved", f"Moved from {account['name']}", target["name"], int(amount), datetime.now().isoformat(timespec="seconds")),
                                    )
                            except sqlite3.Error:
                                set_flash("Move failed. No allocation was changed.", "error")
                            else:
                                set_flash(f"Move successful: {Indian_money(amount)} moved to {target['name']}.")
                            st.rerun()

            elif action == "manage":
                st.divider()
                new_name = st.text_input("Virtual account name", value=account["name"])
                new_description = st.text_input("Purpose", value=account["description"])
                rename_submitted = st.button("Save changes", key=f"rename_submit_{selected_id}")
                if rename_submitted:
                    if not new_name.strip():
                        st.toast("Account name cannot be empty. Nothing was changed.", icon="⚠️")
                    elif any(item["account_id"] != selected_id and item["name"].casefold() == new_name.strip().casefold() for item in accounts):
                        st.toast("An account with that name already exists. Nothing was changed.", icon="⚠️")
                    else:
                        try:
                            with connect() as db:
                                result = db.execute(
                                    "UPDATE accounts SET name = ?, description = ? WHERE account_id = ? AND phone = ?",
                                    (new_name.strip(), new_description.strip(), selected_id, phone),
                                )
                                if result.rowcount != 1:
                                    raise sqlite3.IntegrityError("Virtual account was not found")
                                db.execute(
                                    "UPDATE transactions SET account_name = ? WHERE phone = ? AND account_name = ?",
                                    (new_name.strip(), phone, account["name"]),
                                )
                        except sqlite3.Error:
                            set_flash("Virtual account update failed. No changes were saved.", "error")
                        else:
                            set_flash("Virtual account updated successfully.")
                        st.rerun()
                confirm = st.checkbox(
                    "I understand the allocation will return to money available in the main account.",
                    key=f"confirm_delete_{selected_id}",
                )
                if st.button("Delete virtual account", disabled=not confirm, key=f"delete_{selected_id}"):
                    try:
                        with connect() as db:
                            result = db.execute(
                                "DELETE FROM accounts WHERE account_id = ? AND phone = ?",
                                (selected_id, phone),
                            )
                            if result.rowcount != 1:
                                raise sqlite3.IntegrityError("Virtual account was not found")
                    except sqlite3.Error:
                        set_flash("Delete failed. The virtual account is still there.", "error")
                    else:
                        set_flash(f"{account['name']} was deleted successfully.")
                        st.session_state.pop("selected_account_id", None)
                        st.session_state.account_action = "overview"
                    st.rerun()

            if action != "manage":
                with st.expander("Receive money into this account"):
                    virtual_account_id = "VP-" + selected_id[-6:].upper()
                    st.write(f"VirtualPay ID · **{virtual_account_id}**")
                    st.image(make_qr("virtualpay://receive/" + virtual_account_id), alt="QR code for this virtual account")
                    st.caption("This QR contains a demo ID and does not initiate a real payment.")

def render_transfer(user: dict[str, Any], accounts: list[dict[str, Any]]) -> None:
    st.title("Transfer money")
    st.caption("Choose a recipient, amount, and account to pay from.")
    st.info("Demo only: no bank or UPI payment is sent.", icon=":material/info:")
    phone = user["phone"]
    saved = list_recipients(phone)
    saved_by_id = {item["recipient"]: item for item in saved}

    if not st.session_state.get("camera_enabled", False):
        st.caption("Camera is off. Open it only when you choose to scan a QR code.")
        if st.button("Scan QR code", icon=":material/qr_code_scanner:"):
            st.session_state.camera_enabled = True
            st.rerun()
    else:
        st.caption("Your browser will ask for camera access if it has not been allowed yet.")
        close_col, _ = st.columns([1, 3], vertical_alignment="bottom")
        with close_col:
            if st.button("Close camera", icon=":material/videocam_off:"):
                st.session_state.camera_enabled = False
                st.rerun()
        photo = st.camera_input("Scan recipient QR code", key="transfer_qr")
        if photo is not None:
            try:
                import zxingcpp
                from PIL import Image
                decoded = zxingcpp.read_barcodes(np.asarray(Image.open(photo).convert("RGB")))
                if decoded:
                    st.session_state.transfer_scan_recipient = decoded[0].text.removeprefix("virtualpay://receive/")
                    st.success(f"QR code read: {st.session_state.transfer_scan_recipient}")
                else:
                    st.warning("No QR code was found. Enter the recipient ID manually.")
            except ImportError:
                st.warning("QR decoding is unavailable. Enter the recipient ID manually.")

    with st.container(border=True):
        recipient_col, payment_col = st.columns([1, 1], gap="large")
        with recipient_col:
            st.subheader("Recipient")
            options = ["manual", *saved_by_id.keys()]
            recipient_choice = st.radio(
                "Previously paid",
                options,
                format_func=lambda value: "Enter a new recipient" if value == "manual" else (
                    f"{saved_by_id[value]['recipient_name']} · {value}"
                    if saved_by_id[value]["recipient_name"] else value
                ),
                key="transfer_recipient_choice",
            )
            if recipient_choice == "manual":
                recipient = st.text_input(
                    "Phone number or VirtualPay ID",
                    value=st.session_state.get("transfer_scan_recipient", ""),
                    placeholder="For example, 9876543210 or VP-ABC123",
                )
                st.caption("The recipient must have a VirtualPay demo account to receive this simulated transfer.")
                recipient_name = st.text_input("Recipient name", placeholder="Optional")
            else:
                recipient_data = saved_by_id[recipient_choice]
                recipient = recipient_data["recipient"]
                recipient_name = recipient_data["recipient_name"]
                st.write(f"**{recipient_name or recipient}**")
                st.caption(recipient)

        with payment_col:
            st.subheader("Payment")
            amount = st.number_input("Amount", min_value=1, step=100)
            choices = ["main"] + [account["account_id"] for account in accounts]

            def label_source(source: str) -> str:
                if source == "main":
                    return f"Main account · {available_label(phone)} available"
                account = next(item for item in accounts if item["account_id"] == source)
                return f"{account['name']} · {Indian_money(account['balance'])} available"

            source_id = st.selectbox("Choose account", choices, format_func=label_source)
            pin = st.text_input("Payment PIN", type="password")
            st.caption("Use your demo PIN. Never enter your real UPI PIN.")
            submitted = st.button("Done", type="primary", width="stretch")

    if submitted:
        recipient = recipient.strip()
        recipient_user = find_virtualpay_recipient(recipient) if recipient else None
        display_name = recipient_name.strip() or (recipient_user["name"] if recipient_user else recipient)
        if not recipient:
            st.toast("Enter a phone number or VirtualPay ID.", icon="⚠️")
        elif pin_digest(pin) != user["pin_hash"]:
            st.toast("The payment PIN is incorrect. No transfer was made.", icon="⚠️")
        elif recipient_user is None:
            st.toast("No VirtualPay account matched. No money was sent.", icon="⚠️")
        elif recipient_user["phone"] == phone:
            st.toast("Choose another person's account. No money was sent.", icon="⚠️")
        else:
            account = get_account(phone, source_id) if source_id != "main" else None
            if source_id == "main" and amount > available_to_allocate(phone):
                st.toast("There is not enough money available in the main account.", icon="⚠️")
            elif account is not None and amount > account["balance"]:
                st.toast(f"There is not enough money in {account['name']}.", icon="⚠️")
            else:
                try:
                    with connect() as db:
                        result = None
                        if source_id == "main":
                            if not is_admin(phone):
                                result = db.execute(
                                    "UPDATE users SET bank_balance = bank_balance - ? WHERE phone = ? AND bank_balance - ? >= (SELECT COALESCE(SUM(balance), 0) FROM accounts WHERE phone = ?)",
                                    (amount, phone, amount, phone),
                                )
                        else:
                            if not is_admin(phone):
                                result = db.execute(
                                    "UPDATE users SET bank_balance = bank_balance - ? WHERE phone = ?",
                                    (amount, phone),
                                )
                            account_result = db.execute(
                                "UPDATE accounts SET balance = balance - ? WHERE account_id = ? AND phone = ? AND balance >= ?",
                                (amount, source_id, phone, amount),
                            )
                            if account_result.rowcount != 1:
                                raise sqlite3.IntegrityError("Virtual account balance changed")
                        if result is not None and result.rowcount != 1:
                            raise sqlite3.IntegrityError("Main account balance changed")
                        if not is_admin(recipient_user["phone"]):
                            receiver_result = db.execute(
                                "UPDATE users SET bank_balance = bank_balance + ? WHERE phone = ?",
                                (amount, recipient_user["phone"]),
                            )
                            if receiver_result.rowcount != 1:
                                raise sqlite3.IntegrityError("Recipient account was not found")
                        transferred_at = datetime.now().isoformat(timespec="seconds")
                        sender_transaction = db.execute(
                            """INSERT INTO transactions(phone, name, detail, account_name, amount, created_at)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (phone, display_name, "Transfer to " + recipient_user["name"], account["name"] if account else "Main account", -int(amount), transferred_at),
                        )
                        db.execute(
                            """INSERT INTO transactions(phone, name, detail, account_name, amount, created_at)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (recipient_user["phone"], "Money received", f"From {user['name']}", "Main account", int(amount), transferred_at),
                        )
                        db.execute(
                            "INSERT INTO transfer_receipts(source_transaction_id, recipient_phone, created_at) VALUES (?, ?, ?)",
                            (sender_transaction.lastrowid, recipient_user["phone"], transferred_at),
                        )
                        db.execute(
                            """INSERT INTO recipients(phone, recipient, recipient_name) VALUES (?, ?, ?)
                               ON CONFLICT(phone, recipient) DO UPDATE SET recipient_name =
                               CASE WHEN excluded.recipient_name = '' THEN recipients.recipient_name
                                    ELSE excluded.recipient_name END""",
                            (phone, recipient, recipient_name.strip()),
                        )
                except sqlite3.Error:
                    set_flash("Transfer failed. No account balance was changed.", "error")
                else:
                    st.session_state.transfer_scan_recipient = ""
                    set_flash(f"Transfer successful: {Indian_money(amount)} sent to {display_name} and credited to their main account.")
                st.rerun()

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
