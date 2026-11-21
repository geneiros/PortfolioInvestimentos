"""Independência financeira (FIRE): o número FIRE, a data em que lá chegas e o que a mexe.

Tudo em euros de hoje: os retornos são reais (já descontada a inflação), por isso o rendimento pretendido e o número
FIRE não precisam de ser atualizados ano a ano. É uma simulação, não uma promessa.

A carteira junta o depósito mensal todos os meses. O número FIRE de cada mês é o capital que paga o rendimento
pretendido (depois do IRS) dali em diante:
- sem rendimentos fora da carteira: rendimento ÷ (1 − imposto) ÷ taxa de levantamento, para sempre;
- com rendimentos fora da carteira (pensão, rendas) que começam mais tarde: até cada um começar, a carteira paga
  tudo; a partir daí, só a diferença. Calcula-se para trás, desde o último a começar:
  necessário(t) = levantamento(t) + necessário(t + 1) / (1 + g).
A data FIRE é o primeiro mês em que a carteira chega ao número FIRE desse mês.
"""
from datetime import date

SCENARIOS = (("prudente", "Prudente", 0.03), ("central", "Central", 0.05), ("otimista", "Otimista", 0.07))
MAX_YEARS = 60
MONTHS = MAX_YEARS * 12


def fire_number(expenses, withdrawal_rate, tax_rate):
    """Património que paga `expenses` por ano, já depois do IRS sobre os levantamentos.

    Para gastar `expenses` líquidos é preciso levantar expenses / (1 − imposto efetivo); à taxa de levantamento
    `withdrawal_rate` (ex.: 4%), isso pede um património de levantamento / taxa.
    """
    if expenses <= 0:
        return 0.0
    gross = expenses / (1 - tax_rate) if tax_rate < 1 else float("inf")
    return gross / withdrawal_rate if withdrawal_rate > 0 else float("inf")


def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def months_between(a, b):
    return (b.year - a.year) * 12 + b.month - a.month


def monthly_rate(rate):
    return (1 + rate) ** (1 / 12) - 1


def income_at(incomes, m):
    """Rendimentos fora da carteira (€ por mês) já ativos no mês `m`. `incomes`: [(€ por mês, mês de início)]."""
    return sum(amount for amount, start in incomes if m >= start)


def need_curve(income, withdrawal_rate, tax_rate, incomes=(), rate=0.05, months=MONTHS):
    """O número FIRE de cada mês (0 = hoje): o capital que paga `income` por ano dali em diante, com os rendimentos
    fora da carteira a abater a partir do mês em que começam (ver o início do módulo)."""
    last = max([start for _, start in incomes if start > 0] or [0])
    after = fire_number(max(income - 12 * income_at(incomes, last), 0.0), withdrawal_rate, tax_rate)
    need = [after] * (max(months, last) + 1)
    g = monthly_rate(rate)
    for t in range(last - 1, -1, -1):
        withdrawal = max(income / 12 - income_at(incomes, t), 0.0) / (1 - tax_rate)
        need[t] = withdrawal + need[t + 1] / (1 + g)
    return need[:months + 1]


