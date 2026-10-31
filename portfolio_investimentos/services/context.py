"""Contexto comum às páginas (barra lateral, barra de topo)."""
import json

from ..engine.formatting import MONTHS
from .. import auth
from ..models import Setting
from . import data
from .market import market_status, refresh_state

NAV = [
    ("overview", "Visão Geral", "/", "bi-grid"),
    ("carteira", "Carteira", "/carteira", "bi-wallet2"),
    ("radar", "Radar e alertas", "/radar", "bi-bullseye"),
    ("desempenho", "Desempenho", "/desempenho", "bi-graph-up-arrow"),
    ("dividendos", "Dividendos", "/dividendos", "bi-coin"),
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
    ctx.update(extra)
    return ctx


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
