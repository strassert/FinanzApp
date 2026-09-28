"""Consent flow and fetching into the database (fake bank, no network)."""

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from finanzen import sync
from finanzen.bank import PsuHeaders
from finanzen.bank.fake_scenario import FLATEX, PAYLIFE, PAYPAL, VOLKSBANK
from finanzen.core.recompute import recompute

from .conftest import REDIRECT, TODAY, connect_bank
from .helpers import one, tx


def test_consent_creates_connection_and_accounts(conn, scenario, provider, fake, clock):
    cid = connect_bank(conn, provider, fake, clock, VOLKSBANK)
    c = conn.execute("SELECT * FROM connections WHERE id=?", (cid,)).fetchone()
    assert c["status"] == "active" and c["session_id"]
    acc = conn.execute("SELECT * FROM accounts WHERE connection_id=?", (cid,)).fetchone()
    assert acc["name"] == "Volksbank Salzburg Gehaltskonto"   # not the owner's name
    assert acc["owner_name"] == "Max Mustermann"
    assert acc["kind"] == "giro"
    assert acc["history_loaded_at"] is not None


def test_account_kinds_and_default_patterns(conn, linked):
    rows = {r["institution"] + r["currency"]: r for r in conn.execute("SELECT * FROM accounts")}
    assert rows["PayPalEUR"]["kind"] == "paypal" and rows["PayPalEUR"]["patterns"] == "PAYPAL"
    assert rows["PayPalUSD"]["name"] == "PayPal USD"
    assert rows["PayLifeEUR"]["kind"] == "card" and rows["PayLifeEUR"]["patterns"] == "PAYLIFE"
    assert rows["flatexEUR"]["kind"] == "broker"


def test_full_history_is_loaded_right_after_consent(conn, linked):
    assert one(conn, ref="VB-OLD-1")["amount_minor"] == -120000


def test_state_is_single_use_and_checked(conn, scenario, provider, fake, clock):
    url = sync.start_consent(conn, provider, VOLKSBANK, "AT", REDIRECT, now=clock)
    q = parse_qs(urlparse(fake.approve(url)).query)
    with pytest.raises(sync.ConsentStateError):
        sync.complete_consent(conn, provider, "forged-state", q["code"][0], now=clock)
    sync.complete_consent(conn, provider, q["state"][0], q["code"][0], now=clock)
    with pytest.raises(sync.ConsentStateError):
        sync.complete_consent(conn, provider, q["state"][0], q["code"][0], now=clock)


def test_state_expires(conn, scenario, provider, fake, clock):
    url = sync.start_consent(conn, provider, VOLKSBANK, "AT", REDIRECT, now=clock)
    q = parse_qs(urlparse(fake.approve(url)).query)
    clock.advance(hours=1)
    with pytest.raises(sync.ConsentStateError):
        sync.complete_consent(conn, provider, q["state"][0], q["code"][0], now=clock)


def test_duplicate_records_are_stored_once(conn, linked):
    assert len(tx(conn, ref="VB-DUP-1")) == 1


def test_resync_adds_nothing_twice(conn, linked, provider, clock):
    before = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    clock.advance(hours=2)
    results = sync.sync_all(conn, provider, trigger="user", psu=PsuHeaders("192.0.2.1", "t"), now=clock)
    assert all(r.status == "ok" for r in results)
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == before


def test_pending_replaced_by_booked_keeps_user_data(conn, linked, provider, fake, clock):
    pending = one(conn, ref="VB-PEND-1")
    assert pending["status"] == "pending"
    groceries = conn.execute("SELECT id FROM categories WHERE name='Restaurant & Café'").fetchone()[0]
    conn.execute("UPDATE transactions SET user_category_id=?, note='Jause' WHERE id=?",
                 (groceries, pending["id"]))
    fake.book_pending("hash-giro", "VB-PEND-1", TODAY, amount="24.10")
    clock.advance(hours=2)
    sync.sync_connection(conn, provider, linked[VOLKSBANK], "user",
                         PsuHeaders("192.0.2.1", "t"), now=clock)
    old = one(conn, ref="VB-PEND-1")
    new = one(conn, ref="VB-PEND-1-B")
    assert old["removed_at"] is not None and old["superseded_by"] == new["id"]   # kept, not deleted
    assert old["role"] is None                                               # not counted any more
    assert new["status"] == "booked" and new["amount_minor"] == -2410
    assert new["note"] == "Jause" and new["category"] == "Restaurant & Café"


