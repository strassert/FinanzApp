"""Demo data: two years of invented but plausible finances.

Built by running the fake bank through the real consent and sync code, so the
demo shows exactly what the app computes. No real names, IBANs or hosts.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from .bank.enablebanking import EnableBankingProvider
from .bank.fake import FakeEnableBanking
from .bank.fake_scenario import (
    FLATEX, OWNER, PAYLIFE, PAYPAL, VOLKSBANK, build_scenario, salary_day, tx,
)
from .core import db as core_db
from .core.categories import add_rule, ids_by_name, seed
from .core.fx import store_rates
from .core.recompute import recompute
from .core.store import NewTx, create_manual_account, store_balance, upsert_transactions
from . import sync

DEMO_APP_ID = "demo-application"
DEMO_REDIRECT = "https://finanzen-demo.invalid/connect/callback"


def make_keys() -> tuple[bytes, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
    public_pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo)
    return private_pem, public_pem


def make_fake(today: date, months: int = 25, seed_value: int = 11,
              auth_base: Optional[str] = None) -> tuple[FakeEnableBanking, EnableBankingProvider, "Clock"]:
    private_pem, public_pem = make_keys()
    clock = Clock(datetime(today.year, today.month, today.day, 7, 0, tzinfo=timezone.utc))
    kwargs = {"auth_base": auth_base} if auth_base else {}
    fake = FakeEnableBanking(DEMO_APP_ID, public_pem, now=clock, page_size=200,
                             unattended_daily_limit=1000, **kwargs)
    scenario = build_scenario(fake, today, months=months, seed=seed_value)
    _add_demo_extras(scenario, today, months, random.Random(seed_value))
    provider = EnableBankingProvider(DEMO_APP_ID, private_pem, transport=fake,
                                     clock=lambda: clock().timestamp())
    return fake, provider, clock


class Clock:
    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now


def _add_demo_extras(sc, today: date, months: int, rnd: random.Random) -> None:
    """More variety than the test scenario: subscriptions, holidays, bonuses."""
    g, pl, pe = sc.giro.transactions, sc.paylife.transactions, sc.paypal_eur.transactions
    start = date(today.year, today.month, 1)
    for _ in range(months - 1):
        start = (start - timedelta(days=1)).replace(day=1)
    n = 0

    def ref(prefix: str) -> str:
        nonlocal n
        n += 1
        return f"DEMO-{prefix}-{n:05d}"

    month = start
    while month <= today:
        y, m = month.year, month.month

        def d(day: int) -> date:
            return date(y, m, day)

        def add(lst, amount, day, text, **kw):
            if day <= today:
                lst.append(tx(amount, day, text, ref=ref("X"), **kw))

        # Austrian 13th/14th salary: holiday bonus in June, Christmas bonus in November
        if m in (6, 11):
            add(g, "2150.00", salary_day(y, m), "URLAUBSZUSCHUSS" if m == 6 else "WEIHNACHTSREMUNERATION",
                name="Beispiel Technik GmbH")
        add(g, "-24.90", d(15), "A1 TELEKOM AUSTRIA RECHNUNG", name="A1 Telekom Austria AG")
        add(g, "-38.50", d(20), "UNIQA HAUSHALTSVERSICHERUNG", name="UNIQA Versicherungen AG")
        if m in (1, 4, 7, 10):
            add(g, "-86.40", d(20), "WIENER STAEDTISCHE KFZ", name="Wiener Städtische")
        add(pl, "-12.99", d(7), "NETFLIX.COM", mcc="4899")
        add(pl, "-10.99", d(9), "SPOTIFY AB", mcc="5815")
        for _ in range(rnd.randint(2, 4)):
            add(g, f"-{rnd.randint(1200, 4800) / 100:.2f}", d(rnd.randint(1, 28)),
                rnd.choice(["RESTAURANT ZUM HIRSCHEN", "CAFE TOMASELLI", "MJAM BESTELLUNG"]), mcc="5812")
        for _ in range(rnd.randint(1, 3)):
            add(g, f"-{rnd.randint(1500, 9000) / 100:.2f}", d(rnd.randint(1, 28)),
                rnd.choice(["DM DROGERIE MARKT 123", "BIPA FILIALE 77", "APOTHEKE ZUM LOEWEN"]), mcc="5912")
        if rnd.random() < 0.6:
            add(g, "-100.00", d(rnd.randint(1, 28)), "BANKOMAT SALZBURG ALTSTADT", mcc="6011")
        # summer holiday with foreign card spending
        if m == 8:
            for day in range(3, 13):
                gbp = Decimal(rnd.randint(1500, 9000)) / 100
                eur = (gbp * Decimal("1.17")).quantize(Decimal("0.01"))
                add(pl, f"-{eur}", d(day), rnd.choice(["PRET A MANGER LONDON", "TESCO METRO LONDON",
                                                       "TFL TRAVEL CH"]),
                    mcc=rnd.choice(["5814", "5411", "4111"]), instructed=(f"{gbp}", "GBP"))
            add(pl, "-689.00", d(1), "BOOKING.COM HOTEL LONDON", mcc="7011")
        month = (month + timedelta(days=32)).replace(day=1)

    # settle the extra card spending each month so the card balance stays plausible
    by_month: dict[tuple[int, int], Decimal] = {}
    for t in pl:
        if t["entry_reference"] and t["entry_reference"].startswith("DEMO") and t["credit_debit_indicator"] == "DBIT":
            day = date.fromisoformat(t["booking_date"])
            by_month[(day.year, day.month)] = by_month.get((day.year, day.month), Decimal(0)) + \
                Decimal(t["transaction_amount"]["amount"])
    for (y, m), total in by_month.items():
        settle = date(y, m, 28) + timedelta(days=14)
        if settle <= today:
            g.append(tx(f"-{total:.2f}", settle, "PAYLIFE ABRECHNUNG ZUSATZ", name="BAWAG P.S.K.", ref=ref("S")))
            pl.append(tx(f"{total:.2f}", settle, "ZAHLUNG ERHALTEN - DANKE", ref=ref("S")))

    # recompute balances after the extras (keep the scenario's opening balances)
    def total(txs, currency="EUR"):
        s = Decimal(0)
        for t in txs:
            if t["status"] == "BOOK" and t["transaction_amount"]["currency"] == currency:
                a = Decimal(t["transaction_amount"]["amount"])
                s += -a if t["credit_debit_indicator"] == "DBIT" else a
        return s

    extra_giro = total([t for t in g if (t["entry_reference"] or "").startswith("DEMO")])
    extra_card = total([t for t in pl if (t["entry_reference"] or "").startswith("DEMO")])
    for acc, extra in ((sc.giro, extra_giro), (sc.paylife, extra_card)):
        for b in acc.balances:
            b["balance_amount"]["amount"] = f"{Decimal(b['balance_amount']['amount']) + extra:.2f}"
    del pe  # PayPal stays as in the scenario


def _fx_rates(today: date, days: int, rnd: random.Random) -> list[tuple[str, str, str]]:
    out = []
    usd, gbp = 1.09, 0.855
    day = today - timedelta(days=days)
    while day <= today:
        if day.weekday() < 5:
            usd = max(1.0, min(1.25, usd + rnd.uniform(-0.004, 0.004)))
            gbp = max(0.80, min(0.90, gbp + rnd.uniform(-0.002, 0.002)))
            out += [(day.isoformat(), "USD", f"{usd:.4f}"), (day.isoformat(), "GBP", f"{gbp:.4f}")]
        day += timedelta(days=1)
    return out


def build_demo_db(path: str | Path, today: Optional[date] = None, months: int = 25) -> Path:
    """Create a fresh demo database at `path`."""
    today = today or date.today()
    path = Path(path)
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    conn = core_db.connect(path)
    rnd = random.Random(5)
    fake, provider, clock = make_fake(today, months)
    seed(conn)
    store_rates(conn, _fx_rates(today, months * 31 + 10, rnd))
    for bank in (VOLKSBANK, FLATEX, PAYPAL, PAYLIFE):
        url = sync.start_consent(conn, provider, bank, "AT", DEMO_REDIRECT, now=clock)
        q = parse_qs(urlparse(fake.approve(url)).query)
        sync.complete_consent(conn, provider, q["state"][0], q["code"][0], now=clock)

    # flatex depot without API: monthly valuations growing with the savings plan
    depot = create_manual_account(conn, "flatex Depot", "depot", patterns="WP-KAUF,WP-VERKAUF")
    value = Decimal("8200.00")
    d = today - timedelta(days=months * 30)
    while d <= today:
        value = (value + Decimal(450)) * Decimal(str(1 + rnd.uniform(-0.035, 0.045)))
        store_balance(conn, depot, int(value * 100), "EUR", "MANUAL", d)
        d += timedelta(days=30)

    # Apple Pay notifications of the last days (one already matched by the bank)
    card = conn.execute("SELECT id FROM accounts WHERE institution=?", (PAYLIFE,)).fetchone()[0]
    upsert_transactions(conn, card, "wallet", [
        NewTx(booking_date=today, amount_minor=-5400, currency="EUR", status="pending",
              counterparty="OMV Tankstelle 12", description="Apple Pay", apple_pay=True, card="PayLife"),
        NewTx(booking_date=today, amount_minor=-420, currency="EUR", status="pending",
              counterparty="Café Bazar", description="Apple Pay", apple_pay=True, card="PayLife"),
    ])
    ids = ids_by_name(conn)
    add_rule(conn, "CAFE BAZAR", ids["Restaurant & Café"])
    recompute(conn)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return path
