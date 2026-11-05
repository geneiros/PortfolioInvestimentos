"""Logótipos dos ativos: descarregados uma vez e guardados na base de dados, para as páginas não fazerem pedidos
a sites externos (que ficariam a saber que ações tens) e funcionarem offline.

Ações: o ícone do site da empresa: o `website` que o Yahoo devolve nos dados da empresa ou, se não vier (o pedido
falha muitas vezes, ex.: no PythonAnywhere), o site oficial no Wikidata, encontrado pelo ISIN. ETF: o do emitente,
reconhecido pelo nome (o da corretora, o nome longo do Yahoo ou o do Wikidata): iShares, Vanguard, Xtrackers, … Em Definições → Ativos pode indicar-se o site à mão,
carregar uma imagem ou ficar com as iniciais.
"""
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from flask import g

from ..models import Logo, db

RETRY_DAYS = 7
NOT_FOUND = "none4"  # procurado e não encontrado (com as fontes desta versão)
LEGACY_NOT_FOUND = ("none", "none2", "none3")  # de versões anteriores, com menos fontes: procuram-se já
# outros sites do mesmo emitente, para quando o serviço de ícones não tem o do principal
ALT_DOMAINS = {"xtrackers.com": ["dws.com", "etf.dws.com"], "ssga.com": ["statestreet.com"],
               "amundi.com": ["amundietf.com"], "ishares.com": ["blackrock.com"], "invesco.com": ["invescoetf.com"]}
_blocked = set()  # servidores de ícones que não respondem a partir daqui (ex.: fora da lista de sites do PythonAnywhere)
WIKIDATA = "https://www.wikidata.org/w/api.php"
UA = {"User-Agent": "PortfolioInvestimentos/1.0 (https://github.com/geneiros/PortfolioInvestimentos)"}


class Unavailable(Exception):
    """Uma fonte não respondeu (rede, limite de pedidos): tenta-se outra vez na próxima atualização."""
MAX_BYTES = 200_000
MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml", "image/x-icon",
         "image/vnd.microsoft.icon"}
# emitente do ETF (pelo nome) → site
ISSUERS = [
    (r"\bishares\b|\bblackrock\b", "ishares.com"), (r"\bvanguard\b", "vanguard.com"),
    (r"\bxtrackers\b|\bdws\b|\bdb x-trackers\b", "xtrackers.com"),
    (r"\binvesco\b", "invesco.com"), (r"\bamundi\b|\blyxor\b", "amundi.com"), (r"\bspdr\b", "ssga.com"),
    (r"\bwisdomtree\b", "wisdomtree.eu"), (r"\bvaneck\b", "vaneck.com"), (r"\bhsbc\b", "hsbc.com"),
    (r"\bubs\b", "ubs.com"), (r"\bjpm\b|\bj\.?p\.? ?morgan\b", "jpmorgan.com"),
    (r"\bfranklin\b", "franklintempleton.com"), (r"\bglobal x\b", "globalxetfs.com"), (r"\bark\b", "ark-funds.com"),
    (r"\bbnp\b", "bnpparibas-am.com"), (r"\bdeka\b", "deka.de"), (r"\bl&g\b|legal & general", "lgim.com"),
    (r"\bfidelity\b", "fidelity.com"), (r"\bschwab\b", "schwab.com"), (r"\bfirst trust\b", "ftportfolios.com"),
    (r"\bsparinvest\b", "sparinvest.lu"), (r"\bdimensional\b", "dimensional.com"),
]
# serviços de ícones, por ordem: (nome para o resumo, endereço). O Google responde 404 quando não tem o ícone no
# tamanho pedido (por isso pedem-se tamanhos menores) e redireciona para o gstatic, que também se pede diretamente;
# por fim, o ícone do próprio site
ICON_URLS = [
    ("google", "https://www.google.com/s2/favicons?domain={d}&sz=128"),
    ("google64", "https://www.google.com/s2/favicons?domain={d}&sz=64"),
    ("gstatic", "https://t1.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=https://{d}&size=128"),
    ("duckduckgo", "https://icons.duckduckgo.com/ip3/{d}.ico"),
    ("site", "https://{d}/apple-touch-icon.png"),
    ("site-ico", "https://{d}/favicon.ico"),
]


