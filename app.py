"""VirtualPay: a local, simulated virtual-account budgeting prototype."""

from __future__ import annotations

import hashlib
import io
import secrets
import sqlite3
from datetime import datetime, timedelta
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
SEED_ACCOUNTS = [
    ("shopping", "Shopping", "🛍️", "Little things, big joy", 8200, 12000),
    ("business", "Business", "💼", "For work and what’s next", 14800, 20000),
    ("emergency", "Emergency", "🌱", "A little peace of mind", 5000, 10000),
    ("travel", "Travel", "✈️", "Your next great escape", 7000, 10000),
]


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
                bank_balance INTEGER NOT NULL DEFAULT 50000,
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
                UNIQUE(phone, recipient)
            );
            """
        )


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


def available_to_allocate(phone: str) -> int:
    user = get_user(phone)
    accounts = list_accounts(phone)
    return int(user["bank_balance"] - sum(a["balance"] for a in accounts))


def add_transaction(
    phone: str, name: str, detail: str, account_name: str, amount: int
) -> None:
    with connect() as db:
        db.execute(
            """INSERT INTO transactions(phone, name, detail, account_name, amount, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (phone, name, detail, account_name, amount, datetime.now().isoformat(timespec="seconds")),
        )


def create_user(phone: str, name: str, bank: str, last4: str, pin: str) -> None:
    virtual_id = "VP-" + secrets.token_hex(3).upper()
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as db:
        db.execute(
            """INSERT INTO users(phone, name, bank, last4, virtual_id, pin_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (phone, name.strip(), bank, last4, virtual_id, pin_digest(pin), now),
        )
        for _, account_name, emoji, description, balance, budget in SEED_ACCOUNTS:
            account_id = secrets.token_hex(8)
            db.execute(
                """INSERT INTO accounts(account_id, phone, name, emoji, description,
                   balance, budget, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (account_id, phone, account_name, emoji, description, balance, budget, now),
            )
        seed_transactions = [
            ("Myntra", "UPI · myntra@paytm", "Shopping", -2499, 0),
            ("Monthly allocation", "Budget top-up", "Emergency", 1200, 0),
            ("Notion Plus", "UPI · notion@okaxis", "Business", -800, 1),
            ("Swiggy", "UPI · swiggy@ibl", "Shopping", -680, 1),
            ("Flight booking", "UPI · ixigo@axis", "Travel", -6499, 3),
            ("Monthly allocation", "Budget top-up", "Business", 3000, 5),
            ("Uber", "UPI · uber@axis", "Shopping", -321, 6),
        ]
        for name_, detail, account, amount, days_ago in seed_transactions:
            created = (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")
            db.execute(
                """INSERT INTO transactions(phone, name, detail, account_name, amount, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (phone, name_, detail, account, amount, created),
            )


def record_recipient(phone: str, recipient: str) -> None:
    with connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO recipients(phone, recipient) VALUES (?, ?)",
            (phone, recipient),
        )


def list_recipients(phone: str) -> list[str]:
    with connect() as db:
        rows = db.execute(
            "SELECT recipient FROM recipients WHERE phone = ? ORDER BY recipient_id DESC LIMIT 5",
            (phone,),
        ).fetchall()
    return [row["recipient"] for row in rows]


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
        frame.rename(
            columns={
                "name": "Transaction",
                "detail": "Details",
                "account_name": "Virtual account",
                "status": "Status",
            },
            inplace=True,
        )
    return frame


def make_qr(value: str) -> bytes:
    image = qrcode.make(value)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def set_page(page: str) -> None:
    st.session_state.nav_page = page


def set_accounts_section(section: str) -> None:
    st.session_state.nav_page = "My accounts"
    st.session_state.account_section = section


def authenticate(phone: str) -> None:
    st.session_state.user_phone = phone
    st.session_state.auth_stage = "signed_in"
    st.session_state.nav_page = "Overview"


st.set_page_config(page_title="VirtualPay", page_icon=":material/account_balance_wallet:", layout="wide")
initialize_database()

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
            with st.form("phone_form"):
                phone = st.text_input("Mobile number", max_chars=10, placeholder="10-digit phone number")
                submitted = st.form_submit_button("Continue", type="primary", width="stretch")
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
            with st.form("otp_form"):
                otp = st.text_input("One-time code", max_chars=6, placeholder="6-digit code")
                submitted = st.form_submit_button("Verify", type="primary", width="stretch")
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
            with st.form("register_form"):
                name = st.text_input("Full name", placeholder="Your name")
                bank = st.selectbox("Bank", BANKS)
                last4 = st.text_input("Last 4 digits of account", max_chars=4, placeholder="2841")
                pin = st.text_input("Create demo payment PIN", type="password", max_chars=6)
                st.caption("Use a made-up PIN. Never enter your real bank or UPI PIN.")
                submitted = st.form_submit_button("Create my account", type="primary", width="stretch")
            if submitted:
                if not name.strip():
                    st.error("Enter your name.")
                elif not last4.isdigit() or len(last4) != 4:
                    st.error("Enter the last 4 digits of the demo account.")
                elif not pin.isdigit() or len(pin) not in (4, 5, 6):
                    st.error("Use a 4–6 digit demo PIN.")
                else:
                    create_user(st.session_state.pending_phone, name, bank, last4, pin)
                    authenticate(st.session_state.pending_phone)
                    st.rerun()

        elif stage == "pin":
            st.subheader("Welcome back")
            st.caption("Enter your demo payment PIN to continue.")
            with st.form("pin_form"):
                pin = st.text_input("Demo payment PIN", type="password", max_chars=6)
                submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
            if submitted:
                user = get_user(st.session_state.pending_phone)
                if user and pin_digest(pin) == user["pin_hash"]:
                    authenticate(st.session_state.pending_phone)
                    st.rerun()
                st.error("That demo PIN does not match.")

    st.caption("VirtualPay is a local concept prototype. It does not connect to banks or send payments.")


def render_sidebar(user: dict[str, Any]) -> str:
    with st.sidebar:
        st.markdown("### :material/account_balance_wallet: VirtualPay")
        st.caption(f"{user['name']} · +91 {user['phone']}")
        page = st.radio(
            "Navigation",
            ["Overview", "My accounts", "Transfer money", "Activity"],
            key="nav_page",
            label_visibility="collapsed",
        )
        st.divider()
        st.caption("LINKED BANK")
        st.write(f"**{user['bank']}**")
        st.caption(f"Primary · account ending {user['last4']}")
        st.success("Bank connection is active", icon=":material/verified_user:")
        if st.button("Sign out", icon=":material/logout:", width="stretch"):
            st.session_state.auth_stage = "phone"
            st.session_state.pop("user_phone", None)
            st.rerun()
        return page


def render_overview(user: dict[str, Any], accounts: list[dict[str, Any]]) -> None:
    allocated = sum(account["balance"] for account in accounts)
    free = int(user["bank_balance"] - allocated)
    st.caption(datetime.now().strftime("%A, %d %B %Y").upper())
    st.title(f"Good morning, {user['name'].split()[0]}")
    st.write("Give every rupee a purpose. You're doing great.")

    with st.container(horizontal=True, horizontal_alignment="left"):
        st.button("Transfer money", icon=":material/swap_horiz:", type="primary", on_click=set_page, args=("Transfer money",))
        st.button("My receiving QR", icon=":material/qr_code:", on_click=set_accounts_section, args=("Receive money",))
        st.button("View activity", icon=":material/history:", on_click=set_page, args=("Activity",))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total bank balance", Indian_money(user["bank_balance"]), border=True)
    m2.metric("Allocated to budgets", Indian_money(allocated), border=True)
    m3.metric("Available to allocate", Indian_money(free), border=True)
    m4.metric("Virtual accounts", str(len(accounts)), border=True)

    st.subheader("Your virtual accounts")
    if not accounts:
        st.info("Create your first virtual account to start setting budgets.")
    else:
        with st.grid("auto", min_column_width=220, gap="small"):
            for account in accounts:
                with st.container(border=True):
                    st.markdown(f"### {account['emoji']} {account['name']}")
                    st.caption(account["description"])
                    st.metric("Available", Indian_money(account["balance"]))
                    ratio = min(account["balance"] / max(account["budget"], 1), 1.0)
                    st.progress(ratio, text=f"{Indian_money(account['balance'])} of {Indian_money(account['budget'])}")
                    st.button(
                        "Manage account",
                        key=f"manage_{account['account_id']}",
                        on_click=lambda account_id=account["account_id"]: select_account(account_id),
                    )

    left, right = st.columns([1.2, 1], gap="large")
    with left:
        st.subheader("Spending overview")
        transactions = get_transactions(user["phone"])
        spent = transactions.loc[transactions["amount"] < 0].copy() if not transactions.empty else pd.DataFrame()
        if not spent.empty:
            spent["day"] = spent["created_at"].dt.strftime("%a")
            chart = spent.groupby("day", as_index=False)["amount"].sum().assign(Spend=lambda frame: frame["amount"].abs())
            st.bar_chart(chart, x="day", y="Spend", alt="Recent spending by weekday, in rupees")
            st.caption(f"Recent recorded spending: {Indian_money(-spent['amount'].sum())}")
        else:
            st.info("Your spending activity will appear here.")
    with right:
        st.subheader("A little progress goes a long way")
        emergency = next((a for a in accounts if a["name"].lower() == "emergency"), None)
        if emergency:
            st.info(
                f"Your Emergency fund has {Indian_money(emergency['balance'])} allocated "
                f"toward a {Indian_money(emergency['budget'])} goal.",
                icon=":material/savings:",
            )
            st.progress(
                min(emergency["balance"] / max(emergency["budget"], 1), 1.0),
                text="Emergency fund progress",
            )
        st.caption("Virtual accounts are budget allocations. Your money stays in your linked bank account.")

    st.subheader("Recent activity")
    show_transaction_table(user["phone"], limit=5)


def select_account(account_id: str) -> None:
    st.session_state.selected_account_id = account_id
    st.session_state.nav_page = "My accounts"
    st.session_state.account_section = "Manage accounts"


def render_accounts(user: dict[str, Any], accounts: list[dict[str, Any]]) -> None:
    phone = user["phone"]
    st.title("Virtual accounts")
    st.write("Create budgets for the things that matter. Every rupee stays in your bank.")

    default_section = "Manage accounts" if st.session_state.get("selected_account_id") else "Create account"
    section = st.segmented_control(
        "Account tools",
        ["Create account", "Manage accounts", "Receive money"],
        default=default_section,
        key="account_section",
    )
    if section == "Create account":
        free = available_to_allocate(phone)
        st.metric("Available for allocation", Indian_money(free))
        with st.form("create_account_form"):
            name = st.text_input("Account name", placeholder="For example, Home or Fitness")
            description = st.text_input("What are you saving for?", placeholder="Optional description")
            emoji = st.selectbox("Choose an icon", ["🎯", "🏠", "🎓", "💪", "🎁", "🐾", "🛍️", "✈️"])
            amount = st.number_input("Initial allocation", min_value=0, step=500, value=0)
            submitted = st.form_submit_button("Create account", type="primary")
        if submitted:
            if not name.strip():
                st.error("Enter an account name.")
            elif any(a["name"].casefold() == name.strip().casefold() for a in accounts):
                st.error("An account with that name already exists.")
            elif amount > free:
                st.error("That is more than your available bank balance.")
            else:
                account_id = secrets.token_hex(8)
                with connect() as db:
                    db.execute(
                        """INSERT INTO accounts(account_id, phone, name, emoji, description,
                           balance, budget, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (account_id, phone, name.strip(), emoji, description.strip() or "A budget for what matters", amount, max(amount, 1000), datetime.now().isoformat(timespec="seconds")),
                    )
                if amount:
                    add_transaction(phone, "Allocation added", "Budget top-up", name.strip(), int(amount))
                st.success(f"{name.strip()} account created.")
                st.rerun()

    elif section == "Manage accounts":
        if not accounts:
            st.info("Create an account first.")
        else:
            ids = [account["account_id"] for account in accounts]
            default_id = st.session_state.get("selected_account_id", ids[0])
            if default_id not in ids:
                default_id = ids[0]
            selected_id = st.selectbox(
                "Select a virtual account",
                ids,
                index=ids.index(default_id),
                format_func=lambda account_id: next(a["emoji"] + " " + a["name"] for a in accounts if a["account_id"] == account_id),
                key="manage_account_select",
            )
            account = get_account(phone, selected_id)
            if account:
                st.session_state.selected_account_id = selected_id
                info, qr = st.columns([1.3, 1], gap="large")
                with info, st.container(border=True):
                    st.subheader(f"{account['emoji']} {account['name']}")
                    st.metric("Available to spend", Indian_money(account["balance"]))
                    st.caption(f"Budget: {Indian_money(account['budget'])} · {account['description']}")
                    st.caption(f"VirtualPay ID: VP-{account['account_id'][-6:].upper()}")
                with qr, st.container(border=True):
                    st.markdown("**Receive money to this virtual account**")
                    st.image(make_qr("virtualpay://receive/VP-" + account["account_id"][-6:].upper()), alt="QR code for this virtual account")
                    st.caption("QR is a demo identifier; it does not initiate a real payment.")

                add_tab, move_tab, edit_tab = st.tabs(["Add allocation", "Move allocation", "Edit or delete"])
                with add_tab:
                    free = available_to_allocate(phone)
                    st.caption(f"Available in main account: {Indian_money(free)}")
                    with st.form("add_allocation_form"):
                        amount = st.number_input("Amount to add", min_value=1, step=500, key="add_allocation_amount")
                        submitted = st.form_submit_button("Add allocation", type="primary")
                    if submitted:
                        if amount > free:
                            st.error("That is more than your available bank balance.")
                        else:
                            with connect() as db:
                                db.execute(
                                    "UPDATE accounts SET balance = balance + ?, budget = MAX(budget, balance + ?) WHERE account_id = ? AND phone = ?",
                                    (amount, amount, selected_id, phone),
                                )
                            add_transaction(phone, "Allocation added", "Budget top-up", account["name"], int(amount))
                            st.success(f"{Indian_money(amount)} allocated to {account['name']}.")
                            st.rerun()

                with move_tab:
                    destinations = [a for a in accounts if a["account_id"] != selected_id]
                    if not destinations:
                        st.info("Create another virtual account before moving allocations.")
                    else:
                        with st.form("move_allocation_form"):
                            target_id = st.selectbox(
                                "Move to",
                                [a["account_id"] for a in destinations],
                                format_func=lambda account_id: next(a["name"] for a in destinations if a["account_id"] == account_id),
                            )
                            amount = st.number_input("Amount to move", min_value=1, step=500, key="move_allocation_amount")
                            submitted = st.form_submit_button("Move allocation")
                        if submitted:
                            if amount > account["balance"]:
                                st.error("That is more than this account's current allocation.")
                            else:
                                target = get_account(phone, target_id)
                                with connect() as db:
                                    db.execute("UPDATE accounts SET balance = balance - ? WHERE account_id = ? AND phone = ?", (amount, selected_id, phone))
                                    db.execute("UPDATE accounts SET balance = balance + ?, budget = MAX(budget, balance + ?) WHERE account_id = ? AND phone = ?", (amount, amount, target_id, phone))
                                add_transaction(phone, "Allocation moved", f"Moved from {account['name']}", target["name"], int(amount))
                                st.success(f"{Indian_money(amount)} moved to {target['name']}.")
                                st.rerun()

                with edit_tab:
                    with st.form("rename_account_form"):
                        new_name = st.text_input("Account name", value=account["name"])
                        new_description = st.text_input("Description", value=account["description"])
                        submitted = st.form_submit_button("Save changes")
                    if submitted:
                        if not new_name.strip():
                            st.error("Account name cannot be empty.")
                        elif any(a["account_id"] != selected_id and a["name"].casefold() == new_name.strip().casefold() for a in accounts):
                            st.error("An account with that name already exists.")
                        else:
                            with connect() as db:
                                db.execute(
                                    "UPDATE accounts SET name = ?, description = ? WHERE account_id = ? AND phone = ?",
                                    (new_name.strip(), new_description.strip(), selected_id, phone),
                                )
                                db.execute(
                                    "UPDATE transactions SET account_name = ? WHERE phone = ? AND account_name = ?",
                                    (new_name.strip(), phone, account["name"]),
                                )
                            st.success("Account details updated.")
                            st.rerun()
                    confirm = st.checkbox("I understand that deleting this account returns its allocation to the main account.", key=f"confirm_delete_{selected_id}")
                    if st.button("Delete virtual account", type="secondary", disabled=not confirm, key=f"delete_{selected_id}"):
                        with connect() as db:
                            db.execute("DELETE FROM accounts WHERE account_id = ? AND phone = ?", (selected_id, phone))
                        st.success("Account deleted. Its allocation is available again.")
                        st.rerun()

    elif section == "Receive money":
        st.subheader("Your VirtualPay ID")
        st.write(f"**{user['virtual_id']}** · {user['name']}")
        st.image(make_qr("virtualpay://receive/" + user["virtual_id"]), alt="QR code for your VirtualPay ID")
        st.caption("Share the ID for this demo. A real QR or transfer needs a payment provider integration.")


def render_transfer(user: dict[str, Any], accounts: list[dict[str, Any]]) -> None:
    st.title("Transfer money")
    st.write("Choose a recipient, amount, and account to pay from.")
    st.info("This is a simulation. No bank or UPI payment is sent.", icon=":material/info:")
    phone = user["phone"]
    saved = list_recipients(phone)
    if saved:
        st.caption("Recently used recipients: " + " · ".join(saved))
    photo = st.camera_input("Scan a recipient QR code", key="transfer_qr")
    if photo is not None:
        try:
            import zxingcpp

            from PIL import Image

            decoded = zxingcpp.read_barcodes(np.asarray(Image.open(photo).convert("RGB")))
            if decoded:
                value = decoded[0].text.removeprefix("virtualpay://receive/")
                st.session_state.transfer_recipient = value
                st.success(f"QR code read: {value}")
            else:
                st.warning("No QR code was found in that image. You can enter the recipient ID manually.")
        except ImportError:
            st.warning("Install the requirements to decode QR images, or enter the recipient ID manually.")
    with st.container(border=True):
        with st.form("transfer_form"):
            recipient = st.text_input(
                "Phone number, UPI ID, or VirtualPay ID",
                placeholder="For example, 9876543210 or VP-ABC123",
                key="transfer_recipient",
            )
            amount = st.number_input("Amount", min_value=1, step=100)
            choices = ["main"] + [account["account_id"] for account in accounts]

            def label_source(source: str) -> str:
                if source == "main":
                    return f"Main account · {Indian_money(available_to_allocate(phone))} available"
                account = next(a for a in accounts if a["account_id"] == source)
                return f"{account['emoji']} {account['name']} · {Indian_money(account['balance'])} available"

            source_id = st.selectbox("Pay from", choices, format_func=label_source)
            pin = st.text_input("Demo payment PIN", type="password", max_chars=6)
            st.caption("Use the made-up PIN you chose during setup. Never enter your real UPI PIN.")
            submitted = st.form_submit_button("Review and transfer", type="primary")

    if submitted:
        recipient = recipient.strip()
        if not recipient:
            st.error("Enter a recipient.")
        elif pin_digest(pin) != user["pin_hash"]:
            st.error("That demo PIN does not match.")
        else:
            account = get_account(phone, source_id) if source_id != "main" else None
            if source_id == "main" and amount > available_to_allocate(phone):
                st.error("Not enough unallocated money in the main account.")
            elif account is not None and amount > account["balance"]:
                st.error(f"Not enough allocation in {account['name']}.")
            else:
                with connect() as db:
                    db.execute("UPDATE users SET bank_balance = bank_balance - ? WHERE phone = ?", (amount, phone))
                    if account:
                        db.execute("UPDATE accounts SET balance = balance - ? WHERE account_id = ? AND phone = ?", (amount, source_id, phone))
                record_recipient(phone, recipient)
                add_transaction(
                    phone,
                    recipient,
                    "VirtualPay transfer · " + (account["name"] if account else "Main account"),
                    account["name"] if account else "Main account",
                    -int(amount),
                )
                st.success(f"Demo transfer of {Indian_money(amount)} recorded for {recipient}.")
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
    st.title("Activity")
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
    page = render_sidebar(user)
    if page == "Overview":
        render_overview(user, accounts)
    elif page == "My accounts":
        render_accounts(user, accounts)
    elif page == "Transfer money":
        render_transfer(user, accounts)
    elif page == "Activity":
        render_activity(user["phone"], accounts)
