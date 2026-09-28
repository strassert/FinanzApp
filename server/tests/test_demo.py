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
