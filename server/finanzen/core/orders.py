"""Amazon order history: import, match shipments to card charges, split charges.

Import: the "Your Orders" data export (Retail.OrderHistory.*.csv, also inside
the ZIP). ASSUMED FORMAT – column names from Amazon's export as known so far;
check against a real file: "Order ID", "Order Date", "Ship Date",
"Product Name", "Quantity", "Total Owed", "Currency", "Order Status",
"Payment Instrument Type", "ASIN".

Matching: Amazon charges the card when a shipment leaves, so one order can
become several charges. A shipment matches a bank debit whose text names
Amazon, with exactly the shipment total, from 2 days before to 7 days after
the ship date (order date if none). Unique match -> automatic; several
candidates -> suggestion for the user. User decisions are kept.

Splitting: a matched debit is split into its items; the debit amount is
distributed proportionally (largest remainder), so the lines always add up to
the bank amount even with discounts or shipping. Each item gets a category:
user choice -> user rules -> keywords -> "Shopping".
"""

from __future__ import annotations

import csv
import io
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from ..money import to_minor
from .db import utcnow
from .importer import ImportError_, parse_amount

LOCAL_TZ = ZoneInfo("Europe/Vienna")
MERCHANT_WORDS = ("AMAZON", "AMZN")
BEFORE_DAYS, AFTER_DAYS = 2, 7
SKIP_STATUS = {"cancelled", "canceled", "storniert"}

COLUMNS = {
    "order_id": ("Order ID", "Bestellnummer"),
    "order_date": ("Order Date", "Bestelldatum"),
    "ship_date": ("Ship Date", "Versanddatum"),
    "name": ("Product Name", "Produktname", "Artikelbezeichnung"),
    "quantity": ("Quantity", "Menge"),
    "total": ("Total Owed", "Gesamtbetrag"),
    "unit_price": ("Unit Price", "Stückpreis"),
    "currency": ("Currency", "Währung"),
    "status": ("Order Status", "Bestellstatus"),
    "payment": ("Payment Instrument Type", "Zahlungsart"),
    "asin": ("ASIN",),
}


@dataclass
class OrderItem:
    ext_id: str
    order_id: str
    shipment_key: str
    order_date: date
    ship_date: Optional[date]
    name: str
    quantity: int
    amount_minor: int
    currency: str
    payment: Optional[str]
    status: Optional[str]


def _local_date(value: str) -> Optional[date]:
    v = (value or "").strip()
    if not v or v.lower() in ("not available", "n/a"):
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.strptime(v[:10], "%d.%m.%Y").date()
        except ValueError:
            return None
    if dt.tzinfo:
        dt = dt.astimezone(LOCAL_TZ)
    return dt.date()


def _read_csv_text(data: bytes) -> str:
    if data[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = [n for n in zf.namelist() if "orderhistory" in n.lower().replace(".", "")
                         and n.lower().endswith(".csv")]
                if not names:
                    raise ImportError_("Im ZIP fehlt die Datei Retail.OrderHistory…csv.")
                return "\n".join(zf.read(n).decode("utf-8-sig") for n in sorted(names))
        except zipfile.BadZipFile as exc:
            raise ImportError_("Die ZIP-Datei ist beschädigt.") from exc
    return data.decode("utf-8-sig", errors="replace")


def parse_amazon(data: bytes) -> list[OrderItem]:
    text = _read_csv_text(data)
    rows = list(csv.reader(io.StringIO(text)))
    items: list[OrderItem] = []
    header: Optional[dict[str, int]] = None
    seen: dict[str, int] = {}
    for row in rows:
        if not any(row):
            continue
        is_header = any(n in row for n in COLUMNS["order_id"]) and any(n in row for n in COLUMNS["name"])
        if is_header:                        # several CSVs concatenated: each brings its header
            header = {key: next((row.index(n) for n in names if n in row), None)
                      for key, names in COLUMNS.items()}
            continue
        if header is None:
            continue

        def col(key: str) -> str:
            i = header.get(key)
            return row[i].strip() if i is not None and i < len(row) else ""

        status = col("status")
        if status.lower() in SKIP_STATUS:
            continue
        order_date = _local_date(col("order_date"))
        if not col("order_id") or order_date is None:
            continue
        currency = (col("currency") or "EUR").upper()
        try:
            quantity = max(1, int(float(col("quantity") or "1")))
        except ValueError:
            quantity = 1
        total = parse_amount(col("total"))
        if total is None:
            unit = parse_amount(col("unit_price"))
            if unit is None:
                continue
            total = unit * quantity
        ship_date = _local_date(col("ship_date"))
        shipment_key = f"{col('order_id')}|{(ship_date or order_date).isoformat()}"
        base = f"{col('order_id')}|{col('asin') or col('name')[:40]}|{ship_date or ''}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        items.append(OrderItem(f"{base}#{n}", col("order_id"), shipment_key, order_date, ship_date,
                               col("name") or "Artikel", quantity, abs(to_minor(total, currency)),
                               currency, col("payment") or None, status or None))
    if header is None:
        raise ImportError_("Keine Amazon-Bestellhistorie erkannt (Spalten „Order ID“ und „Product Name“ fehlen).")
    return items


