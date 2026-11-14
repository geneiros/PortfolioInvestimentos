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


def test_position_lines_split_the_portfolio_gain_by_position():
    d0, d1 = date(2024, 1, 2), date(2024, 12, 31)
    prices = book_linear("ACME", d0, d1, 10, 20)
    prices.update(book_linear("USCO", d0, d1, 100, 80))
    txs = [Tx(d0, "DEPOSIT", amount=3000),
           Tx(d0, "BUY", ACME, quantity=100, price=10),
           Tx(d0, "BUY", USCO, quantity=10, price=100, currency="USD"),
           Tx(date(2024, 6, 3), "DIVIDEND", ACME, quantity=100, amount=50)]
    fx = {"USD": [(d0, 1.0)]}
    p = Portfolio(txs, PriceBook(prices, fx), as_of=d1)
    out = p.position_lines("MAX", top=5)
    by = {ln["asset"].ticker: ln for ln in out["lines"]}
    assert out["dates"][0] == d0 and len(by["ACME"]["gain"]) == len(out["dates"])
    assert by["ACME"]["total"] == pytest.approx(100 * 10 + 50)      # valorização + dividendo
    assert by["USCO"]["total"] == pytest.approx(10 * -20)
    assert by["ACME"]["pct"] == pytest.approx(1050 / 1000)
    assert [ln["asset"].ticker for ln in out["lines"]] == ["ACME", "USCO"]  # maior ganho em valor absoluto primeiro
    # as posições somam o ganho da carteira (aqui não há caixa a render)
    perf = p.performance("MAX")
    assert by["ACME"]["total"] + by["USCO"]["total"] == pytest.approx(perf["gain"][-1])
    assert p.position_lines("MAX", top=1)["others"]["count"] == 1


def test_scores_metrics_and_profiles():
    from portfolio_investimentos.engine.scores import PROFILES, Scorer, tier
    d0, d1 = date(2023, 1, 2), date(2025, 12, 31)
    prices = book_linear("ACME", d0, d1, 10, 30)
    prices.update(book_linear("USCO", d0, d1, 100, 60))
    prices.update(book_linear("^GSPC", d0, d1, 4000, 5000))
    txs = [Tx(d0, "DEPOSIT", amount=10000), Tx(d0, "BUY", ACME, quantity=100, price=10, fees=1),
           Tx(d0, "BUY", USCO, quantity=10, price=100, currency="USD", fees=1)]
    for m in range(1, 12):  # compras todos os meses
        txs.append(Tx(date(2023, m + 1, 3), "BUY", ACME, quantity=1, price=10 + m, fees=0.5))
    txs.append(Tx(date(2024, 6, 3), "SELL", USCO, quantity=5, price=80, currency="USD"))
    p = Portfolio(txs, PriceBook(prices, {"USD": [(d0, 1.0)]}), [SPX], as_of=d1)
    s = Scorer(p, countries={"ACME": "Alemanha", "USCO": "EUA"}, payers=set())
    assert s.ok
    for key in PROFILES:
        r = s.investor(key)
        assert r["score"] is None or 0 <= r["score"] <= 100
        assert [m["key"] for m in r["metrics"]] == list(PROFILES[key][3])
    pf = s.portfolio()
    assert 0 <= pf["score"] <= 100 and pf["tier"] in "ABCD"
    conc = next(m for m in pf["metrics"] if m["key"] == "concentration")
    assert "posições efetivas" in conc["detail"]
    pat = s.metric("patience")
    assert pat["score"] > 50  # poucas vendas: cada euro fica muito tempo investido
    assert s.suggest()[0] in PROFILES
    assert tier(85) == ("A", "Excelente") and tier(20) == ("D", "Em construção") and tier(None)[0] is None


