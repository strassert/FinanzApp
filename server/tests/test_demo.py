import sqlite3
from datetime import date

from finanzen.bank.fake_scenario import salary_day
from finanzen.demo import build_demo_db


def test_demo_db_is_plausible_and_invented(tmp_path):
    path = build_demo_db(tmp_path / "demo.db", today=date(2026, 9, 28))
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    first = c.execute("SELECT MIN(booking_date) FROM transactions").fetchone()[0]
    assert first <= "2024-10-05"                   # two years of history (730-day first fetch)
    salaries = [date.fromisoformat(r[0]) for r in c.execute(
        "SELECT booking_date FROM transactions WHERE description LIKE 'GEHALT%'")]
    assert all(d == salary_day(d.year, d.month) and d.weekday() < 5 for d in salaries)
    # every Zalando PayPal purchase counts once
    assert c.execute("""SELECT COUNT(*) FROM transactions t JOIN tx_derived d ON d.tx_id=t.id
                        WHERE t.description LIKE '%PP.4711.PP%' AND d.role != 'transfer'""").fetchone()[0] == 0
    # foreign spending converted with the generated rates
    assert c.execute("""SELECT COUNT(*) FROM transactions t JOIN tx_derived d ON d.tx_id=t.id
                        WHERE t.currency != 'EUR' AND d.amount_eur_minor IS NULL""").fetchone()[0] == 0
    # nothing that looks real: only the scenario's invented owner, no tokens, no hosts
    dump = "\n".join(c.iterdump())
    assert "ts.net" not in dump
    assert c.execute("SELECT COUNT(*) FROM api_tokens").fetchone()[0] == 0
    owners = {r[0] for r in c.execute("SELECT DISTINCT owner_name FROM accounts WHERE owner_name IS NOT NULL")}
    assert owners == {"Max Mustermann"}


def test_demo_amazon_orders_are_split_and_balances_consistent(tmp_path):
    from finanzen.core import reports
    path = build_demo_db(tmp_path / "demo.db", today=date(2026, 9, 28))
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    charges = c.execute("SELECT COUNT(*) FROM transactions WHERE description LIKE 'AMAZON.DE*%'").fetchone()[0]
    split = c.execute("SELECT COUNT(DISTINCT tx_id) FROM tx_splits").fetchone()[0]
    assert charges > 20 and split >= charges * 0.9
    bad = c.execute("""SELECT t.id FROM transactions t JOIN tx_derived d ON d.tx_id=t.id
                       WHERE EXISTS (SELECT 1 FROM tx_splits s WHERE s.tx_id=t.id)
                       AND d.amount_eur_minor != (SELECT SUM(amount_eur_minor) FROM tx_splits s WHERE s.tx_id=t.id)""").fetchall()
    assert bad == []
    # the giro balance reconstructs to the scenario's opening balance
    giro = c.execute("SELECT id FROM accounts WHERE institution='Volksbank Salzburg'").fetchone()[0]
    first = date.fromisoformat(c.execute("SELECT MIN(booking_date) FROM transactions WHERE account_id=?", (giro,)).fetchone()[0])
    from datetime import timedelta
    opening = reports.account_balances(c, [first - timedelta(days=1)])[giro][first - timedelta(days=1)]
    assert opening > 0
