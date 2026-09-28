"""Read/write helpers for the API: transaction list, detail, edits, suggestions."""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Optional

from . import categories as cat
from .db import utcnow
from .reports import mask_iban

TX_SELECT = """
    SELECT t.id, t.account_id, t.source, t.status, t.booking_date, t.value_date, t.amount_minor,
           t.currency, t.original_amount_minor, t.original_currency, t.counterparty,
           t.counterparty_iban, t.description, t.mcc, t.apple_pay, t.card, t.note,
           t.user_category_id, t.user_excluded,
           d.role, d.category_id, d.category_source, d.amount_eur_minor,
           c.name AS category_name, c.color_slot AS category_slot, c.kind AS category_kind,
           a.name AS account_name, a.kind AS account_kind, a.color_slot AS account_slot
    FROM transactions t
    JOIN tx_derived d ON d.tx_id = t.id
    JOIN accounts a ON a.id = t.account_id
    LEFT JOIN categories c ON c.id = d.category_id
"""


def _tx_json(r: sqlite3.Row, links: Optional[list] = None) -> dict:
    return {
        "id": r["id"], "date": r["booking_date"], "status": r["status"], "source": r["source"],
        "amount": r["amount_minor"], "currency": r["currency"], "amount_eur": r["amount_eur_minor"],
        "original_amount": r["original_amount_minor"], "original_currency": r["original_currency"],
        "counterparty": r["counterparty"], "description": r["description"],
        "counterparty_iban": mask_iban(r["counterparty_iban"]),
        "mcc": r["mcc"], "apple_pay": bool(r["apple_pay"]), "note": r["note"],
        "role": r["role"], "excluded_by_user": bool(r["user_excluded"]),
        "category": {"id": r["category_id"], "name": r["category_name"], "color_slot": r["category_slot"],
                     "source": r["category_source"], "kind": r["category_kind"]},
        "account": {"id": r["account_id"], "name": r["account_name"], "kind": r["account_kind"],
                    "color_slot": r["account_slot"]},
        "links": links or [],
    }


def list_transactions(conn: sqlite3.Connection, *, start: Optional[date] = None,
                      end: Optional[date] = None, account_ids: Optional[list[int]] = None,
                      category_id: Optional[int] = None, role: Optional[str] = None,
                      query: Optional[str] = None, limit: int = 100, offset: int = 0) -> dict:
    where, args = ["1=1"], []
    if start:
        where.append("t.booking_date >= ?")
        args.append(start.isoformat())
    if end:
        where.append("t.booking_date <= ?")
        args.append(end.isoformat())
    if account_ids:
        where.append(f"t.account_id IN ({','.join('?' * len(account_ids))})")
        args += account_ids
    if category_id:
        where.append("d.category_id = ?")
        args.append(category_id)
    if role:
        where.append("d.role = ?")
        args.append(role)
    if query:
        where.append("(t.description LIKE ? OR t.counterparty LIKE ? OR t.note LIKE ?)")
        args += [f"%{query}%"] * 3
    sql_where = " WHERE " + " AND ".join(where)
    total = conn.execute(
        "SELECT COUNT(*) FROM transactions t JOIN tx_derived d ON d.tx_id=t.id "
        "JOIN accounts a ON a.id=t.account_id" + sql_where, args).fetchone()[0]
    rows = conn.execute(TX_SELECT + sql_where +
                        " ORDER BY t.booking_date DESC, t.id DESC LIMIT ? OFFSET ?",
                        args + [limit, offset]).fetchall()
    ids = [r["id"] for r in rows]
    link_map = _links_for(conn, ids)
    return {"total": total, "items": [_tx_json(r, link_map.get(r["id"])) for r in rows]}


def _links_for(conn: sqlite3.Connection, ids: list[int]) -> dict[int, list]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    out: dict[int, list] = {}
    for l in conn.execute(f"SELECT * FROM links WHERE a_id IN ({marks}) OR b_id IN ({marks})", ids + ids):
        for own, other in ((l["a_id"], l["b_id"]), (l["b_id"], l["a_id"])):
            if own in ids:
                out.setdefault(own, []).append({"kind": l["kind"], "status": l["status"],
                                                "evidence": l["evidence"], "other_id": other,
                                                "a_id": l["a_id"], "b_id": l["b_id"]})
    return out


def get_transaction(conn: sqlite3.Connection, tx_id: int) -> Optional[dict]:
    row = conn.execute(TX_SELECT + " WHERE t.id = ?", (tx_id,)).fetchone()
    if row is None:
        return None
    data = _tx_json(row, _links_for(conn, [tx_id]).get(tx_id))
    for link in data["links"]:
        if link["other_id"]:
            other = conn.execute(TX_SELECT + " WHERE t.id = ?", (link["other_id"],)).fetchone()
            link["other"] = _tx_json(other) if other else None
    return data


def update_transaction(conn: sqlite3.Connection, tx_id: int, changes: dict) -> None:
    if "category_id" in changes:
        conn.execute("UPDATE transactions SET user_category_id=? WHERE id=?", (changes["category_id"], tx_id))
    if "note" in changes:
        conn.execute("UPDATE transactions SET note=? WHERE id=?", ((changes["note"] or "").strip() or None, tx_id))
    if "excluded" in changes:
        conn.execute("UPDATE transactions SET user_excluded=? WHERE id=?", (int(bool(changes["excluded"])), tx_id))
    if changes.get("rule_pattern") and changes.get("category_id"):
        cat.add_rule(conn, changes["rule_pattern"], changes["category_id"])


def suggestions(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for l in conn.execute("SELECT * FROM links WHERE status='suggested' ORDER BY id"):
        a = conn.execute(TX_SELECT + " WHERE t.id=?", (l["a_id"],)).fetchone()
        b = conn.execute(TX_SELECT + " WHERE t.id=?", (l["b_id"],)).fetchone()
        if a and b:
            out.append({"kind": l["kind"], "evidence": l["evidence"], "a": _tx_json(a), "b": _tx_json(b)})
    return out


def decide(conn: sqlite3.Connection, kind: str, a_id: int, b_id: int, decision: str) -> None:
    if decision not in ("confirmed", "rejected") or kind not in ("transfer", "duplicate"):
        raise ValueError("invalid decision")
    conn.execute("INSERT OR REPLACE INTO link_decisions (kind, a_id, b_id, decision, decided_at) "
                 "VALUES (?,?,?,?,?)", (kind, a_id, b_id, decision, utcnow()))


def list_categories(conn: sqlite3.Connection) -> list[dict]:
    cat.seed(conn)
    return [dict(r) for r in conn.execute("SELECT * FROM categories ORDER BY kind, sort, name")]


def list_rules(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT r.id, r.pattern, r.category_id, c.name AS category FROM category_rules r
           JOIN categories c ON c.id=r.category_id ORDER BY r.id DESC""")]
