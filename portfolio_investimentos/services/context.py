"""Contexto comum às páginas (barra lateral, barra de topo)."""
import json
from datetime import datetime

from flask import request

from ..engine.formatting import MONTHS
from .. import auth
from ..models import Setting
from . import data, widgets
from .market import market_status, refresh_state

NAV = [
    ("overview", "Visão Geral", "/", "bi-grid"),
    ("carteira", "Carteira", "/carteira", "bi-wallet2"),
    ("desempenho", "Desempenho", "/desempenho", "bi-graph-up-arrow"),
    ("dividendos", "Dividendos", "/dividendos", "bi-coin"),
    ("patrimonio", "Património", "/patrimonio", "bi-bank"),
    ("planeamento", "Planeamento", "/planeamento", "bi-flag"),
    ("radar", "Radar e alertas", "/radar", "bi-bullseye"),
    ("noticias", "Notícias", "/noticias", "bi-newspaper"),
    ("fiscal", "Fiscal", "/fiscal", "bi-receipt"),
]
NAV_BOTTOM = [
    ("importar", "Importar", "/importar", "bi-file-earmark-arrow-up"),
    ("transacoes", "Transações", "/transacoes", "bi-list-ul"),
    ("definicoes", "Definições", "/definicoes", "bi-gear"),
]
FEEDBACK_URL = "https://github.com/geneiros/PortfolioInvestimentos/issues"  # pedidos de novas corretoras (Importar)


def js_json(obj):
    """JSON seguro para colocar dentro de <script>."""
    return json.dumps(obj, default=str).replace("<", "\\u003c").replace(">", "\\u003e")


def _regions(p):
    """Bolsas onde há posições abertas: EUA (sufixo .US, sem sufixo ou em USD) e/ou Europa (os restantes)."""
    found = set()
    for pos in p.open_positions:
        a = pos.asset
        if a.kind == "index":
            continue
        t = a.ticker.upper()
        isin_like = len(t) == 12 and t[:2].isalpha() and t[2:].isalnum()
        found.add("US" if a.currency == "USD" or t.endswith(".US") or ("." not in t and not isin_like) else "EU")
    return found or {"EU"}


def build(active, title, **extra):
    broker = data.selected_broker()
    brokers = data.brokers()
    p = data.load_portfolio(broker)
    ctx = dict(
        active=active, title=title, nav=NAV, nav_bottom=NAV_BOTTOM, feedback_url=FEEDBACK_URL,
        brokers=brokers, broker=broker, broker_doc=next((b for b in brokers if b.name == broker), None),
        total_positions=sum(b.positions for b in brokers), p=p, day_change=p.day_change(),
        market=market_status(regions=_regions(p)), eurusd=p.book.latest_fx("USD"),
        hide_banner=Setting.get("hide_banner") == "1", is_demo=Setting.get("demo") == "1",
        has_data=bool(p.transactions), auth_enabled=auth.password_enabled(), MONTHS=MONTHS, js_json=js_json, warnings=list(p.warnings),
    )
    if ctx["has_data"] and not ctx["is_demo"]:
        ctx["warnings"] += _refresh_warnings(p, active)
        ctx["stale_refresh"] = stale_refresh(p)
    try:
        ctx["widget_orders"] = widgets.orders(request.path)
    except RuntimeError:  # fora de um pedido (testes do motor)
        ctx["widget_orders"] = {}
    ctx.update(extra)
    return ctx


STALE_DAYS = 5  # por omissão: aviso no topo quando as posições abertas não são atualizadas há mais de 5 dias


def stale_days():
    """Dias sem atualizar as cotações a partir dos quais aparece o aviso no topo (0 = nunca)."""
    try:
        return max(int(float(Setting.get("stale_days"))), 0)
    except (TypeError, ValueError):
        return STALE_DAYS


def stale_refresh(p, now=None):
    """{"days", "since"} quando a última atualização de cotações tem mais de `stale_days()` dias; senão None.

    Só com posições abertas e depois de pelo menos uma atualização (antes disso há o aviso «Ainda não
    atualizaste»), e nunca durante uma atualização.
    """
    limit = stale_days()
    last = Setting.get("last_refresh")
    if not limit or not last or not p.open_positions or refresh_state()[0]:
        return None
    try:
        since = datetime.fromisoformat(last)
    except ValueError:
        return None
    days = ((now or datetime.now()) - since).days
    return {"days": days, "since": since, "key": last} if days > limit else None


PERF_NOTE = (" No Desempenho, a volatilidade, o drawdown, o Sharpe e a comparação com o mercado ficam distorcidos, "
             "porque o valor só muda nos dias com transações.")


def _refresh_warnings(p, active=None):
    running, error, missing = refresh_state()
    if running:
        return ["A atualizar as cotações… Pode demorar alguns minutos; recarrega a página para ver os valores novos."]
    if error:
        return [f"A última atualização de cotações falhou ({error}). Tenta de novo em Definições → Atualizar cotações agora."]
    if not Setting.get("last_refresh"):
        note = PERF_NOTE if active == "desempenho" else ""
        return ["Ainda não atualizaste as cotações: os valores e os gráficos usam os preços das tuas próprias "
                "transações, por isso podem ter saltos. Atualiza em Definições → Atualizar cotações agora (precisa de internet)."
                + note]
    held = sorted(pos.asset.ticker for pos in p.open_positions if pos.asset.ticker in missing)
    if held:
        note = PERF_NOTE if active == "desempenho" else ""
        return [f"Sem cotações do Yahoo Finance para {', '.join(held)}: estes ativos usam o preço da última transação. "
                "Define o símbolo de dados em Definições → Ativos." + note]
    return []
