"""Acesso mínimo ao Yahoo Finance só com a biblioteca padrão (sem `yfinance`).

Usado quando o `yfinance` não pode ser instalado, por exemplo no Android/Termux, onde a dependência
`curl_cffi` não compila. Imita a pequena parte da interface do `yfinance` que `market.py` usa:
`Ticker(símbolo).history(start=...)`, `history_metadata`, `news`, `info`, `calendar` e `Search`.
"""
import json
import time as _time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
# sem um User-Agent de browser o Yahoo responde muitas vezes com 429/403
HEADERS = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/128.0 Mobile Safari/537.36", "Accept": "application/json"}


RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"  # as notícias da página do ativo, em RSS
HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
_state = {"opener": None, "crumb": None}


class YahooError(OSError):
    """Falha ao contactar o Yahoo, com uma mensagem legível para o resumo da atualização."""


def _opener():
    if _state["opener"] is None:
        import http.cookiejar
        _state["opener"] = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    return _state["opener"]


def _fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with _opener().open(req, timeout=20) as resp:
        return resp.read()


def _crumb():
    """Cookie + "crumb" que o Yahoo exige por vezes (respostas 401/403) a quem não é um browser."""
    if _state["crumb"] is None:
        try:
            _fetch("https://fc.yahoo.com/")  # só serve para receber o cookie; responde muitas vezes 404
        except urllib.error.HTTPError:
            pass
        _state["crumb"] = _fetch("https://query1.finance.yahoo.com/v1/test/getcrumb").decode().strip()
    return _state["crumb"]


def _describe(exc):
    if isinstance(exc, urllib.error.HTTPError):
        hint = {401: "o Yahoo pediu autorização", 403: "o Yahoo recusou o pedido",
                404: "símbolo inexistente", 429: "o Yahoo limitou os pedidos; tenta mais tarde"}.get(exc.code, "")
        return f"HTTP {exc.code}" + (f": {hint}" if hint else "")
    reason = getattr(exc, "reason", None) or exc
    return f"sem ligação ao Yahoo ({reason})"


def _get_json(url, params):
    """GET com o servidor alternativo do Yahoo, nova tentativa em 429 e cookie/crumb em 401/403."""
    path = urllib.parse.urlsplit(url).path
    last = None
    for attempt in range(4):
        host = HOSTS[attempt % 2]
        query = dict(params)
        if attempt >= 2 and _state["crumb"] is not False:
            try:
                query["crumb"] = _crumb()
            except OSError:
                _state["crumb"] = False  # sem crumb: continua a tentar sem ele
        try:
            return json.loads(_fetch(f"https://{host}{path}?" + urllib.parse.urlencode(query)).decode())
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 404:
                break  # símbolo inexistente: não vale a pena insistir
            if exc.code == 429:
                _time.sleep(1.5 * (attempt + 1))
        except (OSError, ValueError) as exc:
            last = exc
    raise YahooError(_describe(last))


class History:
    """Histórico diário com a interface usada por `market._closes`: `empty` e `iterrows()`."""

    def __init__(self, rows):
        self.rows = rows  # [(datetime, {"Close": ..., "Stock Splits": ...})]
        self.empty = not rows

    def iterrows(self):
        return iter(self.rows)


def _parse_chart(data):
    """Converte a resposta do endpoint `chart` em (History, metadados)."""
    result = ((data or {}).get("chart") or {}).get("result") or []
    if not result:
        return History([]), {}
    res = result[0]
    meta = res.get("meta") or {}
    offset = timedelta(seconds=meta.get("gmtoffset") or 0)  # data da sessão na bolsa, não em UTC
    stamps = res.get("timestamp") or []
    closes = (((res.get("indicators") or {}).get("quote") or [{}])[0].get("close")) or []
    splits = {}
    for ev in ((res.get("events") or {}).get("splits") or {}).values():
        num, den = ev.get("numerator"), ev.get("denominator")
        if num and den:
            splits[datetime.fromtimestamp(ev["date"], timezone.utc).replace(tzinfo=None) + offset] = num / den
    split_days = {d.date(): r for d, r in splits.items()}
    rows = []
    for ts, close in zip(stamps, closes):
        day = datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None) + offset
        rows.append((day, {"Close": float("nan") if close is None else float(close),
                           "Stock Splits": split_days.get(day.date(), 0.0)}))
    return History(rows), {"currency": meta.get("currency")}


class Ticker:
    def __init__(self, symbol):
        self.symbol = symbol
        self.history_metadata = {}
        self.info = {}       # dados fundamentais: só servem para o setor, que é opcional
        self.calendar = {}   # eventos (resultados, dividendos): não disponíveis por esta via

    def history(self, start=None, **_):
        start = start or (datetime.now() - timedelta(days=365)).date()
        period1 = int(_time.mktime(start.timetuple())) if hasattr(start, "timetuple") else int(start)
        data = _get_json(CHART_URL.format(symbol=urllib.parse.quote(self.symbol)),
                         {"period1": period1, "period2": int(_time.time()) + 86400, "interval": "1d",
                          "events": "split", "includePrePost": "false"})
        hist, self.history_metadata = _parse_chart(data)
        return hist

    @property
    def news(self):
        """Notícias do ativo: a pesquisa do Yahoo e, se vier vazia, o RSS da página do ativo.

        O motivo de uma falha fica em `news_error` (para o resumo da atualização).
        """
        self.news_error = None
        try:
            data = _get_json(SEARCH_URL, {"q": self.symbol, "quotesCount": 0, "newsCount": 10})
            items = data.get("news") or []
        except (OSError, ValueError) as exc:
            items, self.news_error = [], str(exc)
        if not items:
            try:
                items = _rss_news(self.symbol)
                if items:
                    self.news_error = None
            except (OSError, ValueError, ET.ParseError) as exc:
                self.news_error = self.news_error or f"RSS: {exc}"
        return items


def _rss_news(symbol):
    """Notícias da página do ativo no Yahoo Finance (feed RSS), no formato que `market._store_news` lê."""
    raw = _fetch(RSS_URL + "?" + urllib.parse.urlencode({"s": symbol, "region": "US", "lang": "en-US"}))
    if len(raw) > 2_000_000:
        raise ValueError("resposta demasiado grande")
    out = []
    for item in ET.fromstring(raw).iter("item"):
        title, link = (item.findtext("title") or "").strip(), (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        try:
            stamp = parsedate_to_datetime(item.findtext("pubDate") or "").timestamp()
        except (TypeError, ValueError):
            stamp = _time.time()
        out.append({"title": title, "link": link, "providerPublishTime": stamp, "publisher": "Yahoo Finance"})
    return out[:10]


class Search:
    def __init__(self, query, max_results=10):
        data = _get_json(SEARCH_URL, {"q": query, "quotesCount": max_results, "newsCount": 0})
        self.quotes = data.get("quotes") or []
