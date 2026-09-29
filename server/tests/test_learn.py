import pytest

from finanzen.core import queries
from finanzen.core.categories import ids_by_name, merchant_key
from finanzen.core.learn import Example, Learner
from finanzen.core.recompute import recompute

from .helpers import tx


def ex(payee, cat, sign="-"):
    return Example(f"{sign}:{payee.upper()}", payee, cat)


def test_same_merchant_uses_majority():
    learner = Learner([ex("Trafik Mayr", 1), ex("Trafik Mayr", 1), ex("Trafik Mayr", 2)])
    assert learner.same_merchant("-:TRAFIK MAYR").category_id == 1
    assert learner.same_merchant("+:TRAFIK MAYR") is None                  # other direction
    tie = Learner([ex("Trafik Mayr", 1), ex("Trafik Mayr", 2)])
    assert tie.same_merchant("-:TRAFIK MAYR") is None


def test_distinctive_word_from_another_merchant():
    learner = Learner([ex("Tabak Trafik Linzergasse", 6)])
    guess = learner.by_word("-:TRAFIK MAYR", "TRAFIK MAYR 5020")
    assert guess.category_id == 6 and guess.hint == "Tabak Trafik Linzergasse"
    assert learner.by_word("+:TRAFIK MAYR", "TRAFIK MAYR") is None          # income is learned apart


def test_common_words_and_disagreement_decide_nothing():
    places = [ex(f"Parkgarage {i} Salzburg", 4) for i in range(3)]
    other = [("-:SHOP " + str(i), f"Laden {i} Salzburg") for i in range(5)]
    learner = Learner(places, other)
    assert learner.by_word("-:BUCHHANDLUNG SALZBURG", "Buchhandlung Salzburg") is None   # SALZBURG too common
    mixed = Learner([ex("Tabak Trafik", 6), ex("Trafik Zeitungen", 5)])
    assert mixed.by_word("-:TRAFIK MAYR", "Trafik Mayr") is None           # TRAFIK in two categories
    two = Learner([ex("Tabak Linzergasse", 6), ex("Mayr Zeitungen", 5)])
    assert two.by_word("-:TABAK MAYR", "Tabak Mayr") is None               # two words disagree


def test_stop_words_and_short_words_are_ignored():
    learner = Learner([ex("Zahlung an Hofbauer GmbH", 3)])
    assert learner.by_word("-:ZAHLUNG AN X GMBH", "Zahlung an X GmbH") is None


# --- recompute with the fake bank --------------------------------------------------

def kino(conn):
    return tx(conn, text="KINO CITYPLEXX")


def test_user_choice_is_learned_for_the_same_merchant(conn, linked):
    rows = kino(conn)
    assert len(rows) >= 2 and all(r["category"] == "Freizeit" for r in rows)   # keyword
    shopping = ids_by_name(conn)["Shopping"]
    conn.execute("UPDATE transactions SET user_category_id=? WHERE id=?", (shopping, rows[0]["id"]))
    recompute(conn)
    rows = kino(conn)
    assert rows[0]["category_source"] == "user"
    assert {(r["category"], r["category_source"]) for r in rows[1:]} == {("Shopping", "learned")}
    assert rows[1]["merchant_key"] == merchant_key(-1, "", "KINO CITYPLEXX")
    [item] = [i for i in queries.review(conn) if i["key"] == rows[1]["merchant_key"]]
    assert item["category"]["name"] == "Shopping" and item["source"] == "learned"
    assert item["count"] == len(rows) - 1


def test_confirmed_merchant_survives_recompute_and_leaves_review(conn, linked):
    key = merchant_key(-1, "", "KINO CITYPLEXX")
    reisen = ids_by_name(conn)["Reisen"]
    queries.decide_merchant(conn, key, reisen)
    recompute(conn)
    recompute(conn)
    assert {(r["category"], r["category_source"]) for r in kino(conn)} == {("Reisen", "confirmed")}
    assert key not in {i["key"] for i in queries.review(conn)}


def test_rules_and_own_choice_still_win(conn, linked):
    from finanzen.core.categories import add_rule
    ids = ids_by_name(conn)
    queries.decide_merchant(conn, merchant_key(-1, "", "KINO CITYPLEXX"), ids["Reisen"])
    add_rule(conn, "CITYPLEXX", ids["Gesundheit & Drogerie"])
    recompute(conn)
    assert {r["category_source"] for r in kino(conn)} == {"rule"}


def test_merchant_decision_checks_direction(conn, linked):
    ids = ids_by_name(conn)
    with pytest.raises(ValueError):
        queries.decide_merchant(conn, "-:KINO CITYPLEXX", ids["Gehalt"])      # income category for money out
    with pytest.raises(ValueError):
        queries.decide_merchant(conn, "KINO", ids["Freizeit"])