def import_items(conn: sqlite3.Connection, items: list[OrderItem]) -> dict:
    new = 0
    now = utcnow()
    for it in items:
        cur = conn.execute(
            """INSERT OR IGNORE INTO order_items (source, ext_id, order_id, shipment_key, order_date,
               ship_date, name, quantity, amount_minor, currency, payment, status, imported_at)
               VALUES ('amazon',?,?,?,?,?,?,?,?,?,?,?,?)""",
            (it.ext_id, it.order_id, it.shipment_key, it.order_date.isoformat(),
             it.ship_date.isoformat() if it.ship_date else None, it.name, it.quantity, it.amount_minor,
             it.currency, it.payment, it.status, now))
        new += cur.rowcount
    orders = len({it.order_id for it in items})
    return {"items": len(items), "new": new, "orders": orders,
            "first": min((it.order_date for it in items), default=None),
            "last": max((it.order_date for it in items), default=None)}


# --- matching and splitting (called by recompute) -------------------------------------

@dataclass
class Shipment:
    key: str
    order_id: str
    day: date
    total: int
    currency: str
    item_ids: list[int]


def load_shipments(conn: sqlite3.Connection) -> list[Shipment]:
    out: dict[str, Shipment] = {}
    for r in conn.execute("SELECT * FROM order_items ORDER BY id"):
        day = date.fromisoformat(r["ship_date"] or r["order_date"])
        s = out.get(r["shipment_key"])
        if s is None:
            s = out[r["shipment_key"]] = Shipment(r["shipment_key"], r["order_id"], day, 0, r["currency"], [])
        s.total += r["amount_minor"]
        s.item_ids.append(r["id"])
    return list(out.values())


