"""Testes do motor de cálculo (Python puro, não precisam do Frappe)."""
from datetime import date, timedelta

import pytest

from portfolio_investimentos.engine.portfolio import (
    Instrument, Portfolio, PriceBook, Tx, drawdown, period_returns, streak, xirr,
)

ACME = Instrument("ACME", "Acme Corp", currency="EUR", sector="Tecnologia")
USCO = Instrument("USCO", "US Co", currency="USD")
SPX = Instrument("^GSPC", "S&P 500", kind="index", currency="USD")


def weekdays(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def book_linear(ticker, start, end, p0, p1):
    days = list(weekdays(start, end))
    n = len(days) - 1
    return {ticker: [(d, p0 + (p1 - p0) * i / n) for i, d in enumerate(days)]}


def test_fifo_realized_and_unrealized():
    d0 = date(2024, 1, 2)
    prices = {"ACME": [(d0, 10.0), (date(2024, 3, 1), 15.0), (date(2024, 6, 3), 20.0)]}
    txs = [
        Tx(d0, "DEPOSIT", amount=3000),
        Tx(d0, "BUY", ACME, quantity=100, price=10, fees=1),
        Tx(date(2024, 3, 1), "BUY", ACME, quantity=100, price=15, fees=1),
        Tx(date(2024, 6, 3), "SELL", ACME, quantity=150, price=20, fees=2),
    ]
    p = Portfolio(txs, PriceBook(prices), as_of=date(2024, 6, 3))
    pos = p.positions["ACME"]
    # FIFO: 100 @ (1001/100) + 50 @ (1501/100 por unidade)
    cost = 1001 + 1501 / 2
    assert p.realized == pytest.approx(150 * 20 - 2 - cost)
    assert pos.qty == pytest.approx(50)
    assert pos.invested_eur == pytest.approx(1501 / 2)
    assert pos.value_eur == pytest.approx(1000)
    assert p.sales[0].acquired == d0 and p.sales[1].acquired == date(2024, 3, 1)


def test_implicit_deposit_and_total_return():
    d0 = date(2024, 1, 1)
    prices = book_linear("ACME", d0, date(2024, 12, 31), 10, 12)
    txs = [Tx(d0, "BUY", ACME, quantity=10, price=10)]
    p = Portfolio(txs, PriceBook(prices), as_of=date(2024, 12, 31))
    assert p.implicit_deposits == pytest.approx(100)
    assert p.net_deposits == pytest.approx(100)
    assert p.total_value == pytest.approx(120)
    assert p.total_return_pct == pytest.approx(0.20)
    perf = p.performance("MAX")
    assert perf["twr_total"] == pytest.approx(0.20)
    assert perf["irr"] == pytest.approx(0.20, abs=0.01)


def test_twr_ignores_cash_flows():
    d0 = date(2024, 1, 1)
    prices = book_linear("ACME", d0, date(2024, 12, 31), 10, 20)
    mid = date(2024, 7, 1)
    mid_price = PriceBook(prices).price("ACME", mid)
    txs = [
        Tx(d0, "BUY", ACME, quantity=10, price=10),
        Tx(mid, "BUY", ACME, quantity=100, price=mid_price),  # grande entrada a meio
    ]
    p = Portfolio(txs, PriceBook(prices), as_of=date(2024, 12, 31))
    # o TWR depende só do preço (10 -> 20), não da entrada a meio do ano
    assert p.performance("MAX")["twr_total"] == pytest.approx(1.0, rel=1e-6)


def test_currency_conversion_and_fx_effect():
    d0 = date(2024, 1, 2)
    d1 = date(2024, 2, 1)
    book = PriceBook({"USCO": [(d0, 100.0), (d1, 100.0)]}, {"USD": [(d0, 1.0), (d1, 1.25)]})
    p = Portfolio([Tx(d0, "BUY", USCO, quantity=10, price=100, currency="USD")], book, as_of=d1)
    pos = p.positions["USCO"]
    assert pos.invested_eur == pytest.approx(1000)
    assert pos.value_eur == pytest.approx(800)
    assert pos.fx_effect_eur == pytest.approx(-200)


def test_dividends_and_fiscal():
    d0 = date(2023, 1, 2)
    prices = book_linear("ACME", d0, date(2024, 12, 31), 10, 10)
    txs = [Tx(d0, "BUY", ACME, quantity=100, price=10)]
    for y in (2023, 2024):
        for m in (3, 9):
            txs.append(Tx(date(y, m, 15), "DIVIDEND", ACME, quantity=100, amount=20, tax=3))
    txs.append(Tx(date(2024, 10, 1), "INTEREST", amount=10))
    p = Portfolio(txs, PriceBook(prices), as_of=date(2024, 12, 31))
    s = p.dividend_summary()
    assert s["gross"] == pytest.approx(80) and s["tax"] == pytest.approx(12)
    assert s["net"] == pytest.approx(68)
    assert s["months_with"] == 4
    assert s["forward_gross"] == pytest.approx(40)
    assert [(t, src) for t, _, src in s["forward_by_asset"]] == [("ACME", "recebidos")]
    # mapa do próximo ano: paga em março e setembro, como nos últimos 12 meses (20 por mês, sem a retenção de 15%)
    assert set(s["forward_by_month"]) == {3, 9}
    assert sum(s["forward_by_month"].values()) == pytest.approx(s["forward_net"])
    fiscal = p.fiscal_years()
    assert fiscal[2024]["div_gross"] == pytest.approx(40)
    assert fiscal[2024]["tax_dividends"] == pytest.approx(40 * 0.28 - 6)
    assert fiscal[2024]["interest"] == pytest.approx(10)


def test_dividend_projection_uses_yahoo_per_share_for_recent_positions():
    """Posição comprada há 2 meses, ainda sem dividendos recebidos: a projeção usa os dividendos por ação do Yahoo."""
    d0 = date(2026, 1, 2)
    prices = book_linear("ACME", d0, date(2026, 10, 30), 10, 10)
    prices.update(book_linear("USCO", d0, date(2026, 10, 30), 50, 50))
    txs = [Tx(d0, "BUY", ACME, quantity=10, price=10),
           Tx(date(2026, 3, 15), "DIVIDEND", ACME, quantity=10, amount=5),  # um dividendo recebido (para haver página)
           Tx(date(2026, 9, 1), "BUY", USCO, quantity=100, price=50)]
    announced = {"USCO": [(date(2025, 11, 20), 0.25), (date(2026, 2, 20), 0.25), (date(2026, 5, 20), 0.25),
                          (date(2026, 8, 20), 0.25), (date(2025, 6, 1), 9.0)]}  # o último já não está nos 12 meses
    p = Portfolio(txs, PriceBook(prices, {"USD": [(d0, 1.25)]}), as_of=date(2026, 10, 30))
    s = p.dividend_summary(announced)
    yahoo = dict((t, v) for t, v, src in s["forward_by_asset"] if src == "Yahoo")
    assert yahoo["USCO"] == pytest.approx(100 * 1.0 / 1.25)  # 4 × 0,25 USD por ação, em EUR
    assert set(s["forward_by_month"]) == {2, 3, 5, 8, 11}
    assert p.dividend_summary()["forward_net"] < s["forward_net"]  # sem o Yahoo só contava o ACME


def test_dividend_calendar_by_ex_date():
    """Só tem direito ao dividendo quem detinha as ações antes da data ex-dividendo."""
    d0 = date(2026, 1, 2)
    today = date(2026, 10, 30)
    prices = book_linear("ACME", d0, today, 10, 10)
    prices.update(book_linear("USCO", d0, today, 50, 50))
    txs = [Tx(d0, "BUY", ACME, quantity=10, price=10),
           Tx(date(2026, 8, 25), "DIVIDEND", ACME, quantity=10, amount=5),       # pago 5 dias depois da data ex
           Tx(date(2026, 9, 15), "BUY", USCO, quantity=100, price=50),           # depois da data ex de 1/9
           Tx(date(2026, 10, 1), "BUY", ACME, quantity=5, price=10)]             # mais ações antes de 20/10
    announced = {"ACME": [(date(2026, 8, 20), 0.5), (date(2026, 10, 20), 0.5), (date(2025, 11, 20), 0.5)],
                 "USCO": [(date(2026, 9, 1), 0.25)]}
    p = Portfolio(txs, PriceBook(prices, {"USD": [(d0, 1.25)]}), as_of=today)
    cal = p.dividend_calendar(announced, confirmed={"ACME": [date(2026, 11, 24)]})
    got = [(r["date"], r["asset"].ticker, r["status"], r["qty"]) for r in cal]
    assert (date(2026, 8, 20), "ACME", "recebido", 10) in got
    assert (date(2026, 10, 20), "ACME", "a receber", 15) in got           # ainda não pago; 15 ações antes da data ex
    assert (date(2026, 9, 1), "USCO", "sem direito", 0) in got             # comprado depois da data ex
    # 20/11/2025 + 1 ano ≈ 20/11/2026, mas a data anunciada é 24/11: usa-se essa, com as 15 ações de hoje
    nxt = next(r for r in cal if r["status"] == "previsto" and r["asset"].ticker == "ACME" and r["date"].month == 11)
    assert nxt["date"] == date(2026, 11, 24) and nxt["qty"] == 15 and not nxt["estimated"]
    assert [r["date"] for r in cal] == sorted(r["date"] for r in cal)


def test_fiscal_dividend_credit_is_limited_per_dividend():
    """A retenção a mais num dividendo (30% nos EUA) não abate o imposto de outro dividendo do mesmo ano."""
    d0 = date(2024, 1, 2)
    prices = book_linear("ACME", d0, date(2024, 12, 31), 10, 10)
    txs = [Tx(d0, "BUY", ACME, quantity=100, price=10),
           Tx(date(2024, 3, 15), "DIVIDEND", ACME, quantity=100, amount=100, tax=30),
           Tx(date(2024, 9, 15), "DIVIDEND", ACME, quantity=100, amount=100, tax=0)]
    p = Portfolio(txs, PriceBook(prices), as_of=date(2024, 12, 31))
    assert p.fiscal_years()[2024]["tax_dividends"] == pytest.approx(28.0)  # e não 26


def test_benchmark_merit_and_risk():
    d0, d1 = date(2022, 1, 3), date(2024, 12, 31)
    prices = book_linear("ACME", d0, d1, 100, 150)
    prices.update(book_linear("^GSPC", d0, d1, 4000, 5000))
    p = Portfolio([Tx(d0, "BUY", ACME, quantity=1, price=100)], PriceBook(prices), [SPX], as_of=d1)
    perf = p.performance("MAX")
    assert perf["benchmarks"][0]["total"] == pytest.approx(0.25)
    assert perf["merit"]["excess_cagr"] > 0
    assert perf["risk"]["max_drawdown"] == pytest.approx(0.0)
    assert len(perf["yearly"]) == 3


def test_period_filter_rebases():
    d0, d1 = date(2023, 1, 2), date(2024, 12, 31)
    prices = book_linear("ACME", d0, d1, 100, 200)
    p = Portfolio([Tx(d0, "BUY", ACME, quantity=1, price=100)], PriceBook(prices), as_of=d1)
    ytd = p.performance("YTD")
    assert ytd["twr"][0] == pytest.approx(0.0)
    start_price = PriceBook(prices).price("ACME", date(2023, 12, 29))
    assert ytd["twr_total"] == pytest.approx(200 / start_price - 1, rel=1e-6)


def test_helpers():
    assert drawdown([1, 1.2, 0.9, 1.3]) == pytest.approx([0, 0, -0.25, 0])
    dates = [date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 29)]
    out = period_returns(dates, [1.0, 1.1, 0.99], "month")
    assert [k for k, _ in out] == ["2024-01", "2024-02", "2024-03"]
    assert [r for _, r in out] == pytest.approx([0.0, 0.1, -0.1])
    assert streak([("a", 0.1), ("b", -0.1), ("c", 0.2), ("d", 0.1)]) == (2, "up")
    r = xirr([(date(2020, 1, 1), -100), (date(2021, 1, 1), 110)])
    assert r == pytest.approx(0.10, abs=1e-3)