def test_fire_number_dates_and_tracking():
    from portfolio_investimentos.engine import fire
    # 12 000 €/ano, 4%, 14% de imposto efetivo: 12 000 / 0,86 / 0,04
    assert fire.fire_number(12000, 0.04, 0.14) == pytest.approx(348837.2, rel=1e-6)
    plan = fire.plan(100000, 12000, 0.04, 0.0, 1000, start=date(2026, 11, 1))
    assert plan["number"] == pytest.approx(300000) and plan["done"] == pytest.approx(1 / 3)
    by = {s["name"]: s["date"] for s in plan["scenarios"]}
    assert by["otimista"] < by["base"] < by["pessimista"]  # mais retorno, mais cedo
    assert plan["earliest"] == by["otimista"] and plan["latest"] == by["pessimista"]
    # conferir o cenário base à mão: o mês em que passa os 300 000 €
    g, v, m = 1.05 ** (1 / 12) - 1, 100000.0, 0
    while v < 300000:
        v, m = v * (1 + g) + 1000, m + 1
    assert by["base"] == fire._add_months(date(2026, 11, 1), m)
    assert fire.plan(400000, 12000, 0.04, 0.0, 0, start=date(2026, 11, 1))["date"] == date(2026, 11, 1)  # já lá está
    track = fire.monthly_track([date(2026, 8, 31), date(2026, 9, 30), date(2026, 10, 30)], [100.0, 110.0, 99.0], 1000)
    assert [(r["month"], r["change"]) for r in track] == [((2026, 10), -11.0), ((2026, 9), 10.0)]


def test_fire_lifetime_needs_less_than_forever_and_counts_the_pension():
    from portfolio_investimentos.engine import fire
    start = date(2026, 11, 1)
    # sem retorno: 30 anos de 12 000 € = 360 000 € (contas fáceis)
    need = fire.required_by_month(0.0, 12000, 0.0, 60, 90)
    assert need[0] == pytest.approx(360000) and need[-1] == 0
    # pensão de 600 €/mês × 14 a partir dos 67: menos 8 400 € por ano durante 23 anos
    with_pension = fire.required_by_month(0.0, 12000, 0.0, 60, 90, pension=8400, pension_age=67)
    assert with_pension[0] == pytest.approx(360000 - 8400 * 23)
    life = fire.lifetime_plan(100000, 12000, 0.14, 1000, 45, 90, start=start)
    forever = fire.plan(100000, 12000, 0.04, 0.14, 1000, start=start)
    assert life["date"] < forever["date"] and life["number"] < forever["number"]
    assert 45 < life["age_at"] < 90
    # se já tem o suficiente, é hoje
    rich = fire.lifetime_plan(10_000_000, 12000, 0.0, 0, 45, 90, start=start)
    assert rich["date"] == start and rich["done"] > 1


def test_fire_stops_investing_and_withdraws_after_fire():
    from portfolio_investimentos.engine import fire
    start = date(2026, 11, 1)
    # vida inteira sem retorno: depois da data FIRE, o capital desce até perto de zero aos 90
    life = fire.lifetime_plan(100000, 12000, 0.0, 2000, 45, 90, start=start)
    pess = next(s for s in life["scenarios"] if s["name"] == "pessimista")
    assert pess["date"] and pess["empty"] is None  # chega até aos 90 (acaba perto de zero, mas chega)
    last_value = pess["points"][-1][1]
    assert 0 <= last_value < pess["number"]
    # para sempre, sem idade: depois do número FIRE, a regra dos 4% com 5% de retorno real quase não gasta o capital
    forever = fire.plan(100000, 12000, 0.04, 0.0, 2000, start=start)
    base = next(s for s in forever["scenarios"] if s["name"] == "base")
    after = [v for d, v in base["points"] if d > base["date"]]
    assert after and min(after) >= base["number"] * 0.95 and base["empty"] is None
    # a 3% real e levantamento de 4% do número FIRE, o dinheiro acaba (≈ 47 anos depois)
    pess = next(s for s in forever["scenarios"] if s["name"] == "pessimista")
    assert pess["empty"] is not None and pess["empty"] > pess["date"]
    # deixar de investir aos 46 (antes da data FIRE): chega mais tarde (ou não chega)
    stop = fire.lifetime_plan(100000, 12000, 0.0, 2000, 45, 90, start=start, stop_age=46)
    assert stop["date"] is None or stop["date"] > life["date"]


