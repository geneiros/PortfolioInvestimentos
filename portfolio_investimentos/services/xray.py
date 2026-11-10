"""Raio-X dos ETF: a exposição real por empresa, país e setor, somando as posições dentro de cada ETF às ações
tidas diretamente, e a sobreposição entre ETF.

A composição de cada ETF vem do ficheiro de posições publicado pelo emitente (CSV ou XLSX, ex.: iShares
«Posições → Descarregar», Vanguard, Xtrackers, Amundi, SPDR, Invesco), carregado à mão ou descarregado de um
endereço de um desses emitentes (só desses sites, para a aplicação não fazer pedidos a endereços quaisquer).
"""
import csv
import io
import json
import re
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime

from ..models import EtfHolding, Instrument, Setting, db
from .insights import COUNTRY_BY_ISIN, countries_of

STALE_DAYS = 120   # composição com mais de 4 meses: aviso
MAX_BYTES = 8_000_000
TOP = 15
ISSUER_HOSTS = ("ishares.com", "blackrock.com", "vanguard.co.uk", "vanguard.com", "vanguardinvestor.co.uk",
                "global.vanguard.com", "fund-docs.vanguard.com", "xtrackers.com", "dws.com", "amundietf.com",
                "amundi.com", "ssga.com", "invesco.com", "invescoassetmanagement.com", "spdrs.com",
                "justetf.com", "hanetf.com", "wisdomtree.eu", "vaneck.com", "lyxoretf.com")

# nomes de países em inglês (iShares, Vanguard…) → português, como no resto da aplicação
COUNTRY_PT = {
    "united states": "EUA", "united states of america": "EUA", "usa": "EUA", "us": "EUA",
    "japan": "Japão", "united kingdom": "Reino Unido", "uk": "Reino Unido", "great britain": "Reino Unido",
    "china": "China", "canada": "Canadá", "france": "França", "germany": "Alemanha", "switzerland": "Suíça",
    "taiwan": "Taiwan", "india": "Índia", "australia": "Austrália", "netherlands": "Países Baixos",
    "korea (south)": "Coreia do Sul", "south korea": "Coreia do Sul", "korea": "Coreia do Sul",
    "sweden": "Suécia", "denmark": "Dinamarca", "spain": "Espanha", "italy": "Itália", "hong kong": "Hong Kong",
    "brazil": "Brasil", "ireland": "Irlanda", "belgium": "Bélgica", "finland": "Finlândia", "norway": "Noruega",
    "singapore": "Singapura", "israel": "Israel", "portugal": "Portugal", "austria": "Áustria",
    "luxembourg": "Luxemburgo", "south africa": "África do Sul", "mexico": "México", "saudi arabia": "Arábia Saudita",
    "indonesia": "Indonésia", "thailand": "Tailândia", "malaysia": "Malásia", "poland": "Polónia",
    "new zealand": "Nova Zelândia", "united arab emirates": "Emirados Árabes Unidos", "chile": "Chile",
    "turkey": "Turquia", "philippines": "Filipinas", "greece": "Grécia", "qatar": "Catar", "kuwait": "Kuwait",
    "european union": "União Europeia", "cash and/or derivatives": "Liquidez",
}
SECTOR_PT = {
    "information technology": "Tecnologia", "technology": "Tecnologia", "financials": "Financeiro",
    "financial services": "Financeiro", "health care": "Saúde", "healthcare": "Saúde",
    "consumer discretionary": "Consumo discricionário", "consumer cyclical": "Consumo discricionário",
    "communication": "Comunicações", "communication services": "Comunicações", "industrials": "Indústria",
    "consumer staples": "Consumo básico", "consumer defensive": "Consumo básico", "energy": "Energia",
    "materials": "Materiais", "basic materials": "Materiais", "utilities": "Utilidades",
    "real estate": "Imobiliário", "cash and/or derivatives": "Liquidez", "cash": "Liquidez",
}

