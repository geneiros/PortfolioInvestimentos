"""Independência financeira (FIRE): o número FIRE, a parte já feita e a data em três cenários.

Tudo em euros de hoje: os retornos dos cenários são reais (já descontada a inflação), por isso as despesas e o
número FIRE não precisam de ser atualizados ano a ano. É uma simulação, não uma promessa.
"""
from datetime import date

SCENARIOS = (("pessimista", 0.03), ("base", 0.05), ("otimista", 0.07))
MAX_YEARS = 60


def fire_number(expenses, withdrawal_rate, tax_rate):
    """Património que paga `expenses` por ano, já depois do IRS sobre os levantamentos.

    Para gastar `expenses` líquidos é preciso levantar expenses / (1 − imposto efetivo); à taxa de levantamento
    `withdrawal_rate` (ex.: 4%), isso pede um património de levantamento / taxa.
    """
    gross = expenses / (1 - tax_rate) if tax_rate < 1 else float("inf")
    return gross / withdrawal_rate if withdrawal_rate > 0 else float("inf")


def _add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def project(value, monthly, rate, target, start, max_years=MAX_YEARS):
    """Valor mês a mês (contribuição no fim de cada mês) até `max_years`; devolve (pontos anuais, data FIRE)."""
    g = (1 + rate) ** (1 / 12) - 1
    points, reached = [(start, value)], None
    v = value
    if v >= target:
        reached = start
    for m in range(1, max_years * 12 + 1):
        v = v * (1 + g) + monthly
        d = _add_months(start, m)
        if reached is None and v >= target:
            reached = d
        if m % 12 == 0:
            points.append((d, v))
    return points, reached


def plan(value, expenses, withdrawal_rate, tax_rate, monthly, start=None):
    start = start or date.today().replace(day=1)
    target = fire_number(expenses, withdrawal_rate, tax_rate)
    scenarios = []
    for name, rate in SCENARIOS:
        points, reached = project(value, monthly, rate, target, start)
        scenarios.append({"name": name, "rate": rate, "points": points, "date": reached})
    base = next(s for s in scenarios if s["name"] == "base")
    return {"number": target, "done": value / target if target > 0 else 0.0, "value": value,
            "expenses": expenses, "withdrawal_rate": withdrawal_rate, "tax_rate": tax_rate, "monthly": monthly,
            "scenarios": scenarios, "date": base["date"],
            "earliest": next((s["date"] for s in reversed(scenarios) if s["date"]), None),
            "latest": scenarios[0]["date"]}


def monthly_track(dates, values, target, months=12):
    """Acompanhamento: valor no fim de cada mês (os últimos `months`), a parte do número FIRE e a variação."""
    ends = {}
    for d, v in zip(dates, values):
        ends[(d.year, d.month)] = (d, v)
    rows, prev = [], None
    for key in sorted(ends)[-(months + 1):]:
        d, v = ends[key]
        if prev is not None:
            rows.append({"month": key, "value": v, "done": v / target if target > 0 else 0.0, "change": v - prev})
        prev = v
    return list(reversed(rows))