def test_opening_position_uses_broker_result():
    """Venda de ações compradas antes do histórico: custo estimado pelo resultado da corretora."""
    d0, d1 = date(2026, 1, 2), date(2026, 3, 2)
    book = PriceBook({"ACME": [(d0, 10.0), (d1, 12.0)]})
    txs = [Tx(d0, "DEPOSIT", amount=100),
           Tx(d1, "SELL", ACME, quantity=50, price=12, fees=1, result=99)]  # custo = 600 - 1 - 99 = 500
    p = Portfolio(txs, book, as_of=d1)
    assert len(p.opening) == 1 and p.warnings
    assert p.realized == pytest.approx(99)
    assert p.sales[0].acquired is None
    assert p.positions["ACME"].qty == pytest.approx(0)


def test_transfer_out_has_no_realized_gain():
    d0, d1 = date(2026, 1, 2), date(2026, 2, 2)
    book = PriceBook({"ACME": [(d0, 10.0), (d1, 15.0)]})
    txs = [Tx(d0, "BUY", ACME, quantity=10, price=10), Tx(d1, "TRANSFER_OUT", ACME, quantity=10, price=15)]
    p = Portfolio(txs, book, as_of=d1)
    assert p.sales == [] and p.realized == 0
    assert p.holdings_value == pytest.approx(0)
    # a saída das ações é um fluxo externo: o TWR reflete só a valorização (10 -> 15)
    assert p.performance("MAX")["twr_total"] == pytest.approx(0.5)