def test_fire_forever_with_pension():
    from portfolio_investimentos.engine import fire
    # sem retorno: dos 60 aos 67 todas as despesas (7 × 12 000); depois (12 000 − 8 400) / 4% = 90 000
    need = fire.required_with_pension(0.0, 12000, 0.04, 0.0, 60, 8400, 67, months=40 * 12)
    assert need[0] == pytest.approx(7 * 12000 + 90000)
    assert need[7 * 12] == pytest.approx(90000) and need[-1] == pytest.approx(90000)
    # a pensão paga tudo: só é preciso chegar à idade da pensão
    assert fire.required_with_pension(0.0, 12000, 0.04, 0.0, 60, 12600, 67, months=480)[0] == pytest.approx(84000)
    start = date(2026, 11, 1)
    wp = fire.pension_plan(100000, 12000, 0.04, 0.14, 1000, 45, 8400, 67, 90, start=start)
    forever = fire.plan(100000, 12000, 0.04, 0.14, 1000, start=start)
    assert wp["date"] < forever["date"] and wp["number"] < forever["number"]
    assert wp["after"] == pytest.approx(fire.fire_number(3600, 0.04, 0.14))


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
    from portfolio_investimentos.engine.portfolio import daily_returns
    rets = daily_returns([1 + x for x in perf2["twr"]], [date.fromisoformat(x) for x in perf2["dates"]])
    annual = sum(rets) / len(rets) * 252  # retorno médio diário anualizado, na base da volatilidade
    assert r2["sharpe"] == pytest.approx((annual - 0.02) / r2["volatility"])
    assert r2["sharpe"] < r0["sharpe"]


def test_short_periods_and_incomplete_years():
    """Períodos curtos: Sharpe com o retorno anualizado (positivo se a carteira sobe), sem Calmar, sem beta nem
    alfa com menos de 6 meses; o ano da primeira compra (a meio do ano) não entra no melhor/pior nem na média."""
    d0, d1 = date(2024, 6, 3), date(2026, 10, 30)
    prices = book_linear("ACME", d0, d1, 10.0, 15.0)
    prices.update(book_linear("^GSPC", d0, d1, 4000.0, 5000.0))
    for t in ("ACME", "^GSPC"):  # alguma volatilidade, a subir em média
        prices[t] = [(d, v * (1.004 if i % 2 else 0.997)) for i, (d, v) in enumerate(prices[t])]
    txs = [Tx(d0, "DEPOSIT", amount=1000), Tx(d0, "BUY", ACME, quantity=100, price=10)]
    p = Portfolio(txs, PriceBook(prices), benchmarks=[SPX], as_of=d1)
    one_month = p.performance("1M", risk_free=0.02)
    assert one_month["twr_total"] > 0 and one_month["risk"]["sharpe"] > 0
    assert one_month["risk"]["calmar"] is None and one_month["years"] < 1
    assert one_month["merit"]["beta"] is None and one_month["merit"]["alpha"] is None
    full = p.performance("MAX", risk_free=0.02)
    assert [k for k, _ in full["yearly"]] == ["2024", "2025", "2026"]
    assert full["best_year"][0] == "2025" and full["worst_year"][0] == "2025"  # 2024 (desde junho) e 2026 não
    assert full["risk"]["years"] == 1 and full["risk"]["avg_year"] == pytest.approx(dict(full["yearly"])["2025"])
    assert full["merit"]["years"] == 1 and full["merit"]["beta"] is not None
    from portfolio_investimentos.engine.portfolio import _complete
    months = [("2024-06", 0.1), ("2024-07", 0.2)]
    assert _complete(months, date(2024, 7, 31), "month", start=date(2024, 6, 3)) == months  # 3 de junho: completo
    assert _complete(months, date(2024, 7, 31), "month", start=date(2024, 6, 20)) == [("2024-07", 0.2)]


def _stress_book(as_of, amp):
    """S&P 500 a oscilar semana a semana e ACME a mexer-se `amp` vezes mais (beta = amp)."""
    import math
    days = list(weekdays(as_of - timedelta(weeks=160), as_of))
    spx = [(d, 4000 * (1 + 0.03 * math.sin(i / 3))) for i, d in enumerate(days)]
    acme = [(d, 100 * (1 + amp * 0.03 * math.sin(i / 3))) for i, d in enumerate(days)]
    return PriceBook({"^GSPC": spx, "ACME": acme})


