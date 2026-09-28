import pytest

from finanzen.money import to_major_str, to_minor


def test_to_minor_uses_currency_exponent():
    assert to_minor("12.50", "EUR") == 1250
    assert to_minor("-0.01", "EUR") == -1
    assert to_minor("1234", "JPY") == 1234
    assert to_minor("1.2345", "KWD") == 1235  # rounded half up to 3 decimals


def test_to_minor_rejects_garbage():
    with pytest.raises(ValueError):
        to_minor("12,50 EUR", "EUR")


def test_to_major_str_roundtrip():
    assert to_major_str(1250, "EUR") == "12.50"
    assert to_major_str(-5, "EUR") == "-0.05"
    assert to_major_str(100, "JPY") == "100"
