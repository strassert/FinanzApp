"""HTTP API and static web app (Flask, served by waitress)."""

from __future__ import annotations

import html
import json
import logging
import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from flask import Flask, Response, g, jsonify, request, send_from_directory

from .. import __version__, sync
from ..auth import check_token
from ..bank import BankError, BankProvider, PsuHeaders
from ..config import Config
from ..core import db as core_db
from ..core import forecast, importer, queries, recurring, reports, wallet
from ..core.recompute import recompute
from ..core.store import create_manual_account, store_balance

log = logging.getLogger(__name__)

EXPIRY_WARNING_DAYS = 14


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def create_app(cfg: Config, conn: Optional[sqlite3.Connection] = None,
               provider: Optional[BankProvider] = None,
               now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
    app.config["CFG"] = cfg
    conn = conn or core_db.connect(cfg.db_path)
    if conn.execute("SELECT 1 FROM tx_derived WHERE budget_date IS NULL LIMIT 1").fetchone():
        recompute(conn)               # derived data from before migration 004
    lock = threading.RLock()          # one SQLite connection, serialised access

    def today() -> date:
        return now().date()

    # --- plumbing -----------------------------------------------------------------

    @app.before_request
    def _auth():
        g.conn = conn
        lock.acquire()
        g.locked = True
        path = request.path
        if not path.startswith("/api/"):
            return None
        if cfg.demo:
            g.scope = "demo"
            if request.method not in ("GET", "HEAD"):
                raise ApiError(403, "In der Demo-Version nicht möglich.")
            return None
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else None
        g.scope = check_token(conn, token)
        if g.scope is None:
            raise ApiError(401, "Nicht gekoppelt oder Token ungültig.")
        if g.scope == "home" and path != "/api/home":
            raise ApiError(403, "Token ohne Berechtigung.")
        if g.scope == "wallet" and not (path == "/api/wallet" and request.method == "POST"):
            raise ApiError(403, "Token ohne Berechtigung.")
        return None

    @app.teardown_request
    def _release(exc):
        if g.pop("locked", False):
            lock.release()

    @app.errorhandler(ApiError)
    def _api_error(exc: ApiError):
        return jsonify({"error": exc.message}), exc.status

    @app.errorhandler(BankError)
    def _bank_error(exc: BankError):
        log.warning("bank error: %s (%s)", type(exc).__name__, exc.code)
        return jsonify({"error": "Die Bank hat die Anfrage abgelehnt.", "code": exc.code}), 502

    @app.after_request
    def _headers(resp: Response):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def body() -> dict:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ApiError(400, "JSON-Objekt erwartet.")
        return data

    def int_list(name: str) -> list[int]:
        raw = request.args.get(name, "")
        try:
            return [int(x) for x in raw.split(",") if x.strip()]
        except ValueError:
            raise ApiError(400, f"{name}: Zahlen erwartet.")

    def parse_date(value: Optional[str]) -> Optional[date]:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ApiError(400, "Datum im Format JJJJ-MM-TT erwartet.")

    def period_from_args():
        cal = reports.calendar(conn)
        key = request.args.get("period")
        if key:
            try:
                year, month = (int(x) for x in key.split("-"))
                return cal.period(year, month)
            except ValueError:
                raise ApiError(400, "period im Format JJJJ-MM erwartet.")
        return cal.period_for(today())

    def require_provider() -> BankProvider:
        if provider is None:
            raise ApiError(503, "Kein Bankzugang konfiguriert.")
        return provider

    # --- status -------------------------------------------------------------------

    @app.get("/api/status")
    def status():
        warnings = []
        for c in conn.execute("SELECT * FROM connections ORDER BY id"):
            if c["status"] == "expired":
                warnings.append({"connection_id": c["id"], "institution": c["institution"],
                                 "kind": "expired"})
            elif c["valid_until"]:
                left = (datetime.fromisoformat(c["valid_until"]) - now()).days
                if left <= EXPIRY_WARNING_DAYS:
                    warnings.append({"connection_id": c["id"], "institution": c["institution"],
                                     "kind": "expiring", "days_left": max(0, left)})
            if c["last_error"] and c["status"] != "expired":
                warnings.append({"connection_id": c["id"], "institution": c["institution"],
                                 "kind": c["last_error"], "paused_until": c["paused_until"]})
        last = conn.execute("SELECT MAX(last_sync_at) FROM connections").fetchone()[0]
        return jsonify({
            "version": __version__, "demo": cfg.demo, "today": today().isoformat(),
            "last_sync_at": last, "warnings": warnings,
            "suggestions": conn.execute("SELECT COUNT(*) FROM links WHERE status='suggested'").fetchone()[0],
            "unassigned_wallet": conn.execute(
                "SELECT COUNT(*) FROM wallet_events WHERE status='unassigned'").fetchone()[0],
        })

    # --- figures --------------------------------------------------------------------

    @app.get("/api/overview")
    def overview():
        period = period_from_args()
        data = reports.overview(conn, period, today(), int_list("accounts"))
        data["accounts"] = reports.accounts_summary(conn, today())
        return jsonify(data)

    @app.get("/api/periods")
    def periods():
        cal = reports.calendar(conn)
        first, last = conn.execute("SELECT MIN(budget_date), MAX(budget_date) FROM tx_derived").fetchone()
        start = date.fromisoformat(first) if first else today()
        # a salary booked at the end of the month already opens the next one
        end = max(today(), date.fromisoformat(last)) if last else today()
        items = [reports.period_dict(p) for p in cal.range(start, end)]
        return jsonify({"current": reports.period_dict(cal.period_for(today())), "items": items[::-1]})

    @app.get("/api/networth")
    def networth():
        return jsonify({"range": request.args.get("range", "1J"),
                        "points": reports.net_worth_series(conn, today(), request.args.get("range", "1J"))})

    @app.get("/api/explore")
    def explore():
        start = parse_date(request.args.get("from"))
        end = parse_date(request.args.get("to"))
        cal = reports.calendar(conn)
        if not start or not end:
            p = cal.previous(cal.period_for(today()))
            start, end = p.start, p.end
        first = conn.execute("SELECT MIN(booking_date) FROM transactions").fetchone()[0]
        timeline = []
        if first:
            for p in cal.range(date.fromisoformat(first), today()):
                s = reports.sums(conn, p.start, p.end)
                timeline.append({**reports.period_dict(p), "spent": s.spent, "income": s.income})
        return jsonify({"sankey": reports.sankey(conn, start, end), "timeline": timeline})

    @app.get("/api/forecast")
    def forecast_view():
        return jsonify(forecast.forecast(conn, today()))

    @app.get("/api/recurring")
    def recurring_list():
        return jsonify(recurring.overview(conn, today()))

    @app.post("/api/recurring/decision")
    def recurring_decide():
        data = body()
        key = data.get("key")
        if not isinstance(key, str) or not key:
            raise ApiError(400, "key fehlt.")
        try:
            recurring.decide(conn, key, data.get("decision"))
        except ValueError:
            raise ApiError(400, "Ungültige Entscheidung.")
        return jsonify(recurring.overview(conn, today()))

    # --- transactions -----------------------------------------------------------------

    @app.get("/api/transactions")
    def transactions():
        start, end = parse_date(request.args.get("from")), parse_date(request.args.get("to"))
        budget = None
        if request.args.get("period") or not (start or end or request.args.get("q")):
            period = period_from_args()
            start, end = period.start, period.end
            ov_sums = reports.sums(conn, start, end, int_list("accounts"))
            budget = reports.budget(conn, period, today(), ov_sums, int_list("accounts"))
        try:
            limit = min(500, int(request.args.get("limit", 100)))
            offset = int(request.args.get("offset", 0))
        except ValueError:
            raise ApiError(400, "limit/offset: Zahlen erwartet.")
        category = request.args.get("category")
        data = queries.list_transactions(
            conn, start=start, end=end, account_ids=int_list("accounts"),
            category_id=int(category) if category and category.isdigit() else None,
            role=request.args.get("role") or None, query=request.args.get("q") or None,
            limit=limit, offset=offset)
        data["budget"] = budget
        return jsonify(data)

    @app.get("/api/transactions/<int:tx_id>")
    def transaction_detail(tx_id: int):
        data = queries.get_transaction(conn, tx_id)
        if data is None:
            raise ApiError(404, "Umsatz nicht gefunden.")
        return jsonify(data)

    @app.patch("/api/transactions/<int:tx_id>")
    def transaction_update(tx_id: int):
        if queries.get_transaction(conn, tx_id) is None:
            raise ApiError(404, "Umsatz nicht gefunden.")
        changes = {k: v for k, v in body().items()
                   if k in ("category_id", "note", "excluded", "rule_pattern")}
        with core_db.transaction(conn):
            queries.update_transaction(conn, tx_id, changes)
        recompute(conn)
        return jsonify(queries.get_transaction(conn, tx_id))

    # --- suggestions ----------------------------------------------------------------

    @app.get("/api/suggestions")
    def suggestion_list():
        return jsonify({"items": queries.suggestions(conn)})

    @app.post("/api/suggestions")
    def suggestion_decide():
        data = body()
        try:
            queries.decide(conn, data.get("kind"), int(data["a_id"]), int(data["b_id"]), data.get("decision"))
        except (KeyError, TypeError, ValueError):
            raise ApiError(400, "Ungültige Entscheidung.")
        recompute(conn)
        return jsonify({"ok": True})

    # --- categories and rules -------------------------------------------------------

    @app.get("/api/categories")
    def categories():
        return jsonify({"items": queries.list_categories(conn), "rules": queries.list_rules(conn)})

    @app.post("/api/categories")
    def category_create():
        data = body()
        name = (data.get("name") or "").strip()
        kind = data.get("kind", "expense")
        if not name or kind not in ("expense", "income"):
            raise ApiError(400, "Name und Art (expense/income) angeben.")
        slot = conn.execute("SELECT COALESCE(MAX(color_slot), -1) + 1 FROM categories").fetchone()[0]
        sort = conn.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM categories").fetchone()[0]
        try:
            cid = conn.execute("INSERT INTO categories (name, kind, color_slot, sort) VALUES (?,?,?,?)",
                               (name, kind, slot if kind == "expense" else None, sort)).lastrowid
        except sqlite3.IntegrityError:
            raise ApiError(409, "Kategorie existiert bereits.")
        return jsonify({"id": cid}), 201

    @app.post("/api/rules")
    def rule_create():
        data = body()
        pattern = (data.get("pattern") or "").strip()
        if len(pattern) < 3 or not isinstance(data.get("category_id"), int):
            raise ApiError(400, "Muster (mind. 3 Zeichen) und Kategorie angeben.")
        from ..core.categories import add_rule
        rid = add_rule(conn, pattern, data["category_id"])
        recompute(conn)
        return jsonify({"id": rid}), 201

    @app.delete("/api/rules/<int:rule_id>")
    def rule_delete(rule_id: int):
        conn.execute("DELETE FROM category_rules WHERE id=?", (rule_id,))
        recompute(conn)
        return jsonify({"ok": True})

    # --- accounts and connections -----------------------------------------------------

    @app.get("/api/accounts")
    def accounts():
        items = reports.accounts_summary(conn, today())
        hidden = [dict(id=r["id"], name=r["name"]) for r in conn.execute("SELECT id, name FROM accounts WHERE hidden=1")]
        conns = []
        for c in conn.execute("SELECT * FROM connections ORDER BY id"):
            conns.append({"id": c["id"], "institution": c["institution"], "status": c["status"],
                          "valid_until": c["valid_until"], "last_sync_at": c["last_sync_at"],
                          "last_error": c["last_error"], "paused_until": c["paused_until"]})
        return jsonify({"items": items, "hidden": hidden, "connections": conns})

    @app.post("/api/accounts")
    def account_create():
        data = body()
        name = (data.get("name") or "").strip()
        kind = data.get("kind", "other")
        if not name or kind not in ("depot", "savings", "card", "other"):
            raise ApiError(400, "Name und Art angeben.")
        aid = create_manual_account(conn, name, kind, data.get("currency", "EUR"),
                                    patterns=data.get("patterns", ""))
        return jsonify({"id": aid}), 201

    @app.patch("/api/accounts/<int:account_id>")
    def account_update(account_id: int):
        data = body()
        fields = {k: data[k] for k in ("name", "patterns", "hidden") if k in data}
        if not fields:
            raise ApiError(400, "Nichts zu ändern.")
        if "name" in fields and not str(fields["name"]).strip():
            raise ApiError(400, "Name darf nicht leer sein.")
        if "hidden" in fields:
            fields["hidden"] = int(bool(fields["hidden"]))
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE accounts SET {sets} WHERE id=?", [*fields.values(), account_id])
        recompute(conn)
        return jsonify({"ok": True})

    @app.post("/api/accounts/<int:account_id>/balance")
    def account_balance(account_id: int):
        data = body()
        acc = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if acc is None or acc["source"] == "api":
            raise ApiError(400, "Saldo nur für Konten ohne Bankanbindung eintragbar.")
        if not isinstance(data.get("amount"), int):
            raise ApiError(400, "Betrag in Cent angeben.")
        store_balance(conn, account_id, data["amount"], acc["currency"], "MANUAL",
                      parse_date(data.get("date")) or today())
        return jsonify({"ok": True})

    @app.get("/api/institutions")
    def institutions():
        items = require_provider().list_institutions(cfg.country)
        return jsonify({"items": [{"name": i.name, "country": i.country,
                                   "max_consent_days": i.max_consent_days} for i in items]})

    @app.post("/api/connections")
    def connection_start():
        data = body()
        name = data.get("institution")
        if not name:
            raise ApiError(400, "Bank angeben.")
        url = sync.start_consent(conn, require_provider(), name, data.get("country", cfg.country),
                                 cfg.redirect_url, renew_connection_id=data.get("renew_connection_id"),
                                 max_days=data.get("max_consent_days"), now=now)
        return jsonify({"url": url})

    @app.post("/api/sync")
    def sync_now():
        psu = PsuHeaders(
            (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip(),
            request.headers.get("User-Agent", ""))
        results = sync.sync_all(conn, require_provider(), trigger="user", psu=psu, now=now)
        return jsonify({"results": [{"connection_id": r.connection_id, "status": r.status,
                                     "new": r.new_count, "message": r.message} for r in results]})

    # --- file import (F1) ---------------------------------------------------------------

    def upload() -> tuple[bytes, int]:
        file = request.files.get("file")
        try:
            account_id = int(request.form.get("account_id", ""))
        except ValueError:
            raise ApiError(400, "Konto angeben.")
        if file is None:
            raise ApiError(400, "Keine Datei.")
        if conn.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone() is None:
            raise ApiError(404, "Konto nicht gefunden.")
        return file.read(), account_id

    @app.post("/api/import/preview")
    def import_preview():
        data, account_id = upload()
        try:
            return jsonify(importer.preview(conn, data, account_id))
        except importer.ImportError_ as exc:
            raise ApiError(422, str(exc))

    @app.post("/api/import")
    def import_run():
        data, account_id = upload()
        try:
            mapping = json.loads(request.form.get("mapping", "{}"))
            with core_db.transaction(conn):
                result = importer.run_import(conn, data, account_id, mapping, today=today())
        except (importer.ImportError_, ValueError, TypeError, KeyError) as exc:
            raise ApiError(422, str(exc) if isinstance(exc, importer.ImportError_) else "Ungültige Zuordnung.")
        recompute(conn)
        return jsonify(result)

    # --- Apple Pay notifications (F9) ------------------------------------------------------

    @app.post("/api/wallet")
    def wallet_record():
        data = body()
        result = wallet.record(conn, amount=str(data.get("amount", "")), merchant=str(data.get("merchant", "")),
                               card=str(data.get("card", "")), currency=data.get("currency") or None,
                               when=now())
        if result["status"] == "recorded":
            recompute(conn)
        return jsonify(result), 201 if result["status"] == "recorded" else 200

    @app.get("/api/wallet")
    def wallet_list():
        rows = conn.execute("""SELECT id, occurred_at, amount_minor, currency, merchant, card, status, reason
                               FROM wallet_events ORDER BY id DESC LIMIT 50""").fetchall()
        return jsonify({"items": [dict(r) for r in rows]})

    @app.post("/api/wallet/<int:event_id>/assign")
    def wallet_assign(event_id: int):
        data = body()
        ev = conn.execute("SELECT * FROM wallet_events WHERE id=? AND status='unassigned'", (event_id,)).fetchone()
        if ev is None or ev["amount_minor"] is None:
            raise ApiError(404, "Meldung nicht gefunden.")
        account = conn.execute("SELECT id, patterns FROM accounts WHERE id=?", (data.get("account_id"),)).fetchone()
        if account is None:
            raise ApiError(400, "Konto angeben.")
        if data.get("remember") and ev["card"]:
            patterns = ",".join(p for p in [account["patterns"], ev["card"]] if p)
            conn.execute("UPDATE accounts SET patterns=? WHERE id=?", (patterns, account["id"]))
        conn.execute("UPDATE wallet_events SET status='reassigned' WHERE id=?", (event_id,))
        amount = f"{-ev['amount_minor'] / 100:.2f}"
        result = wallet.record(conn, amount=amount, merchant=ev["merchant"] or "", card=ev["card"] or "",
                               currency=ev["currency"], when=datetime.fromisoformat(ev["occurred_at"]))
        if result["status"] != "recorded":
            # the card still does not match: book directly on the chosen account
            from ..core.store import NewTx, upsert_transactions
            when = datetime.fromisoformat(ev["occurred_at"])
            upsert_transactions(conn, account["id"], "wallet", [NewTx(
                booking_date=when.astimezone(wallet.LOCAL_TZ).date(), amount_minor=ev["amount_minor"],
                currency=ev["currency"], status="pending", ext_ref=f"wallet:{ev['occurred_at']}:{ev['amount_minor']}",
                counterparty=ev["merchant"], description="Apple Pay", apple_pay=True, card=ev["card"])])
        recompute(conn)
        return jsonify({"ok": True})

    # --- consent callback (opened by the bank in the browser) ----------------------------

    @app.get("/connect/callback")
    def connect_callback():
        state, code = request.args.get("state"), request.args.get("code")
        if request.args.get("error") or not state or not code:
            if state:
                conn.execute("DELETE FROM pending_consents WHERE state=?", (state,))
            return _page("Verbindung abgebrochen",
                         "Die Bank hat keine Zustimmung erteilt. Du kannst es in der App erneut versuchen."), 400
        try:
            sync.complete_consent(conn, require_provider(), state, code, now=now)
        except sync.ConsentStateError:
            return _page("Link abgelaufen", "Bitte starte die Verbindung in der App neu."), 400
        except BankError as exc:
            log.warning("consent failed: %s", type(exc).__name__)
            return _page("Verbindung fehlgeschlagen", "Die Bank hat die Zustimmung nicht bestätigt."), 502
        return _page("Bank verbunden",
                     "Die Umsätze werden geladen. Du kannst dieses Fenster schließen und zur App zurückkehren.",
                     link="/#/konten")

    # --- static web app -------------------------------------------------------------

    static_dir = Path(cfg.static_dir)

    @app.get("/")
    @app.get("/<path:path>")
    def static_files(path: str = "index.html"):
        if path.startswith("api/"):
            raise ApiError(404, "Unbekannte Adresse.")
        target = static_dir / path
        if not target.is_file():
            path = "index.html"
        if not (static_dir / path).is_file():
            return _page("Finanzen", "Die Web-App ist noch nicht gebaut (web/: npm run build)."), 503
        resp = send_from_directory(static_dir, path)
        if path in ("index.html", "sw.js", "manifest.webmanifest"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    return app


def _page(title: str, text: str, link: Optional[str] = None) -> str:
    button = f'<p><a href="{html.escape(link)}">Zur App</a></p>' if link else ""
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title>
<style>body{{font:17px/1.5 -apple-system,system-ui,sans-serif;margin:0;padding:48px 24px;
background:#f6f5f1;color:#1f2a24}}@media (prefers-color-scheme:dark){{body{{background:#141816;color:#e7ebe8}}}}
h1{{font-size:24px}}a{{color:#3f7a5c}}</style></head><body><h1>{html.escape(title)}</h1>
<p>{html.escape(text)}</p>{button}</body></html>"""
