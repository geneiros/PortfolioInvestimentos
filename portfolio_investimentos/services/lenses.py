"""As lentes da triagem (Prospeção → Ações): os critérios de cada grande investidor, avaliados numa ação.

Cada lente tem:
- `query`: os limites (um pouco mais largos do que os critérios) da pesquisa ao Yahoo, em todas as regiões, para
  apanhar as ações que entram e as que ficam perto;
- `criteria`: os critérios a sério, avaliados com os dados de cada ação (`metrics`): passa, quase (a menos de 15% do
  limite) ou falha; sem o dado, não conta.
Uma ação «entra» numa lente quando passa em todos os critérios com dados (pelo menos 60% deles); fica «quase» quando
o que falta está perto do limite (até dois critérios) ou, nas lentes com cinco ou mais critérios, só um falha. É um filtro para encontrar ideias, não uma recomendação.
"""
import math

NEAR = 0.15

# câmbios aproximados para o dólar, só para o tamanho das empresas (não entram em contas de valor)
USD_RATE = {"USD": 1.0, "EUR": 1.1, "GBP": 1.27, "CHF": 1.13, "DKK": 0.147, "SEK": 0.095,
            "NOK": 0.093, "JPY": 0.0067, "KRW": 0.00072, "TWD": 0.031, "HKD": 0.128, "CNY": 0.14, "INR": 0.012,
            "SGD": 0.74, "AUD": 0.66, "CAD": 0.73, "PLN": 0.25, "ILS": 0.27, "BRL": 0.18, "MXN": 0.055,
            "ZAR": 0.055, "SAR": 0.27, "TRY": 0.03, "THB": 0.028, "IDR": 0.000063, "MYR": 0.21,
            "CLP": 0.0011, "ARS": 0.001, "NZD": 0.6, "PHP": 0.018, "CZK": 0.044, "HUF": 0.0027,
            "KWF": 0.0033, "AED": 0.27, "QAR": 0.27, "EGP": 0.02, "VND": 0.00004}


MAJOR = {"GBp": "GBP", "GBX": "GBP", "ZAc": "ZAR", "ILA": "ILS"}


def usd(value, currency):
    """Uma capitalização em dólares (aproximado). O Yahoo dá a capitalização na unidade principal (libras, rands,
    shekels) mesmo quando a cotação é em centésimos."""
    cur = MAJOR.get(currency, currency or "USD")
    return value * USD_RATE.get(cur, 0.0) if value else None


def _num(v):
    return float(v) if isinstance(v, (int, float)) and math.isfinite(v) else None


