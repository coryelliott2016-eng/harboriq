"""Money math — exact decimal, no float drift."""
from decimal import Decimal


def test_line_total_is_exact():
    quantity = 7
    unit_price = Decimal("12.99")
    assert quantity * unit_price == Decimal("90.93")


def test_money_addition_exact():
    a = Decimal("0.10")
    b = Decimal("0.20")
    assert a + b == Decimal("0.30")  # would fail with floats


def test_stripe_cents_conversion():
    amount = Decimal("90.93")
    cents = int((amount * 100).quantize(Decimal("1")))
    assert cents == 9093
