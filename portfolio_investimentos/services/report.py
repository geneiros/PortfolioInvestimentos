"""Relatório anual (para imprimir ou guardar em PDF): resumo, dividendos, mais-valias, juros, património e posições
a 31/12 de um ano, da corretora selecionada (ou de todas)."""
from datetime import date

from . import data, networth
from .insights import countries_of

MSCI_WORLD = "URTH"


def years(p):
    """Anos com dados na carteira, do mais recente para o mais antigo."""
    if not p.series.dates:
        return []
    return list(range(p.series.dates[-1].year, p.series.dates[0].year - 1, -1))


def default_year(p, today=None):
    """O último ano completo com dados (o que se envia ao contabilista); sem ele, o ano corrente."""
    today = today or date.today()
    ys = years(p)
    past = [y for y in ys if y < today.year]
    return past[0] if past else (ys[0] if ys else today.year)


def _networth(year, today):
    """Património no fim do ano anterior e no fim deste (ou no mês corrente), se a página Património é usada."""
    if not networth.assets():
        return None
    h = networth.history(data.load_portfolio(None))
    months = h["months"]

    def at(y, m):
        key = f"{y}-{m:02d}"
        earlier = [i for i, k in enumerate(months) if k <= key]
        if not earlier:
            return None
        i = earlier[-1]
        return {"month": months[i], "total": h["total"][i], "available": h["available"][i]}

    end_month = 12 if year < today.year else today.month
    start, end = at(year - 1, 12), at(year, end_month)
    if end is None:
        return None
    return {"start": start, "end": end, "change": end["total"] - (start["total"] if start else 0.0)}


def build(broker, year, today=None):
    """Dados do relatório de `year` para a corretora `broker` (None = todas). None se não houver dados nesse ano."""
    today = today or date.today()
    p = data.load_portfolio(broker)
    summary = p.year_summary(year)
    if summary is None:
        return None
    msci = next((b for b in summary["benchmarks"] if b["ticker"] == MSCI_WORLD), None)

    divs = p.dividends_in(year)
    country_of = countries_of({r["asset"].ticker: r["asset"].currency for r in divs})
    by_country = {}
    for r in divs:
        c = by_country.setdefault(country_of.get(r["asset"].ticker, "Outros"),
                                  {"country": country_of.get(r["asset"].ticker, "Outros"), "n": 0,
                                   "gross": 0.0, "tax": 0.0, "net": 0.0})
        c["n"] += 1
        for k in ("gross", "tax", "net"):
            c[k] += r[k]
    div_total = {k: sum(r[k] for r in divs) for k in ("gross", "tax", "net")}

    fy = p.fiscal_years().get(year)
    sales = {}
    for sl in (fy["sales"] if fy else []):
        g = sales.setdefault(sl.asset.ticker, {"asset": sl.asset, "lots": 0, "qty": 0.0, "proceeds": 0.0, "cost": 0.0})
        g["lots"] += 1
        g["qty"] += sl.qty
        g["proceeds"] += sl.proceeds_eur
        g["cost"] += sl.cost_eur
    for g in sales.values():
        g["gain"] = g["proceeds"] - g["cost"]

    end = min(date(year, 12, 31), today)
    at_end = data.portfolio_at(broker, end)
    positions = [pos for pos in at_end.open_positions if not pos.asset.is_benchmark]
    holdings = sum(pos.value_eur for pos in positions)

    # gráfico: o valor total e o dinheiro investido em cada dia do ano
    s = p.series
    idx = [i for i, d in enumerate(s.dates) if d.year == year]
    chart = {"dates": [s.dates[i].isoformat() for i in idx], "value": [round(s.value[i], 2) for i in idx],
             "deposits": [round(s.net_deposits[i], 2) for i in idx]}
    monthly_div = [0.0] * 12
    for d in p.dividends:
        if d.date.year == year:
            monthly_div[d.date.month - 1] += d.net_eur

    return {
        "year": year, "summary": summary, "msci": msci, "end": end, "partial": summary["partial"],
        "dividends": divs, "dividends_by_country": sorted(by_country.values(), key=lambda c: -c["gross"]),
        "dividends_total": div_total, "fiscal": fy, "sales": sorted(sales.values(), key=lambda g: g["asset"].ticker),
        "interest": fy["interest"] if fy else 0.0, "networth": _networth(year, today),
        "positions": positions, "holdings": holdings, "cash": at_end.cash,
        "chart": chart, "monthly_div": [round(v, 2) for v in monthly_div],
    }
