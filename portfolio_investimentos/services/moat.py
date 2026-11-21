"""O fosso económico (moat) de uma empresa: a prova nos números, a fonte provável e o checklist do utilizador.

Passo 2 das Oportunidades, como no método de Buffett (sistematizado pela Morningstar):
1. A prova nos números (os últimos anos que o Yahoo dá, em regra 4): ROIC alto e consistente, margem bruta alta e
   estável, cash flow livre alto e pouco CapEx, receitas a crescer, lucros sempre positivos e pouca dívida.
   Daí sai uma pontuação de 0 a 100 e uma leitura: «Largo», «Estreito» ou «Sem moat evidente».
2. A fonte provável, sugerida pela indústria da empresa e pelos números: ativos intangíveis, custos de mudança,
   efeito de rede, vantagem de custos ou escala eficiente.
3. O checklist do utilizador: os 5 pilares que confirma e os 3 testes de Buffett, guardados por empresa.
É uma ajuda para pensar, não uma avaliação: a fonte é uma sugestão e os números só cobrem poucos anos.
"""
import json
from datetime import date

from ..models import Setting

TYPES = ("annualTotalRevenue", "annualGrossProfit", "annualOperatingIncome", "annualNetIncome",
         "annualInvestedCapital", "annualFreeCashFlow", "annualOperatingCashFlow", "annualCapitalExpenditure",
         "annualEBITDA", "annualTotalDebt", "annualCashAndCashEquivalents", "annualStockholdersEquity",
         "annualTaxRateForCalcs", "annualCashDividendsPaid")

PILLARS = {
    "intangiveis": ("Ativos intangíveis", "Marcas, patentes e licenças: cobra mais por um produto semelhante sem perder "
                    "clientes, ou tem um monopólio legal?"),
    "mudanca": ("Custos de mudança", "Trocar de fornecedor dá tanto trabalho ou risco ao cliente que ele aceita "
                "aumentos de preço?"),
    "rede": ("Efeito de rede", "O serviço vale mais para todos cada vez que entra um novo utilizador?"),
    "custos": ("Vantagem de custos", "Produz ou entrega mais barato do que os concorrentes (escala, localização, "
               "processos)?"),
    "escala": ("Escala eficiente", "Mercado limitado (monopólio ou oligopólio natural) onde um novo concorrente "
               "estragaria a rentabilidade de todos?"),
}
TESTS = {
    "bilhao": ("O teste dos mil milhões", "Com 10 mil milhões de euros e os melhores gestores, não conseguirias criar "
               "uma empresa para a derrotar."),
    "hibernacao": ("O teste da hibernação", "Ficavas tranquilo a mantê-la 10 anos com a bolsa fechada."),
    "erosao": ("Sem erosão à vista", "Não vês tecnologia, perda de relevância da marca ou dívida a secar o fosso."),
}

# fonte provável pela indústria do Yahoo (em inglês): palavras-chave → pilares
INDUSTRY_HINTS = (
    (("software", "information technology services"), ("mudanca",)),
    (("credit services", "financial data", "capital markets", "internet content", "internet retail",
      "electronic gaming", "travel services", "communication services"), ("rede",)),
    (("beverages", "household & personal products", "luxury", "packaged foods", "confectioners", "tobacco",
      "apparel", "footwear", "restaurants", "drug manufacturers", "biotechnology", "medical devices",
      "medical instruments", "diagnostics", "semiconductor", "entertainment", "specialty chemicals"),
     ("intangiveis",)),
    (("discount stores", "grocery", "home improvement", "insurance", "farm", "integrated freight", "trucking",
      "steel", "aluminum", "building materials"), ("custos",)),
    (("utilities", "railroads", "airports", "waste management", "pipeline", "oil & gas midstream",
      "aerospace & defense", "infrastructure operations", "telecom services", "marine shipping"), ("escala",)),
    (("banks", "asset management"), ("mudanca", "custos")),
)


def _series(raw, kind):
    """{ano: valor} de uma série das demonstrações financeiras."""
    return {int(d[:4]): v for d, v, _ in raw.get(kind, [])}


def _ratio(a, b):
    return {y: a[y] / b[y] for y in a if y in b and b[y]}


