import pytest

from src import live_import as li

ACTIVITY = '''Statement,Header,Field Name,Field Value
Statement,Data,Title,Activity Statement
Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code
Trades,Data,Order,Stocks,USD,AAPL,"2026-10-01, 10:15:02",100,180.00,181,-18000,-1,18001,0,100,O
Trades,Data,Order,Stocks,USD,AAPL,"2026-10-01, 11:20:00",-100,182.50,181,18250,-1,-18001,248,150,C
Trades,Data,Order,Stocks,USD,TSLA,"2026-10-02, 09:45:00",-10,250.00,249,2500,-1,-2500,0,10,O
Trades,Data,Order,Stocks,USD,TSLA,"2026-10-02, 10:05:00",10,255.00,256,-2550,-1,2501,-51,-10,C
Trades,SubTotal,,Stocks,USD,AAPL,,0,,,250,-2,,248,,
Trades,Data,Order,Stocks,USD,MSFT,"2026-10-03, 10:00:00",-5,400.00,401,2000,-1,-1900,99,0,C
'''

FLEX_XML = '''<FlexQueryResponse queryName="t" type="AF"><FlexStatements count="1"><FlexStatement accountId="U123">
<Trades>
<Trade accountId="U123" symbol="NVDA" assetCategory="STK" dateTime="20261005;101500" quantity="20" tradePrice="120" buySell="BUY" ibCommission="-1" fifoPnlRealized="0" tradeID="1" multiplier="1" levelOfDetail="EXECUTION"/>
<Trade accountId="U123" symbol="NVDA" assetCategory="STK" dateTime="20261005;103000" quantity="-10" tradePrice="123" buySell="SELL" ibCommission="-1" fifoPnlRealized="28.5" tradeID="2" multiplier="1" levelOfDetail="EXECUTION"/>
<Trade accountId="U123" symbol="NVDA" assetCategory="STK" dateTime="20261005;150000" quantity="-10" tradePrice="118" buySell="SELL" ibCommission="-1" fifoPnlRealized="-21.5" tradeID="3" multiplier="1" levelOfDetail="EXECUTION"/>
</Trades></FlexStatement></FlexStatements></FlexQueryResponse>'''

GENERIC = '''Date,Time,Symbol,Action,Quantity,Price,Commission
10/06/2026,10:00:00,AMD,BUY,50,150.00,1.00
10/06/2026,10:30:00,AMD,SELL,50,148.00,1.00
'''


@pytest.fixture(autouse=True)
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(li, "LIVE_PATH", tmp_path / "live_trades.csv")


def test_activity_statement_long_short_and_prior_position():
    fills = li.parse_any(ACTIVITY)
    assert len(fills) == 5  # SubTotal row skipped
    res = li.import_text(ACTIVITY)
    assert res["ok"] and res["added"] == 5
    trades, still_open = li.round_trips(li.load_fills())
    by = {t["symbol"]: t for t in trades}
    assert by["AAPL"]["side"] == "long" and by["AAPL"]["pnl"] == pytest.approx(248)
    assert by["AAPL"]["hold_min"] == pytest.approx(65, abs=0.1)
    assert by["TSLA"]["side"] == "short" and by["TSLA"]["pnl"] == pytest.approx(-51)
    assert by["MSFT"]["partial_history"] and by["MSFT"]["pnl"] == pytest.approx(99)  # opened before the file
    assert still_open == []


def test_reimport_is_deduplicated():
    li.import_text(ACTIVITY)
    again = li.import_text(ACTIVITY)
    assert again["added"] == 0 and again["total"] == 5


def test_flex_xml_partial_exits_make_one_trade():
    li.import_text(FLEX_XML)
    trades, _ = li.round_trips(li.load_fills())
    assert len(trades) == 1
    t = trades[0]
    assert t["qty"] == 20 and t["pnl"] == pytest.approx(7.0) and t["sell"] == pytest.approx(120.5)
    assert t["entry_time"].startswith("2026-10-05T10:15:00")


def test_generic_csv_without_realized_uses_fifo_minus_commissions():
    li.import_text(GENERIC)
    trades, _ = li.round_trips(li.load_fills())
    assert trades[0]["pnl"] == pytest.approx(-100 - 2)
    assert trades[0]["pnl_pct"] == pytest.approx(-102 / 7500 * 100)


