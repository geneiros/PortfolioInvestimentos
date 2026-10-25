"""Acesso mínimo ao Yahoo Finance só com a biblioteca padrão (sem `yfinance`).

Usado quando o `yfinance` não pode ser instalado, por exemplo no Android/Termux, onde a dependência
`curl_cffi` não compila. Imita a pequena parte da interface do `yfinance` que `market.py` usa:
`Ticker(símbolo).history(start=...)`, `history_metadata`, `news`, `info`, `calendar` e `Search`.
"""
import json
import time as _time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
# sem um User-Agent de browser o Yahoo responde muitas vezes com 429/403
HEADERS = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/128.0 Mobile Safari/537.36", "Accept": "application/json"}


def _get_json(url, params):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


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
        try:
            data = _get_json(SEARCH_URL, {"q": self.symbol, "quotesCount": 0, "newsCount": 10})
        except (OSError, ValueError):
            return []
        return data.get("news") or []


class Search:
    def __init__(self, query, max_results=10):
        data = _get_json(SEARCH_URL, {"q": query, "quotesCount": max_results, "newsCount": 0})
        self.quotes = data.get("quotes") or []