def test_pending_that_vanishes_without_booking_is_marked_removed(conn, linked, provider, fake, clock):
    fake.accounts["hash-paylife"].transactions = [
        t for t in fake.accounts["hash-paylife"].transactions if t["entry_reference"] != "PL-PEND-1"]
    clock.advance(hours=2)
    sync.sync_connection(conn, provider, linked[PAYLIFE], "user", PsuHeaders("192.0.2.1", "t"), now=clock)
    gone = one(conn, ref="PL-PEND-1")
    assert gone["removed_at"] and gone["superseded_by"] is None


def test_rate_limit_pauses_connection_for_six_hours(conn, linked, provider, fake, clock):
    fake.force_rate_limit = True
    clock.advance(hours=3)
    r = sync.sync_connection(conn, provider, linked[FLATEX], now=clock)
    assert r.status == "rate_limited"
    fake.force_rate_limit = False
    clock.advance(hours=5)
    assert sync.sync_connection(conn, provider, linked[FLATEX], now=clock).status == "skipped"
    clock.advance(hours=1, minutes=1)
    assert sync.sync_connection(conn, provider, linked[FLATEX], now=clock).status == "ok"


def test_tailscale_psu_ip_falls_back_to_unattended(conn, linked, provider, fake, clock):
    r = sync.sync_connection(conn, provider, linked[FLATEX], "user",
                             PsuHeaders("100.100.1.1", "Safari"), now=clock)
    assert r.status == "ok"


def test_expired_consent_is_flagged(conn, linked, provider, fake, clock):
    session_id = conn.execute("SELECT session_id FROM connections WHERE id=?",
                              (linked[PAYLIFE],)).fetchone()[0]
    fake.expire_session(session_id)
    r = sync.sync_connection(conn, provider, linked[PAYLIFE], now=clock)
    assert r.status == "expired"
    assert conn.execute("SELECT status FROM connections WHERE id=?",
                        (linked[PAYLIFE],)).fetchone()[0] == "expired"
    # sync_all skips expired connections
    assert linked[PAYLIFE] not in [x.connection_id for x in sync.sync_all(conn, provider, now=clock)]


def test_renewal_keeps_accounts_and_reactivates(conn, linked, provider, fake, clock):
    session_id = conn.execute("SELECT session_id FROM connections WHERE id=?",
                              (linked[VOLKSBANK],)).fetchone()[0]
    fake.expire_session(session_id)
    sync.sync_connection(conn, provider, linked[VOLKSBANK], now=clock)
    accounts_before = conn.execute("SELECT id, identification_hash FROM accounts").fetchall()
    tx_before = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    cid = connect_bank(conn, provider, fake, clock, VOLKSBANK)
    assert cid == linked[VOLKSBANK]
    assert conn.execute("SELECT id, identification_hash FROM accounts").fetchall() == accounts_before
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == tx_before
    assert conn.execute("SELECT status FROM connections WHERE id=?", (cid,)).fetchone()[0] == "active"


def test_empty_session_is_explained(conn, scenario, provider, fake, clock):
    fake.restricted = True
    cid = connect_bank(conn, provider, fake, clock, VOLKSBANK)
    run = conn.execute("SELECT * FROM sync_runs WHERE connection_id=? ORDER BY id DESC", (cid,)).fetchone()
    assert run["status"] == "empty" and "verknüpft" in run["message"]


def test_no_transaction_content_in_logs(conn, linked, provider, fake, clock, caplog):
    fake.force_rate_limit = False
    session_id = conn.execute("SELECT session_id FROM connections WHERE id=?",
                              (linked[VOLKSBANK],)).fetchone()[0]
    fake.sessions[session_id].uids.clear()
    conn.execute("UPDATE accounts SET uid='gone' WHERE connection_id=?", (linked[VOLKSBANK],))
    with caplog.at_level("DEBUG"):
        sync.sync_connection(conn, provider, linked[VOLKSBANK], now=clock)
    text = caplog.text
    assert "MIETE" not in text and "AT" + "45" not in text and "Mustermann" not in text


def test_balances_stored_booked_not_available(conn, linked):
    card = conn.execute("""SELECT b.* FROM balances b JOIN accounts a ON a.id=b.account_id
                           WHERE a.institution='PayLife'""").fetchone()
    assert card["balance_type"] == "CLBD" and card["amount_minor"] < 0
