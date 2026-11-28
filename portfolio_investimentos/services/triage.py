"""Triagem (Prospeção → Ações): o universo de ações das lentes e a avaliação de cada ação em todas elas.

1. `refresh_step`: cada lente faz a sua pesquisa ao Yahoo em todas as regiões (até `PAGES` × 250 resultados), e as
   ações juntam-se num só universo, uma linha por empresa (sem segundas cotações).
2. `enrich_step`: completa os dados de cada ação (Ticker.info: ROE, margens, crescimento, dívida, setor, país...),
   aos poucos, para a página ir chamando enquanto está aberta (o servidor não tem tarefas em segundo plano).
3. `table`: avalia cada ação em todas as lentes (entra, quase, falha) e devolve as linhas da página.
Tudo fica guardado (Settings «triage:universe» e «triage:info»): a página abre sem perguntar nada ao Yahoo.
"""
import json
import time
from datetime import datetime, timedelta
from math import isfinite

from ..models import Setting
from . import lenses, screener

PAGES = 4  # 4 × 250 = até 1000 ações por lente
PAGE_SIZE = 250
STALE = timedelta(hours=24)
INFO_STALE = timedelta(days=7)

EXCHANGE_COUNTRY = {
    "NMS": "EUA", "NYQ": "EUA", "NGM": "EUA", "NCM": "EUA", "ASE": "EUA", "PCX": "EUA", "BTS": "EUA", "NAS": "EUA",
    "LSE": "Reino Unido", "IOB": "Reino Unido", "GER": "Alemanha", "FRA": "Alemanha", "PAR": "França",
    "AMS": "Países Baixos", "MCE": "Espanha", "MIL": "Itália", "EBS": "Suíça", "VTX": "Suíça", "STO": "Suécia",
    "CPH": "Dinamarca", "OSL": "Noruega", "HEL": "Finlândia", "BRU": "Bélgica", "LIS": "Portugal", "ISE": "Irlanda",
    "VIE": "Áustria", "WSE": "Polónia", "ATH": "Grécia", "PRA": "Chéquia", "BUD": "Hungria", "IST": "Turquia",
    "JPX": "Japão", "HKG": "Hong Kong", "KSC": "Coreia do Sul", "KOE": "Coreia do Sul", "TAI": "Taiwan",
    "TWO": "Taiwan", "NSI": "Índia", "BSE": "Índia", "SHH": "China", "SHZ": "China", "SES": "Singapura",
    "ASX": "Austrália", "NZE": "Nova Zelândia", "TOR": "Canadá", "VAN": "Canadá", "CNQ": "Canadá", "NEO": "Canadá",
    "SAO": "Brasil", "MEX": "México", "SGO": "Chile", "BUE": "Argentina", "JNB": "África do Sul",
    "SAU": "Arábia Saudita", "TLV": "Israel", "SET": "Tailândia", "JKT": "Indonésia", "KLS": "Malásia",
    "PHS": "Filipinas", "DOH": "Catar", "DFM": "Emirados", "CAI": "Egito",
}
COUNTRY_PT = {
    "United States": "EUA", "United Kingdom": "Reino Unido", "Germany": "Alemanha", "France": "França",
    "Netherlands": "Países Baixos", "Spain": "Espanha", "Italy": "Itália", "Switzerland": "Suíça",
    "Sweden": "Suécia", "Denmark": "Dinamarca", "Norway": "Noruega", "Finland": "Finlândia", "Belgium": "Bélgica",
    "Portugal": "Portugal", "Ireland": "Irlanda", "Austria": "Áustria", "Poland": "Polónia", "Greece": "Grécia",
    "Japan": "Japão", "Hong Kong": "Hong Kong", "South Korea": "Coreia do Sul", "Taiwan": "Taiwan",
    "India": "Índia", "China": "China", "Singapore": "Singapura", "Australia": "Austrália", "Canada": "Canadá",
    "Brazil": "Brasil", "Mexico": "México", "Chile": "Chile", "Argentina": "Argentina",
    "South Africa": "África do Sul", "Saudi Arabia": "Arábia Saudita", "Israel": "Israel", "Thailand": "Tailândia",
    "Indonesia": "Indonésia", "Malaysia": "Malásia", "Luxembourg": "Luxemburgo", "Bermuda": "Bermudas",
    "Cayman Islands": "Ilhas Caimão", "Turkey": "Turquia", "New Zealand": "Nova Zelândia",
}
REGION_OF = {
    "Europa": {"Reino Unido", "Alemanha", "França", "Países Baixos", "Espanha", "Itália", "Suíça", "Suécia",
               "Dinamarca", "Noruega", "Finlândia", "Bélgica", "Portugal", "Irlanda", "Áustria", "Polónia", "Grécia",
               "Chéquia", "Hungria", "Luxemburgo", "Turquia"},
    "América do Norte": {"EUA", "Canadá", "Bermudas"},
    "Ásia-Pacífico": {"Japão", "Hong Kong", "Coreia do Sul", "Taiwan", "Índia", "China", "Singapura", "Austrália",
                      "Nova Zelândia", "Tailândia", "Indonésia", "Malásia", "Filipinas"},
    "América Latina": {"Brasil", "México", "Chile", "Argentina"},
}
SECTOR_PT = {
    "Technology": "Tecnologia", "Financial Services": "Financeiro", "Healthcare": "Saúde",
    "Consumer Cyclical": "Consumo cíclico", "Consumer Defensive": "Consumo básico", "Industrials": "Indústria",
    "Energy": "Energia", "Basic Materials": "Materiais", "Utilities": "Utilities", "Real Estate": "Imobiliário",
    "Communication Services": "Comunicações",
}