def metrics_from_info(info, quote=None):
    """Os indicadores de uma ação a partir dos dados do Yahoo (Ticker.info) e, para o que faltar, da cotação do
    filtro. Percentagens em fração (0,15 = 15%); dívida/capital em fração (0,5 = 50%)."""
    q, i = quote or {}, info or {}

    def g(*keys):
        for k in keys:
            v = _num(i.get(k))
            if v is not None:
                return v
        return None
    price = g("regularMarketPrice", "currentPrice") or _num(q.get("price"))
    currency = i.get("currency") or q.get("currency")
    dy = None
    if i.get("dividendYield") is not None:
        dy = _num(i["dividendYield"])
        dy = dy / 100 if dy is not None and (i.get("_yfinance") or dy >= 0.2) else dy
    elif i.get("trailingAnnualDividendYield") is not None:
        dy = _num(i["trailingAnnualDividendYield"])
    elif q.get("div") is not None:
        dy = q["div"]
    de = g("debtToEquity")
    ebitda, debt, cash = g("ebitda"), g("totalDebt"), g("totalCash")
    cap = g("marketCap") or _num(q.get("cap"))
    out = {
        "price": price, "currency": currency, "cap": cap, "cap_usd": usd(cap, currency),
        "pe": g("trailingPE") or _num(q.get("pe")), "fpe": g("forwardPE") or _num(q.get("fpe")),
        "pb": g("priceToBook") or _num(q.get("pb")), "ps": g("priceToSalesTrailing12Months"),
        "ev_ebitda": g("enterpriseToEbitda"), "peg": g("trailingPegRatio", "pegRatio"),
        "roe": g("returnOnEquity"), "roa": g("returnOnAssets"), "net_margin": g("profitMargins"),
        "op_margin": g("operatingMargins"), "gross_margin": g("grossMargins"),
        "rev_growth": g("revenueGrowth"), "eps_growth": g("earningsGrowth"),
        "de": de / 100 if de is not None else None, "current": g("currentRatio"), "quick": g("quickRatio"),
        "net_debt_ebitda": (debt - (cash or 0)) / ebitda if debt is not None and ebitda and ebitda > 0 else None,
        "div": dy if dy is not None and 0 <= dy <= 0.3 else None, "dps": g("dividendRate"),
        "payout": g("payoutRatio"), "eps": g("trailingEps") or _num(q.get("eps")),
        "fwd_eps": g("forwardEps"), "bvps": g("bookValue") or _num(q.get("bvps")),
        "fcf": g("freeCashflow"), "beta": g("beta"),
        "high": g("fiftyTwoWeekHigh") or _num(q.get("high")), "low": g("fiftyTwoWeekLow") or _num(q.get("low")),
        "profit": (g("netIncomeToCommon") or 0) > 0 if i.get("netIncomeToCommon") is not None else
        ((g("trailingEps") or _num(q.get("eps")) or 0) > 0 if (g("trailingEps") or _num(q.get("eps"))) is not None
         else None),
    }
    if out["pe"] is not None and not 1 <= out["pe"] <= 1000:  # P/L abaixo de 1 é erro de dados
        out["pe"] = None
    # por ação, na moeda da cotação: o Yahoo dá o lucro, o valor contabilístico e o dividendo por ação na moeda das
    # contas ou em libras com a cotação em pence (ex.: Shell em Londres, TSMC nos EUA); os rácios dele, não
    out["fin_currency"] = i.get("financialCurrency") or currency
    if price and out["pe"]:
        out["eps"] = price / out["pe"]
    if price and out["fpe"] and out["fpe"] > 0:
        out["fwd_eps"] = price / out["fpe"]
    if price and out["pb"] and 0 < out["pb"] < 50:
        out["bvps"] = price / out["pb"]
    elif out["fin_currency"] != MAJOR.get(currency, currency):
        out["bvps"] = None
    if out["div"] and price:
        out["dps"] = out["div"] * price
    if out["pb"] is not None and out["pb"] > 200:  # erro de dados (ex.: o valor contabilístico noutra moeda)
        out["pb"] = None
    if out["pb"] is not None and out["pb"] < 0:  # capital próprio negativo: ROE e dívida/capital não dizem nada
        out["roe"] = out["de"] = None
    return out


def graham_number(m):
    if m.get("eps") and m.get("bvps") and m["eps"] > 0 and m["bvps"] > 0:
        return math.sqrt(22.5 * m["eps"] * m["bvps"])
    return None


def bazin_ceiling(m, rate=0.06):
    return m["dps"] / rate if m.get("dps") else (m["div"] * m["price"] / rate if m.get("div") and m.get("price")
                                                 else None)


# critérios: (rótulo, função que devolve (valor, limite, sentido, texto)); sentido: "<=" ou ">="
def _c(label, key, op, limit, fmt="{:.1f}", unit="", scale=1.0, text=None):
    def f(m):
        v = m.get(key)
        return (None if v is None else v * scale), limit, op, text or label
    f.label, f.fmt, f.unit = label, fmt, unit
    return f


def _custom(label, fn, fmt="{:.1f}", unit=""):
    fn.label, fn.fmt, fn.unit = label, fmt, unit
    return fn


def _pe_pb(m):
    v = m["pe"] * m["pb"] if m.get("pe") and m.get("pb") and m["pe"] > 0 and m["pb"] > 0 else None
    return v, 22.5, "<=", "P/L × P/VP"


def _graham(m):
    gn = graham_number(m)
    return (m["price"] / gn - 1 if gn and m.get("price") else None), 0.0, "<=", "Cotação face ao número de Graham"