def domain_of(site):
    """«https://www.apple.com/pt/» → «apple.com»; None se não parecer um site."""
    site = (site or "").strip().lower()
    if not site:
        return None
    host = urllib.parse.urlsplit(site if "//" in site else "//" + site).hostname or ""
    host = host.removeprefix("www.")
    return host if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", host) else None


def reset_blocked():
    """Esquece os serviços bloqueados (no início de cada atualização e ao procurar à mão)."""
    _blocked.clear()


def candidates(domain):
    """O domínio e o principal (ir.finvgroup.com → finvgroup.com; investor.x.co.uk → x.co.uk)."""
    parts = domain.split(".")
    keep = 3 if len(parts) >= 3 and len(parts[-2]) <= 3 and len(parts[-1]) == 2 else 2  # co.uk, com.br
    main = ".".join(parts[-keep:])
    return [domain] if main == domain else [domain, main]


def variants(domain):
    """Todos os domínios a tentar, por ordem: o próprio, o principal, com «www.» e os outros sites do emitente."""
    out = []
    for d in candidates(domain):
        out += [d, f"www.{d}"] + ALT_DOMAINS.get(d, [])
    return list(dict.fromkeys(out))


def issuer_domain(name):
    name = (name or "").lower()
    return next((d for pattern, d in ISSUERS if re.search(pattern, name)), None)


def _download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Portfolio Investimentos)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        mime = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        return mime, resp.read(MAX_BYTES + 1)


def _get_json(url, params):
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read(2_000_000).decode())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise Unavailable(str(getattr(exc, "reason", exc))[:100]) from exc


def fetch_icon(domain, download=None, reasons=None):
    """(tipo, imagem) do ícone do site, ou None (nenhum serviço tem ícone). Levanta Unavailable se nenhum serviço
    respondeu (rede, site não permitido). Em `reasons` (lista) fica a resposta de cada serviço, para o resumo."""
    download = download or _download
    reasons = [] if reasons is None else reasons
    failures = 0
    for name, template in ICON_URLS:
        url = template.format(d=urllib.parse.quote(domain))
        host = urllib.parse.urlsplit(url).hostname
        if host in _blocked:  # o servidor do serviço já falhou por rede nesta atualização: não se perde tempo
            failures += 1
            continue
        try:
            mime, data = download(url)
        except urllib.error.HTTPError as exc:  # 404 e afins: o serviço respondeu que não tem ícone
            reasons.append(f"{name} {exc.code}")
            continue
        except (urllib.error.URLError, OSError, ValueError) as exc:
            failures += 1
            if not name.startswith("site"):  # o site de cada empresa é outro servidor: não conta para os outros
                _blocked.add(host)
            reasons.append(f"{name}: {str(getattr(exc, 'reason', exc))[:60]}")
            continue
        if mime in MIMES and 100 < len(data) <= MAX_BYTES:
            return mime, data
        reasons.append(f"{name}: {mime or 'sem tipo'} {len(data)} B")
    if failures == len(ICON_URLS):
        raise Unavailable("serviços de ícones sem resposta: " + ("; ".join(reasons) or "bloqueados neste servidor"))
    return None


