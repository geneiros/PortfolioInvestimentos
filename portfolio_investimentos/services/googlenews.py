"""Notícias do Google Notícias (feed RSS público), como alternativa quando o Yahoo limita os pedidos de notícias.

O Yahoo Finance responde 429 às notícias a partir de alguns servidores partilhados (ex.: PythonAnywhere), mesmo
quando as cotações funcionam. A pesquisa é pelo nome do ativo; o resultado é menos preciso do que o do Yahoo.
"""
import time as _time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from .yahoo import HEADERS

URL = "https://news.google.com/rss/search"


def _fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read(2_000_000)


def search(query, limit=10):
    """Notícias para `query` no formato que `market._store_news` lê; levanta OSError se não houver ligação."""
    params = {"q": query, "hl": "pt-PT", "gl": "PT", "ceid": "PT:pt-150"}
    out = []
    for item in ET.fromstring(_fetch(URL + "?" + urllib.parse.urlencode(params))).iter("item"):
        title, link = (item.findtext("title") or "").strip(), (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        try:
            stamp = parsedate_to_datetime(item.findtext("pubDate") or "").timestamp()
        except (TypeError, ValueError):
            stamp = _time.time()
        out.append({"title": title, "link": link, "providerPublishTime": stamp,
                    "publisher": (item.findtext("source") or "Google Notícias").strip()})
    return out[:limit]