def metrics(raw):
    """Os indicadores ano a ano e os resumos usados na pontuação."""
    rev, gross = _series(raw, "annualTotalRevenue"), _series(raw, "annualGrossProfit")
    ebit, net = _series(raw, "annualOperatingIncome"), _series(raw, "annualNetIncome")
    ic, fcf = _series(raw, "annualInvestedCapital"), _series(raw, "annualFreeCashFlow")
    capex, ebitda = _series(raw, "annualCapitalExpenditure"), _series(raw, "annualEBITDA")
    debt, cash = _series(raw, "annualTotalDebt"), _series(raw, "annualCashAndCashEquivalents")
    equity, tax = _series(raw, "annualStockholdersEquity"), _series(raw, "annualTaxRateForCalcs")
    divs = _series(raw, "annualCashDividendsPaid")
    years = sorted(rev)
    roic = {y: ebit[y] * (1 - min(max(tax.get(y, 0.21), 0), 0.5)) / ic[y] for y in ebit if ic.get(y, 0) > 0}
    out = {
        "years": years,
        "roic": roic,
        "roe": {y: net[y] / equity[y] for y in net if equity.get(y, 0) > 0},
        "gross_margin": _ratio(gross, rev),
        "net_margin": _ratio(net, rev),
        "fcf_conversion": {y: fcf[y] / net[y] for y in fcf if net.get(y, 0) > 0},
        "capex_sales": {y: abs(capex[y]) / rev[y] for y in capex if rev.get(y)},
        "net_income": net,
        "dividends": {y: abs(v) for y, v in divs.items()},
    }
    if len(years) >= 2 and rev[years[0]] > 0 and rev[years[-1]] > 0:
        out["revenue_cagr"] = (rev[years[-1]] / rev[years[0]]) ** (1 / (years[-1] - years[0])) - 1
    last = years[-1] if years else None
    if last and ebitda.get(last, 0) > 0:
        out["net_debt_ebitda"] = (debt.get(last, 0) - cash.get(last, 0)) / ebitda[last]
    return out


def _pt(text):
    """Números à portuguesa: vírgula decimal."""
    return text.replace(".", ",")


def _avg(d):
    return sum(d.values()) / len(d) if d else None


def score(m):
    """Pontuação de 0 a 100 com a prova nos números e o porquê de cada parcela."""
    parts = []
    roic = list(m["roic"].values())
    if roic:
        if min(roic) >= 0.15:
            pts, why = 30, "ROIC acima de 15% em todos os anos"
        elif _avg(m["roic"]) >= 0.12:
            pts, why = 20, "ROIC médio acima de 12%"
        elif _avg(m["roic"]) >= 0.08:
            pts, why = 10, "ROIC médio entre 8% e 12%"
        else:
            pts, why = 0, "ROIC baixo"
        parts.append(("ROIC", pts, 30, why))
    gm = list(m["gross_margin"].values())
    if gm:
        spread = max(gm) - min(gm)
        pts = (12 if min(gm) >= 0.40 else 6 if min(gm) >= 0.25 else 0) + (8 if spread <= 0.05 else 4 if spread <= 0.10 else 0)
        parts.append(("Margem bruta", pts, 20, _pt(f"entre {min(gm):.0%} e {max(gm):.0%}")))
    fc, cx = _avg(m["fcf_conversion"]), _avg(m["capex_sales"])
    if fc is not None or cx is not None:
        pts = (10 if fc is not None and fc >= 0.8 else 5 if fc is not None and fc >= 0.5 else 0) + \
              (10 if cx is not None and cx <= 0.05 else 5 if cx is not None and cx <= 0.10 else 0)
        why = []
        if fc is not None:
            why.append(_pt(f"cash flow livre de {fc:.0%} do lucro"))
        if cx is not None:
            why.append(_pt(f"CapEx de {cx:.0%} das receitas"))
        parts.append(("Cash flow livre e CapEx", pts, 20, ", ".join(why)))
    cagr = m.get("revenue_cagr")
    profits = list(m["net_income"].values())
    if cagr is not None or profits:
        pts = (10 if cagr is not None and cagr >= 0.08 else 5 if cagr is not None and cagr > 0 else 0) + \
              (5 if profits and min(profits) > 0 else 0)
        why = ([_pt(f"receitas a {cagr:+.1%} por ano")] if cagr is not None else []) + \
              (["lucros positivos em todos os anos"] if profits and min(profits) > 0 else ["houve anos de prejuízo"])
        parts.append(("Crescimento e lucros", pts, 15, ", ".join(why)))
    nde = m.get("net_debt_ebitda")
    if nde is not None:
        pts = 15 if nde <= 1 else 10 if nde <= 2.5 else 5 if nde <= 4 else 0
        parts.append(("Dívida", pts, 15, "caixa líquida" if nde < 0 else _pt(f"dívida líquida de {nde:.1f}× o EBITDA")))
    got, max_pts = sum(p[1] for p in parts), sum(p[2] for p in parts)
    value = round(100 * got / max_pts) if max_pts else None
    return {"value": value, "parts": parts, "verdict": verdict(value)}