def wikidata(isin, get=None):
    """(site oficial, nome) da entidade com este ISIN no Wikidata; (None, None) se não houver."""
    get = get or _get_json
    if not isin or not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin):
        return None, None
    found = get(WIKIDATA, {"action": "query", "list": "search", "srsearch": f"haswbstatement:P946={isin}",
                           "srlimit": 1, "format": "json"})
    hits = ((found or {}).get("query") or {}).get("search") or []
    if not hits:
        return None, None
    qid = hits[0].get("title")
    ent = get(WIKIDATA, {"action": "wbgetentities", "ids": qid, "props": "claims|labels", "languages": "en",
                         "format": "json"})
    e = ((ent or {}).get("entities") or {}).get(qid) or {}
    sites = [c.get("mainsnak", {}).get("datavalue", {}).get("value") for c in (e.get("claims") or {}).get("P856", [])]
    label = ((e.get("labels") or {}).get("en") or {}).get("value")
    return next((x for x in sites if isinstance(x, str)), None), label


def yahoo_chart_name(symbol):
    """Nome longo do Yahoo nas cotações (o mesmo pedido das cotações, que raramente é limitado), ex.:
    «Xtrackers II EUR Overnight Rate Swap UCITS ETF 1C»."""
    from datetime import date as _date
    from . import yahoo
    try:
        t = yahoo.Ticker(symbol)
        t.history(start=_date.today() - timedelta(days=7))
    except Exception as exc:
        raise Unavailable(str(exc)[:100]) from exc
    meta = t.history_metadata or {}
    return meta.get("longName") or meta.get("shortName")


def yahoo_website(symbol):
    """`website` dos dados da empresa pelo acesso direto ao Yahoo (quando o yfinance veio sem ele)."""
    from . import yahoo
    try:
        return (yahoo.Ticker(symbol).info or {}).get("website")
    except Exception as exc:
        raise Unavailable(str(exc)[:100]) from exc


def ticker_long_name(t):
    """Nome longo nas cotações pelo cliente da atualização (o yfinance, que o Yahoo não limita como os pedidos
    diretos), ex.: «Xtrackers II EUR Overnight Rate Swap UCITS ETF 1C»."""
    from datetime import date as _date
    if t is None:
        return None
    meta = getattr(t, "history_metadata", None) or {}
    if not (meta.get("longName") or meta.get("shortName")):
        try:
            t.history(start=_date.today() - timedelta(days=7), auto_adjust=False)
        except TypeError:  # o acesso direto (yahoo.py) não tem auto_adjust
            t.history(start=_date.today() - timedelta(days=7))
        except Exception as exc:
            raise Unavailable(str(exc)[:100]) from exc
        meta = getattr(t, "history_metadata", None) or {}
    return meta.get("longName") or meta.get("shortName")


def resolve(inst, info=None, get=None, ticker=None):
    """(domínio, origem, erros): o site para o logótipo e de onde veio; `erros` são as fontes que não responderam.
    `ticker`: o objeto do cliente da atualização (yfinance ou yahoo.py) para este ativo."""
    errors = []
    symbol = inst.data_symbol or inst.ticker

    def attempt(fn, *args):
        try:
            return fn(*args)
        except Unavailable as exc:
            errors.append(f"{fn.__name__}: {exc}")
            return None
    if inst.kind == "etf":
        d = issuer_domain(inst.instrument_name)
        if d:
            return d, "nome", errors
        d = issuer_domain(attempt(ticker_long_name, ticker)) if ticker is not None else None
        if d:
            return d, "Yahoo", errors
        if ticker is None:  # fora da atualização: o acesso direto
            d = issuer_domain(attempt(yahoo_chart_name, symbol))
            if d:
                return d, "Yahoo", errors
        site_label = attempt(wikidata, inst.isin, get) or (None, None)
        d = issuer_domain(site_label[1])
        return (d, "Wikidata", errors) if d else (None, None, errors)
    d = domain_of((info or {}).get("website"))
    if d:
        return d, "Yahoo", errors
    site_label = attempt(wikidata, inst.isin, get) or (None, None)
    d = domain_of(site_label[0])
    if d:
        return d, "Wikidata", errors
    d = domain_of(attempt(yahoo_website, symbol))
    return (d, "Yahoo", errors) if d else (None, None, errors)


