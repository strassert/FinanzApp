"""Bank provider interface.

Everything outside `finanzen.bank` talks to banks only through `BankProvider`
and the plain data types below. No provider-specific JSON leaks out, except
`RawTransaction.raw`, which is stored for later re-parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterator, Optional, Protocol


# --- data types -------------------------------------------------------------

@dataclass(frozen=True)
class Institution:
    name: str
    country: str
    max_consent_days: Optional[int] = None
    psu_types: tuple[str, ...] = ("personal",)


@dataclass(frozen=True)
class AccountInfo:
    uid: str                          # changes with every session
    identification_hash: str          # stable across sessions – use for matching
    currency: str
    iban: Optional[str] = None        # internal only, never returned in full by our API
    name: Optional[str] = None        # product/account name from the bank, if any
    owner_name: Optional[str] = None  # used to detect transfers to oneself, not as label
    cash_account_type: Optional[str] = None  # e.g. CACC (current), CARD, SVGS
    product: Optional[str] = None
    credit_limit_minor: Optional[int] = None


@dataclass(frozen=True)
class Session:
    session_id: str
    institution: Institution
    accounts: tuple[AccountInfo, ...]
    valid_until: datetime


@dataclass(frozen=True)
class Balance:
    amount_minor: int
    currency: str
    balance_type: str                 # ISO 20022 code: CLBD, ITBD, XPCD, ITAV, ...
    reference_date: Optional[date] = None
    name: Optional[str] = None


# Booked/current balance types, preferred over "available" (which includes the
# credit limit). Order = preference.
PREFERRED_BALANCE_TYPES = ("XPCD", "ITBD", "CLBD", "ITAV", "CLAV", "XPAV", "OPBD")


def pick_balance(balances: list[Balance]) -> Optional[Balance]:
    """Pick the balance that best represents what the account holds or owes."""
    by_type = {b.balance_type: b for b in balances}
    for balance_type in PREFERRED_BALANCE_TYPES:
        if balance_type in by_type:
            return by_type[balance_type]
    return balances[0] if balances else None


@dataclass(frozen=True)
class RawTransaction:
    status: str                       # "booked" | "pending"
    amount_minor: int                 # signed: negative = money leaves the account
    currency: str
    booking_date: Optional[date]
    value_date: Optional[date] = None
    transaction_date: Optional[date] = None
    entry_reference: Optional[str] = None
    transaction_id: Optional[str] = None
    counterparty_name: Optional[str] = None
    counterparty_iban: Optional[str] = None
    remittance: str = ""
    mcc: Optional[str] = None
    bank_code: Optional[str] = None
    original_amount_minor: Optional[int] = None   # in instructed currency, if converted
    original_currency: Optional[str] = None
    raw: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def date(self) -> Optional[date]:
        return self.booking_date or self.value_date or self.transaction_date


@dataclass(frozen=True)
class PsuHeaders:
    """Sent when the user triggers a fetch; such fetches do not count against
    the bank's unattended-access limit."""
    ip_address: str
    user_agent: str


# --- errors -----------------------------------------------------------------

class BankError(Exception):
    """Base class. `code` is the provider's error code, if any."""

    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.code = code


class ConsentExpired(BankError):
    """Session expired, closed or revoked: the user must renew the consent."""


class RateLimited(BankError):
    """The bank refuses further unattended fetches for now."""

    def __init__(self, message: str, code: Optional[str] = None,
                 retry_after_seconds: int = 6 * 3600):
        super().__init__(message, code)
        self.retry_after_seconds = retry_after_seconds


class PsuHeadersRejected(BankError):
    """The bank rejected the PSU headers (e.g. a Tailscale 100.x IP).
    Retry as an unattended fetch."""


class AuthorizationFailed(BankError):
    """The consent flow failed or the authorization code is invalid."""


class BankUnavailable(BankError):
    """Temporary problem at the bank or the aggregator; retry later."""


class ApplicationError(BankError):
    """Our application is misconfigured (key, id, redirect URL, not activated)."""


# --- interface --------------------------------------------------------------

class BankProvider(Protocol):
    def list_institutions(self, country: str) -> list[Institution]: ...

    def start_consent(self, institution: Institution, redirect_url: str,
                      state: str, valid_until: datetime) -> str:
        """Return the URL to open in the real browser."""

    def complete_consent(self, code: str) -> Session: ...

    def list_accounts(self, session_id: str) -> list[AccountInfo]: ...

    def fetch_balances(self, account_uid: str,
                       psu: Optional[PsuHeaders] = None) -> list[Balance]: ...

    def fetch_transactions(self, account_uid: str, date_from: date,
                           date_to: Optional[date] = None,
                           psu: Optional[PsuHeaders] = None) -> Iterator[RawTransaction]:
        """Yield all transactions, following pagination."""

    def close_session(self, session_id: str) -> None: ...
