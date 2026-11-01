"""As crises: quanto cairia a carteira de hoje se 2008, 2011, 2020 ou 2022 se repetissem.

Modelo simples e transparente (uma ilustração, não uma previsão):
- a sensibilidade de cada posição ao mercado (beta) estima-se com os retornos semanais, em euros, dos últimos
  3 anos face ao S&P 500 (também em euros); sem 26 semanas de dados usa-se 1 (como o mercado);
- a queda da carteira = Σ peso × beta × queda do S&P 500 nessa crise (a caixa não cai);
- o tempo até recuperar é o do S&P 500, do pico até voltar ao valor do pico (a carteira segue o índice
  na proporção do seu beta, por isso volta ao valor de antes quando o índice volta).

Nas crises, as correlações sobem e as quedas costumam ser maiores do que o beta normal sugere.
"""
from datetime import timedelta

BENCH = "^GSPC"
WEEKS = 156       # 3 anos de semanas
MIN_WEEKS = 26
BETA_RANGE = (0.0, 2.5)

# crise: (chave, nome, ano, queda do S&P 500 do pico ao fundo, meses do pico até voltar ao pico, datas)
CRISES = (
    ("2008", "Crise financeira", 2008, -0.568, 65, "pico 09/10/2007 · fundo 09/03/2009 · recuperado 03/2013"),
    ("2011", "Dívida do euro", 2011, -0.194, 10, "pico 29/04/2011 · fundo 03/10/2011 · recuperado 02/2012"),
    ("2020", "Pandemia", 2020, -0.339, 6, "pico 19/02/2020 · fundo 23/03/2020 · recuperado 08/2020"),
    ("2022", "Inflação e juros", 2022, -0.254, 24, "pico 03/01/2022 · fundo 12/10/2022 · recuperado 01/2024"),
)


def _weekly(p, ticker, currency, days):
    """Fechos semanais em euros (None sem cotação nessa data)."""
    out = []
    first = p.book._prices.get(ticker, ([], []))[0][:1]
    for d in days:
        if not first or d < first[0]:
            out.append(None)
            continue
        price = p.book.price(ticker, d)
        out.append(price / p.book.fx(currency, d) if price else None)
    return out


def _returns(xs):
    return [b / a - 1 if a and b else None for a, b in zip(xs, xs[1:])]


def beta(asset_r, bench_r):
    pairs = [(a, b) for a, b in zip(asset_r, bench_r) if a is not None and b is not None]
    if len(pairs) < MIN_WEEKS:
        return None
    ma = sum(a for a, _ in pairs) / len(pairs)
    mb = sum(b for _, b in pairs) / len(pairs)
    var = sum((b - mb) ** 2 for _, b in pairs)
    if var <= 1e-12:
        return None
    return sum((a - ma) * (b - mb) for a, b in pairs) / var


def _months(n):
    years, months = divmod(int(n), 12)
    parts = []
    if years:
        parts.append(f"{years} ano" + ("s" if years > 1 else ""))
    if months:
        parts.append(f"{months} " + ("meses" if months > 1 else "mês"))
    return " e ".join(parts) or "menos de 1 mês"


def crisis_test(p):
    """Queda estimada da carteira de hoje em cada crise. None sem posições abertas."""
    total = p.total_value
    if not p.open_positions or total <= 0:
        return None
    bench = next((b for b in p.benchmarks if b.ticker == BENCH), None)
    days = [p.as_of - timedelta(weeks=k) for k in range(WEEKS, -1, -1)]
    bench_r = _returns(_weekly(p, BENCH, bench.currency if bench else "USD", days)) if bench else []
    rows = []
    for pos in p.open_positions:
        b = beta(_returns(_weekly(p, pos.asset.ticker, pos.asset.currency, days)), bench_r) if bench_r else None
        estimated = b is None
        b = 1.0 if b is None else min(max(b, BETA_RANGE[0]), BETA_RANGE[1])
        rows.append({"ticker": pos.asset.ticker, "name": pos.asset.name, "weight": pos.value_eur / total,
                     "value": pos.value_eur, "beta": b, "estimated": estimated})
    portfolio_beta = sum(r["weight"] * r["beta"] for r in rows)  # a caixa conta com beta 0
    crises = []
    for key, name, year, drop, months, dates in CRISES:
        fall = max(portfolio_beta * drop, -0.95)
        worst = sorted(rows, key=lambda r: r["weight"] * r["beta"], reverse=True)[:3]
        crises.append({"key": key, "name": name, "year": year, "index_drop": drop, "drop": fall,
                       "loss": fall * total, "months": months, "recovery": _months(months), "dates": dates,
                       "worst": [{"ticker": r["ticker"], "loss": r["weight"] * r["beta"] * drop * total}
                                 for r in worst]})
    return {"crises": crises, "beta": portfolio_beta, "cash_share": max(p.cash, 0) / total, "positions":
            sorted(rows, key=lambda r: -r["weight"]), "estimated": sum(1 for r in rows if r["estimated"]),
            "bench": BENCH, "value": total}