def test_twr_survives_nearly_empty_portfolio():
    """Depois de vender quase tudo, um resíduo de cêntimos não pode gerar retornos absurdos."""
    d = [date(2024, 1, 1) + timedelta(days=i) for i in range(6)]
    book = PriceBook({"ACME": [(d[0], 10.0), (d[2], 10.0), (d[3], 10.5), (d[5], 11.0)]})
    txs = [Tx(d[0], "BUY", ACME, quantity=10, price=10),
           Tx(d[2], "SELL", ACME, quantity=9.999, price=10),
           Tx(d[2], "WITHDRAWAL", amount=99.99),
           Tx(d[3], "BUY", ACME, quantity=10, price=10.5)]   # volta a investir com nova entrada
    p = Portfolio(txs, book, as_of=d[5])
    twr = p.performance("MAX")["twr_total"]
    assert -0.5 < twr < 0.5


def test_fund_conversion_keeps_cost_and_dates():
    """Conversão de fundo (ex.: PRAW -> F50A): custo e datas de compra passam para o novo ativo."""
    old, new = Instrument("OLD"), Instrument("NEW")
    d0, d1, d2 = date(2024, 1, 2), date(2024, 6, 3), date(2024, 9, 2)
    book = PriceBook({"OLD": [(d0, 10.0)], "NEW": [(d1, 12.0), (d2, 13.0)]})
    txs = [Tx(d0, "BUY", old, quantity=100, price=10),
           Tx(d1, "CONVERT_IN", new, quantity=100),
           Tx(d1, "CONVERT_OUT", old, quantity=100, result=-1000),
           Tx(d2, "SELL", new, quantity=100, price=13)]
    p = Portfolio(txs, book, as_of=d2)
    assert p.realized == pytest.approx(300)            # 1300 - 1000, sem a perda falsa da conversão
    assert p.sales[-1].acquired == d0                  # data de compra original (FIFO no IRS)
    assert p.positions["OLD"].realized_eur == 0