def match(conn: sqlite3.Connection, roles: dict[int, str]) -> list[tuple[str, int, str]]:
    """Return [(shipment_key, tx_id, status)]."""
    shipments = load_shipments(conn)
    if not shipments:
        return []
    decisions = {(d["shipment_key"], d["tx_id"]): d["decision"] for d in conn.execute("SELECT * FROM order_decisions")}
    txs = [dict(r) for r in conn.execute(
        """SELECT id, booking_date, amount_minor, currency, counterparty, description FROM transactions
           WHERE removed_at IS NULL AND amount_minor < 0 AND source != 'wallet'""")]
    txs = [t for t in txs if roles.get(t["id"]) == "expense"
           and any(w in f"{t['counterparty'] or ''} {t['description'] or ''}".upper() for w in MERCHANT_WORDS)]

    out: list[tuple[str, int, str]] = []
    used_tx: set[int] = set()
    done: set[str] = set()
    for (key, tx_id), decision in decisions.items():
        if decision == "confirmed" and tx_id not in used_tx:
            out.append((key, tx_id, "confirmed"))
            used_tx.add(tx_id)
            done.add(key)

    candidates: dict[str, list[dict]] = {}
    for s in shipments:
        if s.key in done:
            continue
        lo, hi = s.day - timedelta(days=BEFORE_DAYS), s.day + timedelta(days=AFTER_DAYS)
        candidates[s.key] = [t for t in txs
                             if t["currency"] == s.currency and -t["amount_minor"] == s.total
                             and lo <= date.fromisoformat(t["booking_date"]) <= hi
                             and decisions.get((s.key, t["id"])) != "rejected"]
    # how many shipments compete for each transaction
    demand: dict[int, int] = {}
    for cands in candidates.values():
        for t in cands:
            demand[t["id"]] = demand.get(t["id"], 0) + 1
    by_key = {s.key: s for s in shipments}
    for key in sorted(candidates, key=lambda k: (len(candidates[k]), by_key[k].day)):
        cands = [t for t in candidates[key] if t["id"] not in used_tx]
        if not cands:
            continue
        best = min(cands, key=lambda t: abs((date.fromisoformat(t["booking_date"]) - by_key[key].day).days))
        certain = len(cands) == 1 and demand[best["id"]] == 1
        out.append((key, best["id"], "auto" if certain else "suggested"))
        used_tx.add(best["id"])
    return out


def allocate(total: int, weights: list[int]) -> list[int]:
    """Split `total` proportionally to `weights`; parts sum exactly to `total`."""
    if not weights:
        return []
    if not sum(weights):
        weights = [1] * len(weights)
    wsum = sum(weights)
    raw = [total * w / wsum for w in weights]
    parts = [int(r) for r in raw]                      # truncates towards zero
    rest = total - sum(parts)
    step = 1 if rest > 0 else -1
    order = sorted(range(len(raw)), key=lambda i: abs(raw[i] - parts[i]), reverse=True)
    for i in order[:abs(rest)]:
        parts[i] += step
    return parts


def rebuild(conn: sqlite3.Connection, roles: dict[int, str], categorizer, shopping_id: int) -> dict[int, tuple[int, str]]:
    """Write order_matches and tx_splits. Returns {tx_id: (category of the largest line, 'split')}."""
    matches = match(conn, roles)
    conn.execute("DELETE FROM order_matches")
    conn.execute("DELETE FROM tx_splits")
    conn.executemany("INSERT INTO order_matches (shipment_key, tx_id, status) VALUES (?,?,?)", matches)
    per_tx: dict[int, list[str]] = {}
    for key, tx_id, status in matches:
        if status != "suggested":
            per_tx.setdefault(tx_id, []).append(key)
    headline: dict[int, tuple[int, str]] = {}
    for tx_id, keys in per_tx.items():
        eur = conn.execute("SELECT amount_eur_minor FROM tx_derived WHERE tx_id=?", (tx_id,)).fetchone()
        items = conn.execute(
            f"SELECT * FROM order_items WHERE shipment_key IN ({','.join('?' * len(keys))}) ORDER BY id",
            keys).fetchall()
        if eur is None or eur[0] is None or not items:
            continue
        parts = allocate(eur[0], [it["amount_minor"] for it in items])
        rows = []
        for it, part in zip(items, parts):
            if it["user_category_id"] is not None:
                cat_id, source = it["user_category_id"], "user"
            else:
                cat_id, source = categorizer.categorize(amount_minor=-1, text=it["name"], mcc=None)
                if source == "default":
                    cat_id, source = shopping_id, "order"
            rows.append((tx_id, it["id"], part, cat_id, source))
        conn.executemany("INSERT INTO tx_splits (tx_id, item_id, amount_eur_minor, category_id, category_source) "
                         "VALUES (?,?,?,?,?)", rows)
        largest = min(rows, key=lambda r: r[2])          # most negative = largest spend
        headline[tx_id] = (largest[3], "split")
    return headline