def _not_us(m):
    return (0.0 if m.get("country") and m["country"] != "EUA" else 1.0) if m.get("country") else None, 0.5, "<=", \
        "Fora dos EUA"


def _profit(m):
    return (None if m.get("profit") is None else (1.0 if m["profit"] else 0.0)), 1.0, ">=", "Tem lucro"


def _fcf_pos(m):
    return (None if m.get("fcf") is None else (1.0 if m["fcf"] > 0 else 0.0)), 1.0, ">=", "Caixa livre positivo"


def _size(limit):
    return _custom("Tamanho", lambda m: ((m["cap_usd"] / 1e6) if m.get("cap_usd") else None, limit, ">=",
                                        f"Capitalização de pelo menos {limit / 1000:g} mil M$"), "{:,.0f}", " M$")


def _near_high(m):
    v = (1 - m["price"] / m["high"]) if m.get("price") and m.get("high") else None
    return v, 0.15, "<=", "Até 15% abaixo do máximo de 52 semanas"


for _f, _label in ((_not_us, "Fora dos EUA"), (_profit, "Tem lucro"), (_fcf_pos, "Caixa livre positivo")):
    _custom(_label, _f, "bool")


def _greenblatt(m):
    return m.get("magic_q"), 1.0, "<=", "Quartil de topo do ranking (ROE + earnings yield)"