def needs(ticker, now=None):
    """Falta procurar o logótipo (nunca procurado, ou não encontrado há mais de 7 dias)?"""
    row = db.session.get(Logo, ticker)
    if row is None or row.source in LEGACY_NOT_FOUND:
        return True
    return row.source == NOT_FOUND and row.fetched < (now or datetime.now()) - timedelta(days=RETRY_DAYS)


def _save(ticker, mime, data, source):
    row = db.session.get(Logo, ticker) or Logo(ticker=ticker)
    row.mime, row.data, row.source, row.fetched = mime, data, source, datetime.now()
    db.session.add(row)


def update(inst, info=None, download=None, get=None, ticker=None):
    """Procura e guarda o logótipo de um ativo. Devolve a linha para o resumo da atualização.

    Uma fonte que não respondeu não conta como «não há»: não se grava nada e tenta-se na próxima atualização.
    """
    domain, origin, errors = resolve(inst, info, get, ticker)
    if not domain:
        if errors:
            return "erro (" + "; ".join(errors)[:200] + "); tenta-se na próxima atualização"
        _save(inst.ticker, None, None, NOT_FOUND)
        return "sem site encontrado (indica-o em Definições → Ativos)"
    reasons = []
    try:
        icon, used = _icon_for(domain, download, reasons)
    except Unavailable as exc:
        return f"{domain}: erro ({exc}); tenta-se na próxima atualização"
    if not icon:
        _save(inst.ticker, None, None, NOT_FOUND)
        return f"{domain}: sem ícone ({' | '.join(reasons)[:300]}); indica outro site em Definições → Ativos"
    _save(inst.ticker, icon[0], icon[1], f"site:{used}"[:80])
    return f"{used} ({origin})"


def _icon_for(domain, download=None, reasons=None):
    """(ícone, domínio usado): o do domínio ou, sem ele, o do domínio principal."""
    for d in variants(domain):
        tried = []
        icon = fetch_icon(d, download, tried)
        if reasons is not None:
            reasons.append(f"{d}: " + ", ".join(tried))
        if icon:
            return icon, d
    return None, domain


def set_site(ticker, site, download=None):
    reset_blocked()
    domain = domain_of(site)
    if not domain:
        raise ValueError("Indica um site, por exemplo apple.com.")
    try:
        icon, used = _icon_for(domain, download)
    except Unavailable as exc:
        raise ValueError(f"Não consegui contactar o serviço de ícones ({exc}).") from exc
    if not icon:
        raise ValueError(f"Não encontrei um logótipo para {domain}.")
    _save(ticker, icon[0], icon[1], f"site:{used}"[:80])
    db.session.commit()


def set_image(ticker, mime, data):
    if mime not in MIMES or not data or len(data) > MAX_BYTES:
        raise ValueError("Usa uma imagem PNG, JPEG, GIF, WEBP, SVG ou ICO até 200 KB.")
    _save(ticker, mime, data, "manual")
    db.session.commit()


def remove(ticker):
    """Fica com as iniciais (e deixa de se procurar automaticamente)."""
    _save(ticker, None, None, "off")
    db.session.commit()


def reset(ticker):
    """Volta a procurar automaticamente na próxima atualização."""
    row = db.session.get(Logo, ticker)
    if row:
        db.session.delete(row)
        db.session.commit()


def versions():
    """ticker → versão do logótipo (para o endereço da imagem), lido uma vez por pedido."""
    if "pm_logos" not in g:
        rows = db.session.query(Logo.ticker, Logo.fetched).filter(Logo.data.isnot(None)).all()
        g.pm_logos = {t: int(f.timestamp()) if f else 0 for t, f in rows}
    return g.pm_logos


def url(ticker):
    """Endereço do logótipo guardado ou None (a página mostra as iniciais)."""
    try:
        v = versions().get(ticker)
    except Exception:  # sem base de dados ou fora de um pedido: as iniciais
        return None
    return f"/logo/{urllib.parse.quote(ticker, safe='')}?v={v}" if v is not None else None


def etag(row):
    return hashlib.sha1(row.data).hexdigest()[:16]
