"""Enable Banking client (https://enablebanking.com/docs/api/reference/).

API ASSUMPTIONS – written without access to the current docs. Verify against
the API reference before connecting a real bank (build step 8); everything
provider-specific lives in this file and in `fake.py`:

- Auth: JWT RS256, header `kid` = application id, claims iss
  "enablebanking.com", aud "api.enablebanking.com", iat, exp (max 24 h).
- GET  /aspsps?country=AT            -> {"aspsps": [{name, country, maximum_consent_validity, psu_types}]}
- POST /auth                         -> {"url", "authorization_id"}
- POST /sessions {"code"}            -> {"session_id", "accounts": [AccountResource], "aspsp", "access": {"valid_until"}}
- GET  /sessions/{id}                -> {"accounts": [uid], "access", "status"}
- DELETE /sessions/{id}
- GET  /accounts/{uid}/details       -> AccountResource
- GET  /accounts/{uid}/balances      -> {"balances": [{balance_amount: {amount, currency}, balance_type, reference_date, name}]}
- GET  /accounts/{uid}/transactions?date_from&date_to&continuation_key
                                     -> {"transactions": [...], "continuation_key"}
- Amounts are positive decimal strings; `credit_debit_indicator` CRDT/DBIT
  gives the sign; `status` BOOK/PDNG.
- PSU headers: Psu-Ip-Address, Psu-User-Agent.
- Errors: {"code": <http>, "error": "<CODE>", "message": "...", "detail": ...}.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Iterator, Optional

import jwt

from ..money import to_minor
from .provider import (
    AccountInfo, ApplicationError, AuthorizationFailed, Balance, BankError,
    BankUnavailable, ConsentExpired, Institution, PsuHeaders, PsuHeadersRejected,
    RateLimited, RawTransaction, Session,
)

API_BASE = "https://api.enablebanking.com"
JWT_LIFETIME_SECONDS = 3600


# --- transport --------------------------------------------------------------

@dataclass
class HttpRequest:
    method: str
    url: str
    headers: dict
    params: Optional[dict] = None
    json: Optional[dict] = None


@dataclass
class HttpResponse:
    status: int
    json: Optional[dict]


Transport = Callable[[HttpRequest], HttpResponse]


def requests_transport(timeout: float = 30.0) -> Transport:
    import requests

    http = requests.Session()

    def send(req: HttpRequest) -> HttpResponse:
        try:
            resp = http.request(req.method, req.url, headers=req.headers,
                                params=req.params, json=req.json, timeout=timeout)
        except requests.RequestException as exc:
            raise BankUnavailable(f"network error: {type(exc).__name__}") from exc
        try:
            body = resp.json() if resp.content else None
        except ValueError:
            body = None
        return HttpResponse(resp.status_code, body)

    return send


# --- error mapping ----------------------------------------------------------

_CONSENT_ERRORS = {"EXPIRED_SESSION", "CLOSED_SESSION", "REVOKED_SESSION",
                   "INVALID_SESSION", "SESSION_DOES_NOT_EXIST", "ACCOUNT_DOES_NOT_EXIST",
                   "EXPIRED_ACCESS"}
_RATE_LIMIT_ERRORS = {"ASPSP_RATE_LIMIT_EXCEEDED", "RATE_LIMIT_EXCEEDED"}
_PSU_ERRORS = {"WRONG_PSU_IP_ADDRESS", "INVALID_PSU_HEADERS", "PSU_HEADER_NOT_PROVIDED",
               "WRONG_PSU_HEADERS"}
_AUTH_ERRORS = {"AUTHORIZATION_NOT_PROVIDED", "WRONG_AUTHORIZATION_CODE",
                "EXPIRED_AUTHORIZATION_CODE", "ALREADY_AUTHORIZED"}
_APP_ERRORS = {"WRONG_JWT", "EXPIRED_JWT", "INVALID_JWT", "UNTRUSTED_APPLICATION",
               "APPLICATION_NOT_ACTIVE", "REDIRECT_URI_NOT_ALLOWED", "UNAUTHORIZED"}


def raise_for_error(resp: HttpResponse) -> None:
    if 200 <= resp.status < 300:
        return
    body = resp.json or {}
    code = body.get("error") if isinstance(body, dict) else None
    message = (body.get("message") if isinstance(body, dict) else None) or f"HTTP {resp.status}"
    if code in _RATE_LIMIT_ERRORS or resp.status == 429:
        raise RateLimited(message, code)
    if code in _CONSENT_ERRORS:
        raise ConsentExpired(message, code)
    if code in _PSU_ERRORS:
        raise PsuHeadersRejected(message, code)
    if code in _AUTH_ERRORS:
        raise AuthorizationFailed(message, code)
    if code in _APP_ERRORS or resp.status in (401, 403):
        raise ApplicationError(message, code)
    if resp.status >= 500 or code in {"ASPSP_ERROR", "ASPSP_TIMEOUT"}:
        raise BankUnavailable(message, code)
    raise BankError(message, code)


# --- parsing ----------------------------------------------------------------

def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def _parse_datetime(value) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_institution(data: dict) -> Institution:
    max_seconds = data.get("maximum_consent_validity")
    return Institution(
        name=data["name"],
        country=data["country"],
        max_consent_days=int(max_seconds) // 86400 if max_seconds else None,
        psu_types=tuple(data.get("psu_types") or ("personal",)),
    )


def parse_account(data: dict) -> AccountInfo:
    account_id = data.get("account_id") or {}
    credit_limit = data.get("credit_limit")
    currency = data.get("currency") or "EUR"
    return AccountInfo(
        uid=data["uid"],
        identification_hash=data.get("identification_hash") or data["uid"],
        currency=currency,
        iban=account_id.get("iban"),
        name=data.get("product") or data.get("details") or None,
        owner_name=data.get("name"),
        cash_account_type=data.get("cash_account_type"),
        product=data.get("product"),
        credit_limit_minor=(to_minor(credit_limit["amount"], credit_limit.get("currency", currency))
                            if credit_limit else None),
    )


def parse_balance(data: dict) -> Balance:
    amount = data["balance_amount"]
    return Balance(
        amount_minor=to_minor(amount["amount"], amount["currency"]),
        currency=amount["currency"],
        balance_type=data.get("balance_type") or "OTHR",
        reference_date=_parse_date(data.get("reference_date")),
        name=data.get("name"),
    )


def parse_transaction(data: dict) -> RawTransaction:
    amount = data["transaction_amount"]
    currency = amount["currency"]
    minor = abs(to_minor(amount["amount"], currency))
    debit = data.get("credit_debit_indicator") == "DBIT"
    signed = -minor if debit else minor

    party = data.get("creditor") if debit else data.get("debtor")
    party_account = data.get("creditor_account") if debit else data.get("debtor_account")
    remittance = data.get("remittance_information") or []
    if isinstance(remittance, str):
        remittance = [remittance]

    original_minor = original_currency = None
    instructed = (data.get("exchange_rate") or {}).get("instructed_amount") or {}
    if instructed.get("currency") and instructed.get("amount") is not None:
        original_currency = instructed["currency"]
        original_minor = abs(to_minor(instructed["amount"], original_currency))
        original_minor = -original_minor if debit else original_minor

    status = data.get("status") or "BOOK"
    return RawTransaction(
        status="pending" if status in ("PDNG", "pending") else "booked",
        amount_minor=signed,
        currency=currency,
        booking_date=_parse_date(data.get("booking_date")),
        value_date=_parse_date(data.get("value_date")),
        transaction_date=_parse_date(data.get("transaction_date")),
        entry_reference=data.get("entry_reference"),
        transaction_id=data.get("transaction_id"),
        counterparty_name=(party or {}).get("name"),
        counterparty_iban=(party_account or {}).get("iban"),
        remittance=" ".join(str(r) for r in remittance).strip(),
        mcc=data.get("merchant_category_code"),
        bank_code=((data.get("bank_transaction_code") or {}).get("description")
                   or (data.get("bank_transaction_code") or {}).get("code")),
        original_amount_minor=original_minor,
        original_currency=original_currency,
        raw=data,
    )


# --- client -----------------------------------------------------------------

class EnableBankingProvider:
    def __init__(self, application_id: str, private_key_pem: bytes,
                 transport: Optional[Transport] = None, base_url: str = API_BASE,
                 clock: Callable[[], float] = time.time):
        self._app_id = application_id
        self._key = private_key_pem
        self._send = transport or requests_transport()
        self._base = base_url.rstrip("/")
        self._clock = clock
        self._token: Optional[str] = None
        self._token_exp = 0.0

    # -- plumbing

    def _jwt(self) -> str:
        now = self._clock()
        if self._token is None or now > self._token_exp - 60:
            iat = int(now)
            self._token_exp = iat + JWT_LIFETIME_SECONDS
            self._token = jwt.encode(
                {"iss": "enablebanking.com", "aud": "api.enablebanking.com",
                 "iat": iat, "exp": int(self._token_exp)},
                self._key, algorithm="RS256", headers={"kid": self._app_id},
            )
        return self._token

    def _call(self, method: str, path: str, params: Optional[dict] = None,
              body: Optional[dict] = None, psu: Optional[PsuHeaders] = None) -> dict:
        headers = {"Authorization": f"Bearer {self._jwt()}", "Accept": "application/json"}
        if psu is not None:
            headers["Psu-Ip-Address"] = psu.ip_address
            headers["Psu-User-Agent"] = psu.user_agent
        resp = self._send(HttpRequest(method, self._base + path, headers, params, body))
        raise_for_error(resp)
        return resp.json or {}

    # -- BankProvider

    def application(self) -> dict:
        return self._call("GET", "/application")

    def list_institutions(self, country: str) -> list[Institution]:
        data = self._call("GET", "/aspsps", params={"country": country})
        return [parse_institution(a) for a in data.get("aspsps", [])]

    def start_consent(self, institution: Institution, redirect_url: str,
                      state: str, valid_until: datetime) -> str:
        data = self._call("POST", "/auth", body={
            "access": {"valid_until": valid_until.astimezone(timezone.utc).isoformat()},
            "aspsp": {"name": institution.name, "country": institution.country},
            "state": state,
            "redirect_url": redirect_url,
            "psu_type": "personal",
        })
        return data["url"]

    def complete_consent(self, code: str) -> Session:
        data = self._call("POST", "/sessions", body={"code": code})
        aspsp = data.get("aspsp") or {}
        return Session(
            session_id=data["session_id"],
            institution=Institution(aspsp.get("name", ""), aspsp.get("country", "")),
            accounts=tuple(parse_account(a) for a in data.get("accounts", [])),
            valid_until=_parse_datetime((data.get("access") or {})["valid_until"]),
        )

    def list_accounts(self, session_id: str) -> list[AccountInfo]:
        data = self._call("GET", f"/sessions/{session_id}")
        accounts = []
        for item in data.get("accounts", []):
            uid = item if isinstance(item, str) else item["uid"]
            accounts.append(parse_account(self._call("GET", f"/accounts/{uid}/details")))
        return accounts

    def fetch_balances(self, account_uid: str,
                       psu: Optional[PsuHeaders] = None) -> list[Balance]:
        data = self._call("GET", f"/accounts/{account_uid}/balances", psu=psu)
        return [parse_balance(b) for b in data.get("balances", [])]

    def fetch_transactions(self, account_uid: str, date_from: date,
                           date_to: Optional[date] = None,
                           psu: Optional[PsuHeaders] = None) -> Iterator[RawTransaction]:
        params = {"date_from": date_from.isoformat()}
        if date_to:
            params["date_to"] = date_to.isoformat()
        seen_keys = set()
        while True:
            data = self._call("GET", f"/accounts/{account_uid}/transactions",
                              params=params, psu=psu)
            for item in data.get("transactions", []):
                yield parse_transaction(item)
            key = data.get("continuation_key")
            if not key or key in seen_keys:
                return
            seen_keys.add(key)
            params = {**params, "continuation_key": key}

    def close_session(self, session_id: str) -> None:
        self._call("DELETE", f"/sessions/{session_id}")