def test_open_position_is_reported_not_counted():
    li.import_text("Date,Symbol,Side,Qty,Price\n2026-10-07 10:00:00,META,BUY,3,600\n")
    trades, still_open = li.round_trips(li.load_fills())
    assert trades == [] and still_open[0]["symbol"] == "META" and still_open[0]["qty"] == 3


def test_garbage_file_is_rejected():
    assert not li.import_text("hello,world\n1,2\n")["ok"]


def test_two_accounts_are_never_netted():
    two = '''Date,Symbol,Side,Qty,Price,Account,Currency
2026-10-08 10:00:00,SHOP,BUY,10,100,U111,CAD
2026-10-08 10:05:00,SHOP,SELL,10,101,U222,USD
2026-10-08 11:00:00,SHOP,SELL,10,103,U111,CAD
'''
    li.import_text(two)
    trades, still_open = li.round_trips(li.load_fills())
    assert len(trades) == 1 and trades[0]["account"] == "U111" and trades[0]["currency"] == "CAD"
    assert trades[0]["pnl"] == pytest.approx(30)
    assert still_open[0]["account"] == "U222" and still_open[0]["side"] == "short"
    detail = {d["account"]: d for d in li.summary()["accounts_detail"]}
    assert detail["U111"]["currency"] == "CAD" and detail["U222"]["currency"] == "USD"


def test_activity_statement_picks_up_account_number():
    text = 'Account Information,Header,Field Name,Field Value\nAccount Information,Data,Account,U7654321 (Custom Consolidated)\n' + ACTIVITY
    li.import_text(text)
    assert {f["account"] for f in li.load_fills()} == {"U7654321"}


def test_same_trades_from_flex_and_activity_statement_count_once():
    # Activity Statement: one row per ORDER, no trade ids
    stmt = 'Account Information,Header,Field Name,Field Value\nAccount Information,Data,Account,U123\n' + \
        'Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,Comm/Fee,Realized P/L\n' + \
        'Trades,Data,Order,Stocks,USD,NVDA,"2026-10-05, 10:15:00",20,120,-1,0\n' + \
        'Trades,Data,Order,Stocks,USD,NVDA,"2026-10-05, 15:00:00",-20,119.75,-1,7\n' + \
        'Trades,Data,Order,Stocks,USD,AMD,"2026-10-06, 10:00:00",10,150,-1,0\n' + \
        'Trades,Data,Order,Stocks,USD,AMD,"2026-10-06, 11:00:00",-10,152,-1,18\n'
    li.import_text(FLEX_XML)  # the same NVDA day, as 3 executions with ids (synced)
    li.import_text(stmt)
    assert len(li.load_fills()) == 7  # both stored...
    s = li.summary()
    nv = [t for t in s["closed"] if t["symbol"] == "NVDA"]
    assert len(nv) == 1 and nv[0]["pnl"] == pytest.approx(7.0)  # ...but NVDA counted once (Flex wins)
    assert [t["symbol"] for t in s["closed"]].count("AMD") == 1  # AMD only in the statement: kept
    assert s["duplicates_ignored"] == 2


def test_csv_without_account_does_not_double_a_synced_day():
    li.import_text(FLEX_XML)
    li.import_text("Date,Symbol,Side,Qty,Price\n2026-10-05 10:15:00,NVDA,BUY,20,120\n2026-10-05 15:00:00,NVDA,SELL,20,119.75\n")
    s = li.summary()
    assert [t["symbol"] for t in s["closed"]] == ["NVDA"] and s["duplicates_ignored"] == 2


def test_two_accounts_same_stock_same_day_both_kept():
    li.import_text(FLEX_XML)  # account U123
    li.import_text("Date,Symbol,Side,Qty,Price,Account\n2026-10-05 10:00:00,NVDA,BUY,5,121,U999\n2026-10-05 11:00:00,NVDA,SELL,5,122,U999\n")
    s = li.summary()
    assert sorted(t["account"] for t in s["closed"]) == ["U123", "U999"] and s["duplicates_ignored"] == 0
