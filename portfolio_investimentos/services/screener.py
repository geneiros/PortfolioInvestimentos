"""O filtro de ações do Yahoo (a triagem de Prospeção, services/triage.py): a pesquisa, as cotações que contam (sem
segundas cotações nem certificados) e uma linha por empresa.
"""
import re

# bolsas de segundas cotações (Frankfurt e outras alemãs, OTC dos EUA, Cboe, a internacional de Londres...)
SECONDARY = {"FRA", "BER", "DUS", "MUN", "STU", "HAM", "HAN", "GER2", "PNK", "OID", "OQX", "OQB", "OEM", "OGM",
             "CXE", "IOB", "NEO", "AQS", "DXE", "TLO"}
BDR = re.compile(r"^[A-Z0-9]{4}3[1-9]\.SA$")


def primary(q):
    """Fica de fora o que é uma segunda cotação (Frankfurt, OTC, Cboe, a carteira internacional de Londres...)."""
    if (q.get("exchange") or "").upper() in SECONDARY:
        return False
    sym = q.get("symbol") or ""
    if sym.endswith(".L") and len(sym) == 6 and sym[0] == "0":  # 0XXX.L: ações estrangeiras em Londres
        return False
    if re.search(r"-P[A-Z]?$", sym) and "." not in sym:  # ações preferenciais nos EUA (ex.: JPM-PD)
        return False
    return not BDR.match(sym)  # BDR: certificados de ações estrangeiras em São Paulo


def dedupe(quotes):
    """Uma linha por empresa: entre as cotações com o mesmo nome (ex.: Alphabet nos EUA, no Canadá e no México, ações
    preferenciais), fica a da bolsa principal: a que negoceia na moeda das contas; o México, São Paulo e Viena, onde
    se cotam muitas estrangeiras, e os certificados (CDR, ADR) por último."""
    def name(q):
        return (q.get("longName") or q.get("shortName") or q.get("symbol") or "").lower()

    def key(q):  # sem o que está entre parênteses nem «CDR»/«ADR»: o mesmo nome em todas as bolsas
        n = re.sub(r"\(.*?\)|\b(cdr|adr|bdr|gdr)\b", "", name(q))
        return re.sub(r"[^a-z0-9]", "", n)
    groups = {}
    for i, q in enumerate(quotes):
        groups.setdefault(key(q), []).append((i, q))
    best = []
    for items in groups.values():
        i, q = min(items, key=lambda iq: (
            (iq[1].get("exchange") or "") in ("MEX", "SAO", "VIE")
            or re.search(r"\b(cdr|adr|bdr|gdr)\b", name(iq[1])) is not None,
            # a bolsa principal costuma negociar na moeda das contas da empresa
            bool(iq[1].get("financialCurrency")) and iq[1].get("currency") != iq[1].get("financialCurrency"),
            iq[0]))
        best.append((items[0][0], q))
    return [q for _, q in sorted(best, key=lambda x: x[0])]


def _dividend(q):
    """Rendimento de dividendos (fração). O «dividendYield» do Yahoo vem em %; acima de 25% é erro de dados."""
    # o «dividendYield» (dividendo anual ÷ preço, na mesma moeda) é o mais fiável; o «trailing» falha quando a cotação
    # é noutra moeda (ex.: ações dos EUA no México)
    v = q["dividendYield"] / 100 if q.get("dividendYield") is not None else q.get("trailingAnnualDividendYield")
    return v if v is not None and 0 <= v <= 0.25 else None


def _row(q):
    price = q.get("regularMarketPrice")
    hi, lo = q.get("fiftyTwoWeekHigh"), q.get("fiftyTwoWeekLow")
    return {"ticker": q.get("symbol"), "name": q.get("longName") or q.get("shortName") or q.get("symbol"),
            "exchange": q.get("fullExchangeName") or q.get("exchange"), "currency": (q.get("currency") or "").upper(),
            "price": price, "cap": q.get("marketCap"), "pe": q.get("trailingPE"), "pb": q.get("priceToBook"),
            "fpe": q.get("forwardPE"), "div": _dividend(q),
            "high": hi, "low": lo, "change52": q.get("fiftyTwoWeekChangePercent"),
            "from_high": (price / hi - 1) if price and hi else None,
            "from_low": (price / lo - 1) if price and lo else None,
            "rating": q.get("averageAnalystRating")}


def _equity_query(q):
    """A consulta em dicionário → EquityQuery do yfinance (operadores em minúsculas, como ele os valida)."""
    from yfinance import EquityQuery
    ops = [(_equity_query(o) if isinstance(o, dict) else o) for o in q["operands"]]
    return EquityQuery(q["operator"].lower(), ops)


def fetch_yahoo(body):
    """O filtro do Yahoo: pelo yfinance quando está instalado (trata do cookie e do crumb como um browser, por isso o
    Yahoo não o limita como faz com pedidos simples); senão pelo acesso direto."""
    try:
        import yfinance
    except ImportError:
        yfinance = None
    if yfinance is not None:
        from . import yahoo
        try:
            return yfinance.screen(_equity_query(body["query"]), size=min(int(body.get("size", 100)), 250),
                                   offset=int(body.get("offset", 0)), sortField=body.get("sortField", "intradaymarketcap"),
                                   sortAsc=body.get("sortType", "DESC") == "ASC") or {}
        except Exception as exc:  # o yfinance lança vários tipos; mostra-se a mensagem como as do acesso direto
            raise yahoo.YahooError(str(exc)[:200]) from exc
    from . import yahoo
    return yahoo.screener(body)
