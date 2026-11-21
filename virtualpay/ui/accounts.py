import secrets
import sqlite3
from datetime import datetime
from typing import Any

import streamlit as st

from ..database import available_label, available_to_allocate, connect, get_account, is_admin, list_accounts
from ..formatting import Indian_money, make_qr, pin_digest
from ..state import set_flash

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


def open_virtual_accounts() -> None:
    st.session_state.pop("selected_account_id", None)
    st.session_state.account_page_view = "virtual_list"


def show_main_account() -> None:
    st.session_state.pop("selected_account_id", None)
    st.session_state.account_page_view = "main"


def show_account_create_form() -> None:
    st.session_state.pop("selected_account_id", None)
    st.session_state.account_page_view = "create_form"


def back_to_virtual_accounts() -> None:
    st.session_state.pop("selected_account_id", None)
    st.session_state.account_page_view = "virtual_list"


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
        options = st.columns(3, gap="large")
        options[0].button(
            "Main account",
            icon=":material/account_balance:",
            width="stretch",
            on_click=open_main_account,
        )
        options[1].button(
            "Virtual accounts",
            icon=":material/account_balance_wallet:",
            width="stretch",
            on_click=open_virtual_accounts,
        )
        options[2].button(
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
                    st.session_state.pop("selected_account_id", None)
                    st.session_state.account_page_view = "virtual_list"
                    st.session_state.account_action = "overview"
                    set_flash(f"{name.strip()} virtual account created successfully.")
                    st.rerun()
        return

    if view not in {"main", "virtual_list", "virtual"}:
        st.session_state.account_page_view = "menu"
        st.rerun()

    if view == "main":
        st.button("Back to account options", icon=":material/arrow_back:", on_click=back_to_account_menu)
        with st.container(border=True):
            st.caption("MAIN ACCOUNT")
            st.markdown(f"**{user['bank']} ···· {user['last4']}**")
            allocated = sum(item["balance"] for item in accounts)
            main_balance = "Unlimited" if is_admin(phone) else Indian_money(user["bank_balance"])
            metrics = st.columns(3)
            metrics[0].metric("Main account balance", main_balance)
            metrics[1].metric("Allocated to virtual accounts", Indian_money(allocated))
            metrics[2].metric("Available to allocate", available_label(phone))
            st.caption("Allocating money only reserves it for a purpose. The main balance changes when you make a payment.")
        return

    if view == "virtual_list":
        st.button("Back to account options", icon=":material/arrow_back:", on_click=back_to_account_menu)
    else:
        st.button("Back to virtual accounts", icon=":material/arrow_back:", on_click=back_to_virtual_accounts)

    st.subheader("Virtual accounts")

    account_list_col, account_detail_col = st.columns([1, 1.2], gap="large")
    with account_list_col:
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
            st.button("Create virtual account", on_click=open_new_account)
    selected_id = st.session_state.get("selected_account_id")
    account = get_account(phone, selected_id) if selected_id else None
    with account_detail_col, st.container(border=True):
        if account is None:
            st.subheader("Select a virtual account")
            st.caption("Choose one from the list to view and manage its allocation.")
        else:
            with st.container(horizontal=True, horizontal_alignment="right"):
                st.button(
                    "Close",
                    icon=":material/close:",
                    on_click=back_to_virtual_accounts,
                    key=f"close_account_details_{selected_id}",
                )
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
