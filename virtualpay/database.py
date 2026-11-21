import secrets
import sqlite3
from datetime import datetime
from typing import Any

import pandas as pd

from .config import ADMIN_PHONE, ADMIN_PIN, DB_PATH
from .formatting import Indian_money, pin_digest

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