def region_of(country):
    return next((r for r, cs in REGION_OF.items() if country in cs), "Outras")


def _load(key):
    try:
        return json.loads(Setting.get(key) or "null")
    except ValueError:
        return None


def universe():
    return _load("triage:universe")


def infos():
    return _load("triage:info") or {}


# as bolsas principais do universo e a moeda em que o Yahoo dá a capitalização (o filtro compara-a na moeda local;
# Londres, Joanesburgo e Telavive cotam em centésimos)
EXCHANGE_CURRENCY = {
    "NMS": "USD", "NYQ": "USD", "NGM": "USD", "NCM": "USD", "ASE": "USD", "TOR": "CAD", "LSE": "GBp",
    "GER": "EUR", "PAR": "EUR", "AMS": "EUR", "MCE": "EUR", "MIL": "EUR", "BRU": "EUR", "LIS": "EUR", "ISE": "EUR",
    "VIE": "EUR", "HEL": "EUR", "ATH": "EUR", "EBS": "CHF", "STO": "SEK", "CPH": "DKK", "OSL": "NOK", "WSE": "PLN",
    "JPX": "JPY", "HKG": "HKD", "SHH": "CNY", "SHZ": "CNY", "KSC": "KRW", "KOE": "KRW", "TAI": "TWD", "TWO": "TWD",
    "NSI": "INR", "SES": "SGD", "ASX": "AUD", "NZE": "NZD", "SAO": "BRL", "MEX": "MXN", "SGO": "CLP", "JNB": "ZAc",
    "TLV": "ILA", "SAU": "SAR", "SET": "THB", "KLS": "MYR", "JKT": "IDR", "IST": "TRY",
}
US_EXCHANGES = {"NMS", "NYQ", "NGM", "NCM", "ASE"}
MIN_CAP_USD = 2e9
# a ordem de cada lente (o Yahoo devolve as melhores primeiro): (campo, ascendente)
SORT = {"graham_def": ("peratio.lasttwelvemonths", True), "graham_num": ("pricebookratio.quarterly", True),
        "buffett": ("returnonequity.lasttwelvemonths", False), "lynch": ("pegratio_5y", True),
        "greenblatt": ("returnontotalcapital.lasttwelvemonths", False), "bazin": ("forward_dividend_yield", False),
        "fisher": ("totalrevenues1yrgrowth.lasttwelvemonths", False), "templeton": ("peratio.lasttwelvemonths", True),
        "oneil": ("epsgrowth.lasttwelvemonths", False), "resumo": ("returnonequity.lasttwelvemonths", False)}