def test_total_return_pct_not_inflated_by_withdrawals():
    # deposita 10 000, duplica, levanta quase tudo: o líquido depositado fica negativo/minúsculo
    d0, d1, end = date(2024, 1, 2), date(2024, 12, 31), date(2025, 6, 30)
    prices = book_linear("ACME", d0, d1, 10.0, 20.0)
    prices["ACME"] += [(d, 20.0) for d in weekdays(d1 + timedelta(days=1), end)]
    txs = [
        Tx(d0, "DEPOSIT", amount=10000),
        Tx(d0, "BUY", ACME, quantity=1000, price=10),
        Tx(d1, "SELL", ACME, quantity=900, price=20),
        Tx(d1, "WITHDRAWAL", amount=17500),
    ]
    p = Portfolio(txs, PriceBook(prices), as_of=end)
    assert p.total_return == pytest.approx(10000, abs=1)
    assert p.total_return_pct == pytest.approx(1.0, abs=0.01)  # a ação duplicou: +100%, não +∞
    perf = p.performance("MAX")
    assert perf["return_pct"] == pytest.approx(1.0, abs=0.01)


def test_overview_pct_matches_euros():
    d0 = date(2024, 1, 2)
    prices = {"ACME": [(d0, 10.0), (date(2025, 1, 2), 12.0), (date(2025, 6, 30), 15.0)]}
    txs = [Tx(d0, "DEPOSIT", amount=1000), Tx(d0, "BUY", ACME, quantity=100, price=10),
           Tx(date(2025, 1, 2), "DEPOSIT", amount=1200), Tx(date(2025, 1, 2), "BUY", ACME, quantity=100, price=12)]
    p = Portfolio(txs, PriceBook(prices), as_of=date(2025, 6, 30))
    assert p.total_return == pytest.approx(800)  # 3 000 de valor - 2 200 depositados
    assert p.total_return_pct == pytest.approx(800 / 2200)
    gain, pct = p.year_to_date()
    assert gain == pytest.approx(800)  # 3 000 - 1 000 a 31/12 - 1 200 depositados no ano
    assert pct == pytest.approx(800 / 2200)


