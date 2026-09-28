"""Every linking rule from the README, on the fake scenario and on small cases."""

from datetime import date, timedelta

from finanzen.core.db import utcnow
from finanzen.core.linking import Account, Tx, link_all, merchant_key
from finanzen.core.recompute import recompute
from finanzen.core.store import create_manual_account

from .helpers import links_of, one, tx


def role_of(conn, **kw):
    return one(conn, **kw)["role"]


# --- scenario (all banks connected) -------------------------------------------

def test_salary_is_income(conn, linked):
    for row in tx(conn, text="GEHALT"):
        assert row["role"] == "income" and row["category"] == "Gehalt"


def test_transfer_by_own_iban_is_paired(conn, linked):
    for debit in tx(conn, text="Sparplan", account="Volksbank Salzburg"):
        assert debit["role"] == "transfer"
        link = [l for l in links_of(conn, debit["id"]) if l["kind"] == "transfer"][0]
        assert link["evidence"] == "iban" and link["status"] == "auto"
        credit = conn.execute("SELECT * FROM transactions WHERE id=?", (link["b_id"],)).fetchone()
        assert credit["amount_minor"] == 50000
    for credit in tx(conn, text="Gutschrift Sparplan"):
        assert credit["role"] == "transfer"


def test_transfer_to_owner_without_api(conn, linked):
    for row in tx(conn, text="Notgroschen"):
        assert row["role"] == "transfer" and row["category"] == "Umbuchung"
        assert links_of(conn, row["id"])[0]["evidence"] == "owner"


def test_card_settlement_is_transfer_and_card_purchases_are_expenses(conn, linked):
    settlements = tx(conn, text="PAYLIFE ABRECHNUNG")
    assert settlements
    for s in settlements:
        assert s["role"] == "transfer"
        link = links_of(conn, s["id"])[0]
        assert link["evidence"] == "pattern" and link["b_id"] is not None
    for received in tx(conn, text="ZAHLUNG ERHALTEN"):
        assert received["role"] == "transfer"
    assert all(r["role"] == "expense" for r in tx(conn, text="OEBB TICKET"))


def test_paypal_without_funding_line_links_bank_debit_to_purchase(conn, linked):
    debits = tx(conn, text="Ihr Einkauf bei Zalando", account="Volksbank Salzburg")
    assert debits
    for d in debits:
        assert d["role"] == "transfer"
        link = [l for l in links_of(conn, d["id"]) if l["kind"] == "paypal"][0]
        purchase = one(conn, ref=conn.execute("SELECT ext_id FROM transactions WHERE id=?",
                                              (link["b_id"],)).fetchone()[0])
        assert purchase["account"] == "PayPal" and purchase["amount_minor"] == d["amount_minor"]
        assert purchase["role"] == "expense" and purchase["category"] == "Shopping"


def test_paypal_with_funding_line_pairs_with_funding(conn, linked):
    for d in tx(conn, text="Valve Corporation, Ihr Einkauf", account="Volksbank Salzburg"):
        assert d["role"] == "transfer"
        link = [l for l in links_of(conn, d["id"]) if l["kind"] == "transfer"][0]
        funding = conn.execute("SELECT description FROM transactions WHERE id=?", (link["b_id"],)).fetchone()
        assert funding[0] == "Bankgutschrift auf PayPal-Konto"
    for purchase in tx(conn, text="Zahlung an Valve"):
        assert purchase["role"] == "expense" and purchase["category"] == "Abos & Digitales"


def test_each_purchase_counts_once(conn, linked):
    """Sum of expenses equals the real purchases: no PayPal/card purchase is counted twice."""
    expenses = conn.execute("""SELECT t.description FROM transactions t JOIN tx_derived d ON d.tx_id=t.id
                               WHERE d.role='expense' AND t.amount_minor < 0""").fetchall()
    texts = [r[0] for r in expenses]
    assert not any("PP.4711.PP" in t for t in texts)
    assert not any("PAYLIFE ABRECHNUNG" in t for t in texts)


def test_amount_only_is_a_suggestion_until_confirmed(conn, linked):
    debit = one(conn, ref="VB-AMBIG-1")
    credit = one(conn, ref="FX-AMBIG-1")
    link = links_of(conn, debit["id"])[0]
    assert (link["status"], link["evidence"], link["b_id"]) == ("suggested", "amount", credit["id"])
    assert debit["role"] == "expense"  # still counts until the user decides

    conn.execute("INSERT INTO link_decisions VALUES ('transfer', ?, ?, 'confirmed', ?)",
                 (debit["id"], credit["id"], utcnow()))
    recompute(conn)
    assert role_of(conn, ref="VB-AMBIG-1") == "transfer"
    assert role_of(conn, ref="FX-AMBIG-1") == "transfer"


def test_rejected_suggestion_is_not_suggested_again(conn, linked):
    debit, credit = one(conn, ref="VB-AMBIG-1"), one(conn, ref="FX-AMBIG-1")
    conn.execute("INSERT INTO link_decisions VALUES ('transfer', ?, ?, 'rejected', ?)",
                 (debit["id"], credit["id"], utcnow()))
    recompute(conn)
    assert links_of(conn, debit["id"]) == []
    assert role_of(conn, ref="VB-AMBIG-1") == "expense"
    assert role_of(conn, ref="FX-AMBIG-1") == "income"


def test_refund_reduces_the_purchase_category(conn, linked):
    refund = one(conn, ref="VB-REFUND-2")
    assert refund["role"] == "expense" and refund["category"] == "Shopping"
    assert refund["category_source"] == "refund"
    purchase = one(conn, ref="VB-REFUND-1")
    assert links_of(conn, refund["id"])[0]["b_id"] == purchase["id"]