def _query(lens):
    """A pesquisa de uma lente: os limites largos da lente e, em cada região, pelo menos `MIN_CAP_USD` de
    capitalização (convertida para a moeda local), só nas bolsas principais."""
    spec = lenses.LENSES[lens]
    ops = []
    for field, op, value in spec["query"]:
        ops.append({"operator": "btwn", "operands": [field, value[0], value[1]]} if op == "btwn"
                   else {"operator": op, "operands": [field, value]})
    regions = []
    for code, cur in EXCHANGE_CURRENCY.items():
        if spec.get("no_us") and code in US_EXCHANGES:
            continue
        major = lenses.MAJOR.get(cur)  # no filtro, a capitalização destas bolsas vai em centésimos
        local = MIN_CAP_USD / lenses.USD_RATE[major or cur] * (100 if major else 1)
        regions.append({"operator": "and", "operands": [{"operator": "eq", "operands": ["exchange", code]},
                                                       {"operator": "gt", "operands": ["intradaymarketcap", local]}]})
    ops.append({"operator": "or", "operands": regions})
    return {"operator": "and", "operands": ops}


def refresh_step(budget=8.0, fetch=None, now=None):
    """Um passo da recolha do universo (no máximo `budget` segundos). Devolve o progresso."""
    fetch = fetch or screener.fetch_yahoo
    now = now or datetime.now()
    state = _load("triage:refresh")
    if not state or state.get("done"):
        state = {"started": now.isoformat(timespec="minutes"), "todo": [[k, p] for k in lenses.REAL
                                                                         for p in range(PAGES)],
                 "quotes": {}, "members": {}, "totals": {}, "done": False, "errors": []}
    start = time.monotonic()
    while state["todo"] and time.monotonic() - start < budget:
        lens, page = state["todo"].pop(0)
        field, asc = SORT[lens]
        try:
            res = fetch({"query": _query(lens), "sortField": field, "sortType": "ASC" if asc else "DESC", "size": PAGE_SIZE,
                         "offset": page * PAGE_SIZE}) or {}
        except OSError as exc:
            state["errors"].append(f"{lenses.LENSES[lens]['name']}: {exc}")
            continue
        state["totals"][lens] = res.get("total", 0)
        quotes = [q for q in res.get("quotes") or [] if q.get("symbol") and screener.primary(q)]
        for pos, q in enumerate(quotes):
            sym = q["symbol"]
            state["quotes"][sym] = q
            state["members"].setdefault(sym, {})[lens] = page * PAGE_SIZE + pos
        if len(res.get("quotes") or []) < PAGE_SIZE:  # não há mais páginas desta lente
            state["todo"] = [t for t in state["todo"] if t[0] != lens]
    if not state["todo"]:
        kept = screener.dedupe(list(state["quotes"].values()))
        rows = []
        for q in kept:
            r = screener._row(q)
            r["exchange_code"] = (q.get("exchange") or "").upper()
            r["eps"], r["bvps"] = q.get("epsTrailingTwelveMonths"), q.get("bookValue")
            r["candidate"] = state["members"].get(q["symbol"], {})
            rows.append(r)
        Setting.set("triage:universe", json.dumps({"at": now.isoformat(timespec="minutes"), "rows": rows,
                                                   "totals": state["totals"], "errors": state["errors"]}))
        state = {"done": True}
    Setting.set("triage:refresh", json.dumps(state))
    left = len(state.get("todo", []))
    return {"done": state.get("done", False), "left": left, "total": len(lenses.REAL) * PAGES,
            "found": len(state.get("quotes", {}))}


WORKERS = 2
RETRIES = 3


class RateLimited(OSError):
    pass


def _pending(rows, data, now):
    """As ações ainda sem os dados completos (ou com mais de uma semana), menos as que já falharam `RETRIES` vezes."""
    out = []
    for r in rows:
        d = data.get(r["ticker"])
        if d is None or (not d.get("info") and d.get("fails", 0) < RETRIES) or \
                (d.get("info") and now - datetime.fromisoformat(d["at"]) > INFO_STALE):
            out.append(r["ticker"])
    return out


