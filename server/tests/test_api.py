import io
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from finanzen.api import create_app
from finanzen.auth import create_token, revoke_token
from finanzen.bank.fake_scenario import VOLKSBANK
from finanzen.config import Config

from .helpers import one


@pytest.fixture
def cfg(tmp_path):
    return Config(db_path=":memory:", public_url="https://finanzen.example.ts.net",
                  static_dir=str(tmp_path))


@pytest.fixture
def client(cfg, conn, linked, provider, clock):
    app = create_app(cfg, conn=conn, provider=provider, now=clock)
    token = create_token(conn, "test")
    c = app.test_client()
    c.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    c.token = token
    return c


def test_requires_token(cfg, conn, linked, provider, clock):
    c = create_app(cfg, conn=conn, provider=provider, now=clock).test_client()
    assert c.get("/api/overview").status_code == 401
    assert c.get("/api/overview", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_revoked_token_is_rejected(client, conn):
    token_id = conn.execute("SELECT id FROM api_tokens").fetchone()[0]
    revoke_token(conn, token_id)
    assert client.get("/api/status").status_code == 401


def test_home_token_sees_only_home(cfg, conn, linked, provider, clock):
    c = create_app(cfg, conn=conn, provider=provider, now=clock).test_client()
    token = create_token(conn, "ha", "home")
    assert c.get("/api/transactions", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_overview(client):
    r = client.get("/api/overview")
    assert r.status_code == 200
    data = r.get_json()
    assert data["period"]["label"] == "September 2026"
    assert data["spent"] > 0 and len(data["trend"]) == 12
    assert all("•••• " in a["iban"] for a in data["accounts"] if a["iban"])   # never a full IBAN


def test_no_full_iban_anywhere(client, conn):
    ibans = [r[0] for r in conn.execute("SELECT iban FROM accounts WHERE iban IS NOT NULL")]
    ibans += [r[0] for r in conn.execute("SELECT counterparty_iban FROM transactions WHERE counterparty_iban IS NOT NULL")]
    for url in ("/api/overview", "/api/accounts", "/api/transactions?limit=500&from=2000-01-01",
                "/api/suggestions"):
        text = client.get(url).get_data(as_text=True)
        assert not any(iban in text for iban in ibans), url


def test_transactions_filter_and_budget(client):
    data = client.get("/api/transactions").get_json()
    assert data["budget"]["period"]["label"] == "September 2026"
    assert data["total"] == len(data["items"]) or data["total"] > 100
    found = client.get("/api/transactions?q=MIETE&from=2000-01-01").get_json()
    assert found["total"] >= 6 and all("MIETE" in t["description"] for t in found["items"])


def test_set_category_note_and_rule(client, conn):
    tx_id = conn.execute("SELECT id FROM transactions WHERE description LIKE 'BILLA%' LIMIT 1").fetchone()[0]
    cat_id = conn.execute("SELECT id FROM categories WHERE name='Freizeit'").fetchone()[0]
    r = client.patch(f"/api/transactions/{tx_id}", json={"category_id": cat_id, "note": " Party ",
                                                        "rule_pattern": "BILLA"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["category"]["name"] == "Freizeit" and data["category"]["source"] == "user"
    assert data["note"] == "Party"
    other = conn.execute("""SELECT c.name FROM transactions t JOIN tx_derived d ON d.tx_id=t.id
                            JOIN categories c ON c.id=d.category_id
                            WHERE t.description LIKE 'BILLA%' AND t.id != ? LIMIT 1""", (tx_id,)).fetchone()[0]
    assert other == "Freizeit"   # via the new rule


def test_suggestion_confirm(client, conn):
    items = client.get("/api/suggestions").get_json()["items"]
    s = items[0]
    r = client.post("/api/suggestions", json={"kind": s["kind"], "a_id": s["a"]["id"],
                                              "b_id": s["b"]["id"], "decision": "confirmed"})
    assert r.status_code == 200
    assert client.get(f"/api/transactions/{s['a']['id']}").get_json()["role"] == "transfer"
    assert client.post("/api/suggestions", json={"kind": "x"}).status_code == 400


def test_manual_depot_account_and_balance(client):
    r = client.post("/api/accounts", json={"name": "flatex Depot", "kind": "depot", "patterns": "WP-KAUF"})
    aid = r.get_json()["id"]
    assert client.post(f"/api/accounts/{aid}/balance", json={"amount": 1500000}).status_code == 200
    assert client.post(f"/api/accounts/{aid}/balance", json={"amount": "15000"}).status_code == 400
    acc = next(a for a in client.get("/api/accounts").get_json()["items"] if a["id"] == aid)
    assert acc["balance_eur"] == 1500000


def test_consent_via_callback(cfg, conn, scenario, provider, fake, clock):
    app = create_app(cfg, conn=conn, provider=provider, now=clock)
    c = app.test_client()
    token = create_token(conn, "t")
    r = c.post("/api/connections", json={"institution": VOLKSBANK},
               headers={"Authorization": f"Bearer {token}"})
    url = r.get_json()["url"]
    redirect = urlparse(fake.approve(url))
    assert redirect.path == "/connect/callback"
    page = c.get(f"/connect/callback?{redirect.query}")
    assert page.status_code == 200 and "Bank verbunden" in page.get_data(as_text=True)
    again = c.get(f"/connect/callback?{redirect.query}")
    assert again.status_code == 400
    denied = c.get("/connect/callback?error=access_denied&state=x")
    assert denied.status_code == 400


def test_status_warns_before_expiry(client, clock):
    clock.advance(days=170)
    warnings = client.get("/api/status").get_json()["warnings"]
    assert any(w["kind"] == "expiring" and w["days_left"] <= 14 for w in warnings)


def test_user_sync(client):
    r = client.post("/api/sync", headers={"X-Forwarded-For": "100.101.1.2", "User-Agent": "iPhone"})
    assert r.status_code == 200
    assert {x["status"] for x in r.get_json()["results"]} == {"ok"}


def test_demo_is_read_only(cfg, conn, linked, clock):
    cfg.demo = True
    c = create_app(cfg, conn=conn, provider=None, now=clock).test_client()
    assert c.get("/api/overview").status_code == 200         # no token needed
    r = c.patch("/api/transactions/1", json={"note": "x"})
    assert r.status_code == 403 and "Demo" in r.get_json()["error"]


def test_explore_and_networth(client):
    data = client.get("/api/explore").get_json()
    assert data["sankey"]["nodes"] and len(data["timeline"]) >= 6
    points = client.get("/api/networth?range=3M").get_json()["points"]
    assert len(points) > 30


def test_static_fallback_without_build(client):
    r = client.get("/")
    assert r.status_code == 503


def test_wallet_token_can_only_post_wallet(cfg, conn, linked, provider, clock):
    c = create_app(cfg, conn=conn, provider=provider, now=clock).test_client()
    token = create_token(conn, "shortcut", "wallet")
    h = {"Authorization": f"Bearer {token}"}
    r = c.post("/api/wallet", json={"amount": "3,20 €", "merchant": "Bäckerei", "card": "PayLife Classic"}, headers=h)
    assert r.status_code == 201 and r.get_json()["status"] == "recorded"
    assert c.get("/api/overview", headers=h).status_code == 403
    assert c.get("/api/wallet", headers=h).status_code == 403


def test_unassigned_wallet_event_can_be_assigned(client, conn):
    r = client.post("/api/wallet", json={"amount": "4,00", "merchant": "Kiosk", "card": "Meine Karte"}).get_json()
    assert r["status"] == "unassigned"
    card = conn.execute("SELECT id FROM accounts WHERE institution='PayLife'").fetchone()[0]
    assert client.post(f"/api/wallet/{r['id']}/assign", json={"account_id": card, "remember": True}).status_code == 200
    assert "Meine Karte" in conn.execute("SELECT patterns FROM accounts WHERE id=?", (card,)).fetchone()[0]
    r2 = client.post("/api/wallet", json={"amount": "2,00", "merchant": "Kiosk", "card": "Meine Karte"}).get_json()
    assert r2["status"] == "recorded"


def test_import_endpoints(client, conn):
    aid = client.post("/api/accounts", json={"name": "Alte Karte", "kind": "card"}).get_json()["id"]
    data = b"Datum;Text;Betrag\n01.09.2026;BILLA;-10,00\n"
    prev = client.post("/api/import/preview", data={"account_id": str(aid), "file": (io.BytesIO(data), "x.csv")},
                       content_type="multipart/form-data")
    assert prev.status_code == 200 and prev.get_json()["count"] == 1
    import json as _json
    r = client.post("/api/import", data={"account_id": str(aid), "mapping": _json.dumps(prev.get_json()["mapping"]),
                                         "file": (io.BytesIO(data), "x.csv")}, content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["new"] == 1
    pdf = client.post("/api/import/preview", data={"account_id": str(aid), "file": (io.BytesIO(b"%PDF-1.4"), "a.pdf")},
                      content_type="multipart/form-data")
    assert pdf.status_code == 422 and "CSV" in pdf.get_json()["error"]
