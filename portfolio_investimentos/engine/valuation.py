"""O valor de uma ação: vários métodos, por ordem de popularidade, com as hipóteses à vista, sempre em intervalo,
e o crescimento que o preço de hoje já assume. Uma ilustração para pensar, não uma recomendação.

Sempre visíveis:
- DCF (fluxos de caixa descontados): o cash flow livre por ação (ou, sem ele, o lucro por ação) a crescer `g` ao
  ano durante 10 anos, depois 2,5% para sempre, descontado a 8%–10%. Intervalo: do pessimista (g − 2,5 p.p.,
  desconto 10%) ao otimista (g + 2,5 p.p., desconto 8%).
- Número de Graham: √(22,5 × LPA × VCPA), com o lucro dos últimos 12 meses e o previsto.
- Fórmula de crescimento de Graham (1974): LPA × (8,5 + 2g) × 4,4 ÷ Y (Y: rendimento das obrigações AAA).
- Modelo de Gordon: D₁ ÷ (Ke − g), com o crescimento dos dividendos (no máximo 6%) e Ke de 8% a 10%.
Em «Mais métodos»:
- Owner Earnings (Buffett): lucro líquido + amortizações − CAPEX de manutenção ± fundo de maneio, descontados
  como no DCF.
- Earnings Power Value (Greenwald): NOPAT normalizado ÷ WACC (8%–10%) + caixa − dívida, sem crescimento.
- Bazin: dividendo médio de 3 anos ÷ 6%–8%.
- PEG de Peter Lynch: P/E ÷ crescimento dos lucros; o preço de PEG 1 = LPA × crescimento (em %).
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
AAA_YIELD = 0.05            # rendimento das obrigações AAA (fórmula de crescimento de Graham), por omissão
KE = (0.08, 0.10)           # retorno exigido (Gordon)
DIV_GROWTH_DEFAULT = 0.03   # crescimento dos dividendos sem histórico
DIV_GROWTH_MAX = 0.06       # acima disto o modelo de Gordon explode (g perto de Ke)
WACC = (0.08, 0.10)         # custo do capital (EPV)


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


def _method(key, name, low, high, formula, why, more=False):
    ok = low is not None and high is not None and high > 0
    if ok:
        low, high = max(min(low, high), 0.0), max(low, high)
    return {"key": key, "name": name, "low": low if ok else None, "high": high if ok else None,
            "formula": formula, "why": None if ok else why, "more": more}


def graham_growth(eps, growth, aaa_yield):
    """Fórmula de crescimento de Graham (revista em 1974): LPA × (8,5 + 2g) × 4,4 ÷ Y (g e Y em %)."""
    if eps is None or eps <= 0 or not aaa_yield:
        return None
    return eps * (8.5 + 2 * max(growth, 0) * 100) * 4.4 / (aaa_yield * 100)


def gordon(dividend, growth, required):
    """Modelo de Gordon: D₁ ÷ (Ke − g), com D₁ = D₀ × (1 + g)."""
    if dividend is None or dividend <= 0 or required <= growth:
        return None
    return dividend * (1 + growth) / (required - growth)


def value_stock(price, eps=None, eps_forward=None, bvps=None, fcf=None, growth=None, dividends=None,
                div_growth=None, owner_earnings=None, nopat=None, net_cash=None, aaa_yield=AAA_YIELD):
    """Os métodos de valor de uma ação, por ordem de popularidade, e o crescimento implícito (moeda da cotação).

    `dividends`: dividendo anual médio dos últimos 3 anos; `div_growth`: crescimento anual dos dividendos;
    `owner_earnings`, `nopat`, `net_cash`: por ação (Owner Earnings, NOPAT normalizado, caixa − dívida).
    Os quatro primeiros mostram-se sempre; os outros (`more`) em «Mais métodos». Sem dados: None e o motivo.
    """
    g = GROWTH_DEFAULT if growth is None else min(max(growth, GROWTH_RANGE[0]), GROWTH_RANGE[1])
    lo_g, hi_g = g - GROWTH_SPREAD, g + GROWTH_SPREAD
    base, base_kind = (fcf, "cash flow livre") if fcf is not None and fcf > 0 else (eps, "lucro")
    cut = (f"pessimista: g = {_p(lo_g)}, r = {_p(DISCOUNT[1])}; otimista: g = {_p(hi_g)}, r = {_p(DISCOUNT[0])}")
    dcf_text = (f"Σ C × (1 + g)^t ÷ (1 + r)^t, para t = 1 a {YEARS}, + valor terminal C × (1 + g)^{YEARS} × "
                f"(1 + {_p(TERMINAL)}) ÷ (r − {_p(TERMINAL)}) ÷ (1 + r)^{YEARS}")
    methods = [_method(
        "dcf", "DCF", dcf(base, lo_g, DISCOUNT[1]), dcf(base, hi_g, DISCOUNT[0]),
        f"Fluxos de caixa descontados. Valor = {dcf_text}. C = {base_kind} por ação = {_n(base)}; {cut}.",
        "sem cash flow livre nem lucro positivos")]

    values = [v for v in (graham(eps, bvps), graham(eps_forward, bvps)) if v]
    if len(values) == 1:
        values = [values[0] * 0.95, values[0] * 1.05]
    methods.append(_method(
        "graham", "Graham", min(values) if values else None, max(values) if values else None,
        f"Número de Graham. Valor = √(22,5 × LPA × VCPA); 22,5 = 15 (P/E máximo) × 1,5 (preço/valor contabilístico "
        f"máximo). LPA (lucro por ação): {_n(eps)} (últimos 12 meses) e {_n(eps_forward)} (previsto); VCPA (valor "
        f"contabilístico por ação): {_n(bvps)}.", "sem lucro ou valor contabilístico positivos"))

    methods.append(_method(
        "graham_growth", "Graham g", graham_growth(eps, lo_g, aaa_yield), graham_growth(eps, hi_g, aaa_yield),
        f"Fórmula de crescimento de Graham (1974). Valor = LPA × (8,5 + 2g) × 4,4 ÷ Y, com g em % e Y o rendimento "
        f"das obrigações AAA ({_p(aaa_yield)}). LPA: {_n(eps)}; g de {_p(lo_g)} a {_p(hi_g)}.",
        "sem lucro positivo"))

    dg = DIV_GROWTH_DEFAULT if div_growth is None else min(max(div_growth, 0.0), DIV_GROWTH_MAX)
    dg_lo, dg_hi = max(dg - 0.01, 0.0), min(dg + 0.01, DIV_GROWTH_MAX)
    methods.append(_method(
        "gordon", "Gordon", gordon(dividends, dg_lo, KE[1]), gordon(dividends, dg_hi, KE[0]),
        f"Modelo de Gordon (dividendos). Valor = D₁ ÷ (Ke − g), com D₁ = D₀ × (1 + g). D₀ (dividendo anual médio de "
        f"3 anos): {_n(dividends)}; g (crescimento do dividendo{', por omissão' if div_growth is None else ''}) de "
        f"{_p(dg_lo)} a {_p(dg_hi)}; Ke (retorno exigido) de {_p(KE[0])} a {_p(KE[1])}.",
        "não paga dividendos"))

    methods.append(_method(
        "owner", "Owner E.", dcf(owner_earnings, lo_g, DISCOUNT[1]), dcf(owner_earnings, hi_g, DISCOUNT[0]),
        f"Owner Earnings (Buffett), descontados como no DCF. Owner Earnings = lucro líquido + amortizações − CAPEX "
        f"de manutenção (o menor entre o CAPEX e as amortizações) ± variação do fundo de maneio = {_n(owner_earnings)} "
        f"por ação. Valor = {dcf_text}; {cut}.",
        "sem owner earnings positivos (faltam dados das demonstrações)", more=True))

    epv_low = nopat / WACC[1] + (net_cash or 0.0) if nopat and nopat > 0 else None
    epv_high = nopat / WACC[0] + (net_cash or 0.0) if nopat and nopat > 0 else None
    methods.append(_method(
        "epv", "EPV", epv_low, epv_high,
        f"Earnings Power Value (Greenwald), sem crescimento. EPV = NOPAT normalizado ÷ WACC + caixa − dívida. NOPAT "
        f"(resultado operacional médio × (1 − imposto)) por ação: {_n(nopat)}; caixa − dívida por ação: "
        f"{_n(net_cash)}; WACC de {_p(WACC[0])} a {_p(WACC[1])}.",
        "sem resultado operacional positivo (faltam dados das demonstrações)", more=True))

    has_div = dividends is not None and dividends > 0
    methods.append(_method(
        "bazin", "Bazin", dividends / BAZIN_YIELDS[1] if has_div else None,
        dividends / BAZIN_YIELDS[0] if has_div else None,
        f"Bazin. Valor = dividendo anual ÷ rentabilidade exigida. Dividendo anual médio dos últimos 3 anos: "
        f"{_n(dividends)}; rentabilidade de {_p(BAZIN_YIELDS[0])} (valor alto) a {_p(BAZIN_YIELDS[1])} (valor baixo).",
        "não paga dividendos", more=True))

    # PEG de Peter Lynch: não é um valor, é um rácio; o preço justo é o de PEG = 1
    peg = None
    if price and eps and eps > 0 and g > 0:
        pe = price / eps
        peg = {"pe": pe, "peg": pe / (g * 100), "fair": eps * g * 100,
               "formula": f"PEG de Peter Lynch = P/E ÷ crescimento dos lucros (em %) = {_n(pe, 1)} ÷ "
                          f"{_n(g * 100, 1)}. PEG 1 sugere preço justo (LPA × crescimento = {_n(eps * g * 100)}); "
                          "abaixo de 1, potencialmente subavaliada."}
    tops = [m["high"] for m in methods if m["high"]] + ([price] if price else [])
    scale = max(tops) * 1.15 if tops else None
    return {"methods": methods, "growth": g, "growth_default": growth is None, "base_kind": base_kind,
            "implied": implied_growth(price, base), "scale": scale, "price": price, "peg": peg}
