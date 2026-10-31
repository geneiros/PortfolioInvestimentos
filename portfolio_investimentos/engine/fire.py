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


def required_by_month(rate, expenses, tax_rate, age, until_age, pension=0.0, pension_age=None):
    """Capital necessário em cada mês a partir de hoje para pagar as despesas até `until_age` (e acabar a zero).

    Para trás, desde o último mês: necessário(t) = levantamento(t) + necessário(t + 1) / (1 + g). O levantamento
    é o que falta às despesas depois da pensão (a partir de `pension_age`), já com o imposto sobre a venda.
    Devolve uma lista indexada pelo mês a contar de hoje (0 = hoje).
    """
    g = (1 + rate) ** (1 / 12) - 1
    months = max(int(round((until_age - age) * 12)), 0)
    need = [0.0] * (months + 1)
    for t in range(months - 1, -1, -1):
        age_t = age + t / 12
        income = pension if pension_age is not None and age_t >= pension_age else 0.0
        withdraw = max(expenses - income, 0.0) / 12 / (1 - tax_rate)
        need[t] = withdraw + need[t + 1] / (1 + g)
    return need


def lifetime_plan(value, expenses, tax_rate, monthly, age, until_age, pension=0.0, pension_age=None, start=None):
    """Como `plan`, mas o capital só tem de durar até `until_age`: a data é o primeiro mês em que o valor da
    carteira chega ao capital necessário para viver dele desde esse mês até ao fim."""
    start = start or date.today().replace(day=1)
    scenarios = []
    for name, rate in SCENARIOS:
        need = required_by_month(rate, expenses, tax_rate, age, until_age, pension, pension_age)
        g = (1 + rate) ** (1 / 12) - 1
        v, reached, number = value, None, None
        # o último ano não conta: "chegar" aos 89 para viver até aos 90 não é independência financeira
        for m in range(max(len(need) - 12, 0)):
            if v >= need[m]:
                reached, number = _add_months(start, m), need[m]
                break
            v = v * (1 + g) + monthly
        curve = [(_add_months(start, m), need[m]) for m in range(0, len(need), 12)]
        at = None if reached is None else age + (reached.year - start.year) + (reached.month - start.month) / 12
        scenarios.append({"name": name, "rate": rate, "date": reached, "number": number,
                          "now": need[0] if need else 0.0, "age": at, "curve": curve})
    base = next(s for s in scenarios if s["name"] == "base")
    return {"scenarios": scenarios, "date": base["date"], "number": base["number"], "now": base["now"],
            "age_at": base["age"], "done": value / base["now"] if base["now"] else 0.0,
            "earliest": next((s["date"] for s in reversed(scenarios) if s["date"]), None),
            "latest": scenarios[0]["date"], "until_age": until_age, "pension": pension, "pension_age": pension_age}
