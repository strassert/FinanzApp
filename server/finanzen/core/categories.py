"""Categories: built-in list, keywords for local merchants, MCC mapping.

Precedence (see README): user choice -> transfer -> user rules -> confirmed
merchant -> learned from the same merchant -> built-in keywords -> learned
from a distinctive word -> language model -> card MCC -> "Sonstiges" /
"Sonstige Einnahmen". "learned" and "ai" are suggestions (core.learn, core.ai).
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Optional

from .db import utcnow

TRANSFER = "Umbuchung"
SALARY = "Gehalt"
OTHER_EXPENSE = "Sonstiges"
OTHER_INCOME = "Sonstige Einnahmen"

# (name, kind). Order = colour slot for expense categories.
BUILTIN: list[tuple[str, str]] = [
    ("Lebensmittel", "expense"),
    ("Wohnen", "expense"),
    ("Restaurant & Café", "expense"),
    ("Mobilität", "expense"),
    ("Shopping", "expense"),
    ("Freizeit", "expense"),
    ("Abos & Digitales", "expense"),
    ("Gesundheit & Drogerie", "expense"),
    ("Energie & Telefon", "expense"),
    ("Reisen", "expense"),
    ("Versicherungen", "expense"),
    ("Gebühren & Steuern", "expense"),
    ("Bargeld", "expense"),
    (OTHER_EXPENSE, "expense"),
    ("Gehalt", "income"),
    ("Kapitalerträge", "income"),
    (OTHER_INCOME, "income"),
    (TRANSFER, "transfer"),
]

# Keywords (uppercase, matched as whole words or prefixes) -> category.
KEYWORDS: list[tuple[str, str]] = [
    # groceries (Austria)
    ("BILLA", "Lebensmittel"), ("SPAR", "Lebensmittel"), ("EUROSPAR", "Lebensmittel"),
    ("INTERSPAR", "Lebensmittel"), ("HOFER", "Lebensmittel"), ("LIDL", "Lebensmittel"),
    ("PENNY", "Lebensmittel"), ("MPREIS", "Lebensmittel"), ("UNIMARKT", "Lebensmittel"),
    ("ADEG", "Lebensmittel"), ("NAH&FRISCH", "Lebensmittel"), ("BAECKEREI", "Lebensmittel"),
    ("BÄCKEREI", "Lebensmittel"),
    # housing / energy
    ("MIETE", "Wohnen"), ("HAUSVERWALTUNG", "Wohnen"), ("BETRIEBSKOSTEN", "Wohnen"),
    ("STROM", "Energie & Telefon"), ("SALZBURG AG", "Energie & Telefon"), ("VERBUND", "Energie & Telefon"),
    ("A1 TELEKOM", "Energie & Telefon"), ("MAGENTA", "Energie & Telefon"), ("DREI", "Energie & Telefon"),
    ("HOT", "Energie & Telefon"), ("GIS", "Gebühren & Steuern"), ("ORF", "Gebühren & Steuern"),
    # mobility
    ("OEBB", "Mobilität"), ("ÖBB", "Mobilität"), ("WESTBAHN", "Mobilität"), ("OMV", "Mobilität"),
    ("BP", "Mobilität"), ("SHELL", "Mobilität"), ("ENI", "Mobilität"), ("JET", "Mobilität"),
    ("TURMOEL", "Mobilität"), ("ASFINAG", "Mobilität"), ("PARKGARAGE", "Mobilität"),
    ("WIENER LINIEN", "Mobilität"), ("SALZBURG VERKEHR", "Mobilität"), ("UBER", "Mobilität"),
    # health / drugstore
    ("DM DROGERIE", "Gesundheit & Drogerie"), ("BIPA", "Gesundheit & Drogerie"),
    ("MUELLER", "Gesundheit & Drogerie"), ("APOTHEKE", "Gesundheit & Drogerie"),
    # shopping
    ("ZALANDO", "Shopping"), ("AMAZON", "Shopping"), ("MEDIAMARKT", "Shopping"),
    ("SATURN", "Shopping"), ("IKEA", "Shopping"), ("H&M", "Shopping"), ("THALIA", "Shopping"),
    ("XXXLUTZ", "Shopping"), ("HERVIS", "Shopping"), ("INTERSPORT", "Shopping"),
    # subscriptions / digital
    ("NETFLIX", "Abos & Digitales"), ("SPOTIFY", "Abos & Digitales"), ("DISNEY", "Abos & Digitales"),
    ("APPLE.COM", "Abos & Digitales"), ("GOOGLE", "Abos & Digitales"), ("STEAM", "Abos & Digitales"),
    ("VALVE", "Abos & Digitales"), ("HUMBLE BUNDLE", "Abos & Digitales"),
    # leisure / food out
    ("KINO", "Freizeit"), ("CINEPLEXX", "Freizeit"), ("CITYPLEXX", "Freizeit"),
    ("RESTAURANT", "Restaurant & Café"), ("CAFE", "Restaurant & Café"), ("GASTHOF", "Restaurant & Café"),
    ("MCDONALDS", "Restaurant & Café"), ("LIEFERANDO", "Restaurant & Café"), ("MJAM", "Restaurant & Café"),
    # insurance / fees / cash
    ("VERSICHERUNG", "Versicherungen"), ("UNIQA", "Versicherungen"), ("WIENER STAEDTISCHE", "Versicherungen"),
    ("ALLIANZ", "Versicherungen"), ("KONTOFÜHRUNG", "Gebühren & Steuern"),
    ("KONTOFUEHRUNG", "Gebühren & Steuern"), ("FINANZAMT", "Gebühren & Steuern"),
    ("BARGELD", "Bargeld"), ("BANKOMAT", "Bargeld"), ("ATM", "Bargeld"),
    # income
    ("GEHALT", "Gehalt"), ("LOHN", "Gehalt"), ("BEZUG", "Gehalt"),
    ("DIVIDENDE", "Kapitalerträge"), ("ERTRAG", "Kapitalerträge"), ("ZINSEN", "Kapitalerträge"),
    ("ERTRAGSGUTSCHRIFT", "Kapitalerträge"),
]

# MCC ranges -> category (ISO 18245, simplified).
MCC_RANGES: list[tuple[int, int, str]] = [
    (3000, 3350, "Reisen"), (3351, 3500, "Mobilität"), (3501, 3999, "Reisen"),
    (4011, 4131, "Mobilität"), (4411, 4411, "Reisen"), (4511, 4582, "Reisen"),
    (4722, 4722, "Reisen"), (4784, 4784, "Mobilität"), (4812, 4816, "Energie & Telefon"),
    (4899, 4899, "Abos & Digitales"), (4900, 4900, "Energie & Telefon"),
    (5411, 5499, "Lebensmittel"), (5541, 5542, "Mobilität"),
    (5611, 5699, "Shopping"), (5712, 5735, "Shopping"), (5812, 5814, "Restaurant & Café"),
    (5815, 5818, "Abos & Digitales"), (5912, 5912, "Gesundheit & Drogerie"),
    (5200, 5399, "Shopping"), (5900, 5999, "Shopping"), (6010, 6011, "Bargeld"),
    (6300, 6399, "Versicherungen"), (7011, 7012, "Reisen"), (7512, 7523, "Mobilität"),
    (7832, 7999, "Freizeit"), (8011, 8099, "Gesundheit & Drogerie"), (9311, 9399, "Gebühren & Steuern"),
]


def seed(conn: sqlite3.Connection) -> None:
    """Insert built-in categories that do not exist yet (idempotent)."""
    slot = 0
    for sort, (name, kind) in enumerate(BUILTIN):
        color = None
        if kind == "expense":
            color, slot = slot, slot + 1
        conn.execute(
            "INSERT OR IGNORE INTO categories (name, kind, color_slot, builtin, sort) VALUES (?,?,?,1,?)",
            (name, kind, color, sort))


def ids_by_name(conn: sqlite3.Connection) -> dict[str, int]:
    return {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM categories")}


def fold(text: str) -> str:
    """Uppercase without accents, so CAFÉ matches CAFE and BÄCKEREI matches BACKEREI."""
    decomposed = unicodedata.normalize("NFKD", text.upper())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def payee_key(counterparty: str, description: str) -> str:
    """Normalised payee: counterparty, else booking text; no digits or punctuation."""
    text = fold(counterparty or description)
    text = re.sub(r"[^A-Z& ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def merchant_key(amount_minor: int, counterparty: str, description: str) -> str:
    """Key per merchant and direction; empty when the text has no letters."""
    payee = payee_key(counterparty, description)
    return f"{'+' if amount_minor > 0 else '-'}:{payee}" if payee else ""


def _norm(text: str) -> str:
    return " " + re.sub(r"\s+", " ", fold(text)) + " "


def _contains(haystack: str, needle: str) -> bool:
    """Whole-word match (so SPAR does not match SPARPLAN)."""
    pattern = r"(?<![A-Z0-9])" + re.escape(fold(needle.strip())) + r"(?![A-Z0-9])"
    return re.search(pattern, haystack) is not None


@dataclass
class Rule:
    pattern: str
    category_id: int


def load_rules(conn: sqlite3.Connection) -> list[Rule]:
    return [Rule(r["pattern"], r["category_id"])
            for r in conn.execute("SELECT pattern, category_id FROM category_rules ORDER BY id DESC")]


def add_rule(conn: sqlite3.Connection, pattern: str, category_id: int) -> int:
    cur = conn.execute("INSERT INTO category_rules (pattern, category_id, created_at) VALUES (?,?,?)",
                       (pattern.strip(), category_id, utcnow()))
    return cur.lastrowid


class Categorizer:
    def __init__(self, conn: sqlite3.Connection, learner=None):
        """learner: core.learn.Learner or None (first pass of the recomputation)."""
        self.ids = ids_by_name(conn)
        self.kinds = {r["id"]: r["kind"] for r in conn.execute("SELECT id, kind FROM categories")}
        self.rules = load_rules(conn)
        self.learner = learner
        self.confirmed = {r["key"]: r["category_id"] for r in conn.execute(
            "SELECT key, category_id FROM merchant_categories")}
        self.ai = {r["key"]: r["category_id"] for r in conn.execute(
            "SELECT key, category_id FROM ai_categories WHERE category_id IS NOT NULL")}
        self.hint: Optional[str] = None   # merchant a "learned" category came from

    def _fits(self, category_id: Optional[int], income: bool) -> bool:
        return self.kinds.get(category_id) == ("income" if income else "expense")

    def categorize(self, *, amount_minor: int, text: str, mcc: Optional[str],
                   user_category_id: Optional[int] = None,
                   is_transfer: bool = False, key: str = "", payee: str = "") -> tuple[int, str]:
        """Return (category_id, source). key/payee: merchant key and payee text
        for the merchant-based steps; `hint` is set for learned categories."""
        self.hint = None
        if user_category_id is not None:
            return user_category_id, "user"
        if is_transfer:
            return self.ids[TRANSFER], "transfer"
        income = amount_minor > 0
        hay = _norm(text)
        for rule in self.rules:
            if rule.pattern and fold(rule.pattern.strip()) in hay:
                return rule.category_id, "rule"
        if key and self._fits(self.confirmed.get(key), income):
            return self.confirmed[key], "confirmed"
        if key and self.learner:
            guess = self.learner.same_merchant(key)
            if guess and self._fits(guess.category_id, income):
                self.hint = guess.hint
                return guess.category_id, "learned"
        wanted = "income" if income else "expense"
        for keyword, name in KEYWORDS:
            if self.kinds.get(self.ids.get(name)) == wanted and _contains(hay, keyword):
                return self.ids[name], "keyword"
        if key and self.learner:
            guess = self.learner.by_word(key, payee)
            if guess and self._fits(guess.category_id, income):
                self.hint = guess.hint
                return guess.category_id, "learned"
        if key and self._fits(self.ai.get(key), income):
            return self.ai[key], "ai"
        if mcc and not income:
            try:
                code = int(mcc)
            except ValueError:
                code = -1
            for lo, hi, name in MCC_RANGES:
                if lo <= code <= hi:
                    return self.ids[name], "mcc"
        return self.ids[OTHER_INCOME if income else OTHER_EXPENSE], "default"
