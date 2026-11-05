"""Logótipos dos ativos: descarregados uma vez e guardados na base de dados, para as páginas não fazerem pedidos
a sites externos (que ficariam a saber que ações tens) e funcionarem offline.

Ações: o ícone do site da empresa (o `website` que o Yahoo devolve nos dados da empresa). ETF: o do emitente,
reconhecido pelo nome (iShares, Vanguard, Xtrackers, …). Em Definições → Ativos pode indicar-se o site à mão,
carregar uma imagem ou ficar com as iniciais.
"""
import hashlib
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from flask import g

from ..models import Logo, db

RETRY_DAYS = 30
MAX_BYTES = 200_000
MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml", "image/x-icon",
         "image/vnd.microsoft.icon"}
# emitente do ETF (pelo nome) → site
ISSUERS = [
    (r"\bishares\b", "ishares.com"), (r"\bvanguard\b", "vanguard.com"), (r"\bxtrackers\b", "xtrackers.com"),
    (r"\binvesco\b", "invesco.com"), (r"\bamundi\b|\blyxor\b", "amundi.com"), (r"\bspdr\b", "ssga.com"),
    (r"\bwisdomtree\b", "wisdomtree.eu"), (r"\bvaneck\b", "vaneck.com"), (r"\bhsbc\b", "hsbc.com"),
    (r"\bubs\b", "ubs.com"), (r"\bjpm\b|\bj\.?p\.? ?morgan\b", "jpmorgan.com"),
    (r"\bfranklin\b", "franklintempleton.com"), (r"\bglobal x\b", "globalxetfs.com"), (r"\bark\b", "ark-funds.com"),
    (r"\bbnp\b", "bnpparibas-am.com"), (r"\bdeka\b", "deka.de"), (r"\bl&g\b|legal & general", "lgim.com"),
    (r"\bfidelity\b", "fidelity.com"), (r"\bschwab\b", "schwab.com"), (r"\bfirst trust\b", "ftportfolios.com"),
    (r"\bsparinvest\b", "sparinvest.lu"), (r"\bdimensional\b", "dimensional.com"),
]
ICON_URLS = ["https://www.google.com/s2/favicons?domain={d}&sz=128", "https://icons.duckduckgo.com/ip3/{d}.ico"]


def domain_of(site):
    """«https://www.apple.com/pt/» → «apple.com»; None se não parecer um site."""
    site = (site or "").strip().lower()
    if not site:
        return None
    host = urllib.parse.urlsplit(site if "//" in site else "//" + site).hostname or ""
    host = host.removeprefix("www.")
    return host if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", host) else None


def issuer_domain(name):
    name = (name or "").lower()
    return next((d for pattern, d in ISSUERS if re.search(pattern, name)), None)


def _download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Portfolio Investimentos)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        mime = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        return mime, resp.read(MAX_BYTES + 1)


def fetch_icon(domain, download=None):
    """(tipo, imagem) do ícone do site, ou None (sem ícone, ou o ícone genérico do serviço)."""
    download = download or _download
    for template in ICON_URLS:
        try:
            mime, data = download(template.format(d=urllib.parse.quote(domain)))
        except (urllib.error.URLError, OSError, ValueError):
            continue
        if mime in MIMES and 100 < len(data) <= MAX_BYTES:
            return mime, data
    return None


def needs(ticker, now=None):
    """Falta procurar o logótipo (nunca procurado, ou não encontrado há mais de 30 dias)?"""
    row = db.session.get(Logo, ticker)
    if row is None:
        return True
    return row.source == "none" and row.fetched < (now or datetime.now()) - timedelta(days=RETRY_DAYS)


def _save(ticker, mime, data, source):
    row = db.session.get(Logo, ticker) or Logo(ticker=ticker)
    row.mime, row.data, row.source, row.fetched = mime, data, source, datetime.now()
    db.session.add(row)


def update(inst, website=None, download=None):
    """Procura e guarda o logótipo de um ativo (o site da empresa ou o emitente do ETF). Devolve True se guardou."""
    domain = domain_of(website) or (issuer_domain(inst.instrument_name) if inst.kind == "etf" else None)
    icon = fetch_icon(domain, download) if domain else None
    if icon:
        _save(inst.ticker, icon[0], icon[1], f"site:{domain}"[:80])
    else:
        _save(inst.ticker, None, None, "none")
    return bool(icon)


def set_site(ticker, site, download=None):
    domain = domain_of(site)
    if not domain:
        raise ValueError("Indica um site, por exemplo apple.com.")
    icon = fetch_icon(domain, download)
    if not icon:
        raise ValueError(f"Não encontrei um logótipo para {domain}.")
    _save(ticker, icon[0], icon[1], f"site:{domain}"[:80])
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