def verdict(value):
    if value is None:
        return "Sem dados"
    return "Largo" if value >= 70 else "Estreito" if value >= 45 else "Sem moat evidente"


def sources(industry, sector, m):
    """A fonte provável do moat (sugestão): pela indústria e reforçada pelos números."""
    text = f"{industry or ''} {sector or ''}".lower()
    found = []
    for words, keys in INDUSTRY_HINTS:
        if any(w in text for w in words):
            found += [k for k in keys if k not in found]
    gm = list(m["gross_margin"].values())
    if gm and min(gm) >= 0.6 and "intangiveis" not in found and "mudanca" not in found:
        found.append("intangiveis")  # margem bruta muito alta: poder de fixar preços
    return found


def analyse(ticker, fetch_info=None, fetch_series=None, today=None):
    """Busca os dados ao Yahoo, calcula e guarda a análise («moat:<ticker>»)."""
    from . import yahoo
    fetch_info = fetch_info or info_of
    fetch_series = fetch_series or (lambda t: yahoo.fundamentals(t, years=6, types=TYPES))
    info = fetch_info(ticker) or {}
    raw = fetch_series(ticker) or {}
    m = metrics(raw)
    s = score(m)
    out = {"ticker": ticker, "name": info.get("longName") or info.get("shortName") or ticker,
           "sector": info.get("sector"), "industry": info.get("industry"), "country": info.get("country"),
           "summary": (info.get("longBusinessSummary") or "")[:1500],
           "score": s["value"], "verdict": s["verdict"], "parts": s["parts"],
           "sources": sources(info.get("industry"), info.get("sector"), m),
           "years": m["years"], "roic": _js(m["roic"]), "gross_margin": _js(m["gross_margin"]),
           "fcf_conversion": _js(m["fcf_conversion"]), "capex_sales": _js(m["capex_sales"]),
           "revenue_cagr": m.get("revenue_cagr"), "net_debt_ebitda": m.get("net_debt_ebitda"),
           "roe_now": info.get("returnOnEquity"), "insiders": info.get("heldPercentInsiders"),
           "analysts": info.get("numberOfAnalystOpinions"),
           "date": (today or date.today()).isoformat()}
    Setting.set(f"moat:{ticker}", json.dumps(out, ensure_ascii=False))
    return out


def info_of(ticker):
    """Os dados da ação no Yahoo: pelo yfinance quando está instalado (o Yahoo limita os pedidos simples com HTTP
    429), senão pelo acesso direto. Qualquer falha chega como YahooError."""
    from . import yahoo
    from .market import _yahoo_client
    try:
        client = _yahoo_client()
        info = dict(client.Ticker(ticker).info or {})
        if client is not yahoo:
            info["_yfinance"] = True  # o yfinance dá o «dividendYield» em %
        return info
    except yahoo.YahooError:
        raise
    except Exception as exc:
        raise yahoo.YahooError(str(exc)[:200]) from exc


def _js(d):
    return {str(k): round(v, 4) for k, v in sorted(d.items())}


def get(ticker):
    try:
        return json.loads(Setting.get(f"moat:{ticker}") or "null")
    except ValueError:
        return None


def checklist(ticker):
    """O que o utilizador confirmou: {"pillars": [...], "tests": [...], "note": "..."}."""
    try:
        v = json.loads(Setting.get(f"moat_user:{ticker}") or "null")
    except ValueError:
        v = None
    return v if isinstance(v, dict) else {"pillars": [], "tests": [], "note": ""}


def save_checklist(ticker, pillars, tests, note=""):
    data = {"pillars": [p for p in pillars if p in PILLARS], "tests": [t for t in tests if t in TESTS],
            "note": str(note or "")[:1000]}
    Setting.set(f"moat_user:{ticker}", json.dumps(data, ensure_ascii=False))
    return data


def has_moat(analysis, user):
    """Passa o 2.º passo: os números mostram um moat (pontuação ≥ 70) ou o utilizador confirmou pelo menos um pilar
    e os três testes."""
    return bool((analysis and (analysis.get("score") or 0) >= 70) or
                (user and user.get("pillars") and len(user.get("tests") or []) == len(TESTS)))
