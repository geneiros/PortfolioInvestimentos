"""Ordem dos cartões (widgets) de cada página, mudada com um clique longo e arrastar.

Guarda-se no Setting `widgets:<caminho>` um dicionário {grelha: [nomes dos cartões]}; a página aplica-o antes de
aparecer (static/js/widgets.js). Os nomes vêm do `data-widget` do cartão ou, sem ele, do id ou do título.
"""
import json
import re

from ..models import Setting

PREFIX = "widgets:"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
PAGE = re.compile(r"^/[a-z0-9/_-]{0,40}$")
MAX_GRIDS, MAX_ITEMS = 20, 40


def valid_page(page):
    return bool(PAGE.match(page or "")) and "//" not in page


def orders(page):
    """{grelha: [nomes]} guardado para a página (vazio = a ordem de omissão)."""
    if not valid_page(page):
        return {}
    try:
        saved = json.loads(Setting.get(PREFIX + page) or "{}")
    except ValueError:
        saved = {}
    if not saved and page == "/":  # a primeira versão guardava só a grelha da Visão Geral
        try:
            old = json.loads(Setting.get("widgets_overview") or "[]")
        except ValueError:
            old = []
        saved = {"overviewGrid": old} if old else {}
    if not isinstance(saved, dict):
        return {}
    return {k: [n for n in v if isinstance(n, str) and NAME.match(n)] for k, v in saved.items()
            if isinstance(k, str) and NAME.match(k) and isinstance(v, list)}


def save(page, grid, names):
    if not valid_page(page) or not NAME.match(grid or ""):
        raise ValueError("Página ou grelha inválida.")
    if len(names) > MAX_ITEMS or len(set(names)) != len(names) or not all(NAME.match(n) for n in names):
        raise ValueError("Ordem inválida.")
    current = orders(page)
    current[grid] = names
    if len(current) > MAX_GRIDS:
        raise ValueError("Demasiadas grelhas.")
    Setting.set(PREFIX + page, json.dumps(current))
    if page == "/":
        Setting.set("widgets_overview", None)


def customized():
    """Páginas com uma ordem própria."""
    rows = Setting.query.filter(Setting.key.like(PREFIX + "%"), Setting.value.isnot(None)).all()
    pages = sorted(r.key[len(PREFIX):] for r in rows if r.value not in ("", "{}"))
    if "/" not in pages and Setting.get("widgets_overview"):
        pages.insert(0, "/")
    return pages


def reset(page=None):
    """Volta à ordem de omissão numa página ou, sem página, em todas."""
    pages = [page] if page else customized()
    for pg in pages:
        Setting.set(PREFIX + pg, None)
    if not page or page == "/":
        Setting.set("widgets_overview", None)