def enrich_step(budget=8.0, fetch_info=None, now=None, limit=None):
    """Completa os dados das ações do universo, `WORKERS` de cada vez, durante no máximo `budget` segundos.
    Quando o Yahoo limita os pedidos (HTTP 429), para e diz quanto esperar (`wait`, em segundos)."""
    from concurrent.futures import ThreadPoolExecutor

    from . import moat
    fetch_info = fetch_info or moat.info_of
    now = now or datetime.now()
    u = universe() or {"rows": []}
    data = infos()
    todo = _pending(u["rows"], data, now)
    if limit:
        todo = todo[:limit]

    def one(t):
        try:
            return t, fetch_info(t) or {}, None
        except OSError as exc:
            limited = "429" in str(exc) or "Too Many Requests" in str(exc) or "Rate limited" in str(exc)
            return t, None, "limited" if limited else "error"
    start, i, wait = time.monotonic(), 0, 0
    with ThreadPoolExecutor(WORKERS) as pool:
        while i < len(todo) and time.monotonic() - start < budget and not wait:
            chunk = todo[i:i + WORKERS * 2]
            i += len(chunk)
            for t, info, err in pool.map(one, chunk):
                if err == "limited":
                    wait = 60
                    continue
                slim = _slim(info or {})
                if slim.get("regularMarketPrice") or slim.get("currentPrice") or slim.get("marketCap"):
                    data[t] = {"at": now.isoformat(timespec="minutes"), "info": slim}
                else:  # sem dados: volta a tentar-se mais tarde (até `RETRIES` vezes)
                    old = data.get(t) or {}
                    data[t] = {"at": now.isoformat(timespec="minutes"), "info": old.get("info"),
                               "fails": old.get("fails", 0) + 1}
    Setting.set("triage:info", json.dumps(data))
    left = len(_pending(u["rows"], data, now))
    return {"done": left == 0, "left": left, "total": len(u["rows"]), "wait": wait}


SLIM_KEYS = ("regularMarketPrice", "currentPrice", "currency", "marketCap", "trailingPE", "forwardPE", "priceToBook",
             "priceToSalesTrailing12Months", "enterpriseToEbitda", "trailingPegRatio", "pegRatio", "returnOnEquity",
             "returnOnAssets", "profitMargins", "operatingMargins", "grossMargins", "revenueGrowth", "earningsGrowth",
             "debtToEquity", "currentRatio", "quickRatio", "ebitda", "totalDebt", "totalCash", "dividendYield",
             "trailingAnnualDividendYield", "dividendRate", "payoutRatio", "trailingEps", "forwardEps", "bookValue",
             "freeCashflow", "beta", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "netIncomeToCommon", "sector", "industry",
             "country", "longName", "shortName", "longBusinessSummary", "_yfinance", "fullTimeEmployees", "website",
             "fiftyDayAverage", "twoHundredDayAverage", "numberOfAnalystOpinions", "targetMeanPrice",
             "financialCurrency", "sharesOutstanding")


def _slim(info):
    out = {k: info[k] for k in SLIM_KEYS if info.get(k) is not None}
    if "longBusinessSummary" in out:
        out["longBusinessSummary"] = out["longBusinessSummary"][:1500]
    return out


def metrics(row, info):
    """Os indicadores de uma linha do universo (dados completos quando houver, senão os da cotação)."""
    m = lenses.metrics_from_info(info or {}, row)
    country = COUNTRY_PT.get((info or {}).get("country")) or EXCHANGE_COUNTRY.get(row.get("exchange_code"), "Outros")
    m["country"] = country
    m["region"] = region_of(country)
    m["sector"] = SECTOR_PT.get((info or {}).get("sector"), (info or {}).get("sector"))
    return m


