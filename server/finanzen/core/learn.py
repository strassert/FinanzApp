"""Learning categories from the user's own decisions (KI stage A, local).

Training data: every expense or income whose category comes from the user
(choice on the booking, own rule, confirmed suggestion). Two lookups, both
per direction (money out / money in):

1. Same merchant: a merchant (normalised payee, see categories.payee_key)
   the user already categorised gets that category (majority if mixed).
2. Distinctive word: a word of the payee that only appears in merchants of
   ONE category among the trained ones, and in at most MAX_MERCHANTS
   merchants overall (so place names like SALZBURG never decide). Two words
   pointing to different categories cancel out.

Deterministic, no dependency, no network. Results are suggestions: the app
marks them and asks the user to confirm.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Optional

from .categories import fold

MAX_MERCHANTS = 6
MIN_LENGTH = 3
STOP = {
    # payment words, legal forms, generic shop words
    "GUTSCHRIFT", "RUECKZAHLUNG", "ERSTATTUNG", "STORNO", "REFUND", "DANKT", "DANKE", "ZAHLUNG",
    "KARTE", "KARTENZAHLUNG", "BANKOMAT", "LASTSCHRIFT", "UEBERWEISUNG", "RECHNUNG", "EINKAUF", "IHR",
    "BEI", "VON", "UND", "DER", "DIE", "DAS", "FUER", "MIT", "GMBH", "KG", "OG", "AG", "SE", "LTD",
    "INC", "SARL", "CIE", "SCA", "FILIALE", "FIL", "SHOP", "STORE", "MARKT", "ONLINE", "WWW", "COM",
    "AUSTRIA", "OESTERREICH", "EUROPE", "PAYPAL", "APPLE", "PAY", "POS", "NFC", "EUR",
}


def tokens(payee: str) -> set[str]:
    words = re.findall(r"[A-Z]+", fold(payee))
    return {w for w in words if len(w) >= MIN_LENGTH and w not in STOP}


@dataclass
class Example:
    key: str                          # merchant key "sign:payee"
    payee: str                        # display text
    category_id: int


@dataclass
class Guess:
    category_id: int
    hint: str                         # merchant it was learned from


class Learner:
    def __init__(self, examples: Iterable[Example], all_keys: Iterable[tuple[str, str]] = ()):
        """examples: labelled bookings; all_keys: (key, payee) of every booking,
        labelled or not, to tell distinctive words from common ones."""
        by_key: dict[str, Counter] = defaultdict(Counter)
        names: dict[str, str] = {}
        for e in examples:
            by_key[e.key][e.category_id] += 1
            names[e.key] = e.payee
        self.exact: dict[str, Guess] = {}
        for key, counts in by_key.items():
            (cat, n), *rest = counts.most_common()
            if not rest or n > rest[0][1]:
                self.exact[key] = Guess(cat, names[key])
        # word -> sign -> category -> merchant keys
        self.words: dict[tuple[str, str], dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
        for key, guess in self.exact.items():
            sign = key[0]
            for w in tokens(names[key]):
                self.words[(sign, w)][guess.category_id].add(key)
        spread: dict[tuple[str, str], set[str]] = defaultdict(set)
        for key, payee in [*all_keys, *names.items()]:
            for w in tokens(payee):
                spread[(key[0], w)].add(key)
        self.spread = {k: len(v) for k, v in spread.items()}
        self.names = names

    def same_merchant(self, key: str) -> Optional[Guess]:
        return self.exact.get(key)

    def by_word(self, key: str, payee: str) -> Optional[Guess]:
        sign = key[0]
        found: dict[int, tuple[int, str]] = {}          # category -> (support, example key)
        for w in sorted(tokens(payee)):
            cats = self.words.get((sign, w))
            if not cats or len(cats) != 1 or self.spread.get((sign, w), 0) > MAX_MERCHANTS:
                continue
            (cat, keys), = cats.items()
            others = sorted(k for k in keys if k != key)
            if not others:
                continue
            support = len(others)
            if cat not in found or support > found[cat][0]:
                found[cat] = (support, others[0])
        if len(found) != 1:
            return None                                  # nothing, or words disagree
        (cat, (_, example)), = found.items()
        return Guess(cat, self.names[example])