def test_crisis_test_uses_position_beta_and_cash():
    from portfolio_investimentos.engine import stress
    as_of = date(2026, 6, 5)
    txs = [Tx(as_of - timedelta(weeks=150), "DEPOSIT", amount=12000),
           Tx(as_of - timedelta(weeks=150), "BUY", ACME, quantity=100, price=100)]
    p = Portfolio(txs, _stress_book(as_of, 1.5), benchmarks=[SPX], as_of=as_of)
    out = stress.crisis_test(p)
    acme = out["positions"][0]
    assert acme["beta"] == pytest.approx(1.5, abs=0.05) and not acme["estimated"]
    weight = acme["value"] / p.total_value  # o resto é caixa (beta 0)
    assert out["beta"] == pytest.approx(weight * acme["beta"])
    crisis = {c["key"]: c for c in out["crises"]}
    assert crisis["2008"]["drop"] == pytest.approx(out["beta"] * -0.568)
    assert crisis["2020"]["recovery"] == "6 meses" and crisis["2008"]["recovery"] == "5 anos e 5 meses"
    assert crisis["2022"]["loss"] == pytest.approx(crisis["2022"]["drop"] * p.total_value)
    # sem histórico suficiente: beta 1 (como o mercado), assinalado
    short = Portfolio(txs, PriceBook({"^GSPC": [(as_of, 4000.0)], "ACME": [(as_of, 100.0)]}), benchmarks=[SPX],
                      as_of=as_of)
    out = stress.crisis_test(short)
    assert out["positions"][0]["beta"] == 1.0 and out["estimated"] == 1


def test_cost_report_fees_ter_and_excess_withholding():
    from portfolio_investimentos.engine import costs
    etf = Instrument("WRLD", "ETF Mundo", kind="etf", currency="EUR")
    de = Instrument("DECO", "Empresa alemã", currency="EUR")
    pt = Instrument("PTCO", "Empresa portuguesa", currency="EUR")
    as_of = date(2026, 6, 1)
    d = as_of - timedelta(days=100)
    prices = {"WRLD": [(d, 100.0)], "DECO": [(d, 50.0)], "PTCO": [(d, 10.0)]}
    txs = [Tx(d - timedelta(days=400), "DEPOSIT", amount=50000),
           Tx(d - timedelta(days=400), "BUY", etf, quantity=100, price=100, fees=5),  # há mais de 12 meses
           Tx(d, "BUY", etf, quantity=100, price=100, fees=2),
           Tx(d, "BUY", de, quantity=100, price=50, fees=3),
           Tx(d, "BUY", pt, quantity=100, price=10, fees=1),
           Tx(d, "FEE", amount=-4),
           Tx(d + timedelta(days=10), "DIVIDEND", de, amount=100, tax=26.375),  # Alemanha: 26,375% retido
           Tx(d + timedelta(days=10), "DIVIDEND", pt, amount=100, tax=28)]      # Portugal: liberatória, não conta
    p = Portfolio(txs, PriceBook(prices), as_of=as_of)
    rep = costs.cost_report(p, {"DECO": "Alemanha", "PTCO": "Portugal"}, {"WRLD": 0.002})
    assert rep["fees"] == pytest.approx(2 + 3 + 1 + 4) and rep["operations"] == 4
    assert rep["etf_cost"] == pytest.approx(20000 * 0.002) and rep["etf_ter"] == pytest.approx(0.002)
    assert rep["excess"] == pytest.approx(26.375 - 15) and [r["ticker"] for r in rep["excess_rows"]] == ["DECO"]
    annuity = (1.05 ** 20 - 1) / 0.05
    ter_drag = 20000 * (1.05 ** 20 - 1.048 ** 20)
    assert rep["future"] == pytest.approx((10 + 11.375) * annuity + ter_drag)
    # ETF sem TER: fica de fora e listado
    rep = costs.cost_report(p, {}, {})
    assert rep["missing"] == ["WRLD"] and rep["etf_cost"] == 0 and rep["etf_ter"] is None and rep["excess"] == 0