LENSES = {
    "varias": {"name": "Várias lentes", "sub": "Onde os métodos coincidem", "meta": True,
               "text": "Entra quando pelo menos duas lentes fecham ao mesmo tempo."},
    "graham_def": {
        "name": "Graham defensivo", "sub": "Barato e com balanço folgado",
        "text": "Defensivo: barato, com lucro e balanço folgado.",
        "query": [("peratio.lasttwelvemonths", "btwn", (2, 18)), ("pricebookratio.quarterly", "btwn", (0.05, 2.5))],
        "criteria": [_profit, _c("Preço / lucro", "pe", "<=", 15), _c("Preço / valor patrimonial", "pb", "<=", 1.5),
                     _custom("P/L × P/VP", _pe_pb), _size(2000),
                     _c("Liquidez corrente", "current", ">=", 2.0, "{:.2f}"),
                     _c("Dívida / capital", "de", "<=", 0.5, "{:.2f}")],
    },
    "graham_num": {
        "name": "Número de Graham", "sub": "O chão do que já existe",
        "text": "Cotação abaixo do número de Graham (√(22,5 × lucro por ação × valor contabilístico por ação)).",
        "query": [("peratio.lasttwelvemonths", "btwn", (2, 25)), ("pricebookratio.quarterly", "btwn", (0.05, 4))],
        "criteria": [_custom("Abaixo do número de Graham", _graham, "{:+.0%}"), _profit],
    },
    "buffett": {
        "name": "Buffett", "sub": "Qualidade a um preço que ainda se entende",
        "text": "Qualidade que ainda não custa uma fortuna.",
        "query": [("returnonequity.lasttwelvemonths", "btwn", (12, 150)), ("netincomemargin.lasttwelvemonths", "gt", 8),
                  ("peratio.lasttwelvemonths", "btwn", (3, 28))],
        "criteria": [_c("ROE", "roe", ">=", 15, "{:.1f}", "%", 100), _c("Margem líquida", "net_margin", ">=", 10,
                                                                      "{:.1f}", "%", 100),
                     _profit, _c("Dívida / capital", "de", "<=", 0.5, "{:.2f}"),
                     _c("Preço ainda legível (P/L)", "pe", "<=", 25), _fcf_pos,
                     _c("Não está a encolher (vendas)", "rev_growth", ">=", 0, "{:+.1f}", "%", 100)],
    },
    "lynch": {
        "name": "Lynch", "sub": "Crescimento pelo que ele custa",
        "text": "Crescimento rápido com PEG até 1.",
        "query": [("pegratio_5y", "btwn", (0.1, 1.3)), ("epsgrowth.lasttwelvemonths", "gt", 10)],
        "criteria": [_c("Crescimento rápido (lucro)", "eps_growth", ">=", 15, "{:+.1f}", "%", 100),
                     _c("PEG", "peg", "<=", 1.0, "{:.2f}"), _profit, _c("Dívida / capital", "de", "<=", 0.5, "{:.2f}")],
    },
    "greenblatt": {
        "name": "Greenblatt", "sub": "Boa e barata, em ranking",
        "text": "Fórmula Mágica: entra no quartil de topo do ranking de rentabilidade + earnings yield.",
        "query": [("returnontotalcapital.lasttwelvemonths", "btwn", (12, 80)),
                  ("peratio.lasttwelvemonths", "btwn", (3, 30))],
        "criteria": [_custom("Quartil de topo", _greenblatt, "{:.0f}"), _profit],
    },
    "bazin": {
        "name": "Bazin", "sub": "Preço-teto pelo dividendo",
        "text": "Rendimento de pelo menos 6%, com payout e dívida dentro do limite.",
        "query": [("forward_dividend_yield", "btwn", (5, 25)), ("peratio.lasttwelvemonths", "btwn", (2, 30))],
        "criteria": [_c("Rendimento de 6%", "div", ">=", 6, "{:.1f}", "%", 100), _profit,
                     _c("Payout sustentável", "payout", "<=", 85, "{:.0f}", "%", 100),
                     _c("Dívida / capital", "de", "<=", 1.0, "{:.2f}")],
    },
    "fisher": {
        "name": "Fisher", "sub": "Crescer com margens e sem dívida a mais",
        "text": "Cresce, tem margem e não vive de dívida.",
        "query": [("totalrevenues1yrgrowth.lasttwelvemonths", "gt", 8), ("netincomemargin.lasttwelvemonths", "gt", 8),
                  ("returnonequity.lasttwelvemonths", "btwn", (10, 150))],
        "criteria": [_c("Vendas a crescer", "rev_growth", ">=", 10, "{:+.1f}", "%", 100),
                     _c("Margem operacional", "op_margin", ">=", 15, "{:.1f}", "%", 100),
                     _c("ROE", "roe", ">=", 15, "{:.1f}", "%", 100), _c("Dívida / capital", "de", "<=", 0.6, "{:.2f}"),
                     _profit],
    },
    "templeton": {
        "name": "Templeton", "sub": "Pechincha fora dos EUA",
        "text": "Pechincha fora do mercado americano.", "no_us": True,
        "query": [("peratio.lasttwelvemonths", "btwn", (2, 14))],
        "criteria": [_custom("Fora dos EUA", _not_us), _c("Preço / lucro", "pe", "<=", 12), _profit,
                     _c("Dívida / capital", "de", "<=", 0.8, "{:.2f}"), _size(1000)],
    },
    "oneil": {
        "name": "O'Neil", "sub": "CAN SLIM: lucros a acelerar",
        "text": "Lucros a crescer mais de 25%, rentabilidade alta e a ação perto dos máximos.",
        "query": [("epsgrowth.lasttwelvemonths", "gt", 18), ("totalrevenues1yrgrowth.lasttwelvemonths", "gt", 12),
                  ("returnonequity.lasttwelvemonths", "btwn", (14, 150))],
        "criteria": [_c("Lucro a crescer", "eps_growth", ">=", 25, "{:+.1f}", "%", 100),
                     _c("Vendas a crescer", "rev_growth", ">=", 15, "{:+.1f}", "%", 100),
                     _c("ROE", "roe", ">=", 17, "{:.1f}", "%", 100), _custom("Perto do máximo", _near_high, "{:.0%}")],
    },
    "resumo": {
        "name": "Resumo", "sub": "A interseção dos métodos",
        "text": "Rentabilidade, solidez, crescimento e preço justo ao mesmo tempo.",
        "query": [("returnonequity.lasttwelvemonths", "btwn", (12, 150)), ("netdebtebitda.lasttwelvemonths", "lt", 3),
                  ("totalrevenues1yrgrowth.lasttwelvemonths", "gt", 6), ("pegratio_5y", "btwn", (0.1, 1.5))],
        "criteria": [_c("ROE", "roe", ">=", 15, "{:.1f}", "%", 100),
                     _c("Dívida líquida / EBITDA", "net_debt_ebitda", "<=", 2.5, "{:.1f}"),
                     _c("Vendas a crescer", "rev_growth", ">=", 8, "{:+.1f}", "%", 100),
                     _c("PEG", "peg", "<=", 1.2, "{:.2f}")],
    },
}
REAL = [k for k, v in LENSES.items() if not v.get("meta")]


