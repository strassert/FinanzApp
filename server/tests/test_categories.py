import pytest

from finanzen.core import categories as cat


@pytest.fixture
def categorizer(conn):
    cat.seed(conn)
    return cat.Categorizer(conn)


def name(conn, cid):
    return conn.execute("SELECT name FROM categories WHERE id=?", (cid,)).fetchone()[0]


def test_seed_is_idempotent(conn):
    cat.seed(conn)
    cat.seed(conn)
    assert conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == len(cat.BUILTIN)


@pytest.mark.parametrize("text,mcc,expected", [
    ("BILLA DANKT 4711 SALZBURG", None, "Lebensmittel"),
    ("SPAR FIL. 5020", None, "Lebensmittel"),
    ("OEBB TICKET SHOP", None, "Mobilität"),
    ("Zahlung an Zalando SE", None, "Shopping"),
    ("SOMETHING UNKNOWN", "5812", "Restaurant & Café"),
    ("SOMETHING UNKNOWN", "5541", "Mobilität"),
    ("SOMETHING UNKNOWN", None, "Sonstiges"),
    ("SOMETHING UNKNOWN", "abc", "Sonstiges"),
])
def test_expense_keywords_and_mcc(conn, categorizer, text, mcc, expected):
    cid, _ = categorizer.categorize(amount_minor=-100, text=text, mcc=mcc)
    assert name(conn, cid) == expected


def test_keywords_match_whole_words(conn, categorizer):
    cid, source = categorizer.categorize(amount_minor=-100, text="SPARPLAN FONDS", mcc=None)
    assert name(conn, cid) == "Sonstiges" and source == "default"


def test_income_categories(conn, categorizer):
    cid, _ = categorizer.categorize(amount_minor=100, text="GEHALT 09/2026", mcc=None)
    assert name(conn, cid) == "Gehalt"
    cid, _ = categorizer.categorize(amount_minor=100, text="BILLA", mcc="5411")
    assert name(conn, cid) == "Sonstige Einnahmen"   # grocery keywords do not apply to income


def test_precedence(conn):
    cat.seed(conn)
    ids = cat.ids_by_name(conn)
    cat.add_rule(conn, "billa", ids["Freizeit"])
    c = cat.Categorizer(conn)
    text = "BILLA DANKT"
    assert c.categorize(amount_minor=-1, text=text, mcc="5411")[1] == "rule"
    assert c.categorize(amount_minor=-1, text=text, mcc=None, is_transfer=True) == (ids["Umbuchung"], "transfer")
    assert c.categorize(amount_minor=-1, text=text, mcc=None, user_category_id=ids["Reisen"],
                        is_transfer=True) == (ids["Reisen"], "user")


def test_latest_rule_wins(conn):
    cat.seed(conn)
    ids = cat.ids_by_name(conn)
    cat.add_rule(conn, "AMAZON", ids["Shopping"])
    cat.add_rule(conn, "AMAZON PRIME", ids["Abos & Digitales"])
    c = cat.Categorizer(conn)
    assert c.categorize(amount_minor=-1, text="AMAZON PRIME MEMBERSHIP", mcc=None)[0] == ids["Abos & Digitales"]


def test_expense_categories_have_stable_color_slots(conn):
    cat.seed(conn)
    rows = conn.execute("SELECT name, color_slot FROM categories WHERE kind='expense' ORDER BY sort").fetchall()
    assert [r[1] for r in rows] == list(range(len(rows)))
    assert rows[0][0] == "Lebensmittel"