def table(include_valuation=False):
    """As linhas da página: cada ação com indicadores e estados; pode incluir a comparação de avaliações."""
    u = universe()
    if not u:
        return None
    data = infos()
    rows = []
    for r in u["rows"]:
        if not screener.primary({"symbol": r["ticker"], "exchange": r.get("exchange_code")}):
            continue  # (universos guardados antes de uma regra nova)
        info = (data.get(r["ticker"]) or {}).get("info")
        m = metrics(r, info)
        rows.append({"r": r, "m": m, "info": bool(info), "info_data": info})
    fundamentals = {}
    if include_valuation and rows:
        from ..models import Fundamental
        fundamentals = {f.ticker: f for f in Fundamental.query.all()}
    # Greenblatt: em todo o universo, posição na rentabilidade (ROE) + posição no earnings yield (1 ÷ P/L)
    cand = [x for x in rows if x["m"].get("pe") and x["m"].get("roe") is not None]
    by_q = sorted(cand, key=lambda x: -x["m"]["roe"])
    by_ey = sorted(cand, key=lambda x: x["m"]["pe"])
    pos_q = {id(x): i for i, x in enumerate(by_q)}
    pos_ey = {id(x): i for i, x in enumerate(by_ey)}
    ranked = sorted(cand, key=lambda x: pos_q[id(x)] + pos_ey[id(x)])
    n = len(ranked)
    for i, x in enumerate(ranked):
        x["m"]["magic_rank"], x["m"]["magic_n"] = i + 1, n
        x["m"]["magic_q"] = float(min(int(i * 4 / n) + 1, 4)) if n else None
    out = []
    for x in rows:
        st = {}
        for k in lenses.REAL:
            status, _ = lenses.evaluate(k, x["m"])
            if status is None and k in x["r"]["candidate"] and not x["info"]:
                status = "quase"  # sem os dados completos ainda: apareceu na pesquisa da lente
            st[k] = status
        enters = [k for k, v in st.items() if v == "entra"]
        st["varias"] = "entra" if len(enters) >= 2 else ("quase" if len(enters) == 1 else "falha")
        m = x["m"]
        out.append({"t": x["r"]["ticker"], "n": x["r"]["name"], "c": m["country"], "g": m["region"],
                    "s": m["sector"] or "", "cur": m["currency"], "p": m["price"], "cap": m["cap_usd"],
                    "pe": m["pe"], "pb": m["pb"], "roe": m["roe"], "rg": m["rev_growth"], "dv": m["div"],
                    "de": m["de"], "st": st, "k": len(enters), "full": x["info"], "mq": m.get("magic_q"),
                    "cv": lenses.criterion_values(m),
                    "vg": valuation_gap(x["r"]["ticker"], m, x["info_data"],
                                        fundamentals.get(x["r"]["ticker"])) if include_valuation else None})
    return {"at": u["at"], "rows": out, "errors": u.get("errors") or [],
            "stale": datetime.now() - datetime.fromisoformat(u["at"]) > STALE,
            "missing": sum(1 for x in out if not x["full"])}


# «Se entrar na lista»: o que os números não respondem (chave, pergunta, ajuda)
QUESTIONS = (
    ("negocio", "Percebo como ganha dinheiro?", "Explica numa frase o que vende, a quem e porque lhe compram a ela."),
    ("barata", "Porque está a este preço?", "Se parece barata, o que sabe o mercado? É passageiro ou é o negócio a piorar?"),
    ("fosso", "O que a protege da concorrência?", "Marca, custos de mudança, rede, custos baixos, escala. Dura 10 anos?"),
    ("gestao", "Confio na gestão?", "Alocação do capital, recompras e dívida, quanto dos donos está na empresa."),
    ("risco", "O que pode correr mal?", "Dívida, um cliente ou país de que depende, regulação, tecnologia."),
    ("catalisador", "O que pode fazer o preço mexer?", "Resultados, um produto novo, recompras, o fim de um problema."),
    ("preco", "A que preço compraria, e quanto?", "O preço máximo (Graham, Bazin, DCF) e o peso que teria na carteira."),
)


def row(ticker):
    """A linha da tabela da triagem de uma ação (None se não estiver no universo)."""
    tab = table() or {"rows": []}
    return next((x for x in tab["rows"] if x["t"] == ticker), None)


def reason(ticker, rows=None):
    """O «porque entrou» de uma ação guardada a partir da triagem, ex.: «Entra em Buffett e Bazin. P/L 3,9.»."""
    r = rows.get(ticker) if rows is not None else row(ticker)
    if not r:
        return None
    names = [lenses.LENSES[k]["name"] for k in lenses.REAL if r["st"].get(k) == "entra"]
    parts = []
    if names:
        parts.append("Entra em " + (", ".join(names[:-1]) + " e " + names[-1] if len(names) > 1 else names[0]) + ".")
    if r.get("pe"):
        parts.append(f"P/L {r['pe']:.1f}.".replace(".", ",", 1))
    if r.get("dv"):
        parts.append(f"Dividendo {r['dv'] * 100:.1f}%.".replace(".", ",", 1))
    return " ".join(parts) or None


def answers(ticker):
    return _load(f"triage_notes:{ticker}") or {}


def save_answers(ticker, values):
    clean = {k: str(values.get(k) or "").strip()[:1000] for k, _, _ in QUESTIONS if str(values.get(k) or "").strip()}
    Setting.set(f"triage_notes:{ticker}", json.dumps(clean, ensure_ascii=False) if clean else None)
    return clean


