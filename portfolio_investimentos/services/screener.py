"""Oportunidades (Radar e alertas): ações de todo o mundo que cumprem os critérios dos grandes investidores.

1.º passo: o filtro de ações do Yahoo aplica os critérios de cada método (P/L, P/VP, ROE, dívida, liquidez,
crescimento...) e devolve as empresas que os cumprem; alguns critérios que o Yahoo não filtra (P/L × P/VP do
Graham, distância aos máximos/mínimos de 52 semanas) aplicam-se depois, com os dados de cada cotação.
2.º passo (services/moat.py): o fosso económico (moat) de cada empresa encontrada.

Os limites de cada método podem ser mudados na página; o último resultado fica guardado (Setting
«screen:last») para a página abrir sem voltar a perguntar ao Yahoo. É um filtro, não uma recomendação.
"""
import json
import re
from datetime import datetime

from ..models import Setting

# regiões do Yahoo (códigos ISO em minúsculas)
REGIONS = {
    "mundo": ("Mundo (principais mercados)", ["us", "ca", "gb", "de", "fr", "es", "it", "nl", "ch", "se", "dk", "no",
                                             "fi", "be", "pt", "ie", "at", "jp", "au", "hk", "sg", "kr", "tw", "in",
                                             "br", "mx"]),
    "europa": ("Europa", ["gb", "de", "fr", "es", "it", "nl", "ch", "se", "dk", "no", "fi", "be", "pt", "ie", "at"]),
    "eua": ("EUA", ["us"]),
    "portugal": ("Portugal", ["pt"]),
    "asia": ("Ásia e Pacífico", ["jp", "au", "hk", "sg", "kr", "tw", "in"]),
    "americas": ("Américas (sem os EUA)", ["ca", "br", "mx"]),
}
MIN_CAPS = (("300e6", "Acima de 300 M$"), ("1e9", "Acima de 1 000 M$"), ("1e10", "Acima de 10 000 M$"))

# critérios: (campo do Yahoo, operador, valor por omissão, rótulo, unidade). Os campos em percentagem estão em %.
# Os limites de baixo (P/L ≥ 3 ou 5, PEG ≥ 0,2) e de cima (ROE ≤ 100%) tiram os dados absurdos do Yahoo.
# Sem «sort», ordena-se pela capitalização (as maiores primeiro).
# bolsas onde estão sobretudo segundas cotações (de empresas já cotadas na bolsa principal) e balcões OTC
SECONDARY = {"FRA", "BER", "DUS", "MUN", "STU", "HAM", "HAN", "GER2", "PNK", "OID", "OQX", "OQB", "OEM", "OGM",
             "CXE", "IOB", "NEO", "AQS", "DXE", "TLO"}
