"""In-process fake of the Enable Banking API.

Used as a `Transport` for `EnableBankingProvider`, so tests exercise the real
client (JWT, paging, error mapping) without network. The same fake backs the
local demo server later.

Simulated behaviour:
- consent flow: POST /auth -> `approve()` (the user at the bank) -> POST /sessions
- new account `uid`s for every session, stable `identification_hash`
- restricted application: only linked accounts appear in a session
- paging via `continuation_key`
- full history only within the first hour after consent, else the last 90 days
- unattended fetches limited per account and day (ASPSP_RATE_LIMIT_EXCEEDED);
  fetches with PSU headers do not count
- PSU IPs in 100.64.0.0/10 (Tailscale) rejected
- expired / closed sessions
- pending transactions that later get booked under a new entry_reference
"""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import jwt

from .enablebanking import HttpRequest, HttpResponse

FAKE_AUTH_HOST = "https://fake-bank.invalid"


def _err(status: int, code: str, message: str) -> HttpResponse:
    return HttpResponse(status, {"code": status, "error": code, "message": message, "detail": None})


def _is_tailscale_ip(ip: str) -> bool:
    parts = ip.split(".")
    return len(parts) == 4 and parts[0] == "100" and 64 <= int(parts[1]) <= 127


@dataclass
class FakeAccount:
    bank: str
    resource: dict                    # AccountResource without uid
    transactions: list[dict] = field(default_factory=list)
    balances: list[dict] = field(default_factory=list)

    @property
    def key(self) -> str:
        return self.resource["identification_hash"]


@dataclass
class FakeSession:
    session_id: str
    bank: str
    country: str
    created_at: datetime
    valid_until: datetime
    uids: dict[str, str]              # uid -> account key
    status: str = "AUTHORIZED"