def project(value, monthly, rate, months=MONTHS, rates=None):
    """Valor da carteira mês a mês (0 = hoje), a juntar `monthly` por mês. `rates`, se dada, é a taxa real anual de
    cada ano (simulações com os anos verdadeiros); senão, `rate` todos os anos."""
    out, v = [value], value
    g = monthly_rate(rate)
    for m in range(months):
        if rates is not None:
            g = monthly_rate(rates[m // 12])
        v = v * (1 + g) + monthly
        out.append(v)
    return out


def reach(values, target):
    """Primeiro mês em que `values` chega a `target` (um número ou a curva mês a mês); None se não chega."""
    for m, v in enumerate(values):
        t = target[min(m, len(target) - 1)] if isinstance(target, list) else target
        if v >= t - 0.005:
            return m
    return None


def scenario(value, monthly, income, withdrawal_rate, tax_rate, incomes, rate, months=MONTHS):
    """Um cenário: a curva da carteira, a do número FIRE, o mês FIRE e o número FIRE nesse mês."""
    need = need_curve(income, withdrawal_rate, tax_rate, incomes, rate, months)
    values = project(value, monthly, rate, months)
    m = reach(values, need)
    return {"rate": rate, "values": values, "need": need, "month": m,
            "number": need[m] if m is not None else need[0]}


def monthly_needed(value, income, withdrawal_rate, tax_rate, incomes, rate, target_month, high=100000.0):
    """Depósito mensal que chega ao número FIRE até `target_month` (procura binária); None se nem `high` chega."""
    need = need_curve(income, withdrawal_rate, tax_rate, incomes, rate, max(target_month, 1))

    def ok(monthly):
        m = reach(project(value, monthly, rate, target_month), need)
        return m is not None and m <= target_month
    if ok(0.0):
        return 0.0
    if not ok(high):
        return None
    lo, hi = 0.0, high
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if ok(mid) else (mid, hi)
    return hi


def milestones(history, values, start, step=100000.0, count=5, until=None):
    """Quanto tempo leva cada `step` €: [(n.º, mês em que chegou ou chega, meses que levou)] até `count` marcos (ou
    até ao primeiro acima de `until`).

    `history`: [(data, valor)] real até hoje; `values`: projeção mês a mês desde `start` (o 1.º dia do mês de hoje).
    """
    out, prev = [], None
    first = history[0][0] if history else start
    first = date(first.year, first.month, 1)
    for k in range(1, count + 1):
        level = k * step
        when = next((date(d.year, d.month, 1) for d, v in history if v >= level), None)
        if when is None:
            m = reach(values, level)
            when = add_months(start, m) if m is not None else None
        since = prev or first
        out.append({"n": k, "level": level, "date": when,
                    "months": months_between(since, when) if when else None, "since": since})
        prev = when
        if when is None or (until is not None and level >= until):
            break
    return out


def coverage(items, values, withdrawal_rate, tax_rate, incomes, start):
    """As despesas do mês que o rendimento sustentável paga, da mais barata para a mais cara.

    O rendimento sustentável de cada mês é o valor da carteira × taxa de levantamento, depois do IRS, mais os
    rendimentos fora da carteira já ativos. Cada despesa fica paga quando esse rendimento chega à soma dela com as
    mais baratas. Devolve as despesas com `paid` (hoje), `part` (o que já está pago, na primeira por pagar) e
    `date` (quando fica paga).
    """
    def sustainable(m):
        return values[m] * withdrawal_rate * (1 - tax_rate) / 12 + income_at(incomes, m)
    today = sustainable(0)
    out, total = [], 0.0
    for name, amount in sorted(items, key=lambda x: x[1]):
        before, total = total, total + amount
        m = next((k for k in range(len(values)) if sustainable(k) >= total - 0.005), None)
        out.append({"name": name, "amount": amount, "cum": total, "paid": today >= total - 0.005,
                    "part": max(min(today - before, amount), 0.0),
                    "date": add_months(start, m) if m is not None else None})
    return {"today": today, "items": out}


def historical_paths(value, monthly, need, real_returns, months=MONTHS):
    """Uma simulação por cada ano de partida da tabela: os retornos reais anuais por ordem, a voltar ao início
    quando a tabela acaba. Devolve, por simulação, o ano de partida, a curva anual e o mês FIRE (ou None)."""
    years = sorted(real_returns)
    seq = [real_returns[y] for y in years]
    out = []
    for i, y in enumerate(years):
        rates = [seq[(i + k) % len(seq)] for k in range(months // 12 + 1)]
        values = project(value, monthly, 0.0, months, rates=rates)
        out.append({"from": y, "values": values[::12], "month": reach(values, need)})
    return out


def probability(paths, month):
    """Parte das simulações que chegam ao número FIRE até ao mês `month`."""
    if not paths:
        return 0.0
    return sum(1 for p in paths if p["month"] is not None and p["month"] <= month) / len(paths)
