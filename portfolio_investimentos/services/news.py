"""Notícias dos ativos da carteira e do mercado, de três fontes:

- **Finnhub** (finnhub.io, com a chave em Definições ou na variável FINNHUB_API_KEY): no plano gratuito só tem
  notícias de empresas cotadas nos EUA e no Canadá (o símbolo encontra-se pelo ISIN);
- **Yahoo Finance**, pelo yfinance que já se usa para as cotações (sem chave; também ações europeias e alguns ETF);
- **Google Notícias**, por RSS, pesquisando pelo nome do ativo (sem chave; notícias em português e em inglês).

Obtêm-se ao abrir a página Notícias, guardam-se na base de dados e reaproveitam-se durante 1 hora («Atualizar
notícias» força um pedido novo). Cada pedido tem um limite de tempo e a página no total também: o que ficar por
pedir pede-se na visita seguinte. A chave do Finnhub vai num cabeçalho, nunca no endereço.
"""
import email.utils
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from ..models import Instrument, NewsItem, Setting, db

API = "https://finnhub.io/api/v1"
GOOGLE_RSS = "https://news.google.com/rss/search"
PROVIDERS = {"finnhub": "Finnhub", "yahoo": "Yahoo Finance", "google": "Google Notícias"}
TTL = timedelta(hours=1)
DAYS = 7          # notícias dos últimos 7 dias
KEEP_DAYS = 30    # as mais antigas apagam-se
LIMIT = 150       # notícias mostradas por separador
BUDGET = 25.0     # segundos de pedidos por visita à página
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{10,80}$")
UA = "Mozilla/5.0 (PortfolioInvestimentos)"


class NewsError(Exception):
    """Falha ao obter notícias, com uma mensagem legível."""


# ------------------------------------------------------------------ configuração
def api_key():
    return os.environ.get("FINNHUB_API_KEY") or Setting.get("finnhub_key") or None


def key_from_env():
    return bool(os.environ.get("FINNHUB_API_KEY"))


def enabled():
    """Fontes ligadas (Definições); por omissão todas. O Finnhub só conta com a chave."""
    raw = Setting.get("news_sources")
    chosen = [p for p in (raw.split(",") if raw is not None else PROVIDERS) if p in PROVIDERS]
    return [p for p in chosen if p != "finnhub" or api_key()]


def _json_setting(name):
    try:
        out = json.loads(Setting.get(name) or "{}")
    except ValueError:
        return {}
    return out if isinstance(out, dict) else {}