def test_valuation_methods_ranges_and_implied_growth():
    from portfolio_investimentos.engine import valuation as val
    # DCF sem crescimento e desconto = terminal + algo: confere com a fórmula fechada
    v = val.dcf(10, 0.0, 0.10, years=10, terminal=0.0)
    assert v == pytest.approx(10 / 0.10)  # perpetuidade de 10 a 10%
    assert val.dcf(-1, 0.05, 0.09) is None and val.dcf(10, 0.05, 0.02) is None
    # crescimento implícito: o g que dá o preço; com o preço = dcf(g=7%), devolve 7%
    price = val.dcf(5, 0.07, 0.09)
    assert val.implied_growth(price, 5) == pytest.approx(0.07, abs=1e-6)
    assert val.implied_growth(100, -2) is None
    assert val.graham(4, 25) == pytest.approx((22.5 * 100) ** 0.5) and val.graham(-1, 25) is None
    out = val.value_stock(60, eps=4, eps_forward=5, bvps=25, fcf=3, growth=0.08, dividends=2.4)
    m = {x["key"]: x for x in out["methods"]}
    assert m["dcf"]["low"] == pytest.approx(val.dcf(3, 0.055, 0.10))
    assert m["dcf"]["high"] == pytest.approx(val.dcf(3, 0.105, 0.08))
    assert m["graham"]["low"] == pytest.approx(val.graham(4, 25)) and m["graham"]["high"] == pytest.approx(val.graham(5, 25))
    assert m["bazin"]["low"] == pytest.approx(2.4 / 0.08) and m["bazin"]["high"] == pytest.approx(2.4 / 0.06)
    assert out["base_kind"] == "cash flow livre" and out["implied"] is not None
    # a fórmula de cada método, com os números usados
    assert "C = cash flow livre por ação = 3,00" in m["dcf"]["formula"] and "g = 5,5%, r = 10,0%" in m["dcf"]["formula"]
    assert "√(22,5 × LPA × VCPA)" in m["graham"]["formula"]
    assert "4,00 (últimos 12 meses) e 5,00 (previsto)" in m["graham"]["formula"] and "25,00" in m["graham"]["formula"]
    assert "2,40" in m["bazin"]["formula"] and "6,0%" in m["bazin"]["formula"]
    # por ordem de popularidade; os quatro primeiros sempre visíveis, os outros em «Mais métodos»
    assert [x["key"] for x in out["methods"]] == ["dcf", "graham", "graham_growth", "gordon", "owner", "epv", "bazin"]
    assert [x["key"] for x in out["methods"] if not x["more"]] == ["dcf", "graham", "graham_growth", "gordon"]


def test_valuation_more_methods():
    from portfolio_investimentos.engine import valuation as val
    out = val.value_stock(60, eps=4, bvps=25, growth=0.08, dividends=2.4, div_growth=0.04, owner_earnings=3.5,
                          nopat=3.2, net_cash=-5, aaa_yield=0.05)
    m = {x["key"]: x for x in out["methods"]}
    # crescimento de Graham: LPA × (8,5 + 2g) × 4,4 ÷ Y, com g de 5,5% a 10,5% e Y = 5%
    assert m["graham_growth"]["low"] == pytest.approx(4 * (8.5 + 11) * 4.4 / 5)
    assert m["graham_growth"]["high"] == pytest.approx(4 * (8.5 + 21) * 4.4 / 5)
    # Gordon: D₀ × (1 + g) ÷ (Ke − g), g de 3% a 5%, Ke de 10% (baixo) a 8% (alto)
    assert m["gordon"]["low"] == pytest.approx(2.4 * 1.03 / (0.10 - 0.03))
    assert m["gordon"]["high"] == pytest.approx(2.4 * 1.05 / (0.08 - 0.05))
    # Owner Earnings descontados como no DCF; EPV = NOPAT ÷ WACC + caixa − dívida
    assert m["owner"]["low"] == pytest.approx(val.dcf(3.5, 0.055, 0.10)) and m["owner"]["more"]
    assert m["epv"]["low"] == pytest.approx(3.2 / 0.10 - 5) and m["epv"]["high"] == pytest.approx(3.2 / 0.08 - 5)
    # PEG: P/E ÷ crescimento em %; preço com PEG 1 = LPA × crescimento
    assert out["peg"]["peg"] == pytest.approx(15 / 8) and out["peg"]["fair"] == pytest.approx(32)
    # crescimento dos dividendos limitado a 6% (o Gordon não explode) e sem dados: motivo
    capped = {x["key"]: x for x in val.value_stock(60, eps=4, dividends=2, div_growth=0.30)["methods"]}
    assert capped["gordon"]["high"] == pytest.approx(2 * 1.06 / (0.08 - 0.06))
    none = {x["key"]: x for x in val.value_stock(10, eps=-1)["methods"]}
    assert none["owner"]["low"] is None and "demonstrações" in none["owner"]["why"]
    assert none["epv"]["low"] is None and none["graham_growth"]["why"] == "sem lucro positivo"
    assert val.value_stock(10, eps=-1)["peg"] is None
    assert out["scale"] >= max(60, m["dcf"]["high"])
    # sem cash flow livre: usa o lucro; sem dividendos nem lucro: métodos vazios com o motivo
    out = val.value_stock(10, eps=-1, bvps=5)
    m = {x["key"]: x for x in out["methods"]}
    assert m["dcf"]["low"] is None and m["graham"]["low"] is None and m["bazin"]["why"] == "não paga dividendos"
    assert out["implied"] is None and out["growth"] == val.GROWTH_DEFAULT and out["growth_default"]


