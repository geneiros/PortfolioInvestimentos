"""O valor de uma ação: três métodos com as hipóteses à vista, sempre em intervalo, e o crescimento que o preço
de hoje já assume. Uma ilustração para pensar, não uma recomendação.

- DCF (fluxos de caixa descontados): o cash flow livre por ação (ou, sem ele, o lucro por ação) a crescer `g` ao
  ano durante 10 anos, depois 2,5% para sempre, descontado a 8%–10% ao ano. Intervalo: do pessimista
  (g − 2,5 p.p., desconto 10%) ao otimista (g + 2,5 p.p., desconto 8%).
- Graham: o número de Graham, √(22,5 × lucro por ação × valor contabilístico por ação), com o lucro dos últimos
  12 meses e o previsto (o intervalo vai de um ao outro).
- Bazin: o dividendo anual médio dos últimos 3 anos a dividir por uma rentabilidade exigida de 6% a 8%.
- Crescimento implícito: a taxa `g` que faz o DCF (desconto 9%) dar exatamente o preço de hoje.
"""
from math import sqrt

YEARS = 10
TERMINAL = 0.025
DISCOUNT = (0.08, 0.10)
DISCOUNT_MID = 0.09
GROWTH_SPREAD = 0.025
GROWTH_DEFAULT = 0.06
GROWTH_RANGE = (-0.10, 0.25)
BAZIN_YIELDS = (0.06, 0.08)


def dcf(base, growth, discount, years=YEARS, terminal=TERMINAL):
    """Valor por ação: `base` (cash flow por ação) a crescer `growth` durante `years`, depois `terminal`."""
    if base is None or base <= 0 or discount <= terminal:
        return None
    value, cash = 0.0, base
    for year in range(1, years + 1):
        cash *= 1 + growth
        value += cash / (1 + discount) ** year
    value += cash * (1 + terminal) / (discount - terminal) / (1 + discount) ** years
    return value


def implied_growth(price, base, discount=DISCOUNT_MID):
    """Crescimento anual (10 anos) que o preço já assume: o `g` com dcf(base, g) = preço (bisseção)."""
    if not price or base is None or base <= 0:
        return None
    lo, hi = -0.5, 1.0
    if dcf(base, lo, discount) > price or dcf(base, hi, discount) < price:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if dcf(base, mid, discount) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def graham(eps, bvps):
    if eps is None or bvps is None or eps <= 0 or bvps <= 0:
        return None
    return sqrt(22.5 * eps * bvps)


def _n(x, d=2):
    return "—" if x is None else f"{x:,.{d}f}".replace(",", " ").replace(".", ",")


def _p(x):
    return f"{x * 100:.1f}%".replace(".", ",")


def value_stock(price, eps=None, eps_forward=None, bvps=None, fcf=None, growth=None, dividends=None):
    """Os três intervalos e o crescimento implícito de uma ação (todos na moeda da cotação).

    `dividends`: dividendo anual médio dos últimos 3 anos (por ação). Um método sem dados fica None, com o motivo.
    """
    g = GROWTH_DEFAULT if growth is None else min(max(growth, GROWTH_RANGE[0]), GROWTH_RANGE[1])
    base, base_kind = (fcf, "cash flow livre") if fcf is not None and fcf > 0 else (eps, "lucro")
    methods = []
    low = dcf(base, g - GROWTH_SPREAD, DISCOUNT[1])
    high = dcf(base, g + GROWTH_SPREAD, DISCOUNT[0])
    lo_g, hi_g = g - GROWTH_SPREAD, g + GROWTH_SPREAD
    dcf_formula = (f"Valor = Σ C × (1 + g)^t ÷ (1 + r)^t, para t = 1 a {YEARS}, + valor terminal "
                   f"C × (1 + g)^{YEARS} × (1 + {_p(TERMINAL)}) ÷ (r − {_p(TERMINAL)}) ÷ (1 + r)^{YEARS}. "
                   f"C = {base_kind} por ação = {_n(base)}; pessimista: g = {_p(lo_g)}, r = {_p(DISCOUNT[1])}; "
                   f"otimista: g = {_p(hi_g)}, r = {_p(DISCOUNT[0])}.")
    methods.append({"key": "dcf", "name": "DCF", "low": low, "high": high, "formula": dcf_formula,
                    "why": None if low else "sem cash flow livre nem lucro positivos",
                    "hypothesis": f"{base_kind} por ação a crescer {(g - GROWTH_SPREAD) * 100:.1f}% a "
                                  f"{(g + GROWTH_SPREAD) * 100:.1f}% ao ano durante {YEARS} anos, depois "
                                  f"{TERMINAL * 100:.1f}%; desconto de {DISCOUNT[0] * 100:.0f}% a "
                                  f"{DISCOUNT[1] * 100:.0f}% ao ano"})
    values = [v for v in (graham(eps, bvps), graham(eps_forward, bvps)) if v]
    if len(values) == 1:
        values = [values[0] * 0.95, values[0] * 1.05]
    graham_formula = (f"Valor = √(22,5 × lucro por ação × valor contabilístico por ação). 22,5 = 15 (preço/lucro "
                      f"máximo) × 1,5 (preço/valor contabilístico máximo). Lucro por ação: {_n(eps)} (últimos 12 "
                      f"meses) e {_n(eps_forward)} (previsto); valor contabilístico por ação: {_n(bvps)}.")
    methods.append({"key": "graham", "name": "Graham", "low": min(values) if values else None, "formula": graham_formula,
                    "high": max(values) if values else None,
                    "why": None if values else "sem lucro ou valor contabilístico positivos",
                    "hypothesis": "√(22,5 × lucro por ação × valor contabilístico por ação), com o lucro dos "
                                  "últimos 12 meses e o previsto"})
    has_div = dividends is not None and dividends > 0
    bazin_formula = (f"Valor = dividendo anual ÷ rentabilidade exigida. Dividendo anual médio dos últimos 3 anos: "
                     f"{_n(dividends)}; rentabilidade de {_p(BAZIN_YIELDS[0])} (valor alto) a {_p(BAZIN_YIELDS[1])} "
                     "(valor baixo).")
    methods.append({"key": "bazin", "name": "Bazin", "formula": bazin_formula,
                    "low": dividends / BAZIN_YIELDS[1] if has_div else None,
                    "high": dividends / BAZIN_YIELDS[0] if has_div else None,
                    "why": None if has_div else "não paga dividendos",
                    "hypothesis": f"dividendo médio de 3 anos ÷ {BAZIN_YIELDS[0] * 100:.0f}% a "
                                  f"{BAZIN_YIELDS[1] * 100:.0f}% de rentabilidade exigida"})
    tops = [m["high"] for m in methods if m["high"]] + ([price] if price else [])
    scale = max(tops) * 1.15 if tops else None
    return {"methods": methods, "growth": g, "growth_default": growth is None, "base_kind": base_kind,
            "implied": implied_growth(price, base), "scale": scale, "price": price}
