"""Linking: transfers, PayPal, refunds, duplicates, wallet notifications.

Pure function over plain rows; `recompute` loads the rows and stores the
result. Nothing is deleted: linking only decides the role of each
transaction (expense | income | transfer | excluded).

Evidence, strongest first (see README):
1. user decisions (confirmed pairs) and user exclusions
2. wallet notification + bank booking of the same payment -> duplicate
3. debit names the IBAN of an own account -> transfer
4. text matches the pattern of an own account -> transfer
   (PayPal without funding line: bank debit linked to the PayPal purchase)
5. counterparty is the account owner -> transfer
6. same amount on another own account within 3 days -> suggestion
7. credit from the same merchant within 120 days after a purchase -> refund
8. same amount, same account, from file import and API (+-1 day) -> suggestion
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

TRANSFER_WINDOW = 5
AMOUNT_ONLY_WINDOW = 3
PAYPAL_WINDOW = 4
REFUND_WINDOW = 120
WALLET_BEFORE, WALLET_AFTER = 2, 10
WALLET_FX_TOLERANCE = 0.03


@dataclass
class Tx:
    id: int
    account_id: int
    source: str
    date: date
    amount: int                       # minor units, own currency
    currency: str
    amount_eur: Optional[int] = None
    counterparty: str = ""
    counterparty_iban: str = ""
    description: str = ""
    user_excluded: bool = False

    @property
    def text(self) -> str:
        return f"{self.counterparty} {self.description}".upper()


@dataclass
class Account:
    id: int
    kind: str
    iban: str = ""
    patterns: tuple[str, ...] = ()
    owner_name: str = ""
    institution: str = ""


@dataclass
class Link:
    kind: str                         # transfer | paypal | refund | duplicate | wallet
    a_id: int
    b_id: Optional[int]
    status: str                       # auto | suggested | confirmed
    evidence: str


@dataclass
class Result:
    roles: dict[int, str] = field(default_factory=dict)
    links: list[Link] = field(default_factory=list)
    refund_of: dict[int, int] = field(default_factory=dict)   # refund id -> purchase id


def norm_iban(iban: Optional[str]) -> str:
    return re.sub(r"\s+", "", iban or "").upper()


def name_words(name: Optional[str]) -> frozenset[str]:
    words = re.findall(r"[A-ZÄÖÜß]+", (name or "").upper())
    return frozenset(w for w in words if len(w) > 1)


_MERCHANT_STOP = {"GUTSCHRIFT", "RUECKZAHLUNG", "RÜCKZAHLUNG", "ERSTATTUNG", "STORNO", "REFUND",
                  "DANKT", "ZAHLUNG", "AN", "VON", "FIL", "SE", "GMBH", "AG", "CO", "KG", "INC",
                  "LTD", "SARL", "BEI", "IHR", "EINKAUF", "RETOURE"}


def merchant_key(tx: Tx) -> str:
    base = tx.counterparty or tx.description
    words = [w for w in re.findall(r"[A-ZÄÖÜß]+", base.upper()) if w not in _MERCHANT_STOP and len(w) > 1]
    return " ".join(words[:2])


def link_all(txs: list[Tx], accounts: dict[int, Account],
             decisions: dict[tuple[str, int, int], str],
             extra_owner_names: tuple[str, ...] = ()) -> Result:
    res = Result()
    by_id = {t.id: t for t in txs}
    by_account: dict[int, list[Tx]] = {}
    for t in sorted(txs, key=lambda t: (t.date, t.id)):
        by_account.setdefault(t.account_id, []).append(t)
    used: set[int] = set()            # paired in a transfer / duplicate / wallet / paypal link
    suggested: set[int] = set()

    def rejected(kind: str, a: int, b: int) -> bool:
        return decisions.get((kind, a, b)) == "rejected" or decisions.get((kind, b, a)) == "rejected"

    def counterpart(t: Tx, account_ids, window: int, same_sign: bool = False,
                    amount: Optional[int] = None) -> Optional[Tx]:
        want = amount if amount is not None else (t.amount if same_sign else -t.amount)
        best = None
        for acc_id in account_ids:
            for c in by_account.get(acc_id, []):
                if c.id == t.id or c.id in used or c.currency != t.currency or c.amount != want:
                    continue
                gap = abs((c.date - t.date).days)
                if gap <= window and not rejected("transfer", t.id, c.id):
                    if best is None or gap < abs((best.date - t.date).days):
                        best = c
        return best

    # 1. user exclusions and confirmed decisions
    for t in txs:
        if t.user_excluded:
            res.roles[t.id] = "excluded"
    for (kind, a, b), decision in sorted(decisions.items()):
        if decision != "confirmed" or a not in by_id or b not in by_id or a in used or b in used:
            continue
        if kind == "duplicate":
            ta, tb = by_id[a], by_id[b]
            drop = ta if (ta.source == "import" and tb.source != "import") else tb
            res.roles.setdefault(drop.id, "excluded")
        else:
            res.roles.setdefault(a, "transfer")
            res.roles.setdefault(b, "transfer")
        res.links.append(Link(kind, a, b, "confirmed", "user"))
        used.update((a, b))

    # 2. wallet notifications vs. bank bookings
    for w in (t for t in txs if t.source == "wallet" and t.id not in used):
        best = None
        for c in by_account.get(w.account_id, []):
            if c.source == "wallet" or c.id in used or (c.amount < 0) != (w.amount < 0):
                continue
            if not (w.date - timedelta(days=WALLET_BEFORE) <= c.date <= w.date + timedelta(days=WALLET_AFTER)):
                continue
            if c.currency == w.currency:
                if c.amount != w.amount:
                    continue
            elif c.amount_eur is None or w.amount_eur is None or \
                    abs(c.amount_eur - w.amount_eur) > abs(w.amount_eur) * WALLET_FX_TOLERANCE:
                continue
            if best is None or abs((c.date - w.date).days) < abs((best.date - w.date).days):
                best = c
        if best:
            res.links.append(Link("wallet", best.id, w.id, "auto", "wallet"))
            res.roles.setdefault(w.id, "excluded")
            used.update((w.id, best.id))

    own_ibans = {norm_iban(a.iban): a.id for a in accounts.values() if a.iban}
    owners = {name_words(a.owner_name) for a in accounts.values() if len(name_words(a.owner_name)) >= 2}
    owners |= {name_words(n) for n in extra_owner_names if len(name_words(n)) >= 2}
    others = lambda acc_id: [a for a in accounts if a != acc_id]  # noqa: E731

    def mark_transfer(t: Tx, c: Optional[Tx], evidence: str, kind: str = "transfer") -> None:
        res.roles.setdefault(t.id, "transfer")
        used.add(t.id)
        if c is not None:
            if kind == "transfer":
                res.roles.setdefault(c.id, "transfer")
            used.add(c.id)
        res.links.append(Link(kind, t.id, c.id if c else None, "auto", evidence))

    candidates = [t for t in sorted(txs, key=lambda t: (t.date, t.id))
                  if t.id not in used and t.id not in res.roles and t.source != "wallet"]

    # 3. IBAN of an own account
    for t in candidates:
        if t.id in used:
            continue
        target = own_ibans.get(norm_iban(t.counterparty_iban))
        if target is not None and target != t.account_id:
            mark_transfer(t, counterpart(t, [target], TRANSFER_WINDOW), "iban")

    # 4. pattern of an own account
    for t in candidates:
        if t.id in used:
            continue
        text = t.text
        own = accounts.get(t.account_id)
        # Patterns point to another institution: "PAYPAL" on a PayPal account is not a transfer.
        target = next((a for a in accounts.values() if a.id != t.account_id and a.patterns
                       and not (own and own.institution and a.institution == own.institution)
                       and any(p and p.upper() in text for p in a.patterns)), None)
        if target is None:
            continue
        pair = counterpart(t, [target.id], PAYPAL_WINDOW if target.kind == "paypal" else TRANSFER_WINDOW)
        if pair is None and target.kind == "paypal" and t.amount < 0:
            purchase = counterpart(t, [target.id], PAYPAL_WINDOW, same_sign=True)
            if purchase is not None:
                mark_transfer(t, purchase, "pattern", kind="paypal")
                continue
        mark_transfer(t, pair, "pattern")

    # 5. counterparty is the owner
    for t in candidates:
        if t.id in used:
            continue
        words = name_words(t.counterparty)
        if len(words) >= 2 and any(words == o for o in owners):
            mark_transfer(t, counterpart(t, others(t.account_id), TRANSFER_WINDOW), "owner")

    # 6. amount only -> suggestion
    for t in candidates:
        if t.id in used or t.id in suggested or t.amount >= 0:
            continue
        for c in (c for acc in others(t.account_id) for c in by_account.get(acc, [])):
            if c.id in used or c.id in suggested or c.source == "wallet" or c.currency != t.currency:
                continue
            if c.amount == -t.amount and abs((c.date - t.date).days) <= AMOUNT_ONLY_WINDOW \
                    and not rejected("transfer", t.id, c.id):
                res.links.append(Link("transfer", t.id, c.id, "suggested", "amount"))
                suggested.update((t.id, c.id))
                break

    # 7. refunds
    purchases_by_key: dict[str, list[Tx]] = {}
    for t in txs:
        if t.amount < 0 and res.roles.get(t.id) is None:  # expenses (incl. PayPal-linked purchases)
            key = merchant_key(t)
            if key:
                purchases_by_key.setdefault(key, []).append(t)
    for t in sorted(txs, key=lambda t: (t.date, t.id)):
        if t.amount <= 0 or t.id in used or t.id in res.roles:
            continue
        key = merchant_key(t)
        options = [p for p in purchases_by_key.get(key, [])
                   if p.date <= t.date <= p.date + timedelta(days=REFUND_WINDOW)
                   and abs(p.amount_eur if p.amount_eur is not None else p.amount)
                   >= abs(t.amount_eur if t.amount_eur is not None else t.amount)]
        if options:
            purchase = max(options, key=lambda p: (p.date, p.id))
            res.roles[t.id] = "expense"
            res.refund_of[t.id] = purchase.id
            res.links.append(Link("refund", t.id, purchase.id, "auto", "merchant"))

    # 8. file import vs. API -> duplicate suggestion
    for t in txs:
        if t.source != "import" or t.id in used:
            continue
        for c in by_account.get(t.account_id, []):
            if c.source == "api" and c.id not in used and c.currency == t.currency \
                    and c.amount == t.amount and abs((c.date - t.date).days) <= 1 \
                    and not rejected("duplicate", t.id, c.id) and not rejected("duplicate", c.id, t.id):
                res.links.append(Link("duplicate", t.id, c.id, "suggested", "import"))
                break

    # 9. everything else
    for t in txs:
        res.roles.setdefault(t.id, "expense" if t.amount < 0 else "income")
    return res