def test_price_book_recent():
    d0 = date(2026, 1, 5)
    book = PriceBook({"ACME": [(d0 + timedelta(days=i), 10.0 + i) for i in range(10)]})
    assert book.recent("ACME", 3) == [(d0 + timedelta(days=7), 17.0), (d0 + timedelta(days=8), 18.0),
                                      (d0 + timedelta(days=9), 19.0)]
    assert book.recent("NADA", 3) == [] and len(book.recent("ACME", 50)) == 10


def test_opening_positions_are_estimated_per_broker():
    """Uma venda numa corretora sem o histórico completo não consome as ações de outra corretora:
    a carteira consolidada continua a ser a soma das corretoras."""
    d0 = date(2026, 1, 5)
    prices = {"ACME": [(d0, 10.0), (date(2026, 3, 2), 12.0)]}
    txs = [
        Tx(d0, "DEPOSIT", amount=2000, broker="A"),
        Tx(d0, "BUY", ACME, quantity=100, price=10, broker="A"),
        # na corretora B só há a venda (as compras são anteriores ao extrato importado)
        Tx(date(2026, 2, 2), "SELL", ACME, quantity=30, price=11, result=60.0, broker="B"),
    ]
    both = Portfolio(txs, PriceBook(prices), as_of=date(2026, 3, 2))
    only_a = Portfolio([t for t in txs if t.broker == "A"], PriceBook(prices), as_of=date(2026, 3, 2))
    assert both.positions["ACME"].qty == pytest.approx(100)  # as 100 da A ficam: a B tinha as suas 30
    assert only_a.positions["ACME"].qty == pytest.approx(100)
    assert any("já existiam antes" in w for w in both.warnings)



def test_parse_number_portuguese_and_other_formats():
    import pytest as _pytest
    from portfolio_investimentos.engine.formatting import parse_number
    cases = {"1000": 1000, "1 000": 1000, "1 000,50": 1000.5, "1.000": 1000, "1.000,50": 1000.5,
             "1.000.000": 1e6, "1000,5": 1000.5, "1000.5": 1000.5, "1,000.50": 1000.5, "1,000,000": 1e6,
             "0.125": 0.125, "2.5": 2.5, "0,22": 0.22, "12,345": 12.345, "-1.250,75": -1250.75, "−3,5": -3.5,
             "+4": 4, ",5": 0.5, 7: 7, 2.5: 2.5}
    for text, want in cases.items():
        assert abs(parse_number(text) - want) < 1e-9, text
    for bad in ("", "abc", "nan", "inf", "1e5", "1.000,000,5", "1,2.3.4", ".", "1..2", "--1", True):
        with _pytest.raises(ValueError):
            parse_number(bad)


def test_irr_short_period_not_annualized():
    # +2% em ~1 mês, sem depósitos no período: o IRR mostra +2% (do período), não ~+27% ao ano
    d0, d1 = date(2024, 1, 1), date(2024, 12, 31)
    first = book_linear("ACME", d0, date(2024, 11, 29), 10, 10)["ACME"]
    prices = {"ACME": first + book_linear("ACME", date(2024, 12, 2), d1, 10, 10.2)["ACME"]}
    p = Portfolio([Tx(d0, "BUY", ACME, quantity=10, price=10)], PriceBook(prices), as_of=d1)
    perf = p.performance("1M")
    assert perf["years"] < 1
    assert perf["irr"] == pytest.approx(perf["twr_total"], abs=0.003)
    assert perf["irr"] < 0.03 and perf["irr_annual"] > 0.15
    full = p.performance("MAX")  # 1 ano: igual ao anual
    assert full["years"] >= 0.99 and full["irr"] == pytest.approx(full["irr_annual"])


