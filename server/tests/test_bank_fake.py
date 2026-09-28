"""The Enable Banking client against the fake bank (no network)."""

from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from finanzen.bank import (
    ApplicationError, AuthorizationFailed, BankError, BankUnavailable, ConsentExpired,
    Institution, PsuHeaders, PsuHeadersRejected, RateLimited, pick_balance,
)
from finanzen.bank.enablebanking import EnableBankingProvider, HttpResponse, raise_for_error
from finanzen.bank.fake_scenario import (
    EXPIRED_BANK, FLATEX, GIRO_IBAN, PAYLIFE, PAYPAL, VOLKSBANK, make_iban, salary_day,
)

from .conftest import APP_ID, TODAY

REDIRECT = "https://finanzen.example.ts.net/connect/callback"
PSU = PsuHeaders("192.0.2.10", "Mozilla/5.0 (iPhone)")


def connect(provider, fake, bank, state="state-1"):
    url = provider.start_consent(Institution(bank, "AT"), REDIRECT, state,
                                 datetime.now(timezone.utc) + timedelta(days=180))
    redirect = fake.approve(url)
    query = parse_qs(urlparse(redirect).query)
    assert query["state"] == [state]
    return provider.complete_consent(query["code"][0])


def all_tx(provider, account, days=400, psu=PSU):
    return list(provider.fetch_transactions(account.uid, TODAY - timedelta(days=days), psu=psu))


# --- helpers ------------------------------------------------------------------

def test_make_iban_has_valid_checksum():
    iban = make_iban("AT", "4501000000123456")
    digits = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    assert int(digits) % 97 == 1


def test_salary_day_moves_before_weekends_and_short_months():
    assert salary_day(2026, 8) == date(2026, 8, 28)    # 29.8.2026 is a Saturday
    assert salary_day(2026, 2) == date(2026, 2, 27)    # 28.2. is a Saturday
    assert salary_day(2026, 9) == date(2026, 9, 29)    # Tuesday


# --- auth and consent ---------------------------------------------------------

def test_institutions_listed(scenario, provider):
    names = {i.name for i in provider.list_institutions("AT")}
    assert {VOLKSBANK, FLATEX, PAYPAL, PAYLIFE} <= names
    paypal = next(i for i in provider.list_institutions("AT") if i.name == PAYPAL)
    assert paypal.max_consent_days == 90


def test_wrong_key_is_rejected(scenario, fake, keypair):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    bad = EnableBankingProvider(APP_ID, other, transport=fake)
    with pytest.raises(ApplicationError):
        bad.list_institutions("AT")


def test_unknown_application_id_is_rejected(scenario, fake, keypair):
    bad = EnableBankingProvider("someone-else", keypair[0], transport=fake)
    with pytest.raises(ApplicationError):
        bad.list_institutions("AT")


def test_jwt_is_reused_and_renewed(scenario, provider, fake, clock):
    provider.list_institutions("AT")
    provider.list_institutions("AT")
    first, second = (c.headers["Authorization"] for c in fake.calls[-2:])
    assert first == second
    clock.advance(hours=2)
    provider.list_institutions("AT")  # would fail with an expired token
    assert fake.calls[-1].headers["Authorization"] != first


def test_consent_flow_returns_accounts(scenario, provider, fake):
    session = connect(provider, fake, VOLKSBANK)
    assert len(session.accounts) == 1
    acc = session.accounts[0]
    assert acc.iban == GIRO_IBAN
    assert acc.owner_name == "Max Mustermann"
    assert acc.name == "Gehaltskonto"  # product, not the owner's name
    assert acc.credit_limit_minor == 150000
    assert session.valid_until > datetime.now(timezone.utc) + timedelta(days=170)


def test_consent_validity_capped_by_bank_maximum(scenario, provider, fake, clock):
    session = connect(provider, fake, PAYPAL)
    assert session.valid_until <= clock() + timedelta(days=90)
    assert {a.currency for a in session.accounts} == {"EUR", "USD"}


def test_renewed_consent_changes_uid_but_not_identification_hash(scenario, provider, fake):
    first = connect(provider, fake, VOLKSBANK).accounts[0]
    second = connect(provider, fake, VOLKSBANK, state="state-2").accounts[0]
    assert first.uid != second.uid
    assert first.identification_hash == second.identification_hash


def test_list_accounts_of_session(scenario, provider, fake):
    session = connect(provider, fake, PAYPAL)
    accounts = provider.list_accounts(session.session_id)
    assert {a.identification_hash for a in accounts} == {"hash-paypal-eur", "hash-paypal-usd"}


