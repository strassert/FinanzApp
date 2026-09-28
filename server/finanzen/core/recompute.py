"""Rebuild derived data (roles, links, categories, EUR amounts) for all
transactions. Runs after every sync, import or user change."""

from __future__ import annotations

import sqlite3
from datetime import date

from . import categories as cat
from .db import get_setting, transaction
from .fx import Rates
from .linking import Account, Tx, link_all


def load_accounts(conn: sqlite3.Connection) -> dict[int, Account]:
    return {
        r["id"]: Account(r["id"], r["kind"], r["iban"] or "",
                         tuple(p.strip() for p in (r["patterns"] or "").split(",") if p.strip()),
                         r["owner_name"] or "", r["institution"] or "")
        for r in conn.execute("SELECT * FROM accounts")
    }


def recompute(conn: sqlite3.Connection) -> dict:
    cat.seed(conn)
    rates = Rates(conn)
    categorizer = cat.Categorizer(conn)
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM transactions WHERE removed_at IS NULL ORDER BY booking_date, id")]
    txs = []
    eur: dict[int, int | None] = {}
    for r in rows:
        day = date.fromisoformat(r["booking_date"])
        eur[r["id"]] = rates.to_eur(r["amount_minor"], r["currency"], day)
        txs.append(Tx(r["id"], r["account_id"], r["source"], day, r["amount_minor"], r["currency"],
                      eur[r["id"]], r["counterparty"] or "", r["counterparty_iban"] or "",
                      r["description"] or "", bool(r["user_excluded"])))
    decisions = {(d["kind"], d["a_id"], d["b_id"]): d["decision"]
                 for d in conn.execute("SELECT * FROM link_decisions")}
    owner_setting = get_setting(conn, "owner_names", "") or ""
    result = link_all(txs, load_accounts(conn), decisions,
                      tuple(n.strip() for n in owner_setting.split(";") if n.strip()))

    derived: dict[int, tuple[str, int, str, int | None]] = {}
    for r in rows:
        role = result.roles[r["id"]]
        if r["id"] in result.refund_of:
            continue  # after purchases, below
        cat_id, source = categorizer.categorize(
            amount_minor=r["amount_minor"], text=f"{r['counterparty'] or ''} {r['description'] or ''}",
            mcc=r["mcc"], user_category_id=r["user_category_id"], is_transfer=role == "transfer")
        derived[r["id"]] = (role, cat_id, source, eur[r["id"]])
    for refund_id, purchase_id in result.refund_of.items():
        r = next(x for x in rows if x["id"] == refund_id)
        if r["user_category_id"] is not None:
            cat_id, source = r["user_category_id"], "user"
        else:
            cat_id, source = derived[purchase_id][1], "refund"
        derived[refund_id] = ("expense", cat_id, source, eur[refund_id])

    with transaction(conn):
        conn.execute("DELETE FROM tx_derived")
        conn.execute("DELETE FROM links")
        conn.executemany(
            "INSERT INTO tx_derived (tx_id, role, category_id, category_source, amount_eur_minor) "
            "VALUES (?,?,?,?,?)",
            [(tx_id, *values) for tx_id, values in derived.items()])
        conn.executemany(
            "INSERT INTO links (kind, a_id, b_id, status, evidence) VALUES (?,?,?,?,?)",
            [(l.kind, l.a_id, l.b_id, l.status, l.evidence) for l in result.links])
    return {"transactions": len(rows), "links": len(result.links),
            "suggestions": sum(1 for l in result.links if l.status == "suggested")}
