"""Glue between the bank module and the database: consent flow and fetching.

This is the only place that uses both `finanzen.bank` and `finanzen.core`.
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

from .bank import (
    BankError, BankProvider, ConsentExpired, Institution, PsuHeaders, PsuHeadersRejected,
    RateLimited, RawTransaction, pick_balance,
)
from .core.db import transaction, utcnow
from .core.recompute import recompute
from .core.store import (
    NewTx, replace_missing_pending, store_balance, upsert_api_account, upsert_transactions,
)

log = logging.getLogger(__name__)

FULL_HISTORY_DAYS = 730
OVERLAP_DAYS = 30
CONSENT_DAYS = 180
STATE_TTL = timedelta(minutes=30)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def to_new_tx(raw: RawTransaction) -> NewTx:
    return NewTx(
        booking_date=raw.date or date.today(),
        amount_minor=raw.amount_minor,
        currency=raw.currency,
        status=raw.status,
        ext_ref=raw.entry_reference or raw.transaction_id,
        value_date=raw.value_date,
        counterparty=raw.counterparty_name,
        counterparty_iban=raw.counterparty_iban,
        description=raw.remittance,
        mcc=raw.mcc,
        original_amount_minor=raw.original_amount_minor,
        original_currency=raw.original_currency,
        raw=json.dumps(raw.raw, ensure_ascii=False, sort_keys=True) if raw.raw else None,
    )


# --- consent ----------------------------------------------------------------------

def start_consent(conn: sqlite3.Connection, provider: BankProvider, institution: str,
                  country: str, redirect_url: str, renew_connection_id: Optional[int] = None,
                  max_days: Optional[int] = None, now: Callable[[], datetime] = _now) -> str:
    state = secrets.token_urlsafe(24)
    conn.execute("INSERT INTO pending_consents (state, institution, country, connection_id, created_at) "
                 "VALUES (?,?,?,?,?)", (state, institution, country, renew_connection_id,
                                          now().isoformat()))
    days = min(CONSENT_DAYS, max_days or CONSENT_DAYS)
    return provider.start_consent(Institution(institution, country), redirect_url, state,
                                  now() + timedelta(days=days))


class ConsentStateError(Exception):
    pass


def complete_consent(conn: sqlite3.Connection, provider: BankProvider, state: str, code: str,
                     now: Callable[[], datetime] = _now) -> int:
    """Finish the consent, store accounts, fetch the full history. Returns connection id."""
    row = conn.execute("SELECT * FROM pending_consents WHERE state=?", (state,)).fetchone()
    if row is None:
        raise ConsentStateError("unknown or used state")
    conn.execute("DELETE FROM pending_consents WHERE state=?", (state,))
    created = datetime.fromisoformat(row["created_at"])
    if now() - created > STATE_TTL:
        raise ConsentStateError("state expired")
    session = provider.complete_consent(code)
    with transaction(conn):
        connection_id = row["connection_id"]
        if connection_id is None:
            # renewing without explicit id: reuse the connection that owns one of the accounts
            hashes = [a.identification_hash for a in session.accounts]
            found = conn.execute(
                "SELECT connection_id FROM accounts WHERE identification_hash IN (%s) "
                "AND connection_id IS NOT NULL LIMIT 1" % ",".join("?" * len(hashes)),
                hashes).fetchone() if hashes else None
            connection_id = found[0] if found else None
        if connection_id is None:
            connection_id = conn.execute(
                "INSERT INTO connections (institution, country, created_at) VALUES (?,?,?)",
                (row["institution"], row["country"], utcnow())).lastrowid
        conn.execute(
            """UPDATE connections SET session_id=?, valid_until=?, status='active', paused_until=NULL,
               last_error=NULL WHERE id=?""",
            (session.session_id, session.valid_until.isoformat(), connection_id))
        for acc in session.accounts:
            upsert_api_account(conn, connection_id, row["institution"], uid=acc.uid,
                               identification_hash=acc.identification_hash, currency=acc.currency,
                               iban=acc.iban, product=acc.product, owner_name=acc.owner_name,
                               cash_account_type=acc.cash_account_type,
                               credit_limit_minor=acc.credit_limit_minor)
    sync_connection(conn, provider, connection_id, trigger="consent", now=now)
    return connection_id


# --- fetching --------------------------------------------------------------------

@dataclass
class SyncResult:
    connection_id: int
    status: str                        # ok | rate_limited | expired | error | skipped | empty
    new_count: int = 0
    message: str = ""
    accounts: list[int] = field(default_factory=list)


def sync_connection(conn: sqlite3.Connection, provider: BankProvider, connection_id: int,
                    trigger: str = "schedule", psu: Optional[PsuHeaders] = None,
                    now: Callable[[], datetime] = _now, do_recompute: bool = True) -> SyncResult:
    c = conn.execute("SELECT * FROM connections WHERE id=?", (connection_id,)).fetchone()
    run_id = conn.execute("INSERT INTO sync_runs (connection_id, trigger, started_at, status) "
                          "VALUES (?,?,?,'running')", (connection_id, trigger, utcnow())).lastrowid
    result = SyncResult(connection_id, "ok")
    try:
        if c["status"] == "expired":
            result.status, result.message = "expired", "Zustimmung abgelaufen"
        elif c["paused_until"] and datetime.fromisoformat(c["paused_until"]) > now():
            result.status, result.message = "skipped", "pausiert (Rate Limit)"
        else:
            accounts = conn.execute("SELECT * FROM accounts WHERE connection_id=? AND uid IS NOT NULL",
                                    (connection_id,)).fetchall()
            if not accounts:
                result.status = "empty"
                result.message = "Keine Konten in der Verbindung – ist das Konto in Enable Banking verknüpft?"
            for acc in accounts:
                result.new_count += _sync_account(conn, provider, acc, psu, now)
                result.accounts.append(acc["id"])
            conn.execute("UPDATE connections SET last_sync_at=?, last_error=NULL WHERE id=?",
                         (utcnow(), connection_id))
    except RateLimited as exc:
        until = now() + timedelta(seconds=exc.retry_after_seconds)
        conn.execute("UPDATE connections SET paused_until=?, last_error=? WHERE id=?",
                     (until.isoformat(), "rate_limited", connection_id))
        result.status, result.message = "rate_limited", f"pausiert bis {until.isoformat()}"
    except ConsentExpired:
        conn.execute("UPDATE connections SET status='expired', last_error='expired' WHERE id=?",
                     (connection_id,))
        result.status, result.message = "expired", "Zustimmung abgelaufen"
    except BankError as exc:
        conn.execute("UPDATE connections SET last_error=? WHERE id=?",
                     (type(exc).__name__, connection_id))
        result.status, result.message = "error", type(exc).__name__
        log.warning("sync of connection %s failed: %s (%s)", connection_id,
                    type(exc).__name__, exc.code)
    conn.execute("UPDATE sync_runs SET finished_at=?, status=?, message=?, new_count=? WHERE id=?",
                 (utcnow(), result.status, result.message, result.new_count, run_id))
    if do_recompute and result.status == "ok":
        recompute(conn)
    return result


def _with_psu_fallback(call, psu: Optional[PsuHeaders]):
    if psu is None:
        return call(None)
    try:
        return call(psu)
    except PsuHeadersRejected:
        return call(None)


def _sync_account(conn: sqlite3.Connection, provider: BankProvider, acc: sqlite3.Row,
                  psu: Optional[PsuHeaders], now: Callable[[], datetime]) -> int:
    today = now().date()
    if acc["history_loaded_at"] is None:
        date_from = today - timedelta(days=FULL_HISTORY_DAYS)
    else:
        oldest_pending = conn.execute(
            "SELECT MIN(booking_date) FROM transactions WHERE account_id=? AND source='api' "
            "AND status='pending' AND removed_at IS NULL", (acc["id"],)).fetchone()[0]
        date_from = today - timedelta(days=OVERLAP_DAYS)
        if oldest_pending:
            date_from = min(date_from, date.fromisoformat(oldest_pending) - timedelta(days=3))

    balances = _with_psu_fallback(lambda p: provider.fetch_balances(acc["uid"], psu=p), psu)
    raw = _with_psu_fallback(
        lambda p: list(provider.fetch_transactions(acc["uid"], date_from, psu=p)), psu)

    with transaction(conn):
        chosen = pick_balance(balances)
        if chosen:
            store_balance(conn, acc["id"], chosen.amount_minor, chosen.currency,
                          chosen.balance_type, chosen.reference_date or today)
        result = upsert_transactions(conn, acc["id"], "api", [to_new_tx(r) for r in raw])
        replace_missing_pending(conn, acc["id"], date_from, result.seen_ids, result.new_ids)
        if acc["history_loaded_at"] is None:
            conn.execute("UPDATE accounts SET history_loaded_at=? WHERE id=?", (utcnow(), acc["id"]))
    return len(result.new_ids)


def sync_all(conn: sqlite3.Connection, provider: BankProvider, trigger: str = "schedule",
             psu: Optional[PsuHeaders] = None, now: Callable[[], datetime] = _now) -> list[SyncResult]:
    ids = [r[0] for r in conn.execute("SELECT id FROM connections WHERE status != 'expired' ORDER BY id")]
    results = [sync_connection(conn, provider, cid, trigger, psu, now, do_recompute=False) for cid in ids]
    recompute(conn)
    return results
