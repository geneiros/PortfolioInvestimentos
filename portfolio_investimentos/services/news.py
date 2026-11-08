"""Notícias dos ativos da carteira e do mercado, de três fontes:

- **Finnhub** (finnhub.io, com a chave em Definições ou na variável FINNHUB_API_KEY): no plano gratuito só tem
  notícias de empresas cotadas nos EUA e no Canadá (o símbolo encontra-se pelo ISIN);
- **Google Notícias** (RSS, sem chave), pelo nome do ativo, em português;
- **Marketaux** (marketaux.com, com a chave em Definições ou na variável MARKETAUX_API_KEY): no plano gratuito
  são 100 pedidos por dia e 3 notícias por pedido, por isso as do Marketaux reaproveitam-se durante 6 horas.

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
MARKETAUX = "https://api.marketaux.com/v1/news/all"
GOOGLE_RSS = "https://news.google.com/rss/search"
PROVIDERS = {"finnhub": "Finnhub", "google": "Google Notícias", "marketaux": "Marketaux"}  # o Yahoo foi retirado
KEYED = {"finnhub", "marketaux"}  # fontes que só contam com a chave
TTL = timedelta(hours=1)
TTL_BY = {"marketaux": timedelta(hours=6)}  # o plano gratuito do Marketaux tem 100 pedidos por dia
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


def marketaux_key():
    return os.environ.get("MARKETAUX_API_KEY") or Setting.get("marketaux_key") or None


def marketaux_from_env():
    return bool(os.environ.get("MARKETAUX_API_KEY"))


def has_key(provider):
    return {"finnhub": api_key, "marketaux": marketaux_key}.get(provider, lambda: True)() is not None


def enabled():
    """Fontes ligadas (Definições); por omissão todas. O Finnhub e o Marketaux só contam com a chave."""
    raw = Setting.get("news_sources")
    chosen = [p for p in (raw.split(",") if raw is not None else PROVIDERS) if p in PROVIDERS]
    return [p for p in chosen if p not in KEYED or has_key(p)]


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


def _clean_name(inst):
    """O nome do ativo sem a forma jurídica (Inc, N.V., S.A., …): «Stellantis N.V.» → «Stellantis»."""
    return re.sub(r"\b(Inc|Corp|Corporation|S\.?A|N\.?V|plc|AG|SE|Ltd|Holdings?|Group|UCITS ETF.*)\b\.?",
                  "", getattr(inst, "instrument_name", None) or "", flags=re.I).strip(" ,.-")


def _us_symbol(inst):
    try:
        return _json_setting("finnhub_symbols").get(inst.ticker) or ""
    except RuntimeError:  # fora da aplicação (testes do motor)
        return ""


def _mentions(inst, title):
    """O título fala do ativo? A primeira palavra do nome ou o nome todo (sem contar maiúsculas; os acentos contam,
    para «Sitio» não ser «sítio»), ou o símbolo dos EUA ou o ticker (com 4 ou mais letras) em maiúsculas
    (ex.: STLA, ADBE, STLAP)."""
    title = title or ""
    name = _clean_name(inst)
    words = [w for w in re.findall(r"[^\W\d_][\w&'-]*", name) if len(w) >= 3]
    for term in ([words[0]] if words else []) + ([name] if len(name) >= 3 else []):
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", title, re.I):
            return True
    base = (inst.ticker or "").split(".")[0]
    for sym in {base if len(base) >= 4 else "", _us_symbol(inst)}:  # «ADB» sozinho também é o banco asiático
        if len(sym) >= 3 and re.search(rf"(?<![\w]){re.escape(sym.upper())}(?![\w])", title):
            return True
    return False


def _google(inst, now, fetch=None):
    """Google Notícias (RSS), dos últimos 7 dias: do ativo pelo nome, com contexto de bolsa, e só as notícias cujo
    título fala dele (a pesquisa do Google encontra a palavra em qualquer sítio da página, ex.: o crédito «Adobe
    Stock» das fotografias de receitas); o mercado pelos termos de bolsa. Os ETF e os índices não se pesquisam: o
    nome do índice aparece em páginas de outras empresas. O Google Finance não tem API nem feed: as notícias que
    mostra são as do Google Notícias para a empresa."""
    if inst is None:
        query = "bolsa OR mercados OR ações"
    else:
        if getattr(inst, "kind", None) in ("etf", "index"):
            return []
        name = _clean_name(inst)
        if len(name) < 3:
            name = inst.ticker or ""
        symbol = _us_symbol(inst) or (inst.ticker or "").split(".")[0]
        extra = f" OR {symbol}" if re.fullmatch(r"[A-Z0-9]{2,6}", symbol or "") else ""
        query = f'"{name}" (ações OR bolsa OR resultados{extra})'
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
        if inst is None or _mentions(inst, title):
            out.append(_row(title, it.findtext("link"), source, ts))
    return out


def _purge_google(ticker, inst):
    """Apaga as notícias do Google guardadas deste ativo que não falam dele (as de antes do filtro)."""
    if inst is None:
        return
    for n in NewsItem.query.filter_by(ticker=ticker, provider="google").all():
        if inst.kind in ("etf", "index") or not _mentions(inst, n.headline):
            db.session.delete(n)


def _marketaux(inst, now, fetch=None):
    """Marketaux: notícias do ativo (pelo símbolo dos EUA, se o Finnhub o encontrou, ou pelo do Yahoo) ou, sem
    ativo, do mercado. O Marketaux só aceita a chave no endereço (api_token): o endereço não se mostra nem regista."""
    key = marketaux_key()
    if not key:
        raise NewsError("falta a chave do Marketaux (Definições → Dados de mercado)")
    params = {"language": "pt,en", "published_after": (now - timedelta(days=DAYS)).strftime("%Y-%m-%dT%H:%M"),
              "limit": 3, "api_token": key}
    if inst is None:
        params.update(countries="us,pt", filter_entities="false")
    else:
        symbol = _json_setting("finnhub_symbols").get(inst.ticker) or inst.data_symbol or inst.ticker
        params.update(symbols=symbol, filter_entities="true")
    try:
        data = json.loads((fetch or _http)(f"{MARKETAUX}?{urllib.parse.urlencode(params)}").decode())
    except urllib.error.HTTPError as exc:
        msg = {401: "chave do Marketaux inválida", 402: "o Marketaux limitou os pedidos (limite diário do plano)",
               429: "o Marketaux limitou os pedidos; tenta mais tarde"}.get(exc.code)
        raise NewsError(msg or f"o Marketaux respondeu HTTP {exc.code}") from None  # sem o endereço (tem a chave)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise NewsError(f"sem ligação ao Marketaux ({str(getattr(exc, 'reason', exc))[:100]})") from None
    return [_row(r.get("title"), r.get("url"), r.get("source"), _parse_iso(r.get("published_at")),
                 r.get("description") or r.get("snippet")) for r in data.get("data") or []]


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


def refresh(tickers, force=False, now=None, fetchers=None, budget=BUDGET, market=True):
    """Pede as notícias (das fontes ligadas) dos ativos e do mercado cujo último pedido a essa fonte já passou da
    validade (1 hora; 6 no Marketaux). Devolve {"ativo · fonte": erro}.

    `fetchers`: {fonte: função(inst ou None, agora)} para os testes."""
    now = now or datetime.now()
    fetchers = fetchers or {"finnhub": _finnhub, "google": _google, "marketaux": _marketaux}
    fetched = _json_setting("news_fetched")
    errors, t0 = {}, time.monotonic()
    blocked = set()  # fontes que falharam por chave ou limite: não adianta insistir nesta visita
    sources = [p for p in enabled() if p in fetchers]
    last = {}  # por fonte, nesta atualização: pedidos, notícias encontradas, novas e erros

    def due(provider, ticker):
        try:
            return force or now - datetime.fromisoformat(fetched[f"{provider}:{ticker}"]) > TTL_BY.get(provider, TTL)
        except (KeyError, ValueError):
            return True
    for ticker in ([""] if market else []) + list(tickers):
        inst = None if ticker == "" else db.session.get(Instrument, ticker)
        if ticker and inst is None:
            continue
        todo = [p for p in sources if p not in blocked and due(p, ticker)]
        if not todo:
            continue
        if time.monotonic() - t0 > budget:  # o resto fica para a visita seguinte
            break
        for provider in todo:
            st = last.setdefault(provider, {"new": 0, "found": 0, "asked": 0, "errors": 0})
            st["asked"] += 1
            try:
                rows = fetchers[provider](inst, now)
                if provider == "google":
                    _purge_google(ticker, inst)
                st["found"] += len(rows or [])
                st["new"] += _store(ticker, provider, rows)
            except NewsError as exc:
                st["errors"] += 1
                errors[f"{ticker or 'Mercado'} · {PROVIDERS[provider]}"] = str(exc)
                if any(w in str(exc) for w in ("inválida", "limitou", "sem ligação", "falta a chave")):
                    blocked.add(provider)
                    continue
            fetched[f"{provider}:{ticker}"] = now.isoformat(timespec="seconds")
    NewsItem.query.filter(NewsItem.published < now - timedelta(days=KEEP_DAYS)).delete(synchronize_session=False)
    # fontes retiradas (o Yahoo Finance): as notícias delas deixam de aparecer
    NewsItem.query.filter(NewsItem.provider.notin_(list(PROVIDERS))).delete(synchronize_session=False)
    Setting.set("news_fetched", json.dumps(fetched))
    if last:
        saved = _json_setting("news_last")
        for provider, st in last.items():
            prev = saved.get(provider) if saved.get(provider, {}).get("batch") == now.strftime("%Y-%m-%dT%H:%M") else None
            if prev:  # vários passos da mesma atualização (botão): somam
                st = {k: st[k] + prev.get(k, 0) for k in st}
            saved[provider] = {**st, "batch": now.strftime("%Y-%m-%dT%H:%M"), "at": now.isoformat(timespec="seconds")}
        Setting.set("news_last", json.dumps(saved))
    db.session.commit()
    return errors


def items(tickers=None, market=False, limit=LIMIT):
    q = NewsItem.query.filter(NewsItem.ticker == "") if market else NewsItem.query.filter(NewsItem.ticker.in_(tickers or [""]))
    q = q.filter(NewsItem.provider.in_(list(PROVIDERS)))
    return q.order_by(NewsItem.published.desc()).limit(limit).all()


def last_results():
    """Por fonte, o resultado da última atualização (para Definições): pedidos, encontradas, novas, erros."""
    return _json_setting("news_last")


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