_COLS = {
    "name": ("name", "nome", "holding", "holding name", "security name", "issuer", "emitente", "descrição",
             "description", "security", "constituent", "company"),
    "weight": ("weight (%)", "weight", "peso (%)", "peso", "% of funds", "% of fund", "% of net assets",
               "% net assets", "market value weight", "% weight", "weighting", "% do fundo", "ponderação",
               "% of market value", "weight %"),
    "country": ("location", "country", "país", "pais", "country of risk", "domicile", "localização"),
    "sector": ("sector", "setor", "sector (gics)", "gics sector", "industry"),
    "isin": ("isin", "código isin"),
    "ticker": ("ticker", "symbol", "código", "issuer ticker"),
}


def _cell(v):
    return "" if v is None else str(v).strip().strip("﻿")


def _rows(data, filename=""):
    """As linhas do ficheiro (CSV com «,» ou «;», ou XLSX), como listas de texto."""
    if data[:2] == b"PK":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        return [[_cell(c) for c in row] for row in ws.iter_rows(values_only=True)]
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [[_cell(c) for c in r] for r in csv.reader(io.StringIO(text), dialect=dialect)]


def _number(v):
    v = _cell(v).replace("%", "").replace("\xa0", "").replace(" ", "")
    if not v or v in {"-", "—"}:
        return None
    if "," in v and "." in v:
        v = v.replace(".", "").replace(",", ".") if v.rfind(",") > v.rfind(".") else v.replace(",", "")
    elif "," in v:
        v = v.replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def parse_holdings(data, filename=""):
    """[{name, isin, ticker, weight (fração), country, sector}] do ficheiro de posições de um ETF.

    Procura a linha de cabeçalho (os emitentes põem umas linhas de texto antes) pela coluna do nome e pela do peso;
    os pesos em % passam a fração. Linhas sem peso (totais, notas no fim) ficam de fora."""
    rows = _rows(data, filename)
    for i, row in enumerate(rows[:60]):
        low = [c.lower() for c in row]
        cols = {k: next((j for j, c in enumerate(low) if c in names), None) for k, names in _COLS.items()}
        if cols["name"] is not None and cols["weight"] is not None:
            break
    else:
        raise ValueError("não encontrei as colunas do nome e do peso (ex.: «Name» e «Weight (%)»)")
    out = []
    for row in rows[i + 1:]:
        get = (lambda k: row[cols[k]] if cols[k] is not None and cols[k] < len(row) else "")  # noqa: E731
        name, w = get("name"), _number(get("weight"))
        if not name or w is None or w <= 0:
            continue
        isin = get("isin").upper()
        out.append({"name": name[:200], "isin": isin if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin) else None,
                    "ticker": get("ticker").upper()[:32] or None, "weight": w,
                    "country": _country(get("country"), isin), "sector": _sector(get("sector"))})
    if not out:
        raise ValueError("o ficheiro não tem posições com peso")
    total = sum(r["weight"] for r in out)
    scale = 100.0 if total > 1.5 else 1.0  # pesos em % (somam ~100) ou já em fração (somam ~1)
    for r in out:
        r["weight"] /= scale
    return out


def _country(v, isin=""):
    v = (v or "").strip()
    if v:
        return COUNTRY_PT.get(v.lower(), v)
    return COUNTRY_BY_ISIN.get((isin or "")[:2]) if isin else None


def _sector(v):
    v = (v or "").strip()
    return SECTOR_PT.get(v.lower(), v) if v else None


# ------------------------------------------------------------------ guardar e descarregar
def _meta(ticker):
    try:
        out = json.loads(Setting.get(f"xray:{ticker}") or "{}")
    except ValueError:
        return {}
    return out if isinstance(out, dict) else {}


def save(ticker, rows, source, url=None):
    """Substitui a composição de um ETF e guarda a data, a origem e o endereço (para voltar a descarregar)."""
    inst = db.session.get(Instrument, ticker)
    if inst is None:
        raise ValueError(f"ativo não encontrado: {ticker}")
    EtfHolding.query.filter_by(etf=ticker).delete()
    db.session.add_all(EtfHolding(etf=ticker, **r) for r in rows)
    meta = {"date": date.today().isoformat(), "source": source, "count": len(rows)}
    if url:
        meta["url"] = url
    Setting.set(f"xray:{ticker}", json.dumps(meta))
    db.session.commit()
    return len(rows)