# ------------------------------------------------------------------ pedidos
def _http(url, headers=None, limit=5_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return resp.read(limit)


def _get(path, params, key=None):
    """Pedido à API do Finnhub (JSON)."""
    key = key or api_key()
    if not key:
        raise NewsError("falta a chave do Finnhub (Definições → Dados de mercado)")
    try:
        return json.loads(_http(f"{API}{path}?{urllib.parse.urlencode(params)}", {"X-Finnhub-Token": key}).decode())
    except urllib.error.HTTPError as exc:
        msg = {401: "chave do Finnhub inválida", 403: "o plano do Finnhub não inclui estes dados",
               429: "o Finnhub limitou os pedidos (60 por minuto); tenta daqui a um minuto"}.get(exc.code)
        raise NewsError(msg or f"o Finnhub respondeu HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise NewsError(f"sem ligação ao Finnhub ({str(getattr(exc, 'reason', exc))[:100]})") from exc


def symbol_for(inst, get=None):
    """Símbolo do ativo no Finnhub (cotação dos EUA ou do Canadá), ou None. Fica guardado para não procurar de novo."""
    if inst.kind in ("etf", "index"):
        return None
    cache = _json_setting("finnhub_symbols")
    if inst.ticker in cache:
        return cache[inst.ticker] or None
    sym = None
    data_symbol = (inst.data_symbol or inst.ticker or "").upper()
    if data_symbol and "." not in data_symbol and re.fullmatch(r"[A-Z0-9-]{1,10}", data_symbol):
        sym = data_symbol  # já é o da bolsa americana (ex.: FINV, CLDI)
    elif inst.isin:
        found = (get or _get)("/search", {"q": inst.isin}).get("result") or []
        us = [r.get("symbol") for r in found if r.get("symbol") and "." not in r["symbol"]
              and (r.get("type") or "").lower() in ("common stock", "adr", "")]
        sym = us[0] if us else None
    cache[inst.ticker] = sym or ""
    Setting.set("finnhub_symbols", json.dumps(cache))
    return sym


def _finnhub(inst, now, get=None):
    if inst is None:
        return [_row(r.get("headline"), r.get("url"), r.get("source"), r.get("datetime"), r.get("summary"), r.get("id"))
                for r in (get or _get)("/news", {"category": "general"}) or []]
    sym = symbol_for(inst, get)
    if not sym:
        return []
    rows = (get or _get)("/company-news", {"symbol": sym, "from": (now.date() - timedelta(days=DAYS)).isoformat(),
                                           "to": now.date().isoformat()}) or []
    return [_row(r.get("headline"), r.get("url"), r.get("source"), r.get("datetime"), r.get("summary"), r.get("id"))
            for r in rows]


def _yahoo(inst, now, client=None):
    """Notícias do Yahoo Finance pelo yfinance (os dois formatos: o antigo e o de 2025)."""
    if client is None:
        try:
            import yfinance as client
        except ImportError:
            return []  # sem yfinance (ex.: Android): fica o Google Notícias
    symbol = "^GSPC" if inst is None else (inst.data_symbol or inst.ticker)
    try:
        raw = client.Ticker(symbol).news or []
    except Exception as exc:
        raise NewsError(f"Yahoo Finance: {str(exc)[:100]}") from exc
    out = []
    for r in raw:
        c = r.get("content") if isinstance(r.get("content"), dict) else None
        if c:
            url = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
            ts = _parse_iso(c.get("pubDate"))
            out.append(_row(c.get("title"), url, (c.get("provider") or {}).get("displayName"), ts, c.get("summary")))
        else:
            out.append(_row(r.get("title"), r.get("link"), r.get("publisher"), r.get("providerPublishTime")))
    return out


def _google(inst, now, fetch=None):
    """Google Notícias (RSS) pelo nome do ativo, dos últimos 7 dias; o mercado pelos termos de bolsa."""
    if inst is None:
        query = "bolsa OR mercados OR ações"
    else:
        name = re.sub(r"\b(Inc|Corp|Corporation|SA|S\.A\.|NV|N\.V\.|plc|AG|SE|Ltd|Holdings?|Group|UCITS ETF.*)\b\.?",
                      "", inst.instrument_name or "", flags=re.I).strip(" ,.-")
        query = f'"{name}"' if len(name) >= 3 else (inst.ticker or "")
    params = {"q": f"{query} when:{DAYS}d", "hl": "pt-PT", "gl": "PT", "ceid": "PT:pt-150"}
    try:
        xml = (fetch or _http)(f"{GOOGLE_RSS}?{urllib.parse.urlencode(params)}", limit=2_000_000)
        root = ET.fromstring(xml)
    except (urllib.error.URLError, OSError, ET.ParseError, ValueError) as exc:
        raise NewsError(f"Google Notícias: {str(getattr(exc, 'reason', exc))[:100]}") from exc
    out = []
    for it in list(root.iter("item"))[:40]:
        title = (it.findtext("title") or "").strip()
        source = (it.findtext("source") or "").strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        try:
            ts = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "").timestamp()
        except (TypeError, ValueError):
            ts = None
        out.append(_row(title, it.findtext("link"), source, ts))
    return out


def _parse_iso(text):
    try:
        return datetime.fromisoformat((text or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _row(headline, url, source, ts, summary="", ident=None):
    return {"headline": headline, "url": url, "source": source, "datetime": ts, "summary": summary, "id": ident}


# ------------------------------------------------------------------ guardar e mostrar
def _norm(title):
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()[:120]


def _store(ticker, provider, rows):
    """Guarda as notícias novas (sem repetir o endereço nem o mesmo título de outra fonte)."""
    have = db.session.query(NewsItem.url, NewsItem.headline).filter(NewsItem.ticker == ticker).all()
    urls, titles = {u for u, _ in have}, {_norm(h) for _, h in have}
    n = 0
    for r in rows or []:
        url, headline, ts = (r.get("url") or "").strip(), (r.get("headline") or "").strip(), r.get("datetime")
        if not url.startswith(("http://", "https://")) or not headline or not ts:
            continue
        key = _norm(headline)
        if url in urls or key in titles:
            continue
        urls.add(url)
        titles.add(key)
        try:
            published = datetime.fromtimestamp(float(ts))
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        db.session.add(NewsItem(ticker=ticker, headline=headline[:500], summary=(r.get("summary") or "")[:2000],
                                source=(r.get("source") or "")[:120], url=url[:1000], published=published,
                                finnhub_id=r.get("id") if isinstance(r.get("id"), int) else None, provider=provider))
        n += 1
    return n


def refresh(tickers, force=False, now=None, fetchers=None, budget=BUDGET):
    """Pede as notícias (das fontes ligadas) dos ativos e do mercado com mais de 1 hora. Devolve {"ativo · fonte": erro}.

    `fetchers`: {fonte: função(inst ou None, agora)} para os testes."""
    now = now or datetime.now()
    fetchers = fetchers or {"finnhub": _finnhub, "yahoo": _yahoo, "google": _google}
    fetched = _json_setting("news_fetched")
    errors, t0 = {}, time.monotonic()
    blocked = set()  # fontes que falharam por chave ou limite: não adianta insistir nesta visita
    sources = [p for p in enabled() if p in fetchers]

    def due(key):
        try:
            return force or now - datetime.fromisoformat(fetched[key]) > TTL
        except (KeyError, ValueError):
            return True
    for ticker in [""] + list(tickers):
        inst = None if ticker == "" else db.session.get(Instrument, ticker)
        if (ticker and inst is None) or not due(ticker):
            continue
        if time.monotonic() - t0 > budget:  # o resto fica para a visita seguinte
            break
        for provider in sources:
            if provider in blocked:
                continue
            try:
                _store(ticker, provider, fetchers[provider](inst, now))
            except NewsError as exc:
                errors[f"{ticker or 'Mercado'} · {PROVIDERS[provider]}"] = str(exc)
                if "inválida" in str(exc) or "limitou" in str(exc) or "sem ligação" in str(exc):
                    blocked.add(provider)
        fetched[ticker] = now.isoformat(timespec="seconds")
    NewsItem.query.filter(NewsItem.published < now - timedelta(days=KEEP_DAYS)).delete(synchronize_session=False)
    Setting.set("news_fetched", json.dumps(fetched))
    db.session.commit()
    return errors


def items(tickers=None, market=False, limit=LIMIT):
    q = NewsItem.query.filter(NewsItem.ticker == "") if market else NewsItem.query.filter(NewsItem.ticker.in_(tickers or [""]))
    return q.order_by(NewsItem.published.desc()).limit(limit).all()


def stats():
    """Por fonte: notícias guardadas, de quantos ativos, se há do mercado, e a mais recente."""
    out = {}
    rows = db.session.query(NewsItem.provider, NewsItem.ticker, db.func.count(NewsItem.id),
                            db.func.max(NewsItem.published)).group_by(NewsItem.provider, NewsItem.ticker).all()
    for provider, ticker, n, last in rows:
        st = out.setdefault(provider or "", {"count": 0, "assets": 0, "market": False, "last": None})
        st["count"] += n
        st["market"] = st["market"] or ticker == ""
        st["assets"] += ticker != ""
        st["last"] = max(st["last"], last) if st["last"] else last
    return out


def without_news(insts, shown):
    """Os ativos que ficaram sem notícias: [(ticker, motivo)]."""
    cache = _json_setting("finnhub_symbols")
    out = []
    for i in insts:
        if i.ticker in shown:
            continue
        reason = "ETF" if i.kind == "etf" else ("sem cotação nos EUA para o Finnhub" if cache.get(i.ticker) == "" else
                                                 "nenhuma notícia nos últimos 7 dias")
        out.append((i.ticker, reason))
    return out