def valuation_gap(ticker, m, info, fundamental=None):
    """Diferença relativa entre a cotação e o menor valor positivo da ficha lateral."""
    price = m.get("price")
    if not isinstance(price, (int, float)) or not isfinite(price) or price <= 0:
        return None
    values = [lenses.graham_number(m), lenses.bazin_ceiling(m)]
    v = valuation_of(ticker, m, info, fundamental=fundamental)
    if v:
        values.extend(method.get("low") for method in v["methods"])
        if v.get("peg"):
            values.append(v["peg"].get("fair"))
    valid = [value for value in values
             if isinstance(value, (int, float)) and isfinite(value) and value > 0]
    if not valid:
        return None
    gap = price / min(valid) - 1
    return gap if isfinite(gap) else None


_FUNDAMENTAL_UNSET = object()


def valuation_of(ticker, m, info, fundamental=_FUNDAMENTAL_UNSET):
    """O valor da ação pelos vários métodos (os mesmos de «O valor de cada ação», na Carteira). Com os dados
    fundamentais da Carteira (e as correções que lá fizeste) quando a ação é tua; senão, pelos dados do Yahoo,
    tudo por ação e na moeda da cotação."""
    from ..engine import valuation
    from ..models import Fundamental, db
    price = m.get("price")
    if not price:
        return None
    f = db.session.get(Fundamental, ticker) if fundamental is _FUNDAMENTAL_UNSET else fundamental

    def pick(name):
        manual = getattr(f, "manual_" + name, None) if f else None
        return manual if manual is not None else (getattr(f, name, None) if f else None)
    major = lenses.MAJOR.get(m.get("currency"), m.get("currency"))
    k = 100 if m.get("currency") in lenses.MAJOR else 1
    shares = (info or {}).get("sharesOutstanding")

    def per_share(total):  # total na moeda das contas → por ação, na moeda da cotação (câmbio aproximado)
        fin, quote = lenses.USD_RATE.get(m.get("fin_currency")), lenses.USD_RATE.get(major)
        if total is None or not shares or not fin or not quote:
            return None
        return total / shares * fin / quote * k
    growth = None
    if m.get("pe") and m.get("peg") and m["peg"] > 0:
        growth = m["pe"] / m["peg"] / 100  # o crescimento que os analistas esperam (5 anos), implícito no PEG
    elif m.get("eps_growth") is not None:
        growth = m["eps_growth"]
    cash, debt = (info or {}).get("totalCash"), (info or {}).get("totalDebt")
    inputs = {"eps": pick("eps") if f else m.get("eps"), "bvps": pick("bvps") if f else m.get("bvps"),
              "fcf": pick("fcf") if f else per_share(m.get("fcf")),
              "growth": pick("growth") if f and pick("growth") is not None else growth,
              "owner": pick("owner") if f else None, "nopat": pick("nopat") if f else None,
              "net_cash": pick("net_cash") if f else (per_share((cash or 0) - debt) if debt is not None else None)}
    try:
        aaa = float(Setting.get("aaa_yield")) / 100
    except (TypeError, ValueError):
        aaa = valuation.AAA_YIELD
    v = valuation.value_stock(price, eps=inputs["eps"], eps_forward=(f.eps_forward if f else m.get("fwd_eps")),
                              bvps=inputs["bvps"], fcf=inputs["fcf"], growth=inputs["growth"],
                              dividends=m.get("dps"), owner_earnings=inputs["owner"], nopat=inputs["nopat"],
                              net_cash=inputs["net_cash"], aaa_yield=aaa)
    v.update(currency=m.get("currency"), from_portfolio=f is not None)
    return v


PEER_METRICS = (("pe", "P/E", "o preço a dividir pelo lucro"), ("div", "Dividendo", "por ano, em % do preço"),
                ("net_margin", "Margem líquida", "o lucro em % das vendas"),
                ("roe", "ROE", "o lucro em % do capital próprio"), ("rev_growth", "Vendas", "o crescimento do último ano"))
MIN_PEERS = 5


