"""Realistic, invented test data for the fake bank.

Covers: several banks and currencies, salary on the 29th (earlier if weekend),
transfers by IBAN / pattern / owner name / amount only, PayPal purchases with
and without a funding line, credit card with settlement and foreign currency,
refunds, pending transactions, a duplicate record, a restricted/expired case.

All names, IBANs and merchants are invented. Everything is relative to `today`
so tests stay stable over time.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from .fake import FakeAccount, FakeEnableBanking

OWNER = "Max Mustermann"

VOLKSBANK = "Volksbank Salzburg"
FLATEX = "flatex"
PAYPAL = "PayPal"
PAYLIFE = "PayLife"
EXPIRED_BANK = "Testbank Abgelaufen"


def make_iban(country: str, bban: str) -> str:
    """Build an IBAN with valid check digits (ISO 13616)."""
    rearranged = bban + country + "00"
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    check = 98 - int(digits) % 97
    return f"{country}{check:02d}{bban}"


GIRO_IBAN = make_iban("AT", "4501000000123456")        # invented
FLATEX_IBAN = make_iban("AT", "1946000000987654")      # invented
SAVINGS_IBAN = make_iban("AT", "2011100000555555")     # own account without API
LANDLORD_IBAN = make_iban("AT", "3500000000777777")
EMPLOYER_IBAN = make_iban("DE", "500105175407324931")


def tx(amount: str, day: date, text: str = "", *, name: Optional[str] = None,
       iban: Optional[str] = None, status: str = "BOOK", mcc: Optional[str] = None,
       currency: str = "EUR", ref: Optional[str] = None,
       instructed: Optional[tuple[str, str]] = None) -> dict:
    """Build an Enable-Banking-shaped transaction. `amount` is signed."""
    value = Decimal(amount)
    debit = value < 0
    party = {"name": name} if name else None
    party_account = {"iban": iban} if iban else None
    data = {
        "entry_reference": ref,
        "transaction_amount": {"currency": currency, "amount": str(abs(value))},
        "credit_debit_indicator": "DBIT" if debit else "CRDT",
        "status": status,
        "booking_date": day.isoformat() if status == "BOOK" else None,
        "value_date": day.isoformat(),
        "transaction_date": day.isoformat(),
        "creditor": party if debit else None,
        "creditor_account": party_account if debit else None,
        "debtor": None if debit else party,
        "debtor_account": None if debit else party_account,
        "remittance_information": [text] if text else [],
        "merchant_category_code": mcc,
        "bank_transaction_code": None,
    }
    if instructed:
        data["exchange_rate"] = {
            "unit_currency": instructed[1],
            "instructed_amount": {"amount": instructed[0], "currency": instructed[1]},
        }
    return data


def salary_day(year: int, month: int, nominal: int = 29) -> date:
    """Salary is paid on the 29th; on a weekend the Friday before. February: last day."""
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    day = date(year, month, min(nominal, last))
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _months_back(today: date, n: int) -> list[tuple[int, int]]:
    out = []
    y, m = today.year, today.month
    for _ in range(n):
        out.append((y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return list(reversed(out))


@dataclass
class Scenario:
    fake: FakeEnableBanking
    giro: FakeAccount
    flatex: FakeAccount
    paypal_eur: FakeAccount
    paypal_usd: FakeAccount
    paylife: FakeAccount
    expired: FakeAccount


def build_scenario(fake: FakeEnableBanking, today: date, months: int = 7,
                   seed: int = 7) -> Scenario:
    rnd = random.Random(seed)
    for bank in (VOLKSBANK, FLATEX, PAYPAL, PAYLIFE, EXPIRED_BANK):
        fake.add_institution(bank, "AT", 180 if bank != PAYPAL else 90)

    giro = fake.add_account(FakeAccount(VOLKSBANK, {
        "identification_hash": "hash-giro", "account_id": {"iban": GIRO_IBAN},
        "name": OWNER, "currency": "EUR", "cash_account_type": "CACC",
        "product": "Gehaltskonto", "credit_limit": {"amount": "1500.00", "currency": "EUR"},
    }))
    flatex = fake.add_account(FakeAccount(FLATEX, {
        "identification_hash": "hash-flatex", "account_id": {"iban": FLATEX_IBAN},
        "name": OWNER, "currency": "EUR", "cash_account_type": "CACC",
        "product": "Verrechnungskonto",
    }))
    paypal_eur = fake.add_account(FakeAccount(PAYPAL, {
        "identification_hash": "hash-paypal-eur", "account_id": {},
        "name": OWNER, "currency": "EUR", "cash_account_type": "CACC", "product": "PayPal",
    }))
    paypal_usd = fake.add_account(FakeAccount(PAYPAL, {
        "identification_hash": "hash-paypal-usd", "account_id": {},
        "name": OWNER, "currency": "USD", "cash_account_type": "CACC", "product": "PayPal USD",
    }))
    paylife = fake.add_account(FakeAccount(PAYLIFE, {
        "identification_hash": "hash-paylife", "account_id": {},
        "name": OWNER, "currency": "EUR", "cash_account_type": "CARD",
        "product": "PayLife Classic", "credit_limit": {"amount": "3000.00", "currency": "EUR"},
    }))
    expired = fake.add_account(FakeAccount(EXPIRED_BANK, {
        "identification_hash": "hash-expired", "account_id": {"iban": make_iban("AT", "9999900000000001")},
        "name": OWNER, "currency": "EUR", "cash_account_type": "CACC", "product": "Altes Konto",
    }))

    g, f, pe, pu, pl = (giro.transactions, flatex.transactions, paypal_eur.transactions,
                        paypal_usd.transactions, paylife.transactions)
    n = 0

    def ref(prefix: str) -> str:
        nonlocal n
        n += 1
        return f"{prefix}-{n:05d}"

    groceries = [("BILLA DANKT 4711 SALZBURG", "5411"), ("SPAR FIL. 5020 SALZBURG", "5411"),
                 ("HOFER DANKT 0815", "5411"), ("DM DROGERIE MARKT 123", "5912")]
    card_merchants = [("OEBB TICKET SHOP WIEN", "4111"), ("RESTAURANT ZUM HIRSCHEN", "5812"),
                      ("OMV TANKSTELLE 12", "5541"), ("KINO CITYPLEXX", "7832"),
                      ("CAFE TOMASELLI", "5814")]

    for year, month in _months_back(today, months):
        def d(day: int) -> date:
            return date(year, month, day)

        if d(1) > today:
            break

        # Salary (booked on the salary day, which may be before the 29th)
        pay = salary_day(year, month)
        if pay <= today:
            g.append(tx("3240.00", pay, f"GEHALT {month:02d}/{year}", name="Beispiel Technik GmbH",
                        iban=EMPLOYER_IBAN, ref=ref("VB")))
        # Rent and utilities
        g.append(tx("-950.00", d(1), "MIETE WOHNUNG TOP 4", name="Hausverwaltung Sonnenhof",
                    iban=LANDLORD_IBAN, ref=ref("VB")))
        if d(5) <= today:
            g.append(tx("-68.40", d(5), "Salzburg AG Strom Teilbetrag", name="Salzburg AG",
                        ref=ref("VB")))
        # Transfer to flatex: evidence = own IBAN on both sides
        if d(2) <= today:
            g.append(tx("-500.00", d(2), "Sparplan", name=OWNER, iban=FLATEX_IBAN, ref=ref("VB")))
            f.append(tx("500.00", d(3), "Gutschrift Sparplan", name=OWNER, iban=GIRO_IBAN, ref=ref("FX")))
        # ETF purchase on flatex (moves cash into the depot – not an expense)
        if d(6) <= today:
            f.append(tx("-450.00", d(6), "WP-KAUF A0RPWH ISHARES CORE MSCI WORLD", ref=ref("FX")))
        # Transfer to an own savings account without API: evidence = owner name
        if d(3) <= today:
            g.append(tx("-200.00", d(3), "Notgroschen", name=OWNER, iban=SAVINGS_IBAN, ref=ref("VB")))

        # Debit card groceries on the giro account
        for _ in range(6):
            day = rnd.randint(1, 28)
            if d(day) > today:
                continue
            text, mcc = rnd.choice(groceries)
            amount = f"-{rnd.randint(800, 9500) / 100:.2f}"
            g.append(tx(amount, d(day), text, mcc=mcc, ref=ref("VB")))

        # Credit card purchases (PayLife) and settlement on the 10th of next month
        card_total = Decimal(0)
        for _ in range(5):
            day = rnd.randint(1, 28)
            if d(day) > today:
                continue
            text, mcc = rnd.choice(card_merchants)
            amount = Decimal(rnd.randint(500, 12000)) / 100
            card_total += amount
            pl.append(tx(f"-{amount:.2f}", d(day), text, mcc=mcc, ref=ref("PL")))
        settle = d(28) + timedelta(days=13)
        if card_total and settle <= today:
            g.append(tx(f"-{card_total:.2f}", settle, "PAYLIFE ABRECHNUNG KARTE XXXX 1234",
                        name="BAWAG P.S.K.", ref=ref("VB")))
            pl.append(tx(f"{card_total:.2f}", settle, "ZAHLUNG ERHALTEN - DANKE", ref=ref("PL")))

        # PayPal purchase WITHOUT funding line: only the bank debit shows the link
        if d(12) <= today:
            amount = f"{rnd.randint(1500, 9000) / 100:.2f}"
            pp_id = f"{rnd.randint(10**12, 10**13 - 1)}"
            pe.append(tx(f"-{amount}", d(12), "Zahlung an Zalando SE", name="Zalando SE",
                         ref=ref("PP")))
            g.append(tx(f"-{amount}", d(13), f"{pp_id} PP.4711.PP . Zalando SE, Ihr Einkauf bei Zalando SE",
                        name="PayPal Europe S.a.r.l. et Cie S.C.A", ref=ref("VB")))
        # PayPal purchase WITH funding line (bank -> PayPal, then purchase)
        if d(18) <= today:
            amount = f"{rnd.randint(500, 6000) / 100:.2f}"
            pe.append(tx(amount, d(18), "Bankgutschrift auf PayPal-Konto", name=OWNER, ref=ref("PP")))
            pe.append(tx(f"-{amount}", d(18), "Zahlung an Valve Corporation (Steam)",
                         name="Valve Corporation", ref=ref("PP")))
            g.append(tx(f"-{amount}", d(19), "PP.4711.PP . Valve Corporation, Ihr Einkauf",
                        name="PayPal Europe S.a.r.l. et Cie S.C.A", ref=ref("VB")))

    # One-offs relative to today --------------------------------------------------
    def ago(days: int) -> date:
        return today - timedelta(days=days)

    # Refund: purchase and credit from the same merchant within 120 days
    g.append(tx("-199.00", ago(60), "MEDIAMARKT SALZBURG 1234", mcc="5732", ref="VB-REFUND-1"))
    g.append(tx("199.00", ago(41), "MEDIAMARKT SALZBURG GUTSCHRIFT", ref="VB-REFUND-2"))
    # PayPal partial refund
    pe.append(tx("29.95", ago(20), "Rückzahlung von Zalando SE", name="Zalando SE", ref="PP-REFUND-1"))
    # Amount-only transfer (no IBAN, no pattern): should become a suggestion
    g.append(tx("-250.00", ago(30), "Umbuchung", ref="VB-AMBIG-1"))
    f.append(tx("250.00", ago(29), "Gutschrift", ref="FX-AMBIG-1"))
    # Dividend on flatex (income)
    f.append(tx("12.34", ago(45), "ERTRAGSGUTSCHRIFT A0RPWH", ref="FX-DIV-1"))
    # Foreign currency: card in GBP (converted by the bank), PayPal USD account
    pl.append(tx("-27.61", ago(35), "PRET A MANGER LONDON", mcc="5814", ref="PL-GBP-1",
                 instructed=("23.50", "GBP")))
    pu.append(tx("-12.99", ago(25), "Zahlung an Humble Bundle Inc.", name="Humble Bundle Inc.",
                 currency="USD", ref="PP-USD-1"))
    pu.append(tx("20.00", ago(26), "Bankgutschrift auf PayPal-Konto", currency="USD", ref="PP-USD-0"))
    # Pending card transactions (one gets booked later in tests)
    g.append(tx("-23.80", ago(1), "BILLA DANKT 4711 SALZBURG", status="PDNG", mcc="5411",
                ref="VB-PEND-1"))
    pl.append(tx("-54.00", ago(0), "OMV TANKSTELLE 12", status="PDNG", mcc="5541", ref="PL-PEND-1"))
    # Duplicate record as some banks deliver it (same entry_reference twice)
    dup = tx("-15.90", ago(8), "SPAR FIL. 5020 SALZBURG", mcc="5411", ref="VB-DUP-1")
    g.extend([dup, dict(dup)])
    # Old history: only visible within the first hour after consent
    g.append(tx("-1200.00", ago(150), "KAUTION RUECKZAHLUNG ALT", name="Hausverwaltung Alt", ref="VB-OLD-1"))
    expired.transactions.append(tx("-10.00", ago(5), "Kontoführung", ref="EX-1"))

    # Balances ---------------------------------------------------------------------
    def total(txs: list[dict], currency: str = "EUR") -> Decimal:
        s = Decimal(0)
        for t in txs:
            if t["status"] != "BOOK" or t["transaction_amount"]["currency"] != currency:
                continue
            a = Decimal(t["transaction_amount"]["amount"])
            s += -a if t["credit_debit_indicator"] == "DBIT" else a
        return s

    def bal(amount: Decimal, kind: str, currency: str = "EUR") -> dict:
        return {"name": kind, "balance_amount": {"amount": f"{amount:.2f}", "currency": currency},
                "balance_type": kind, "reference_date": today.isoformat()}

    giro_bal = Decimal("2150.00") + total(g) - total([dup])  # duplicate is not real money
    giro.balances = [bal(giro_bal, "CLBD"), bal(giro_bal + Decimal("1500.00") - Decimal("23.80"), "ITAV")]
    flatex.balances = [bal(Decimal("300.00") + total(f), "CLBD")]
    paypal_eur.balances = [bal(total(pe), "ITAV")]
    paypal_usd.balances = [bal(total(pu, "USD"), "ITAV", "USD")]
    card_bal = total(pl)
    paylife.balances = [bal(card_bal, "CLBD"), bal(Decimal("3000.00") + card_bal - Decimal("54.00"), "ITAV")]
    expired.balances = [bal(Decimal("42.00"), "CLBD")]

    return Scenario(fake, giro, flatex, paypal_eur, paypal_usd, paylife, expired)