def remove(ticker):
    EtfHolding.query.filter_by(etf=ticker).delete()
    Setting.set(f"xray:{ticker}", None)
    db.session.commit()


def allowed_url(url):
    """Só endereços https de emitentes de ETF conhecidos (evita pedidos a endereços internos ou quaisquer)."""
    try:
        u = urllib.parse.urlsplit((url or "").strip())
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in ISSUER_HOSTS)


def download(url, fetch=None):
    if not allowed_url(url):
        raise ValueError("indica um endereço https do site do emitente do ETF (iShares, Vanguard, Xtrackers, "
                         "Amundi, SPDR, Invesco, …)")
    if fetch is None:
        req = urllib.request.Request(url.strip(), headers={"User-Agent": "Mozilla/5.0 (Portfolio Investimentos)"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                if not allowed_url(resp.geturl()):  # um redirecionamento para fora dos emitentes
                    raise ValueError("o endereço redireciona para fora do site do emitente")
                data = resp.read(MAX_BYTES + 1)
        except OSError as exc:
            raise ValueError(f"não foi possível descarregar: {getattr(exc, 'reason', exc)}") from exc
    else:
        data = fetch(url)
    if len(data) > MAX_BYTES:
        raise ValueError("o ficheiro é grande demais")
    return data


def refresh_urls(fetch=None):
    """Volta a descarregar as composições guardadas com endereço. Devolve {ticker: erro ou nº de posições}."""
    out = {}
    for row in Setting.query.filter(Setting.key.like("xray:%")).all():
        ticker = row.key.split(":", 1)[1]
        url = _meta(ticker).get("url")
        if not url:
            continue
        try:
            out[ticker] = save(ticker, parse_holdings(download(url, fetch)), "url", url)
        except ValueError as exc:
            out[ticker] = str(exc)
    return out


# ------------------------------------------------------------------ cálculo
def _norm(name):
    """Nome para juntar a mesma empresa vinda de fontes diferentes: sem acentos, parênteses e forma jurídica."""
    n = unicodedata.normalize("NFKD", re.sub(r"\([^)]*\)", " ", name or "")).encode("ascii", "ignore").decode()
    n = re.sub(r"[^A-Z0-9 ]", " ", n.upper())
    n = re.sub(r"\b(INC|CORP|CORPORATION|CO|LTD|PLC|SA|NV|AG|SE|ASA|AB|OYJ|SPA|HOLDINGS?|GROUP|CLASS [A-Z]|"
               r"CL [A-Z]|THE|COMMON|STOCK|ORD|REG|SHS|ADR)\b", " ", n)
    return " ".join(n.split())


def status(p):
    """Os ETF das posições abertas, com a composição guardada (nº de posições, data, origem) ou a falta dela."""
    etfs = [pos for pos in p.open_positions if pos.asset.kind == "etf"]
    counts = dict(db.session.query(EtfHolding.etf, db.func.count(EtfHolding.id))
                  .filter(EtfHolding.etf.in_([e.asset.ticker for e in etfs] or [""])).group_by(EtfHolding.etf))
    out = []
    for pos in sorted(etfs, key=lambda x: -x.value_eur):
        meta = _meta(pos.asset.ticker)
        when = meta.get("date")
        age = (date.today() - datetime.fromisoformat(when).date()).days if when else None
        out.append({"ticker": pos.asset.ticker, "name": pos.asset.name or pos.asset.ticker,
                    "value": pos.value_eur, "count": counts.get(pos.asset.ticker, 0), "date": when,
                    "stale": age is not None and age > STALE_DAYS, "source": meta.get("source"), "url": meta.get("url")})
    return out


def xray(p, top=TOP):
    """A exposição real da carteira (posições abertas): por empresa (as `top` maiores), país e setor, e a
    sobreposição entre cada par de ETF com composição. None sem ETF nas posições abertas."""
    positions = [pos for pos in p.open_positions if pos.value_eur > 0]
    etf_tickers = [pos.asset.ticker for pos in positions if pos.asset.kind == "etf"]
    if not etf_tickers:
        return None
    holdings = defaultdict(list)
    for h in EtfHolding.query.filter(EtfHolding.etf.in_(etf_tickers)).all():
        holdings[h.etf].append(h)
    country_of = countries_of({pos.asset.ticker: pos.asset.currency for pos in positions})
    isin_of = dict(db.session.query(Instrument.ticker, Instrument.isin)
                   .filter(Instrument.ticker.in_([pos.asset.ticker for pos in positions])))
    total = sum(pos.value_eur for pos in positions)

    keys = {}  # ISIN / ticker / nome normalizado → chave da empresa
    companies = {}

    def key_for(name, isin=None, ticker=None):
        for k in (f"isin:{isin}" if isin else None, f"tk:{ticker}" if ticker else None, f"nm:{_norm(name)}"):
            if k and k in keys:
                return keys[k]
        key = f"isin:{isin}" if isin else f"nm:{_norm(name)}"
        for k in (f"isin:{isin}" if isin else None, f"tk:{ticker}" if ticker else None, f"nm:{_norm(name)}"):
            if k:
                keys.setdefault(k, key)
        return key

    def add(key, name, value, via):
        c = companies.setdefault(key, {"name": name, "value": 0.0, "via": defaultdict(float)})
        c["value"] += value
        c["via"][via] += value

    by_country, by_sector = defaultdict(float), defaultdict(float)
    covered = 0.0
    missing = []
    # primeiro as ações diretas, para os nomes das empresas serem os da carteira
    for pos in sorted(positions, key=lambda x: x.asset.kind == "etf"):
        a, v = pos.asset, pos.value_eur
        if a.kind != "etf":
            add(key_for(a.name or a.ticker, isin_of.get(a.ticker), a.ticker), a.name or a.ticker, v, "direto")
            by_country[country_of.get(a.ticker) or "Outros"] += v
            by_sector[a.sector or "Outros"] += v
            covered += v
            continue
        rows = holdings.get(a.ticker)
        if not rows:
            missing.append(a.ticker)
            by_country["ETF sem composição"] += v
            by_sector["ETF sem composição"] += v
            continue
        wsum = sum(h.weight for h in rows)
        for h in rows:
            hv = v * h.weight
            add(key_for(h.name, h.isin, h.ticker), h.name, hv, a.ticker)
            by_country[h.country or "Outros"] += hv
            by_sector[h.sector or "Outros"] += hv
        if wsum < 0.999:  # o resto do ETF (posições pequenas que o ficheiro não traz, liquidez)
            by_country["Outros"] += v * (1 - wsum)
            by_sector["Outros"] += v * (1 - wsum)
        covered += v

    def ranked(groups):
        rows = sorted(groups.items(), key=lambda kv: -kv[1])
        return [{"name": k, "value": val, "pct": val / total if total else 0.0} for k, val in rows if val > 0.005]

    comps = sorted(companies.values(), key=lambda c: -c["value"])
    top_rows = [{"name": c["name"], "value": c["value"], "pct": c["value"] / total if total else 0.0,
                 "via": sorted(c["via"], key=lambda k: -c["via"][k])} for c in comps[:top]]

    overlap = []
    with_rows = [t for t in etf_tickers if holdings.get(t)]
    weights = {t: defaultdict(float) for t in with_rows}
    for t in with_rows:
        for h in holdings[t]:
            weights[t][key_for(h.name, h.isin, h.ticker)] += h.weight
    for i, a in enumerate(with_rows):
        for b in with_rows[i + 1:]:
            common = set(weights[a]) & set(weights[b])
            share = sum(min(weights[a][k], weights[b][k]) for k in common)
            if share > 0.001:
                overlap.append({"a": a, "b": b, "share": share, "common": len(common)})
    overlap.sort(key=lambda x: -x["share"])
    return {"companies": top_rows, "countries": ranked(by_country), "sectors": ranked(by_sector),
            "overlap": overlap, "coverage": covered / total if total else 0.0, "missing": missing,
            "total": total, "count": len(companies)}