def _pct(values, q):
    """O percentil `q` (0–1) de uma lista ordenada, com interpolação."""
    if not values:
        return None
    i = (len(values) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (i - lo)


def peers(ticker, m, info, data=None, rows=None):
    """«Ao lado dos pares»: a ação face às empresas da mesma indústria no universo da triagem (ou do mesmo setor,
    se forem menos de `MIN_PEERS`). Para cada medida: mínimo e máximo (5–95%), o intervalo 25–75%, a mediana e o valor
    da ação. Usa só os dados guardados (nada ao Yahoo)."""
    data = infos() if data is None else data
    rows = (universe() or {"rows": []})["rows"] if rows is None else rows
    info = info or {}

    def group(key):
        val = info.get(key)
        if not val:
            return []
        out = []
        for r in rows:
            i = (data.get(r["ticker"]) or {}).get("info") or {}
            if r["ticker"] != ticker and i.get(key) == val:
                out.append(lenses.metrics_from_info(i, r))
        return out
    scope, label = "industry", info.get("industry")
    group_m = group("industry")
    if len(group_m) < MIN_PEERS:
        scope, label, group_m = "sector", SECTOR_PT.get(info.get("sector"), info.get("sector")), group("sector")
    if len(group_m) < MIN_PEERS:
        return None
    out = []
    for key, name, sub in PEER_METRICS:
        vals = sorted(x[key] for x in group_m if x.get(key) is not None and (key != "pe" or x[key] > 0))
        if len(vals) < MIN_PEERS:
            continue
        lo, hi = _pct(vals, 0.05), _pct(vals, 0.95)
        span = (hi - lo) or 1.0

        def pos(v, lo=lo, span=span):
            return None if v is None else max(0.0, min(100.0, (v - lo) / span * 100))
        p25, med, p75, me = _pct(vals, 0.25), _pct(vals, 0.5), _pct(vals, 0.75), m.get(key)
        out.append({"key": key, "name": name, "sub": sub, "value": me, "median": med, "n": len(vals),
                    "p25": pos(p25), "p75": pos(p75), "mid": pos(med), "me": pos(me),
                    "pct": key != "pe"})
    return {"scope": scope, "label": label, "n": len(group_m), "rows": out} if out else None


def detail(ticker, overrides=None):
    """A ficha de uma ação do universo (ou de qualquer ação, lendo os dados ao Yahoo)."""
    from . import moat
    u = universe() or {"rows": []}
    row = next((r for r in u["rows"] if r["ticker"] == ticker), None)
    data = infos()
    info = (data.get(ticker) or {}).get("info")
    if not info:
        info = _slim(moat.info_of(ticker))
        # só se guarda uma resposta com dados: vazia (o Yahoo falhou), volta a pedir-se na próxima vez que se abrir
        if info.get("regularMarketPrice") or info.get("currentPrice") or info.get("marketCap"):
            data[ticker] = {"at": datetime.now().isoformat(timespec="minutes"), "info": info}
            Setting.set("triage:info", json.dumps(data))
    row = row or {"ticker": ticker, "name": info.get("longName") or info.get("shortName") or ticker,
                  "exchange_code": "", "candidate": {}}
    m = metrics(row, info)
    tab = table() or {"rows": []}
    me = next((x for x in tab["rows"] if x["t"] == ticker), None)
    m["magic_q"] = me.get("mq") if me else None  # fora do universo, o ranking de Greenblatt não se aplica
    overrides = overrides or {}
    evals = {k: lenses.evaluate(k, m, overrides.get(k)) for k in lenses.REAL}
    if me:  # o estado é o da tabela (conta com o ranking e com as ações ainda sem os dados completos)
        evals = {k: ((me["st"][k] if k not in overrides else s_), rows) for k, (s_, rows) in evals.items()}
    return {"ticker": ticker, "name": row.get("name") or ticker, "m": m, "info": info, "evals": evals,
            "enters": [k for k, (s, _) in evals.items() if s == "entra"], "tags": lenses.tags(m),
            "blurb": lenses.blurb(m), "graham": lenses.graham_number(m), "bazin": lenses.bazin_ceiling(m),
            "row": row, "in_universe": me is not None, "questions": QUESTIONS, "answers": answers(ticker),
            "val": valuation_of(ticker, m, info), "peers": peers(ticker, m, info, data, u["rows"]),
            "custom": [k for k in lenses.REAL if k in overrides],
            "custom_names": [lenses.LENSES[k]["name"] for k in lenses.REAL if k in overrides]}
