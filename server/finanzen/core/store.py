"""Storing accounts, balances and transactions. Nothing is ever deleted."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, Optional

from .db import utcnow


@dataclass
class NewTx:
    """A transaction as delivered by any source (bank, file import, wallet)."""
    booking_date: date
    amount_minor: int
    currency: str
    status: str = "booked"                 # booked | pending
    ext_ref: Optional[str] = None          # bank reference; None -> fingerprint
    value_date: Optional[date] = None
    counterparty: Optional[str] = None
    counterparty_iban: Optional[str] = None
    description: str = ""
    mcc: Optional[str] = None
    original_amount_minor: Optional[int] = None
    original_currency: Optional[str] = None
    apple_pay: bool = False
    card: Optional[str] = None
    raw: Optional[str] = field(default=None, repr=False)


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().upper())


def fingerprint(tx: NewTx) -> str:
    base = "|".join([tx.booking_date.isoformat(), str(tx.amount_minor), tx.currency,
                     _norm_text(tx.counterparty or ""), _norm_text(tx.description)])
    return "fp:" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]


def assign_ext_ids(txs: Iterable[NewTx]) -> list[tuple[str, NewTx]]:
    """Give every transaction a stable identity.

    Bank references are used as they are; a record repeated with the same
    reference is the same record. Without a reference, the fingerprint plus
    the position among identical rows is used, so two identical coffees on
    the same day stay two, and re-importing an overlapping file adds only
    what is new.
    """
    out: list[tuple[str, NewTx]] = []
    seen_refs: set[str] = set()
    occurrences: dict[str, int] = {}
    for tx in txs:
        if tx.ext_ref:
            if tx.ext_ref in seen_refs:
                continue
            seen_refs.add(tx.ext_ref)
            out.append((tx.ext_ref, tx))
        else:
            fp = fingerprint(tx)
            n = occurrences.get(fp, 0)
            occurrences[fp] = n + 1
            out.append((f"{fp}#{n}", tx))
    return out


@dataclass
class UpsertResult:
    new_ids: list[int] = field(default_factory=list)
    seen_ids: list[int] = field(default_factory=list)


def upsert_transactions(conn: sqlite3.Connection, account_id: int, source: str,
                        txs: Iterable[NewTx]) -> UpsertResult:
    now = utcnow()
    result = UpsertResult()
    for ext_id, tx in assign_ext_ids(txs):
        row = conn.execute("SELECT id FROM transactions WHERE account_id=? AND source=? AND ext_id=?",
                           (account_id, source, ext_id)).fetchone()
        values = (tx.status, tx.booking_date.isoformat(),
                  tx.value_date.isoformat() if tx.value_date else None,
                  tx.amount_minor, tx.currency, tx.original_amount_minor, tx.original_currency,
                  tx.counterparty, tx.counterparty_iban, tx.description or "", tx.mcc,
                  int(tx.apple_pay), tx.card, tx.raw)
        if row:
            conn.execute(
                """UPDATE transactions SET status=?, booking_date=?, value_date=?, amount_minor=?,
                   currency=?, original_amount_minor=?, original_currency=?, counterparty=?,
                   counterparty_iban=?, description=?, mcc=?, apple_pay=?, card=?, raw=?,
                   last_seen=?, removed_at=NULL WHERE id=?""",
                values + (now, row["id"]))
            result.seen_ids.append(row["id"])
        else:
            cur = conn.execute(
                """INSERT INTO transactions (status, booking_date, value_date, amount_minor, currency,
                   original_amount_minor, original_currency, counterparty, counterparty_iban,
                   description, mcc, apple_pay, card, raw, account_id, source, ext_id,
                   first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                values + (account_id, source, ext_id, now, now))
            result.new_ids.append(cur.lastrowid)
            result.seen_ids.append(cur.lastrowid)
    return result


def replace_missing_pending(conn: sqlite3.Connection, account_id: int, window_from: date,
                            seen_ids: Iterable[int], new_ids: Iterable[int]) -> list[tuple[int, Optional[int]]]:
    """Pending bank transactions that the latest fetch no longer returned are
    marked removed and, where possible, linked to the booked transaction that
    replaced them. User category, note and decisions move to the booked one.

    Returns [(pending_id, booked_id or None)].
    """
    seen = set(seen_ids)
    new_ids = list(new_ids)
    candidates = [dict(r) for r in conn.execute(
        "SELECT * FROM transactions WHERE id IN (%s) AND status='booked'"
        % ",".join("?" * len(new_ids)), new_ids)] if new_ids else []
    missing = [dict(r) for r in conn.execute(
        """SELECT * FROM transactions WHERE account_id=? AND source='api' AND status='pending'
           AND removed_at IS NULL AND booking_date >= ?""", (account_id, window_from.isoformat()))
        if r["id"] not in seen]
    taken: set[int] = set(
        r[0] for r in conn.execute("SELECT superseded_by FROM transactions WHERE superseded_by IS NOT NULL"))
    now = utcnow()
    out = []
    for p in sorted(missing, key=lambda r: r["booking_date"]):
        match = _find_booked(p, [c for c in candidates if c["id"] not in taken])
        booked_id = match["id"] if match else None
        conn.execute("UPDATE transactions SET removed_at=?, superseded_by=? WHERE id=?",
                     (now, booked_id, p["id"]))
        if match:
            taken.add(booked_id)
            carry_user_data(conn, p["id"], booked_id)
        out.append((p["id"], booked_id))
    return out