def test_restricted_application_returns_empty_session_until_linked(scenario, provider, fake):
    fake.restricted = True
    assert connect(provider, fake, VOLKSBANK).accounts == ()
    fake.linked_keys.add("hash-giro")
    assert len(connect(provider, fake, VOLKSBANK, state="s2").accounts) == 1


def test_redirect_must_be_https(scenario, provider):
    with pytest.raises(ApplicationError):
        provider.start_consent(Institution(VOLKSBANK, "AT"), "http://insecure/cb", "s",
                               datetime.now(timezone.utc) + timedelta(days=10))


def test_code_can_only_be_used_once(scenario, provider, fake):
    url = provider.start_consent(Institution(VOLKSBANK, "AT"), REDIRECT, "s",
                                 datetime.now(timezone.utc) + timedelta(days=10))
    code = parse_qs(urlparse(fake.approve(url)).query)["code"][0]
    provider.complete_consent(code)
    with pytest.raises(AuthorizationFailed):
        provider.complete_consent(code)


def test_denied_consent_redirects_with_error(scenario, provider, fake):
    url = provider.start_consent(Institution(VOLKSBANK, "AT"), REDIRECT, "s",
                                 datetime.now(timezone.utc) + timedelta(days=10))
    query = parse_qs(urlparse(fake.deny(url)).query)
    assert query["error"] == ["access_denied"] and query["state"] == ["s"]


# --- data ---------------------------------------------------------------------

def test_paging_returns_everything(scenario, provider, fake):
    fake.page_size = 7
    acc = connect(provider, fake, VOLKSBANK).accounts[0]
    txs = all_tx(provider, acc)
    assert len(txs) == len(scenario.giro.transactions)
    pages = [c for c in fake.calls if c.url.endswith("/transactions")]
    assert len(pages) > 3
    assert "continuation_key" in pages[-1].params


def test_transactions_are_parsed(scenario, provider, fake):
    acc = connect(provider, fake, VOLKSBANK).accounts[0]
    txs = all_tx(provider, acc)
    rent = next(t for t in txs if "MIETE" in t.remittance)
    assert rent.amount_minor == -95000 and rent.currency == "EUR"
    assert rent.counterparty_name == "Hausverwaltung Sonnenhof"
    assert rent.status == "booked"
    salary = next(t for t in txs if t.remittance.startswith("GEHALT"))
    assert salary.amount_minor == 324000
    assert salary.counterparty_name == "Beispiel Technik GmbH"
    pending = next(t for t in txs if t.entry_reference == "VB-PEND-1")
    assert pending.status == "pending" and pending.booking_date is None
    assert pending.date == TODAY - timedelta(days=1)
    assert pending.mcc == "5411"


def test_foreign_currency_is_kept(scenario, provider, fake):
    session = connect(provider, fake, PAYLIFE)
    gbp = next(t for t in all_tx(provider, session.accounts[0]) if t.entry_reference == "PL-GBP-1")
    assert (gbp.amount_minor, gbp.currency) == (-2761, "EUR")
    assert (gbp.original_amount_minor, gbp.original_currency) == (-2350, "GBP")

    paypal = connect(provider, fake, PAYPAL, state="s2")
    usd_acc = next(a for a in paypal.accounts if a.currency == "USD")
    usd = next(t for t in all_tx(provider, usd_acc) if t.entry_reference == "PP-USD-1")
    assert (usd.amount_minor, usd.currency) == (-1299, "USD")


def test_paypal_with_and_without_funding_line(scenario, provider, fake):
    session = connect(provider, fake, PAYPAL)
    eur = next(a for a in session.accounts if a.currency == "EUR")
    texts = [t.remittance for t in all_tx(provider, eur)]
    assert any("Zalando" in t for t in texts)
    assert any("Bankgutschrift" in t for t in texts)
    giro = connect(provider, fake, VOLKSBANK, state="s2").accounts[0]
    assert any("PP.4711.PP" in t.remittance for t in all_tx(provider, giro))


def test_duplicate_records_are_passed_through(scenario, provider, fake):
    acc = connect(provider, fake, VOLKSBANK).accounts[0]
    dups = [t for t in all_tx(provider, acc) if t.entry_reference == "VB-DUP-1"]
    assert len(dups) == 2  # deduplication is the job of the sync layer


