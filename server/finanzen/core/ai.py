"""KI stage B: a language model suggests categories for unknown merchants.

Runs after a sync (and via `finanzen categorize`), never during the
recomputation: results go into `ai_categories` per merchant key, and the
categorizer only reads that table.

What is sent: the payee text of merchants that are still "Sonstiges" or only
categorised by card code (MCC), with long digit runs removed, their MCC, and
the names of the expense categories. Never: amounts, dates, IBANs, notes,
income, transfers, or payees that look like private persons (a transfer
with an IBAN whose counterparty has no company marker). Each merchant is
asked once; "unsure" answers are stored too, so they are not asked again.
Logs contain counts only.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Callable, Optional

from .categories import OTHER_EXPENSE, TRANSFER, fold
from .db import transaction, utcnow

log = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"
BATCH = 50
MAX_PER_RUN = 300
UNSURE = "unsicher"
COMPANY = re.compile(r"\b(GMBH|AG|KG|OG|SE|EU|E U|LTD|INC|LLC|SARL|SPA|BV|NV|BANK|SPARKASSE|VERSICHERUNG|VERSICHERUNGEN|"
                     r"VEREIN|MAGISTRAT|GEMEINDE|STADT|LAND|FINANZAMT|UNIVERSITAET|SCHULE|HOTEL|APOTHEKE|"
                     r"RESTAURANT|GASTHOF|STADTWERKE|WERKE|ENERGIE|TELEKOM|PAYPAL|AMAZON|KLARNA)\b")

SYSTEM = (
    "Du ordnest Händler aus österreichischen Kontoauszügen einer Ausgabenkategorie zu. "
    "Jeder Eintrag hat eine id, den Buchungstext des Händlers und manchmal den Kartencode (MCC). "
    "Wähle für jeden Eintrag genau eine der vorgegebenen Kategorien. Wenn du den Händler nicht "
    f"sicher erkennst oder er zu keiner Kategorie klar passt, antworte mit „{UNSURE}“. "
    "Rate nicht: lieber unsicher als falsch."
)


def clean(payee: str) -> str:
    """Payee text without long digit runs (card numbers, references), shortened."""
    text = re.sub(r"\b[A-Z]{2}\d{2}[A-Z0-9]{8,}\b", " ", payee, flags=re.I)   # IBAN-like
    text = re.sub(r"\d{4,}", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:80]


def looks_private(counterparty: str, counterparty_iban: Optional[str]) -> bool:
    return bool(counterparty_iban) and not COMPANY.search(fold(counterparty or ""))


def candidates(conn: sqlite3.Connection, limit: int = MAX_PER_RUN) -> list[dict]:
    rows = conn.execute("""
        SELECT d.merchant_key AS key, t.counterparty, t.counterparty_iban, t.description, t.mcc
        FROM tx_derived d JOIN transactions t ON t.id=d.tx_id
        WHERE d.role='expense' AND t.amount_minor < 0 AND d.category_source IN ('default','mcc')
          AND d.merchant_key IS NOT NULL AND d.merchant_key != '' AND t.removed_at IS NULL
          AND d.merchant_key NOT IN (SELECT key FROM ai_categories)
          AND d.merchant_key NOT IN (SELECT key FROM merchant_categories)
        ORDER BY t.booking_date DESC, t.id DESC""").fetchall()
    out: dict[str, dict] = {}
    private: set[str] = set()
    for r in rows:
        if looks_private(r["counterparty"], r["counterparty_iban"]):
            private.add(r["key"])
            continue
        if r["key"] not in out:
            text = clean((r["counterparty"] or r["description"] or "").strip())
            if text:
                out[r["key"]] = {"key": r["key"], "text": text, "mcc": r["mcc"]}
    return [c for k, c in out.items() if k not in private][:limit]


def schema(names: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {"results": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "category": {"type": "string", "enum": [*names, UNSURE]}},
            "required": ["id", "category"], "additionalProperties": False,
        }}},
        "required": ["results"], "additionalProperties": False,
    }


def ask(client, model: str, items: list[dict], names: list[str]) -> dict[int, str]:
    """One request for up to BATCH merchants: {index: category name or UNSURE}."""
    lines = [{"id": i, "text": it["text"], **({"mcc": it["mcc"]} if it["mcc"] else {})} for i, it in enumerate(items)]
    response = client.messages.create(
        model=model, max_tokens=4096, system=SYSTEM,
        messages=[{"role": "user", "content":
                   "Kategorien: " + ", ".join(names) + "\n\nHändler:\n" + json.dumps(lines, ensure_ascii=False)}],
        output_config={"format": {"type": "json_schema", "schema": schema(names)}},
    )
    if response.stop_reason not in ("end_turn", "stop_sequence"):
        raise ValueError(f"unexpected stop reason {response.stop_reason}")
    text = next(b.text for b in response.content if b.type == "text")
    return {int(r["id"]): r["category"] for r in json.loads(text)["results"]}


def run(conn: sqlite3.Connection, client, model: str = MODEL) -> int:
    """Ask the model about new merchants; returns how many got a category."""
    names_to_id = {r["name"]: r["id"] for r in conn.execute(
        "SELECT id, name FROM categories WHERE kind='expense' AND name NOT IN (?, ?) ORDER BY sort, name",
        (TRANSFER, OTHER_EXPENSE))}
    names = list(names_to_id)
    todo = candidates(conn)
    found = 0
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        answers = ask(client, model, batch, names)
        with transaction(conn):
            for i, item in enumerate(batch):
                if i not in answers:
                    continue                      # not answered: ask again next time
                category_id = names_to_id.get(answers[i])
                found += category_id is not None
                conn.execute("INSERT OR REPLACE INTO ai_categories (key, category_id, model, created_at) "
                             "VALUES (?,?,?,?)", (item["key"], category_id, model, utcnow()))
    log.info("ai categories: %d merchants asked, %d categorised", len(todo), found)
    return found


def client_from_key_file(path: str | Path, timeout: float = 60.0):
    """Anthropic client with the key from a file; None when the file is missing."""
    key_file = Path(path)
    if not key_file.is_file():
        return None
    key = key_file.read_text(encoding="utf-8").strip()
    if not key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=2)


def run_safely(conn: sqlite3.Connection, key_path: str, model: str = MODEL,
               make_client: Callable = client_from_key_file) -> Optional[int]:
    """For the sync: never fails it. None = not configured or failed."""
    client = make_client(key_path)
    if client is None:
        return None
    try:
        return run(conn, client, model)
    except Exception as exc:   # network, API or parse error: the next sync tries again
        log.warning("ai categories failed: %s %s", type(exc).__name__, getattr(exc, "status_code", ""))
        return None