def test_day_change_ignores_weekend_movements():
    # sexta 23/10 e quinta 22/10 com cotações; juros no sábado 24/10 prolongam a série
    thu, fri, sat = date(2026, 10, 22), date(2026, 10, 23), date(2026, 10, 24)
    prices = {"ACME": [(date(2026, 10, 21), 10.0), (thu, 10.0), (fri, 11.0)], "^GSPC": [(thu, 100.0), (fri, 102.0)]}
    txs = [Tx(date(2026, 10, 21), "DEPOSIT", amount=1000), Tx(date(2026, 10, 21), "BUY", ACME, quantity=100, price=10),
           Tx(sat, "INTEREST", amount=0.5)]
    p = Portfolio(txs, PriceBook(prices), benchmarks=[SPX], as_of=fri)
    assert p.series.dates[-1] == sat
    diff, pct = p.day_change()
    assert diff == pytest.approx(100) and pct == pytest.approx(0.1)  # sexta vs quinta, não sábado vs sexta
    assert p.positions["ACME"].day_change_pct == pytest.approx(0.1)
    assert p.benchmark_day_change(SPX) == pytest.approx(0.02)


def test_lisbon_fallback_matches_zoneinfo():
    # sem base de fusos (ex.: Termux sem tzdata) a hora de Lisboa calculada tem de coincidir com a oficial
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from portfolio_investimentos.services.market import _LisbonFallback
    real, fallback = ZoneInfo("Europe/Lisbon"), _LisbonFallback()
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    while t < datetime(2028, 1, 1, tzinfo=timezone.utc):
        assert t.astimezone(fallback).replace(tzinfo=None) == t.astimezone(real).replace(tzinfo=None), t
        t += timedelta(minutes=30)


def test_benchmarks_compared_in_euros():
    # carteira = um fundo do S&P 500 em USD; índice e fundo parados em USD, dólar cai 20% face ao euro
    fund = Instrument("SPYX", "Fundo S&P 500", currency="USD")
    d0, d1 = date(2025, 1, 2), date(2025, 12, 31)
    days = list(weekdays(d0, d1))
    n = len(days) - 1
    prices = {"SPYX": [(d, 100.0) for d in days], "^GSPC": [(d, 5000.0) for d in days]}
    fx = {"USD": [(d, 1.0 + 0.25 * i / n) for i, d in enumerate(days)]}
    txs = [Tx(d0, "DEPOSIT", amount=1000), Tx(d0, "BUY", fund, quantity=10, price=100, currency="USD")]
    p = Portfolio(txs, PriceBook(prices, fx), benchmarks=[SPX], as_of=d1)
    perf = p.performance("MAX")
    assert perf["twr_total"] == pytest.approx(-0.2, abs=1e-3)
    assert perf["benchmarks"][0]["total"] == pytest.approx(-0.2, abs=1e-3)  # o índice também, em euros
    assert perf["merit"]["excess_cagr"] == pytest.approx(0.0, abs=1e-3)      # sem mérito nem demérito


def test_volatility_ignores_weekend_points():
    from portfolio_investimentos.engine.portfolio import annualized_vol
    d0 = date(2025, 1, 6)  # segunda-feira
    dates = [d0 + timedelta(days=i) for i in range(28)]
    index, v = [], 1.0
    for d in dates:  # +1% / −1% alternados nos dias úteis; fim de semana sem variação (só juros)
        if d.weekday() < 5:
            v *= 1.01 if len([x for x in dates if x <= d and x.weekday() < 5]) % 2 else 0.99
        index.append(v)
    weekdays_only = [x for d, x in zip(dates, index) if d.weekday() < 5]
    assert annualized_vol(index, dates) == pytest.approx(annualized_vol(weekdays_only))
    assert annualized_vol(index, dates) > annualized_vol(index)  # com os fins de semana ficava mais baixa


def test_incomplete_periods_and_risk_free():
    from portfolio_investimentos.engine.portfolio import _complete
    months = [("2026-09", 0.05), ("2026-10", -0.30)]
    assert _complete(months, date(2026, 10, 23), "month") == [("2026-09", 0.05)]   # outubro ainda a decorrer
    assert _complete(months, date(2026, 10, 30), "month") == months                 # último dia útil: completo
    d0, d1 = date(2024, 1, 2), date(2026, 10, 23)
    prices = book_linear("ACME", d0, d1, 10.0, 20.0)
    prices["ACME"][-1] = (d1, 12.0)  # queda forte no mês em curso
    txs = [Tx(d0, "DEPOSIT", amount=1000), Tx(d0, "BUY", ACME, quantity=100, price=10)]
    p = Portfolio(txs, PriceBook(prices), as_of=d1)
    perf0, perf2 = p.performance("MAX", risk_free=0.0), p.performance("MAX", risk_free=0.02)
    assert perf0["worst_month"][0] != "2026-10" and perf0["partial_month"] == "2026-10"
    assert perf0["worst_year"][0] != "2026"
    r0, r2 = perf0["risk"], perf2["risk"]
    assert r2["sharpe"] == pytest.approx((perf2["cagr"] - 0.02) / r2["volatility"])
    assert r2["sharpe"] < r0["sharpe"]
