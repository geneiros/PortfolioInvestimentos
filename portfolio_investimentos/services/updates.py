"""Aviso de versão nova (só no executável único): a última release no GitHub é mais recente do que esta versão?

O executável (PyInstaller) não se atualiza sozinho; quem o usa descarrega a versão nova da página da release. Quem
corre o código da pasta (scripts iniciar.*, PythonAnywhere) atualiza com «git pull» e não vê este aviso.
Um pedido ao GitHub no máximo uma vez por dia; sem internet não acontece nada.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta

from .. import __version__
from ..models import Setting

LATEST_URL = "https://api.github.com/repos/geneiros/PortfolioInvestimentos/releases/latest"
RELEASES_URL = "https://github.com/geneiros/PortfolioInvestimentos/releases/latest"
EVERY = timedelta(days=1)


def is_executable():
    """Executável único (PyInstaller) ou app Android: os que se atualizam descarregando a versão nova."""
    return bool(getattr(sys, "frozen", False)) or os.environ.get("PORTFOLIO_ANDROID") == "1"


def version_tuple(v):
    """«v0.10.2» → (0, 10, 2); o que não for número conta como 0."""
    parts = re.findall(r"\d+", str(v or ""))[:3]
    return tuple(int(p) for p in parts) + (0,) * (3 - len(parts))


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": f"PortfolioInvestimentos/{__version__}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _state():
    try:
        return json.loads(Setting.get("update_check") or "{}")
    except ValueError:
        return {}


def check(now=None, fetch=None, force=False):
    """Pergunta ao GitHub pela última release (no máximo uma vez por dia, salvo `force`). Devolve o estado guardado
    {checked, tag, url}; erros de rede ficam calados (o estado anterior mantém-se)."""
    now = now or datetime.now()
    state = _state()
    try:
        if not force and state.get("checked") and now - datetime.fromisoformat(state["checked"]) < EVERY:
            return state
    except ValueError:
        pass
    try:
        data = (fetch or _fetch)(LATEST_URL)
        tag = str(data.get("tag_name") or "")
        url = str(data.get("html_url") or RELEASES_URL)
        if not url.startswith("https://github.com/"):
            url = RELEASES_URL
        state = {"checked": now.isoformat(timespec="seconds"), "tag": tag, "url": url}
        Setting.set("update_check", json.dumps(state))
    except Exception:  # sem internet, GitHub em baixo, limite de pedidos: tenta-se noutro dia
        return state
    return state


def notice_enabled():
    return Setting.get("update_notice") != "0"


def available():
    """{tag, url} se houver uma versão mais recente do que esta e o aviso não estiver desligado nem fechado."""
    if not notice_enabled():
        return None
    state = _state()
    tag = state.get("tag")
    if not tag or version_tuple(tag) <= version_tuple(__version__):
        return None
    if Setting.get("update_dismissed") == tag:
        return None
    url = state.get("url") or ""
    return {"tag": tag, "url": url if url.startswith("https://github.com/") else RELEASES_URL}
