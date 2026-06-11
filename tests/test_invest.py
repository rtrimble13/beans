from datetime import date
from decimal import Decimal

import pytest

from beans import invest
from beans.utils import BeansError
from tests.conftest import post


def seed_cash(led):
    post(led, date(2026, 1, 1), "opening",
         ("Assets:Checking", 1000000), ("Equity:Opening Balances", -1000000))


def brokerage(led):
    return led.find_account("Assets:Investments:Brokerage")


def checking(led):
    return led.find_account("Assets:Checking")


def test_buy_creates_lot_and_transaction(led):
    seed_cash(led)
    result = invest.buy(led, "vti", Decimal("10"), 28000,
                        brokerage(led), checking(led), date(2026, 2, 1))
    assert result["cost"] == 280000
    raw = led.balances()
    assert raw[brokerage(led).id] == 280000
    assert raw[checking(led).id] == 1000000 - 280000
    [lot] = led.lots(symbol="VTI")
    assert lot["quantity"] == "10"
    assert lot["cost"] == 280000
    assert led.latest_price("VTI") == (date(2026, 2, 1), 28000)


def test_sell_fifo_realizes_gain(led):
    seed_cash(led)
    invest.buy(led, "VTI", Decimal("10"), 20000,
               brokerage(led), checking(led), date(2026, 1, 10))
    invest.buy(led, "VTI", Decimal("10"), 30000,
               brokerage(led), checking(led), date(2026, 2, 10))
    result = invest.sell(led, "VTI", Decimal("15"), 40000,
                         brokerage(led), checking(led), date(2026, 3, 1))
    # FIFO: all of lot 1 (cost 200,000) + half of lot 2 (cost 150,000).
    assert result["cost_relieved"] == 350000
    assert result["proceeds"] == 600000
    assert result["gain"] == 250000
    [lot] = led.lots(symbol="VTI")
    assert lot["quantity"] == "5"
    assert lot["cost"] == 150000
    realized = led.find_account("Income:Realized Gains")
    assert led.balances()[realized.id] == -250000


def test_sell_more_than_held_fails(led):
    seed_cash(led)
    invest.buy(led, "VTI", Decimal("10"), 20000,
               brokerage(led), checking(led), date(2026, 1, 10))
    with pytest.raises(BeansError, match="only 10 held"):
        invest.sell(led, "VTI", Decimal("11"), 20000,
                    brokerage(led), checking(led), date(2026, 2, 1))


def test_portfolio_valuation(led):
    seed_cash(led)
    invest.buy(led, "VTI", Decimal("10"), 28000,
               brokerage(led), checking(led), date(2026, 2, 1))
    led.set_price("VTI", date(2026, 3, 1), 30000)
    data = invest.portfolio(led, as_of=date(2026, 3, 15))
    [row] = data["rows"]
    assert row["market_value"] == 300000
    assert row["unrealized"] == 20000
    assert data["total_unrealized"] == 20000


def test_mark_to_market_balances(led):
    from beans.reports import balance_sheet

    seed_cash(led)
    invest.buy(led, "VTI", Decimal("10"), 28000,
               brokerage(led), checking(led), date(2026, 2, 1))
    led.set_price("VTI", date(2026, 3, 1), 30000)
    data = invest.mark_to_market(led, date(2026, 3, 15))
    [adj] = data["adjustments"]
    assert adj["adjustment"] == 20000
    assert led.balances()[brokerage(led).id] == 300000
    # Marking again is a no-op.
    again = invest.mark_to_market(led, date(2026, 3, 16))
    assert again["adjustments"] == []
    # And the books still balance, with the gain in equity via income.
    sheet = balance_sheet(led, date(2026, 3, 31))
    assert sheet["balanced"]
    assert sheet["retained_earnings"] == 20000


def test_mark_requires_prices(led):
    seed_cash(led)
    invest.buy(led, "VTI", Decimal("10"), 28000,
               brokerage(led), checking(led), date(2026, 2, 1))
    led.db.execute("DELETE FROM prices")
    led.db.commit()
    with pytest.raises(BeansError, match="no price for VTI"):
        invest.mark_to_market(led, date(2026, 3, 1))


def test_fractional_quantities(led):
    seed_cash(led)
    invest.buy(led, "VTI", Decimal("2.5"), 10000,
               brokerage(led), checking(led), date(2026, 1, 1))
    result = invest.sell(led, "VTI", Decimal("1.25"), 12000,
                         brokerage(led), checking(led), date(2026, 2, 1))
    assert result["proceeds"] == 15000
    assert result["cost_relieved"] == 12500
    [lot] = led.lots(symbol="VTI")
    assert Decimal(lot["quantity"]) == Decimal("1.25")


def test_parse_quantity_validation():
    with pytest.raises(BeansError, match="invalid quantity"):
        invest.parse_quantity("abc")
    with pytest.raises(BeansError, match="positive"):
        invest.parse_quantity("-1")