BDR = re.compile(r"^[A-Z0-9]{4}3[1-9]\.SA$")
METHODS = {
    "graham": {
        "investor": "Benjamin Graham", "title": "Deep value e margem de segurança",
        "text": "Empresas baratas face aos lucros e ao património, com balanço sólido e dividendos.",
        "criteria": [("peratio.lasttwelvemonths", "btwn", (3, 15), "P/L", ""),
                     ("pricebookratio.quarterly", "btwn", (0.1, 3), "P/VP", ""),
                     ("currentratio.lasttwelvemonths", "gt", 2, "Liquidez corrente", ""),
                     ("forward_dividend_yield", "gt", 0, "Rendimento de dividendos", "%")],
        "post": [("pe_pb", 22.5, "P/L × P/VP")],
        "later": "Lucros positivos em todos os anos (no 2.º passo).",
    },
    "buffett": {
        "investor": "Warren Buffett e Charlie Munger", "title": "Qualidade a um preço justo",
        "text": "Rentabilidade alta, margens fortes e pouca dívida, sem pagar demasiado.",
        "criteria": [("returnonequity.lasttwelvemonths", "btwn", (15, 100), "ROE", "%"),
                     ("netincomemargin.lasttwelvemonths", "gt", 10, "Margem líquida", "%"),
                     ("netdebtebitda.lasttwelvemonths", "lt", 3, "Dívida líquida / EBITDA", ""),
                     ("peratio.lasttwelvemonths", "btwn", (5, 25), "P/L", "")],
        "post": [],
        "later": "ROE consistente, cash flow livre (owner earnings) e moat (no 2.º passo).",
    },
    "lynch": {
        "investor": "Peter Lynch", "title": "GARP: crescimento a um preço razoável",
        "text": "Lucros a crescer depressa, com o PEG abaixo de 1 e balanço sólido.",
        "criteria": [("pegratio_5y", "btwn", (0.2, 1), "PEG", ""),
                     ("epsgrowth.lasttwelvemonths", "gt", 15, "Crescimento do lucro por ação", "%"),
                     ("totaldebtequity.lasttwelvemonths", "lt", 50, "Dívida / capital próprio", "%")],
        "post": [],
        "later": "Baixa cobertura de analistas e gestores a comprar ações (a ver à mão).",
    },
    "greenblatt": {
        "investor": "Joel Greenblatt", "title": "Fórmula Mágica",
        "text": "Boas empresas (retorno sobre o capital alto) a preços baixos (earnings yield alto), por ranking.",
        "criteria": [("returnontotalcapital.lasttwelvemonths", "btwn", (15, 80), "Retorno sobre o capital (ROIC)", "%"),
                     ("peratio.lasttwelvemonths", "btwn", (5, 30), "P/L", "")],
        "post": [], "sort": "returnontotalcapital.lasttwelvemonths", "order": "DESC", "rank": "magic",
        "later": "Ordenadas pela soma das posições no retorno sobre o capital e no earnings yield (1 ÷ P/L).",
    },
    "oneil": {
        "investor": "William O'Neil", "title": "CAN SLIM",
        "text": "Lucros a crescer mais de 25%, rentabilidade alta e a ação perto dos máximos.",
        "criteria": [("epsgrowth.lasttwelvemonths", "gt", 25, "Crescimento do lucro por ação", "%"),
                     ("totalrevenues1yrgrowth.lasttwelvemonths", "gt", 15, "Crescimento das receitas", "%"),
                     ("returnonequity.lasttwelvemonths", "gt", 17, "ROE", "%")],
        "post": [("near_high", 15, "Até x% abaixo do máximo de 52 semanas")],
        "later": "Procura institucional e novos produtos (a ver à mão).",
    },
    "templeton": {
        "investor": "John Templeton", "title": "Contrarian global",
        "text": "Comprar no pessimismo: lucros baratos, com a ação perto dos mínimos.",
        "criteria": [("peratio.lasttwelvemonths", "btwn", (3, 12), "P/L", "")],
        "post": [("near_low", 20, "Até x% acima do mínimo de 52 semanas"), ("forward_pe", 12, "P/L previsto até")],
        "later": "Mercados deprimidos: vale a pena olhar sobretudo para fora dos EUA.",
    },
    "resumo": {
        "investor": "Resumo dos métodos", "title": "A interseção",
        "text": "Rentabilidade, solidez, crescimento e preço justo ao mesmo tempo.",
        "criteria": [("returnonequity.lasttwelvemonths", "btwn", (15, 100), "ROE", "%"),
                     ("netdebtebitda.lasttwelvemonths", "lt", 2.5, "Dívida líquida / EBITDA", ""),
                     ("totalrevenues1yrgrowth.lasttwelvemonths", "gt", 8, "Crescimento das receitas", "%"),
                     ("pegratio_5y", "btwn", (0.2, 1.2), "PEG", "")],
        "post": [],
        "later": "O PDF pede 5 anos de crescimento; o filtro usa o último ano e o 2.º passo vê os 4 anos.",
    },
}


class ScreenError(ValueError):
    """Pedido inválido (método ou região desconhecidos, limite que não é número): a mensagem é para o utilizador."""