def _status(v, limit, op):
    if v is None:
        return None
    ok = v <= limit if op == "<=" else v >= limit
    if ok:
        return "pass"
    gap = abs(v - limit) / (abs(limit) if limit else 1.0)
    return "near" if gap <= NEAR else "fail"


def evaluate(lens, m):
    """(estado, [(rótulo, texto, valor formatado, estado)]) de uma ação numa lente: «entra», «quase», «falha» ou
    None (sem dados)."""
    rows, passes, fails, nears, known = [], 0, 0, 0, 0
    crit = LENSES[lens]["criteria"]
    for f in crit:
        v, limit, op, text = f(m)
        st = _status(v, limit, op)
        if v is None:
            shown = None
        elif f.fmt == "bool":
            shown = "sim" if (v <= limit if op == "<=" else v >= limit) else "não"
        else:
            shown = f.fmt.format(v).replace(",", " ").replace(".", ",") + f.unit
        rows.append((f.label, text, shown, st))
        if st is None:
            continue
        known += 1
        passes += st == "pass"
        nears += st == "near"
        fails += st == "fail"
    if known == 0 or known < 0.6 * len(crit):
        return None, rows
    if passes == known:
        return "entra", rows
    # perto: o que falta está a menos de 15% do limite (até dois critérios), ou só um falha nas lentes longas
    if (fails == 0 and nears <= 2) or (fails == 1 and nears == 0 and known >= 5):
        return "quase", rows
    return "falha", rows


def tags(m):
    """As etiquetas curtas da ficha («Lucrativa», «Vendas rápidas»...)."""
    out = []
    if (m.get("roe") or 0) >= 0.2 or (m.get("net_margin") or 0) >= 0.2:
        out.append(("Lucrativa", "up"))
    if (m.get("rev_growth") or 0) >= 0.15:
        out.append(("Vendas rápidas", "up"))
    if m.get("pe") and 0 < m["pe"] <= 12:
        out.append(("Preço baixo", "up"))
    if m.get("de") is not None and m["de"] <= 0.8:
        out.append(("Dívida contida", "warn" if m["de"] > 0.5 else "up"))
    elif m.get("de") is not None and m["de"] > 1.5:
        out.append(("Dívida alta", "down"))
    if (m.get("div") or 0) >= 0.05:
        out.append(("Dividendo alto", "up"))
    if m.get("rev_growth") is not None and m["rev_growth"] < 0:
        out.append(("Vendas a cair", "down"))
    return out


def blurb(m):
    """Uma frase sobre a ação, a partir das etiquetas."""
    parts = []
    if (m.get("roe") or 0) >= 0.2:
        parts.append("Negócio muito lucrativo")
    elif (m.get("roe") or 0) >= 0.1:
        parts.append("Negócio lucrativo")
    elif m.get("profit") is False:
        parts.append("Está a dar prejuízo")
    if (m.get("rev_growth") or 0) >= 0.15:
        parts.append("as vendas crescem depressa")
    elif m.get("rev_growth") is not None and m["rev_growth"] < 0:
        parts.append("as vendas estão a cair")
    if m.get("pe") and 0 < m["pe"] <= 12:
        parts.append("o preço está barato face ao lucro")
    elif m.get("pe") and m["pe"] >= 30:
        parts.append("o preço já conta com muito crescimento")
    if not parts:
        return ""
    s = parts[0] + (". " + ", ".join(parts[1:]).capitalize() if len(parts) > 1 else "")
    return s.replace(". As", ". As") + "."