class FakeEnableBanking:
    def __init__(self, application_id: str, public_key_pem: bytes,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 page_size: int = 50, unattended_daily_limit: int = 4,
                 restricted: bool = False):
        self.application_id = application_id
        self._public_key = public_key_pem
        self.now = now
        self.page_size = page_size
        self.unattended_daily_limit = unattended_daily_limit
        self.restricted = restricted
        self.linked_keys: set[str] = set()      # used when restricted
        self.redirect_urls: set[str] = set()    # empty = any https URL allowed
        self.institutions: dict[tuple[str, str], dict] = {}
        self.accounts: dict[str, FakeAccount] = {}
        self.sessions: dict[str, FakeSession] = {}
        self._auths: dict[str, dict] = {}
        self._codes: dict[str, str] = {}        # code -> authorization id
        self._unattended: dict[tuple[str, date], int] = {}
        self.force_rate_limit = False
        self.calls: list[HttpRequest] = []

    # --- setup ----------------------------------------------------------------

    def add_institution(self, name: str, country: str = "AT",
                        max_consent_days: int = 180) -> None:
        self.institutions[(name, country)] = {
            "name": name, "country": country,
            "maximum_consent_validity": max_consent_days * 86400,
            "psu_types": ["personal"],
        }

    def add_account(self, account: FakeAccount) -> FakeAccount:
        self.accounts[account.key] = account
        return account

    # --- simulated user / bank actions ---------------------------------------

    def approve(self, auth_url: str) -> str:
        """The user approves at the bank. Returns the redirect URL (with code+state)."""
        auth_id = parse_qs(urlparse(auth_url).query)["authorization_id"][0]
        auth = self._auths[auth_id]
        code = secrets.token_urlsafe(16)
        self._codes[code] = auth_id
        return auth["redirect_url"] + "?" + urlencode({"code": code, "state": auth["state"]})

    def deny(self, auth_url: str) -> str:
        auth_id = parse_qs(urlparse(auth_url).query)["authorization_id"][0]
        auth = self._auths[auth_id]
        return auth["redirect_url"] + "?" + urlencode(
            {"error": "access_denied", "state": auth["state"]})

    def expire_session(self, session_id: str) -> None:
        self.sessions[session_id].valid_until = self.now() - timedelta(seconds=1)

    def book_pending(self, account_key: str, entry_reference: str,
                     booking_date: date, new_reference: Optional[str] = None,
                     amount: Optional[str] = None) -> dict:
        """Replace a pending transaction with its booked version (new reference,
        possibly a slightly different amount, as banks do)."""
        account = self.accounts[account_key]
        for i, tx in enumerate(account.transactions):
            if tx.get("entry_reference") == entry_reference and tx["status"] == "PDNG":
                booked = dict(tx, status="BOOK", booking_date=booking_date.isoformat(),
                              entry_reference=new_reference or entry_reference + "-B")
                if amount is not None:
                    booked["transaction_amount"] = dict(tx["transaction_amount"], amount=amount)
                account.transactions[i] = booked
                return booked
        raise KeyError(entry_reference)

    # --- transport ------------------------------------------------------------

    def __call__(self, req: HttpRequest) -> HttpResponse:
        self.calls.append(req)
        auth_error = self._check_jwt(req.headers.get("Authorization", ""))
        if auth_error:
            return auth_error
        path = urlparse(req.url).path.rstrip("/")
        parts = path.strip("/").split("/")
        m = req.method.upper()
        if m == "GET" and path == "/application":
            return HttpResponse(200, {"name": "fake", "active": True,
                                      "redirect_urls": sorted(self.redirect_urls)})
        if m == "GET" and path == "/aspsps":
            country = (req.params or {}).get("country")
            return HttpResponse(200, {"aspsps": [i for (n, c), i in self.institutions.items()
                                                 if country in (None, c)]})
        if m == "POST" and path == "/auth":
            return self._start_auth(req.json or {})
        if m == "POST" and path == "/sessions":
            return self._create_session((req.json or {}).get("code"))
        if len(parts) == 2 and parts[0] == "sessions":
            return self._session(m, parts[1])
        if len(parts) == 3 and parts[0] == "accounts" and m == "GET":
            return self._account(parts[1], parts[2], req)
        return _err(404, "NOT_FOUND", f"{m} {path}")

    # --- handlers -------------------------------------------------------------

    def _check_jwt(self, header: str) -> Optional[HttpResponse]:
        if not header.startswith("Bearer "):
            return _err(401, "UNAUTHORIZED", "missing token")
        token = header[len("Bearer "):]
        try:
            if jwt.get_unverified_header(token).get("kid") != self.application_id:
                return _err(401, "UNTRUSTED_APPLICATION", "unknown kid")
            claims = jwt.decode(token, self._public_key, algorithms=["RS256"],
                                audience="api.enablebanking.com", issuer="enablebanking.com",
                                options={"verify_exp": False, "verify_iat": False,
                                         "verify_nbf": False})
        except jwt.PyJWTError as exc:
            return _err(401, "WRONG_JWT", type(exc).__name__)
        now = self.now().timestamp()
        if claims["iat"] > now + 60:
            return _err(401, "WRONG_JWT", "issued in the future")
        if claims["exp"] < now:
            return _err(401, "EXPIRED_JWT", "token expired")
        if claims["exp"] - claims["iat"] > 86400:
            return _err(401, "WRONG_JWT", "lifetime above 24h")
        return None

    def _start_auth(self, body: dict) -> HttpResponse:
        aspsp = body.get("aspsp") or {}
        inst = self.institutions.get((aspsp.get("name"), aspsp.get("country")))
        if inst is None:
            return _err(422, "ASPSP_NOT_FOUND", "unknown institution")
        redirect = body.get("redirect_url") or ""
        if not redirect.startswith("https://") or (self.redirect_urls and redirect not in self.redirect_urls):
            return _err(422, "REDIRECT_URI_NOT_ALLOWED", "redirect url not allowed")
        valid_until = datetime.fromisoformat(body["access"]["valid_until"].replace("Z", "+00:00"))
        max_until = self.now() + timedelta(seconds=inst["maximum_consent_validity"])
        auth_id = secrets.token_hex(8)
        self._auths[auth_id] = {
            "bank": inst["name"], "country": inst["country"], "state": body.get("state"),
            "redirect_url": redirect, "valid_until": min(valid_until, max_until),
        }
        return HttpResponse(200, {"url": f"{FAKE_AUTH_HOST}/authorize?authorization_id={auth_id}",
                                  "authorization_id": auth_id})

    def _create_session(self, code: Optional[str]) -> HttpResponse:
        auth_id = self._codes.pop(code or "", None)
        if auth_id is None:
            return _err(422, "WRONG_AUTHORIZATION_CODE", "invalid code")
        auth = self._auths.pop(auth_id)
        session_id = secrets.token_hex(16)
        uids = {}
        for key, acc in self.accounts.items():
            if acc.bank != auth["bank"]:
                continue
            if self.restricted and key not in self.linked_keys:
                continue
            uids[secrets.token_hex(12)] = key
        session = FakeSession(session_id, auth["bank"], auth["country"], self.now(),
                              auth["valid_until"], uids)
        self.sessions[session_id] = session
        return HttpResponse(200, {
            "session_id": session_id,
            "accounts": [self._resource(uid) for uid in uids],
            "aspsp": {"name": auth["bank"], "country": auth["country"]},
            "psu_type": "personal",
            "access": {"valid_until": session.valid_until.isoformat()},
        })

    def _session(self, method: str, session_id: str) -> HttpResponse:
        session = self.sessions.get(session_id)
        if session is None:
            return _err(404, "SESSION_DOES_NOT_EXIST", "no such session")
        if method == "DELETE":
            session.status = "CLOSED"
            return HttpResponse(200, {"message": "OK"})
        return HttpResponse(200, {
            "status": self._session_status(session),
            "accounts": list(session.uids),
            "aspsp": {"name": session.bank, "country": session.country},
            "access": {"valid_until": session.valid_until.isoformat()},
        })

    def _session_status(self, session: FakeSession) -> str:
        if session.status == "CLOSED":
            return "CLOSED"
        return "EXPIRED" if session.valid_until <= self.now() else "AUTHORIZED"

    def _resource(self, uid: str) -> dict:
        key = next(s.uids[uid] for s in self.sessions.values() if uid in s.uids)
        return dict(self.accounts[key].resource, uid=uid)

    def _account(self, uid: str, what: str, req: HttpRequest) -> HttpResponse:
        session = next((s for s in self.sessions.values() if uid in s.uids), None)
        if session is None:
            return _err(404, "ACCOUNT_DOES_NOT_EXIST", "no such account")
        status = self._session_status(session)
        if status == "CLOSED":
            return _err(401, "CLOSED_SESSION", "session closed")
        if status == "EXPIRED":
            return _err(401, "EXPIRED_SESSION", "session expired")
        account = self.accounts[session.uids[uid]]
        if what == "details":
            return HttpResponse(200, dict(account.resource, uid=uid))

        psu_ip = req.headers.get("Psu-Ip-Address")
        if psu_ip and _is_tailscale_ip(psu_ip):
            return _err(400, "WRONG_PSU_IP_ADDRESS", "PSU IP address not accepted")
        if what in ("balances", "transactions") and not psu_ip:
            if self.force_rate_limit:
                return _err(429, "ASPSP_RATE_LIMIT_EXCEEDED", "rate limit")
            # Count one unattended access per account per call to /balances or the
            # first page of /transactions.
            if what == "balances" or not (req.params or {}).get("continuation_key"):
                slot = (account.key, self.now().date())
                self._unattended[slot] = self._unattended.get(slot, 0) + 1
                if self._unattended[slot] > self.unattended_daily_limit:
                    return _err(429, "ASPSP_RATE_LIMIT_EXCEEDED", "rate limit")

        if what == "balances":
            return HttpResponse(200, {"balances": account.balances})
        if what == "transactions":
            return self._transactions(session, account, req.params or {})
        return _err(404, "NOT_FOUND", what)

    def _transactions(self, session: FakeSession, account: FakeAccount,
                      params: dict) -> HttpResponse:
        date_from = date.fromisoformat(params["date_from"]) if params.get("date_from") else date.min
        date_to = date.fromisoformat(params["date_to"]) if params.get("date_to") else date.max
        if self.now() - session.created_at > timedelta(hours=1):
            date_from = max(date_from, self.now().date() - timedelta(days=90))

        def tx_date(tx: dict) -> date:
            return date.fromisoformat(tx.get("booking_date") or tx.get("value_date")
                                      or tx["transaction_date"])

        items = [tx for tx in account.transactions if date_from <= tx_date(tx) <= date_to]
        items.sort(key=tx_date, reverse=True)
        offset = 0
        if params.get("continuation_key"):
            try:
                offset = int(base64.urlsafe_b64decode(params["continuation_key"]).decode())
            except ValueError:
                return _err(422, "WRONG_CONTINUATION_KEY", "bad continuation key")
        page = items[offset:offset + self.page_size]
        next_offset = offset + self.page_size
        key = (base64.urlsafe_b64encode(str(next_offset).encode()).decode()
               if next_offset < len(items) else None)
        return HttpResponse(200, {"transactions": page, "continuation_key": key})