def _num(v):
    try:
        return float(str(v).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise ScreenError(f"Valor inválido: {v}") from exc


def criteria(method, values=None):
    """Os critérios do método com os limites indicados (`values`: {"c0": "15", "c0b": "30", "p0": "22.5"})."""
    m = METHODS.get(method)
    if not m:
        raise ScreenError("Método desconhecido.")
    values = values or {}
    out, post = [], []
    for i, (field, op, default, label, unit) in enumerate(m["criteria"]):
        if op == "btwn":
            lo = _num(values.get(f"c{i}", default[0])) if values.get(f"c{i}") not in (None, "") else default[0]
            hi = _num(values.get(f"c{i}b", default[1])) if values.get(f"c{i}b") not in (None, "") else default[1]
            value = (lo, hi)
        else:
            value = _num(values[f"c{i}"]) if values.get(f"c{i}") not in (None, "") else default
        out.append({"field": field, "op": op, "value": value, "label": label, "unit": unit, "key": f"c{i}"})
    for i, (kind, default, label) in enumerate(m["post"]):
        value = _num(values[f"p{i}"]) if values.get(f"p{i}") not in (None, "") else default
        post.append({"kind": kind, "value": value, "label": label, "key": f"p{i}"})
    return out, post


def build_query(crit, region="mundo", min_cap="1e9"):
    """A consulta do Yahoo: região, capitalização mínima e os critérios do método."""
    if region not in REGIONS:
        raise ScreenError("Região desconhecida.")
    codes = REGIONS[region][1]
    ops = [{"operator": "or", "operands": [{"operator": "eq", "operands": ["region", c]} for c in codes]}
           if len(codes) > 1 else {"operator": "eq", "operands": ["region", codes[0]]},
           {"operator": "gt", "operands": ["intradaymarketcap", _num(min_cap)]}]
    for c in crit:
        if c["op"] == "btwn":
            ops.append({"operator": "btwn", "operands": [c["field"], c["value"][0], c["value"][1]]})
        else:
            ops.append({"operator": c["op"], "operands": [c["field"], c["value"]]})
    return {"operator": "and", "operands": ops}


def primary(q):
    """Fica de fora o que é uma segunda cotação (Frankfurt, OTC, Cboe, a carteira internacional de Londres...)."""
    if (q.get("exchange") or "").upper() in SECONDARY:
        return False
    sym = q.get("symbol") or ""
    if sym.endswith(".L") and len(sym) == 6 and sym[0] == "0":  # 0XXX.L: ações estrangeiras em Londres
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


def _passes(row, post):
    for p in post:
        v = p["value"]
        if p["kind"] == "pe_pb" and not (row["pe"] and row["pb"] and row["pe"] * row["pb"] < v):
            return False
        if p["kind"] == "near_high" and not (row["from_high"] is not None and row["from_high"] >= -v / 100):
            return False
        if p["kind"] == "near_low" and not (row["from_low"] is not None and row["from_low"] <= v / 100):
            return False
        if p["kind"] == "forward_pe" and not (row["fpe"] and 0 < row["fpe"] <= v):
            return False
    return True


def magic_rank(rows):
    """Fórmula Mágica: posição no retorno sobre o capital (a ordem do Yahoo) + posição no earnings yield (1 ÷ P/L).
    A soma menor fica primeiro."""
    by_ey = sorted(range(len(rows)), key=lambda i: -(1 / rows[i]["pe"] if rows[i]["pe"] else 0))
    ey_pos = {i: k for k, i in enumerate(by_ey)}
    for i, r in enumerate(rows):
        r["rank"] = i + 1 + ey_pos[i] + 1
    return sorted(rows, key=lambda r: r["rank"])


def run(method, region="mundo", min_cap="1e9", values=None, fetch=None, size=100):
    """Corre o método e guarda o resultado. `fetch(body)` é o filtro do Yahoo (substituível nos testes)."""
    from . import yahoo
    fetch = fetch or yahoo.screener
    crit, post = criteria(method, values)
    m = METHODS[method]
    body = {"query": build_query(crit, region, min_cap), "sortField": m.get("sort", "intradaymarketcap"),
            "sortType": m.get("order", "DESC"), "size": 250}
    result = fetch(body)
    rows = [_row(q) for q in dedupe([q for q in result.get("quotes") or [] if q.get("symbol") and primary(q)])]
    rows = [r for r in rows if _passes(r, post)][:size]
    if m.get("rank") == "magic":
        rows = magic_rank(rows)
    out = {"method": method, "region": region, "min_cap": min_cap, "values": values or {},
           "total": result.get("total", len(rows)), "rows": rows, "at": datetime.now().isoformat(timespec="minutes")}
    Setting.set("screen:last", json.dumps(out, ensure_ascii=False))
    return out


def last():
    """O último resultado guardado (None se ainda não houve nenhum)."""
    try:
        return json.loads(Setting.get("screen:last") or "null")
    except ValueError:
        return None
