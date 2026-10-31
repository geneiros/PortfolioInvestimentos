"""Independência financeira (FIRE): o número FIRE, a parte já feita e a data em três cenários.

Tudo em euros de hoje: os retornos dos cenários são reais (já descontada a inflação), por isso as despesas e o
número FIRE não precisam de ser atualizados ano a ano. É uma simulação, não uma promessa.

Cada cenário tem duas fases: até à data FIRE juntas o investimento mensal (ou só até à idade em que deixas de
investir); a partir dela deixas de investir e passas a levantar o que as despesas pedem (já com o IRS dos
levantamentos), menos a pensão a partir da idade em que a recebes.
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


def _withdrawal(expenses, tax_rate, age_t, pension, pension_age):
    """Levantamento mensal: o que a pensão (a partir da idade dela) não paga, já com o IRS da venda."""
    income = pension if pension_age is not None and age_t is not None and age_t >= pension_age else 0.0
    return max(expenses - income, 0.0) / 12 / (1 - tax_rate)


def simulate(value, monthly, rate, start, months, is_fire, expenses, tax_rate, age=None, pension=0.0,
             pension_age=None, stop_age=None):
    """Simula mês a mês: junta `monthly` até à data FIRE (ou até `stop_age`), depois levanta.

    `is_fire(m, v)` diz se, no mês `m` com o valor `v`, a carteira já chega. Devolve os pontos anuais, o mês
    FIRE e o mês em que o dinheiro acaba (None se não acabar dentro de `months`).
    """
    g = (1 + rate) ** (1 / 12) - 1
    v, fire_m, empty_m = value, None, None
    points = [(start, value)]
    for m in range(months + 1):
        age_t = None if age is None else age + m / 12
        if fire_m is None and is_fire(m, v):
            fire_m = m
        if m == months:
            break
        if fire_m is None:
            investing = stop_age is None or age_t is None or age_t < stop_age
            v = v * (1 + g) + (monthly if investing else 0.0)
        else:
            v = v * (1 + g) - _withdrawal(expenses, tax_rate, age_t, pension, pension_age)
            if v <= 0:
                v = 0.0
                if empty_m is None:
                    empty_m = m + 1
        if (m + 1) % 12 == 0:
            points.append((_add_months(start, m + 1), v))
    return points, fire_m, empty_m


def _summary(name, rate, start, points, fire_m, empty_m, age, number=None):
    reached = None if fire_m is None else _add_months(start, fire_m)
    return {"name": name, "rate": rate, "points": points, "date": reached, "number": number,
            "age": None if age is None or fire_m is None else age + fire_m / 12,
            "empty": None if empty_m is None else _add_months(start, empty_m),
            "empty_age": None if age is None or empty_m is None else age + empty_m / 12}


def plan(value, expenses, withdrawal_rate, tax_rate, monthly, start=None, age=None, pension=0.0, pension_age=None,
         stop_age=None, horizon_age=None):
    """Para sempre: a data FIRE é quando a carteira chega ao número FIRE (regra dos x%)."""
    start = start or date.today().replace(day=1)
    target = fire_number(expenses, withdrawal_rate, tax_rate)
    months = int(round((horizon_age - age) * 12)) if age is not None and horizon_age else MAX_YEARS * 12
    scenarios = []
    for name, rate in SCENARIOS:
        points, fire_m, empty_m = simulate(value, monthly, rate, start, months, lambda m, v: v >= target, expenses,
                                           tax_rate, age, pension, pension_age, stop_age)
        scenarios.append(_summary(name, rate, start, points, fire_m, empty_m, age, target))
    base = next(s for s in scenarios if s["name"] == "base")
    return {"number": target, "done": value / target if target > 0 else 0.0, "value": value,
            "expenses": expenses, "withdrawal_rate": withdrawal_rate, "tax_rate": tax_rate, "monthly": monthly,
            "scenarios": scenarios, "date": base["date"],
            "earliest": next((s["date"] for s in reversed(scenarios) if s["date"]), None),
            "latest": scenarios[0]["date"]}


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
        need[t] = _withdrawal(expenses, tax_rate, age + t / 12, pension, pension_age) + need[t + 1] / (1 + g)
    return need


def lifetime_plan(value, expenses, tax_rate, monthly, age, until_age, pension=0.0, pension_age=None, start=None,
                  stop_age=None):
    """Até `until_age`: a data FIRE é o primeiro mês em que a carteira chega ao capital necessário para viver dela
    desse mês até ao fim (o último ano não conta: "chegar" aos 89 para viver até aos 90 não é FIRE)."""
    start = start or date.today().replace(day=1)
    scenarios = []
    for name, rate in SCENARIOS:
        need = required_by_month(rate, expenses, tax_rate, age, until_age, pension, pension_age)
        last = len(need) - 12
        points, fire_m, empty_m = simulate(value, monthly, rate, start, len(need) - 1,
                                           lambda m, v: m < last and v >= need[m], expenses, tax_rate, age,
                                           pension, pension_age, stop_age)
        s = _summary(name, rate, start, points, fire_m, empty_m, age, None if fire_m is None else need[fire_m])
        s["now"] = need[0] if need else 0.0
        s["curve"] = [(_add_months(start, m), need[m]) for m in range(0, len(need), 12)]
        scenarios.append(s)
    base = next(s for s in scenarios if s["name"] == "base")
    return {"scenarios": scenarios, "date": base["date"], "number": base["number"], "now": base["now"],
            "age_at": base["age"], "done": value / base["now"] if base["now"] else 0.0,
            "earliest": next((s["date"] for s in reversed(scenarios) if s["date"]), None),
            "latest": scenarios[0]["date"], "until_age": until_age, "pension": pension, "pension_age": pension_age}


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


def required_with_pension(rate, expenses, withdrawal_rate, tax_rate, age, pension, pension_age, months):
    """Capital necessário em cada mês para viver para sempre, contando com a pensão a partir de `pension_age`.

    Duas partes: até à pensão, pagar as despesas todas (com o IRS dos levantamentos); a partir dela, o que a
    pensão não cobre, pela regra da taxa de levantamento (para sempre). Calcula-se para trás desde o mês da pensão:
    necessário(t) = levantamento(t) + necessário(t + 1) / (1 + g), e daí em diante fica o número da segunda parte.
    """
    g = (1 + rate) ** (1 / 12) - 1
    after = fire_number(max(expenses - pension, 0.0), withdrawal_rate, tax_rate) if expenses > pension else 0.0
    to_pension = max(int(round((pension_age - age) * 12)), 0)
    need = [after] * (max(months, to_pension) + 1)
    for t in range(to_pension - 1, -1, -1):
        need[t] = _withdrawal(expenses, tax_rate, age + t / 12, 0.0, None) + need[t + 1] / (1 + g)
    return need


def pension_plan(value, expenses, withdrawal_rate, tax_rate, monthly, age, pension, pension_age, horizon_age,
                 start=None, stop_age=None):
    """Para sempre, com a pensão: a data FIRE é o primeiro mês em que a carteira chega ao capital necessário
    (até à pensão as despesas todas; depois, o que a pensão não cobre, para sempre)."""
    start = start or date.today().replace(day=1)
    months = max(int(round((horizon_age - age) * 12)), 12)
    scenarios = []
    for name, rate in SCENARIOS:
        need = required_with_pension(rate, expenses, withdrawal_rate, tax_rate, age, pension, pension_age, months)
        points, fire_m, empty_m = simulate(value, monthly, rate, start, months, lambda m, v: v >= need[m],
                                           expenses, tax_rate, age, pension, pension_age, stop_age)
        s = _summary(name, rate, start, points, fire_m, empty_m, age, None if fire_m is None else need[fire_m])
        s["now"] = need[0]
        scenarios.append(s)
    base = next(s for s in scenarios if s["name"] == "base")
    return {"scenarios": scenarios, "date": base["date"], "number": base["number"], "now": base["now"],
            "age_at": base["age"], "done": value / base["now"] if base["now"] else 0.0,
            "earliest": next((s["date"] for s in reversed(scenarios) if s["date"]), None),
            "latest": scenarios[0]["date"],
            "after": fire_number(max(expenses - pension, 0.0), withdrawal_rate, tax_rate) if expenses > pension else 0.0}
