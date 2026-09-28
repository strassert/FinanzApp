from datetime import datetime, timedelta, timezone

from finanzen.core import wallet
from finanzen.core.recompute import recompute

from .conftest import TODAY
from .helpers import one

NOON = datetime(TODAY.year, TODAY.month, TODAY.day, 10, 0, tzinfo=timezone.utc)


def test_payment_counts_immediately_as_pending(conn, linked):
    r = wallet.record(conn, amount="12,50 €", merchant="Café Bazar", card="PayLife Classic", when=NOON)
    assert r["status"] == "recorded"
    recompute(conn)
    row = conn.execute("""SELECT t.*, d.role FROM transactions t JOIN tx_derived d ON d.tx_id=t.id
                          WHERE t.id=?""", (r["tx_id"],)).fetchone()
    assert (row["amount_minor"], row["status"], row["apple_pay"], row["role"]) == (-1250, "pending", 1, "expense")


def test_same_payment_twice_within_15_minutes_is_stored_once(conn, linked):
    wallet.record(conn, amount="€12.50", merchant="Café Bazar", card="PayLife", when=NOON)
    r = wallet.record(conn, amount="12,50", merchant="CAFE BAZAR", card="PayLife", when=NOON + timedelta(minutes=9))
    assert r["status"] == "duplicate"
    r = wallet.record(conn, amount="12,50", merchant="Café Bazar", card="PayLife", when=NOON + timedelta(minutes=20))
    assert r["status"] == "recorded"


def test_bank_booking_replaces_the_notification(conn, linked):
    # the fake bank has a pending OMV payment of 54.00 on the card today
    r = wallet.record(conn, amount="54,00 €", merchant="OMV", card="PayLife", when=NOON)
    recompute(conn)
    row = conn.execute("SELECT d.role FROM tx_derived d WHERE d.tx_id=?", (r["tx_id"],)).fetchone()
    assert row["role"] == "excluded"
    assert one(conn, ref="PL-PEND-1")["role"] == "expense"


def test_unknown_card_and_non_payments(conn, linked):
    r = wallet.record(conn, amount="9,99 €", merchant="Kiosk", card="Unbekannte Karte", when=NOON)
    assert r["status"] == "unassigned" and "Unbekannte Karte" in r["reason"]
    assert wallet.record(conn, amount="abc", merchant="X", card="PayLife", when=NOON)["status"] == "unassigned"
    assert wallet.record(conn, amount="50 €", merchant="Aufladung", card="PayLife", when=NOON)["status"] == "ignored"


def test_local_date_is_used(conn, linked):
    late = datetime(TODAY.year, TODAY.month, TODAY.day, 22, 30, tzinfo=timezone.utc)   # 00:30 in Vienna
    r = wallet.record(conn, amount="5,00", merchant="Taxi", card="PayLife", when=late)
    day = conn.execute("SELECT booking_date FROM transactions WHERE id=?", (r["tx_id"],)).fetchone()[0]
    assert day == (TODAY + timedelta(days=1)).isoformat()


def test_fetch_never_removes_wallet_entries(conn, linked, provider, clock):
    from finanzen import sync
    from finanzen.bank import PsuHeaders
    r = wallet.record(conn, amount="7,00", merchant="Bäckerei", card="PayLife", when=NOON)
    clock.advance(hours=2)
    sync.sync_all(conn, provider, "user", PsuHeaders("192.0.2.1", "t"), now=clock)
    row = conn.execute("SELECT removed_at FROM transactions WHERE id=?", (r["tx_id"],)).fetchone()
    assert row["removed_at"] is None
