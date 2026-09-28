"""Apple Pay notifications from the iOS Shortcuts automation "Transaktion".

Every recognised payment becomes a pending transaction (source 'wallet') on
its account and counts immediately. The same payment reported twice within
15 minutes is stored once. When the bank books it, linking marks the wallet
entry as duplicate (see linking.py). Fetches never remove wallet entries.
Payments that cannot be assigned are kept with a reason and shown in the app.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from ..money import to_minor
from .db import utcnow
from .importer import detect_currency, parse_amount
from .store import NewTx, upsert_transactions

DEDUP_MINUTES = 15
LOCAL_TZ = ZoneInfo("Europe/Vienna")
IGNORE = re.compile(r"abgelehnt|declined|aufladung|top.?up|umtausch|exchange|bestätig|confirm", re.I)


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9ÄÖÜ]", "", (text or "").upper())


def find_account(conn: sqlite3.Connection, card: str) -> Optional[int]:
    """The Shortcut reports the card name as shown in Wallet ("PayLife Classic",
    "Volksbank Debit"). Match against account names and patterns."""
    wanted = _norm(card)
    if not wanted:
        return None
    for r in conn.execute("SELECT id, name, institution, patterns FROM accounts WHERE hidden=0 ORDER BY sort"):
        keys = [r["name"], r["institution"] or ""] + [p for p in (r["patterns"] or "").split(",")]
        if any(_norm(k) and (_norm(k) in wanted or wanted in _norm(k)) for k in keys):
            return r["id"]
    return None


def record(conn: sqlite3.Connection, *, amount: str, merchant: str, card: str,
           currency: Optional[str] = None, when: Optional[datetime] = None) -> dict:
    now = when or datetime.now(timezone.utc)
    value = parse_amount(amount)
    cur = (currency or detect_currency(amount) or "EUR").upper()

    def store(status: str, reason: Optional[str] = None, account_id=None, tx_id=None, minor=None) -> dict:
        eid = conn.execute(
            """INSERT INTO wallet_events (received_at, occurred_at, amount_minor, currency, merchant, card,
               account_id, tx_id, status, reason) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (utcnow(), now.isoformat(), minor, cur, merchant, card, account_id, tx_id, status, reason)).lastrowid
        return {"id": eid, "status": status, "reason": reason, "tx_id": tx_id}

    if IGNORE.search(f"{merchant} {amount}"):
        return store("ignored", "keine Zahlung")
    if value is None or value == 0:
        return store("unassigned", "Betrag nicht erkannt")
    minor = -abs(to_minor(value, cur))          # Apple Pay notifications are payments
    account_id = find_account(conn, card)
    if account_id is None:
        return store("unassigned", f"Karte „{card}“ keinem Konto zugeordnet", minor=minor)

    since = (now - timedelta(minutes=DEDUP_MINUTES)).isoformat()
    dup = conn.execute(
        """SELECT tx_id FROM wallet_events WHERE status='recorded' AND account_id=? AND amount_minor=?
           AND currency=? AND occurred_at >= ?""", (account_id, minor, cur, since)).fetchone()
    if dup:
        return store("duplicate", "bereits gemeldet", account_id, dup[0], minor)

    tx = NewTx(booking_date=now.astimezone(LOCAL_TZ).date(), amount_minor=minor, currency=cur, status="pending",
               ext_ref=f"wallet:{now.isoformat()}:{minor}", counterparty=merchant.strip() or None,
               description="Apple Pay", apple_pay=True, card=card)
    result = upsert_transactions(conn, account_id, "wallet", [tx])
    return store("recorded", None, account_id, result.seen_ids[0], minor)
