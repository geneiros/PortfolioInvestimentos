"""Logótipos dos ativos, escolhidos à mão em Definições → Ativos (clicar no logótipo ou nas iniciais): uma imagem
carregada, ou o ícone de um site indicado (procurado nos serviços de ícones nesse momento). Ficam guardados na base
de dados, por isso as páginas não fazem pedidos a sites externos (que ficariam a saber que ações tens) e funcionam
offline. Sem logótipo aparecem as iniciais.
"""
import hashlib
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from flask import g

from ..models import Logo, db

_blocked = set()  # servidores de ícones que não respondem a partir daqui (ex.: fora da lista do PythonAnywhere)


class Unavailable(Exception):
    """Nenhum serviço de ícones respondeu (rede, site não permitido)."""


MAX_BYTES = 200_000
MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml", "image/x-icon",
         "image/vnd.microsoft.icon"}
# serviços de ícones, por ordem: (nome para o resumo, endereço). O Google responde 404 quando não tem o ícone no
# tamanho pedido (por isso pedem-se tamanhos menores) e redireciona para o gstatic, que também se pede diretamente;
# por fim, o ícone do próprio site
ICON_URLS = [
    ("google", "https://www.google.com/s2/favicons?domain={d}&sz=128"),
    ("google64", "https://www.google.com/s2/favicons?domain={d}&sz=64"),
    ("gstatic", "https://t1.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=https://{d}&size=128"),
    ("duckduckgo", "https://icons.duckduckgo.com/ip3/{d}.ico"),
    ("duckduckgo2", "https://icons.duckduckgo.com/ip2/{d}.ico"),  # às vezes vazio num e com ícone no outro
    ("duckduckgo-ext", "https://external-content.duckduckgo.com/ip3/{d}.ico"),
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
    """Esquece os serviços bloqueados (a cada procura)."""
    _blocked.clear()


def candidates(domain):
    """O domínio e o principal (ir.finvgroup.com → finvgroup.com; investor.x.co.uk → x.co.uk)."""
    parts = domain.split(".")
    keep = 3 if len(parts) >= 3 and len(parts[-2]) <= 3 and len(parts[-1]) == 2 else 2  # co.uk, com.br
    main = ".".join(parts[-keep:])
    return [domain] if main == domain else [domain, main]


def variants(domain):
    """Todos os domínios a tentar, por ordem: o próprio e o principal, cada um também com «www.»."""
    out = []
    for d in candidates(domain):
        out += [d, f"www.{d}"]
    return list(dict.fromkeys(out))


def _download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Portfolio Investimentos)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        mime = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        return mime, resp.read(MAX_BYTES + 1)


def fetch_icon(domain, download=None, reasons=None):
    """(tipo, imagem) do ícone do site, ou None (nenhum serviço tem ícone). Levanta Unavailable se nenhum serviço
    respondeu (rede, site não permitido). Em `reasons` (lista) fica a resposta de cada serviço."""
    download = download or _download
    reasons = [] if reasons is None else reasons
    failures = 0
    for name, template in ICON_URLS:
        url = template.format(d=urllib.parse.quote(domain))
        host = urllib.parse.urlsplit(url).hostname
        if host in _blocked:  # o servidor do serviço já falhou por rede nesta procura: não se perde tempo
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


def _save(ticker, mime, data, source):
    row = db.session.get(Logo, ticker) or Logo(ticker=ticker)
    row.mime, row.data, row.source, row.fetched = mime, data, source, datetime.now()
    db.session.add(row)


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
    reasons = []
    try:
        icon, used = _icon_for(domain, download, reasons)
    except Unavailable as exc:
        raise ValueError(f"Não consegui contactar os serviços de ícones ({str(exc)[:200]}). Carrega uma imagem.") from exc
    if not icon:
        raise ValueError(f"Não encontrei um logótipo para {domain}. Carrega uma imagem.")
    _save(ticker, icon[0], icon[1], f"site:{used}"[:80])
    db.session.commit()


def set_image(ticker, mime, data):
    if mime not in MIMES or not data or len(data) > MAX_BYTES:
        raise ValueError("Usa uma imagem PNG, JPEG, GIF, WEBP, SVG ou ICO até 200 KB.")
    _save(ticker, mime, data, "manual")
    db.session.commit()


def remove(ticker):
    """Tira o logótipo: ficam as iniciais."""
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