def _find_booked(pending: dict, candidates: list[dict]) -> Optional[dict]:
    p_date = date.fromisoformat(pending["booking_date"])
    p_amount = pending["amount_minor"]
    p_text = _norm_text(pending["description"])[:12]
    best, best_score = None, None
    for c in candidates:
        if c["currency"] != pending["currency"] or (c["amount_minor"] < 0) != (p_amount < 0):
            continue
        c_date = date.fromisoformat(c["booking_date"])
        if not (p_date - timedelta(days=1) <= c_date <= p_date + timedelta(days=10)):
            continue
        diff = abs(c["amount_minor"] - p_amount)
        if diff > max(abs(p_amount) * 0.2, 100):   # tips, fuel pre-authorisations
            continue
        same_text = p_text and _norm_text(c["description"]).startswith(p_text)
        score = (0 if same_text else 1, diff, abs((c_date - p_date).days))
        if best_score is None or score < best_score:
            best, best_score = c, score
    return best


def carry_user_data(conn: sqlite3.Connection, old_id: int, new_id: int) -> None:
    old = conn.execute("SELECT user_category_id, note, user_excluded FROM transactions WHERE id=?",
                       (old_id,)).fetchone()
    conn.execute(
        """UPDATE transactions SET
             user_category_id = COALESCE(user_category_id, ?),
             note = COALESCE(note, ?),
             user_excluded = MAX(user_excluded, ?)
           WHERE id=?""", (old["user_category_id"], old["note"], old["user_excluded"], new_id))
    for col in ("a_id", "b_id"):
        conn.execute(f"UPDATE OR IGNORE link_decisions SET {col}=? WHERE {col}=?", (new_id, old_id))


# --- accounts and balances ---------------------------------------------------------

DEFAULT_PATTERNS = {
    "paypal": "PAYPAL",
    "PayLife": "PAYLIFE",
    "flatex": "FLATEX",
}


def account_kind(institution: str, cash_account_type: Optional[str], product: Optional[str]) -> str:
    inst = (institution or "").lower()
    if "paypal" in inst:
        return "paypal"
    if cash_account_type == "CARD" or "paylife" in inst:
        return "card"
    if "flatex" in inst:
        return "broker"
    if cash_account_type == "SVGS":
        return "savings"
    return "giro"


def default_patterns(institution: str, kind: str) -> str:
    if kind == "paypal":
        return "PAYPAL"
    for key, pattern in DEFAULT_PATTERNS.items():
        if key.lower() in (institution or "").lower():
            return pattern
    return ""


def upsert_api_account(conn: sqlite3.Connection, connection_id: int, institution: str, *,
                       uid: str, identification_hash: str, currency: str,
                       iban: Optional[str], product: Optional[str], owner_name: Optional[str],
                       cash_account_type: Optional[str], credit_limit_minor: Optional[int]) -> int:
    row = conn.execute("SELECT id FROM accounts WHERE identification_hash=?",
                       (identification_hash,)).fetchone()
    if row:
        conn.execute("""UPDATE accounts SET connection_id=?, uid=?, iban=COALESCE(?, iban),
                        owner_name=COALESCE(?, owner_name), credit_limit_minor=? WHERE id=?""",
                     (connection_id, uid, iban, owner_name, credit_limit_minor, row["id"]))
        return row["id"]
    kind = account_kind(institution, cash_account_type, product)
    if not product or product.lower() in institution.lower():
        name = institution
    elif institution.lower() in product.lower():
        name = product
    else:
        name = f"{institution} {product}"
    if currency != "EUR" and currency not in name:
        name = f"{name} {currency}"
    sort = conn.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM accounts").fetchone()[0]
    cur = conn.execute(
        """INSERT INTO accounts (connection_id, identification_hash, uid, source, kind, name,
           institution, currency, iban, owner_name, patterns, credit_limit_minor, sort, color_slot,
           created_at) VALUES (?,?,?,'api',?,?,?,?,?,?,?,?,?,?,?)""",
        (connection_id, identification_hash, uid, kind, name, institution, currency, iban,
         owner_name, default_patterns(institution, kind), credit_limit_minor, sort, sort - 1, utcnow()))
    return cur.lastrowid


def create_manual_account(conn: sqlite3.Connection, name: str, kind: str, currency: str = "EUR",
                          iban: Optional[str] = None, patterns: str = "",
                          source: str = "manual") -> int:
    sort = conn.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM accounts").fetchone()[0]
    cur = conn.execute(
        """INSERT INTO accounts (source, kind, name, currency, iban, patterns, sort, color_slot,
           created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
        (source, kind, name, currency, iban, patterns, sort, sort - 1, utcnow()))
    return cur.lastrowid


def store_balance(conn: sqlite3.Connection, account_id: int, amount_minor: int, currency: str,
                  balance_type: str, as_of: date) -> None:
    row = conn.execute("SELECT id FROM balances WHERE account_id=? AND as_of=? AND balance_type=?",
                       (account_id, as_of.isoformat(), balance_type)).fetchone()
    if row:
        conn.execute("UPDATE balances SET amount_minor=?, currency=?, fetched_at=? WHERE id=?",
                     (amount_minor, currency, utcnow(), row["id"]))
    else:
        conn.execute("""INSERT INTO balances (account_id, amount_minor, currency, balance_type, as_of,
                        fetched_at) VALUES (?,?,?,?,?,?)""",
                     (account_id, amount_minor, currency, balance_type, as_of.isoformat(), utcnow()))
