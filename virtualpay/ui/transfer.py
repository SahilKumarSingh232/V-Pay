import sqlite3
from datetime import datetime
from typing import Any

import numpy as np
import streamlit as st

from ..database import (
    available_label,
    available_to_allocate,
    find_virtualpay_recipient,
    get_account,
    is_admin,
    list_recipients,
)
from ..formatting import Indian_money, pin_digest
from ..state import set_flash

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
            if source_id == "main" and not is_admin(phone) and amount > user["bank_balance"]:
                st.toast("There is not enough money in the main account and its virtual allocations.", icon="⚠️")
            elif account is not None and amount > account["balance"]:
                st.toast(f"There is not enough money in {account['name']}.", icon="⚠️")
            else:
                allocation_deductions: list[tuple[str, int]] = []
                try:
                    with connect() as db:
                        result = None
                        if source_id == "main":
                            if not is_admin(phone):
                                current_balance = db.execute(
                                    "SELECT bank_balance FROM users WHERE phone = ?", (phone,)
                                ).fetchone()
                                if current_balance is None or amount > current_balance["bank_balance"]:
                                    raise sqlite3.IntegrityError("Main account balance changed")
                                virtual_accounts = db.execute(
                                    """SELECT account_id, name, balance FROM accounts WHERE phone = ?
                                       ORDER BY created_at DESC, rowid DESC""",
                                    (phone,),
                                ).fetchall()
                                current_allocated = sum(item["balance"] for item in virtual_accounts)
                                available_before = int(current_balance["bank_balance"]) - current_allocated
                                remaining_to_cover = max(0, int(amount) - available_before)
                                result = db.execute(
                                    "UPDATE users SET bank_balance = bank_balance - ? WHERE phone = ? AND bank_balance >= ?",
                                    (amount, phone, amount),
                                )
                                if result.rowcount != 1:
                                    raise sqlite3.IntegrityError("Main account balance changed")
                                for virtual_account in virtual_accounts:
                                    if remaining_to_cover <= 0:
                                        break
                                    deduction = min(int(virtual_account["balance"]), remaining_to_cover)
                                    if deduction <= 0:
                                        continue
                                    account_result = db.execute(
                                        "UPDATE accounts SET balance = balance - ? WHERE account_id = ? AND phone = ? AND balance >= ?",
                                        (deduction, virtual_account["account_id"], phone, deduction),
                                    )
                                    if account_result.rowcount != 1:
                                        raise sqlite3.IntegrityError("Virtual account balance changed")
                                    allocation_deductions.append((virtual_account["name"], deduction))
                                    db.execute(
                                        """INSERT INTO transactions(phone, name, detail, account_name, amount, created_at)
                                           VALUES (?, ?, ?, ?, ?, ?)""",
                                        (
                                            phone,
                                            "Allocation used for payment",
                                            f"Main account payment to {recipient_user['name']}",
                                            virtual_account["name"],
                                            -deduction,
                                            datetime.now().isoformat(timespec="seconds"),
                                        ),
                                    )
                                    remaining_to_cover -= deduction
                                if remaining_to_cover > 0:
                                    raise sqlite3.IntegrityError("Virtual allocations could not cover the payment")
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
                    message = f"Transfer successful: {Indian_money(amount)} sent to {display_name} and credited to their main account."
                    if allocation_deductions:
                        deductions = " → ".join(
                            f"{name} {Indian_money(value)}" for name, value in allocation_deductions
                        )
                        message += f" Virtual account amounts used (newest first): {deductions}."
                    set_flash(message)
                st.rerun()