def test_shadow_investment_same_money_in_index():
    from datetime import date
    from portfolio_investimentos.engine.portfolio import shadow_investment
    days = [date(2025, 1, 1), date(2025, 7, 1), date(2026, 1, 1)]
    closes = [100.0, 200.0, 300.0]
    # 1000 € no início (10 unidades) e +2000 € a meio (10 unidades): 20 × 300 = 6000 €
    r = shadow_investment(days, closes, 1000.0, [0.0, 2000.0, 0.0], years=1.0)
    assert r["value"] == [1000.0, 4000.0, 6000.0]
    assert r["final"] == 6000.0 and r["gain"] == 3000.0 and r["irr"] > 0
    # um levantamento vende unidades: −1000 € a meio são 5 unidades; ficam 5 × 300 = 1500 €
    r = shadow_investment(days, closes, 1000.0, [0.0, -1000.0, 0.0], years=1.0)
    assert r["final"] == 1500.0 and r["gain"] == 1500.0
    # carteira vazia no início: o primeiro dia conta o fluxo desse dia
    r = shadow_investment(days, closes, 0.0, [500.0, 0.0, 0.0], years=1.0)
    assert r["final"] == 1500.0
    assert shadow_investment(days, [None, None, None], 1000.0, [0.0, 0.0, 0.0], years=1.0) is None


def test_bridge_transfers_between_brokers():
    from portfolio_investimentos.engine.portfolio import Instrument, Tx, bridge_transfers
    f50, f50de = Instrument("F50A"), Instrument("F50A.DE")
    other = Instrument("XYZ")
    txs = [
        Tx(date(2026, 4, 9), "WITHDRAWAL", amount=9000.0, broker="t212"),
        Tx(date(2026, 4, 11), "WITHDRAWAL", amount=8616.57, broker="t212"),       # chega com €16,57 a menos
        Tx(date(2026, 4, 13), "DEPOSIT", amount=8600.0, broker="xtb"),
        Tx(date(2026, 4, 13), "DEPOSIT", amount=9000.0, broker="xtb"),
        Tx(date(2026, 4, 21), "TRANSFER_OUT", f50, 229, 31.39, broker="t212"),
        Tx(date(2026, 4, 23), "TRANSFER_IN", f50de, 77, 31.39, broker="xtb"),    # chega em duas linhas
        Tx(date(2026, 4, 23), "TRANSFER_IN", f50de, 152, 31.39, broker="xtb"),
        # não são passagens entre corretoras: montante diferente, demasiado tarde, mesma corretora, outro ativo
        Tx(date(2026, 5, 1), "WITHDRAWAL", amount=1181.34, broker="t212"),
        Tx(date(2026, 5, 1), "DEPOSIT", amount=1000.0, broker="xtb"),
        Tx(date(2026, 6, 1), "WITHDRAWAL", amount=500.0, broker="t212"),
        Tx(date(2026, 6, 20), "DEPOSIT", amount=500.0, broker="xtb"),
        Tx(date(2026, 7, 1), "WITHDRAWAL", amount=300.0, broker="xtb"),
        Tx(date(2026, 7, 2), "DEPOSIT", amount=300.0, broker="xtb"),
        Tx(date(2026, 8, 1), "TRANSFER_OUT", other, 10, 5.0, broker="t212"),
        Tx(date(2026, 8, 2), "TRANSFER_IN", f50de, 10, 5.0, broker="xtb"),
    ]
    out = bridge_transfers(txs, {"F50A": "IE0009DRDY20"})
    assert [t.date for t in out[:2]] == [date(2026, 4, 13)] * 2   # o dinheiro sai no dia em que chega
    assert out[4].date == date(2026, 4, 23)                        # as ações também
    assert [t.date for t in out[7:]] == [t.date for t in txs[7:]]  # o resto fica igual
    assert out[2:4] == txs[2:4] and out[5:7] == txs[5:7]


def test_bridge_transfers_keep_total_value_in_transit():
    from portfolio_investimentos.engine.portfolio import Portfolio, PriceBook, Tx, bridge_transfers
    txs = [Tx(date(2026, 4, 1), "DEPOSIT", amount=10000.0, broker="a"),
           Tx(date(2026, 4, 6), "WITHDRAWAL", amount=10000.0, broker="a"),
           Tx(date(2026, 4, 8), "DEPOSIT", amount=10000.0, broker="b")]
    raw = Portfolio(txs, PriceBook({}, {}), []).series
    assert min(raw.value) == 0.0                                    # sem a junção, cai a zero dois dias
    s = Portfolio(bridge_transfers(txs), PriceBook({}, {}), []).series
    assert min(s.value) == pytest.approx(10000.0) and s.value[-1] == pytest.approx(10000.0)