def test_partial_paypal_refund(conn, linked):
    refund = one(conn, ref="PP-REFUND-1")
    assert refund["role"] == "expense" and refund["category"] == "Shopping"


def test_dividend_is_income(conn, linked):
    assert one(conn, ref="FX-DIV-1")["category"] == "Kapitalerträge"


def test_depot_purchase_is_transfer_once_depot_exists(conn, linked):
    assert all(r["role"] == "expense" for r in tx(conn, text="WP-KAUF"))
    create_manual_account(conn, "flatex Depot", "depot", patterns="WP-KAUF,WP-VERKAUF")
    recompute(conn)
    assert all(r["role"] == "transfer" for r in tx(conn, text="WP-KAUF"))


def test_user_exclusion_and_category_win(conn, linked):
    rent = tx(conn, text="MIETE")[0]
    conn.execute("UPDATE transactions SET user_excluded=1 WHERE id=?", (rent["id"],))
    salary = tx(conn, text="GEHALT")[0]
    other = conn.execute("SELECT id FROM categories WHERE name='Sonstige Einnahmen'").fetchone()[0]
    conn.execute("UPDATE transactions SET user_category_id=? WHERE id=?", (other, salary["id"]))
    recompute(conn)
    assert one(conn, ref=rent["ext_id"])["role"] == "excluded"
    s = one(conn, ref=salary["ext_id"])
    assert s["category"] == "Sonstige Einnahmen" and s["category_source"] == "user"


def test_recompute_never_deletes_transactions(conn, linked):
    before = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    recompute(conn)
    recompute(conn)
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == before
    assert conn.execute("SELECT COUNT(*) FROM tx_derived").fetchone()[0] == conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE removed_at IS NULL").fetchone()[0]


# --- small cases ----------------------------------------------------------------

D = date(2026, 9, 10)
ACCS = {1: Account(1, "giro", "AT000000000000000001", (), "Max Mustermann"),
        2: Account(2, "card", "", ("PAYLIFE",), "Max Mustermann")}


def t(id, acc, amount, days=0, source="api", **kw):
    return Tx(id, acc, source, D + timedelta(days=days), amount, kw.pop("currency", "EUR"),
              kw.pop("eur", amount), **kw)


def test_wallet_notification_is_replaced_by_bank_booking():
    wallet = t(1, 2, -450, source="wallet", counterparty="Cafe Tomaselli")
    bank = t(2, 2, -450, days=2, description="CAFE TOMASELLI")
    res = link_all([wallet, bank], ACCS, {})
    assert res.roles == {1: "excluded", 2: "expense"}
    assert res.links[0].kind == "wallet"


def test_wallet_matching_window_and_fx_tolerance():
    too_late = [t(1, 2, -450, source="wallet"), t(2, 2, -450, days=11)]
    assert link_all(too_late, ACCS, {}).roles[1] == "expense"
    foreign = [t(1, 2, -1000, source="wallet", currency="GBP", eur=-1170),
               t(2, 2, -1195, days=1, eur=-1195)]            # 2.1 % off -> same payment
    assert link_all(foreign, ACCS, {}).roles[1] == "excluded"
    far = [t(1, 2, -1000, source="wallet", currency="GBP", eur=-1170), t(2, 2, -1250, days=1)]
    assert link_all(far, ACCS, {}).roles[1] == "expense"


def test_import_and_api_duplicate_is_suggested_and_confirmable():
    txs = [t(1, 1, -999, source="import"), t(2, 1, -999, days=1)]
    res = link_all(txs, ACCS, {})
    assert [(l.kind, l.status) for l in res.links] == [("duplicate", "suggested")]
    assert res.roles == {1: "expense", 2: "expense"}
    res = link_all(txs, ACCS, {("duplicate", 1, 2): "confirmed"})
    assert res.roles == {1: "excluded", 2: "expense"}
    res = link_all(txs, ACCS, {("duplicate", 1, 2): "rejected"})
    assert res.links == []


def test_owner_name_needs_two_words():
    accs = {1: Account(1, "giro", "", (), "Max")}
    res = link_all([t(1, 1, -100, counterparty="Max")], accs, {})
    assert res.roles[1] == "expense"
    res = link_all([t(1, 1, -100, counterparty="MUSTERMANN, MAX")], ACCS, {})
    assert res.roles[1] == "transfer"


def test_refund_window_and_amount():
    purchase = t(1, 1, -5000, counterparty="Zalando SE")
    late = t(2, 1, 5000, days=121, counterparty="Zalando SE")
    assert link_all([purchase, late], ACCS, {}).roles[2] == "income"
    too_big = t(3, 1, 6000, days=10, counterparty="Zalando SE")
    assert link_all([purchase, too_big], ACCS, {}).roles[3] == "income"
    ok = t(4, 1, 2000, days=10, counterparty="Zalando SE")
    assert link_all([purchase, ok], ACCS, {}).refund_of == {4: 1}


def test_merchant_key():
    assert merchant_key(t(1, 1, 1, description="MEDIAMARKT SALZBURG GUTSCHRIFT")) == "MEDIAMARKT SALZBURG"
    assert merchant_key(t(1, 1, 1, description="MEDIAMARKT SALZBURG 1234")) == "MEDIAMARKT SALZBURG"
    assert merchant_key(t(1, 1, 1, counterparty="Zalando SE", description="x")) == "ZALANDO"
