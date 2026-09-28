"""Money helpers. Amounts are always integers in minor units (e.g. cents)."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# ISO 4217 minor-unit exponents that differ from the default of 2.
_EXPONENTS = {
    "BHD": 3, "IQD": 3, "JOD": 3, "KWD": 3, "LYD": 3, "OMR": 3, "TND": 3,
    "BIF": 0, "CLP": 0, "DJF": 0, "GNF": 0, "ISK": 0, "JPY": 0, "KMF": 0,
    "KRW": 0, "PYG": 0, "RWF": 0, "UGX": 0, "VND": 0, "VUV": 0, "XAF": 0,
    "XOF": 0, "XPF": 0, "HUF": 2,
}


def exponent(currency: str) -> int:
    return _EXPONENTS.get(currency.upper(), 2)


def to_minor(amount, currency: str) -> int:
    """Convert a decimal string/number in major units to integer minor units."""
    try:
        value = Decimal(str(amount).strip())
    except InvalidOperation as exc:
        raise ValueError(f"not a decimal amount: {amount!r}") from exc
    scaled = value.scaleb(exponent(currency)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(scaled)


def to_major_str(minor: int, currency: str) -> str:
    """Format minor units as a plain decimal string (for APIs, not for display)."""
    exp = exponent(currency)
    return str(Decimal(minor).scaleb(-exp).quantize(Decimal(1).scaleb(-exp)))