def test_simulate_sale_fifo_without_touching_lots():
    from portfolio_investimentos.engine.portfolio import Lot, simulate_sale, tax_delta
    lots = [Lot(date(2024, 1, 10), 10, 1010.0, 1000.0, 1.01),          # €100 por ação
            Lot(date(2025, 3, 5), 10, 1515.0, 1500.0, 1.01, opening=False)]  # €150 por ação
    rows = simulate_sale(lots, 15, 220.0, 1.1, fees_local=22.0)  # (15 × 220 − 22) / 1,1 = €2 980
    assert [(r["acquired"], r["qty"]) for r in rows] == [(date(2024, 1, 10), 10), (date(2025, 3, 5), 5)]
    assert [round(r["cost_eur"], 2) for r in rows] == [1000.0, 750.0]
    assert round(sum(r["proceeds_eur"] for r in rows), 2) == 2980.0
    assert round(sum(r["gain_eur"] for r in rows), 2) == 1230.0
    assert [lot.qty for lot in lots] == [10, 10] and lots[0].cost_eur == 1000.0  # os lotes ficam iguais
    assert sum(r["qty"] for r in simulate_sale(lots, 99, 1.0, 1.0)) == 20     # não vende mais do que existe
    assert simulate_sale(lots[:1], 0, 1.0, 1.0) == []
    opening = simulate_sale([Lot(date(2020, 1, 1), 1, 5.0, 5.0, 1.0, opening=True)], 1, 6.0, 1.0)
    assert opening[0]["acquired"] is None
    assert tax_delta(1000.0, 500.0) == pytest.approx({"before": 280.0, "after": 420.0, "delta": 140.0})
    assert tax_delta(-300.0, 200.0) == pytest.approx({"before": 0.0, "after": 0.0, "delta": 0.0})  # perdas não dão reembolso
    assert tax_delta(500.0, -800.0)["delta"] == pytest.approx(-140.0)  # só abate até zero


def test_year_summary_and_dividends_in():
    from portfolio_investimentos.engine.portfolio import Instrument, Portfolio, PriceBook, Tx
    a = Instrument("AAA")
    prices = {"AAA": [(date(2024, 12, 31), 10.0), (date(2025, 6, 30), 11.0), (date(2025, 12, 31), 12.0)]}
    txs = [Tx(date(2024, 12, 31), "DEPOSIT", amount=1000.0), Tx(date(2024, 12, 31), "BUY", a, 100, 10.0),
           Tx(date(2025, 6, 30), "DEPOSIT", amount=1100.0), Tx(date(2025, 6, 30), "BUY", a, 100, 11.0),
           Tx(date(2025, 9, 1), "DIVIDEND", a, amount=50.0, tax=7.5)]
    p = Portfolio(txs, PriceBook(prices, {}), [])
    y = p.year_summary(2025)
    assert y["start"] == date(2024, 12, 31) and y["end"] == date(2025, 12, 31) and not y["partial"]
    assert y["value_start"] == pytest.approx(1000.0)
    assert y["value_end"] == pytest.approx(200 * 12 + 50 - 7.5)
    assert y["deposits"] == pytest.approx(1100.0)
    assert y["gain"] == pytest.approx(y["value_end"] - 1000.0 - 1100.0)
    assert y["twr"] == pytest.approx((1100 / 1000) * ((2400 + 42.5) / 2200) - 1, rel=1e-6)
    assert y["irr"] is not None and y["irr"] > 0
    first = p.year_summary(2024)  # a carteira começou a 31/12/2024: parte do zero
    assert first["start"] is None and first["value_start"] == 0.0 and first["deposits"] == pytest.approx(1000.0)
    assert p.year_summary(2023) is None
    d = p.dividends_in(2025)
    assert len(d) == 1 and d[0]["n"] == 1 and d[0]["gross"] == pytest.approx(50.0) and d[0]["net"] == pytest.approx(42.5)
    assert p.dividends_in(2024) == []
