"""Os custos da carteira: comissões, custo anual dos ETF (TER) e retenções na fonte a mais, por ano e daqui a N anos.

- Comissões: as das operações (compras, vendas) e os movimentos de comissão, nos últimos 12 meses, em euros.
- Custo dos ETF: valor de cada ETF × TER (indicado pelo utilizador). Os ETF sem TER ficam de fora e são listados.
- Retenções a mais: num dividendo estrangeiro, o IRS português só aceita como crédito a retenção até à taxa da
  convenção (15% na maioria dos países). O que o país de origem reteve acima disso só se recupera lá, com um
  pedido de reembolso. Estimativa com 15% (as convenções têm exceções). Os dividendos portugueses (28% é a taxa
  liberatória) e os de país desconhecido ficam de fora.
- Daqui a N anos: as comissões e as retenções a mais de hoje, todos os anos, a render o que a carteira renderia
  (anuidade); o TER é um custo sobre o valor, por isso compara-se a carteira a crescer com e sem ele.
"""
from datetime import timedelta

TREATY_RATE = 0.15
HORIZON = 20
RATE = 0.05  # retorno anual (real) usado na projeção, o do cenário base do Planeamento


def cost_report(p, countries, ters, horizon=HORIZON, rate=RATE):
    """`countries`: ticker → país; `ters`: ticker → TER (fração) ou None. Devolve o relatório ou None."""
    if not p.transactions:
        return None
    since = p.as_of - timedelta(days=365)
    fees, operations = 0.0, 0
    excess, excess_rows = 0.0, {}
    for t in p.transactions:
        if t.date <= since:
            continue
        if t.fees:
            fees += t.fees / p.book.fx(t.currency, t.date)
            operations += 1
        if t.type == "FEE" and t.amount:
            fees += abs(p.book.to_eur(t.amount, t.currency, t.date))
            operations += 1
        country = countries.get(t.asset.ticker) if t.asset is not None else None
        # Portugal: a retenção de 28% é a taxa liberatória, não é "a mais"; país desconhecido: não se sabe
        if t.type == "DIVIDEND" and t.tax and t.amount and country not in (None, "Outros", "Portugal"):
            gross = p.book.to_eur(t.amount, t.currency, t.date)
            tax = p.book.to_eur(t.tax, t.currency, t.date)
            extra = tax - TREATY_RATE * gross
            if extra > 0.005:
                excess += extra
                row = excess_rows.setdefault(t.asset.ticker, {"ticker": t.asset.ticker, "country": country,
                                                               "gross": 0.0, "tax": 0.0, "excess": 0.0})
                row["gross"] += gross
                row["tax"] += tax
                row["excess"] += extra
    etfs, missing, etf_cost, etf_value = [], [], 0.0, 0.0
    for pos in p.open_positions:
        if pos.asset.kind != "etf":
            continue
        ter = ters.get(pos.asset.ticker)
        etfs.append({"ticker": pos.asset.ticker, "name": pos.asset.name, "value": pos.value_eur, "ter": ter,
                     "cost": pos.value_eur * ter if ter is not None else None})
        if ter is None:
            missing.append(pos.asset.ticker)
        else:
            etf_cost += pos.value_eur * ter
            etf_value += pos.value_eur
    value = p.total_value
    annuity = ((1 + rate) ** horizon - 1) / rate
    drag_ter = etf_value * ((1 + rate) ** horizon - (1 + rate - (etf_cost / etf_value)) ** horizon) if etf_value else 0.0
    future = (fees + excess) * annuity + drag_ter
    for r in excess_rows.values():
        r["rate"] = r["tax"] / r["gross"] if r["gross"] else 0.0
    return {"fees": fees, "operations": operations, "etf_cost": etf_cost,
            "etf_ter": etf_cost / etf_value if etf_value else None, "etfs": etfs, "missing": missing,
            "excess": excess, "excess_rows": sorted(excess_rows.values(), key=lambda r: -r["excess"]),
            "annual": fees + etf_cost + excess, "annual_pct": (fees + etf_cost + excess) / value if value > 0 else None,
            "future": future, "horizon": horizon, "rate": rate}