def test_pending_gets_booked_with_new_reference(scenario, provider, fake):
    acc = connect(provider, fake, VOLKSBANK).accounts[0]
    fake.book_pending("hash-giro", "VB-PEND-1", TODAY, amount="23.95")
    txs = all_tx(provider, acc)
    assert not any(t.entry_reference == "VB-PEND-1" for t in txs)
    booked = next(t for t in txs if t.entry_reference == "VB-PEND-1-B")
    assert booked.status == "booked" and booked.amount_minor == -2395


def test_full_history_only_in_first_hour(scenario, provider, fake, clock):
    acc = connect(provider, fake, VOLKSBANK).accounts[0]
    assert any(t.entry_reference == "VB-OLD-1" for t in all_tx(provider, acc))
    clock.advance(hours=2)
    later = all_tx(provider, acc)
    assert not any(t.entry_reference == "VB-OLD-1" for t in later)
    assert min(t.date for t in later) >= clock().date() - timedelta(days=90)


def test_balances_prefer_booked_over_available(scenario, provider, fake):
    card = connect(provider, fake, PAYLIFE).accounts[0]
    balances = provider.fetch_balances(card.uid, psu=PSU)
    assert {b.balance_type for b in balances} == {"CLBD", "ITAV"}
    chosen = pick_balance(balances)
    assert chosen.balance_type == "CLBD"
    assert chosen.amount_minor < 0  # card debt, not the positive available limit


# --- limits and failures ------------------------------------------------------

def test_unattended_fetches_are_rate_limited(scenario, provider, fake):
    acc = connect(provider, fake, FLATEX).accounts[0]
    for _ in range(4):
        provider.fetch_balances(acc.uid)
    with pytest.raises(RateLimited) as exc:
        provider.fetch_balances(acc.uid)
    assert exc.value.code == "ASPSP_RATE_LIMIT_EXCEEDED"
    assert exc.value.retry_after_seconds == 6 * 3600
    # user-triggered fetches with PSU headers are not limited
    for _ in range(5):
        provider.fetch_balances(acc.uid, psu=PSU)


def test_paging_counts_as_one_access(scenario, provider, fake):
    fake.page_size = 5
    acc = connect(provider, fake, VOLKSBANK).accounts[0]
    for _ in range(4):
        list(provider.fetch_transactions(acc.uid, TODAY - timedelta(days=60)))


def test_tailscale_psu_ip_is_rejected(scenario, provider, fake):
    acc = connect(provider, fake, VOLKSBANK).accounts[0]
    with pytest.raises(PsuHeadersRejected):
        provider.fetch_balances(acc.uid, psu=PsuHeaders("100.101.5.7", "Safari"))
    provider.fetch_balances(acc.uid)  # retried unattended


def test_expired_session(scenario, provider, fake):
    session = connect(provider, fake, EXPIRED_BANK)
    fake.expire_session(session.session_id)
    with pytest.raises(ConsentExpired) as exc:
        provider.fetch_balances(session.accounts[0].uid, psu=PSU)
    assert exc.value.code == "EXPIRED_SESSION"


def test_closed_session(scenario, provider, fake):
    session = connect(provider, fake, VOLKSBANK)
    provider.close_session(session.session_id)
    with pytest.raises(ConsentExpired):
        all_tx(provider, session.accounts[0])


@pytest.mark.parametrize("status,body,expected", [
    (429, {}, RateLimited),
    (500, {"error": "ASPSP_ERROR"}, BankUnavailable),
    (422, {"error": "WRONG_AUTHORIZATION_CODE"}, AuthorizationFailed),
    (401, {"error": "EXPIRED_SESSION"}, ConsentExpired),
    (400, {"error": "ASPSP_PSU_ACTION_REQUIRED"}, ConsentExpired),
    (422, {"error": "WRONG_SESSION_STATUS"}, ConsentExpired),
    (400, {"error": "ASPSP_ACCOUNT_NOT_ACCESSIBLE"}, BankUnavailable),
    (400, {"error": "ACCESS_DENIED"}, AuthorizationFailed),
    (401, {"error": "UNAUTHORIZED_ACCESS"}, ApplicationError),
    (400, {"error": "UNAUTHORIZED_IP"}, ApplicationError),
    (403, {}, ApplicationError),
    (418, {"error": "SOMETHING_NEW"}, BankError),
])
def test_error_mapping(status, body, expected):
    with pytest.raises(expected):
        raise_for_error(HttpResponse(status, body))
