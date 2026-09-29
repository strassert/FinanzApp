import json
import re
from types import SimpleNamespace

from finanzen.core import ai, queries
from finanzen.core.recompute import recompute

from .helpers import tx


class FakeClient:
    """Stands in for anthropic.Anthropic: answers from a function of the sent items."""

    def __init__(self, answer):
        self.answer = answer
        self.requests = []
        self.messages = self

    def create(self, **kw):
        self.requests.append(kw)
        items = json.loads(kw["messages"][0]["content"].split("Händler:\n", 1)[1])
        results = [{"id": it["id"], "category": self.answer(it)} for it in items]
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps({"results": results}))])


class Broken:
    messages = property(lambda self: self)

    def create(self, **kw):
        raise ConnectionError("offline")


def test_clean_and_private_person():
    assert ai.clean("SPAR DANKT 4711 KARTE 1234567890") == "SPAR DANKT KARTE"
    assert ai.clean("AT611904300234573201 Miete") == "Miete"
    assert ai.looks_private("Anna Huber", "AT611904300234573201")
    assert not ai.looks_private("Salzburg AG", "AT611904300234573201")
    assert not ai.looks_private("", None)                               # card payment, no IBAN


def test_candidates_are_unknown_expenses_only(conn, linked):
    items = ai.candidates(conn)
    keys = {c["key"] for c in items}
    assert keys and all(k.startswith("-:") for k in keys)             # never income
    known = {r["merchant_key"] for r in conn.execute(
        "SELECT merchant_key FROM tx_derived WHERE category_source IN ('keyword','rule','user','transfer')")}
    assert not keys & known
    assert all(set(c) == {"key", "text", "mcc"} for c in items)


def test_run_stores_answers_and_recompute_uses_them(conn, linked):
    first = ai.candidates(conn)[0]
    client = FakeClient(lambda it: "Freizeit" if it["id"] == 0 else ai.UNSURE)
    found = ai.run(conn, client)
    assert found == 1
    stored = dict(conn.execute("SELECT key, category_id FROM ai_categories").fetchall())
    assert stored[first["key"]] is not None and sum(v is None for v in stored.values()) == len(stored) - 1
    recompute(conn)
    rows = [r for r in tx(conn) if r["merchant_key"] == first["key"]]
    assert {(r["category"], r["category_source"]) for r in rows} == {("Freizeit", "ai")}
    assert any(i["key"] == first["key"] and i["source"] == "ai" for i in queries.review(conn))
    assert ai.candidates(conn) == []                                   # unsure ones are not asked again
    assert ai.run(conn, client) == 0 and len(client.requests) == 1


def test_request_contains_no_amounts_or_ibans(conn, linked):
    client = FakeClient(lambda it: ai.UNSURE)
    ai.run(conn, client)
    sent = json.dumps(client.requests, ensure_ascii=False)
    assert client.requests[0]["model"] == ai.MODEL
    items = json.loads(client.requests[0]["messages"][0]["content"].split("Händler:\n", 1)[1])
    assert items and all(set(it) <= {"id", "text", "mcc"} for it in items)
    assert not any(re.search(r"\d{4,}", it["text"]) for it in items)     # MCC is the only number
    assert "amount" not in sent and "iban" not in sent.lower()


def test_keyword_beats_model_and_model_beats_mcc(conn, linked):
    from finanzen.core.categories import merchant_key
    keyword = merchant_key(-1, "", "BILLA DANKT")
    mcc_only = next(r["merchant_key"] for r in tx(conn) if r["category_source"] == "mcc")
    for key in (keyword, mcc_only):
        conn.execute("INSERT INTO ai_categories (key, category_id, model, created_at) "
                     "SELECT ?, id, 'test', 'now' FROM categories WHERE name='Reisen'", (key,))
    recompute(conn)
    assert {r["category_source"] for r in tx(conn) if r["merchant_key"] == mcc_only} == {"ai"}
    assert all(r["category_source"] == "keyword" for r in tx(conn, text="BILLA"))


def test_failures_never_break_the_sync(conn, linked, tmp_path):
    assert ai.run_safely(conn, str(tmp_path / "missing.key")) is None
    assert ai.run_safely(conn, "x", make_client=lambda path: Broken()) is None
    empty = tmp_path / "empty.key"
    empty.write_text("\n")
    assert ai.client_from_key_file(empty) is None
