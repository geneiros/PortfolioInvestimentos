"""Páginas da aplicação."""
from datetime import date, timedelta
from types import SimpleNamespace

from flask import Blueprint, Response, abort, current_app, render_template, request

from .engine import costs, stress, valuation
from .engine.portfolio import MERIT_BENCHMARK
from .models import (LIQUIDITY, OTHER_CATEGORIES, Broker, DividendHistory, Event, Fundamental, ImportBatch,
                     Instrument, Price, Setting, Transaction, WatchItem, WatchRule, db)
from . import auth, is_portable
from .services import context as ctx
from .services import backups, data, insights, market, networth, portfolio_alerts, report, sale_sim, widgets
from .services import news as news_svc
from .services.importer import BROKERS, INSTRUCTIONS
from .services.market import refresh_state, upcoming_events, yfinance_available

bp = Blueprint("pages", __name__)

PERIODS = [("1M", "1 mês"), ("3M", "3 meses"), ("6M", "6 meses"), ("YTD", "Ano corrente"),
           ("1A", "1 ano"), ("3A", "3 anos"), ("5A", "5 anos"), ("MAX", "Máx")]
# índices que se podem comparar no gráfico de evolução da Visão Geral
OVERVIEW_TICKERS = [t for t, *_ in market.OVERVIEW_BENCHMARKS]
# o período no widget Carteira da Visão Geral («Variação · 3 meses»)
PERIOD_NAMES = {k: ("desde o início" if k == "MAX" else v.lower()) for k, v in PERIODS}
LABELS = {"BUY": "Compra", "SELL": "Venda", "DIVIDEND": "Dividendo", "DEPOSIT": "Depósito",
          "WITHDRAWAL": "Levantamento", "FEE": "Comissão", "INTEREST": "Juros",
          "TRANSFER_IN": "Transferência (entrada)", "TRANSFER_OUT": "Transferência (saída)",
          "CONVERT_IN": "Conversão (entrada)", "CONVERT_OUT": "Conversão (saída)"}

def _tracking_check():
    from .services import tracking
    return tracking.check()


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _round(obj, ndigits=5):
    """Arredonda todos os decimais de uma estrutura de listas/dicionários (o JSON embutido na página pesa menos)."""
    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, (list, tuple)):
        return [_round(x, ndigits) for x in obj]
    if isinstance(obj, dict):
        return {k: _round(v, ndigits) for k, v in obj.items()}
    return obj


def _sample(dates, period):
    """Índices a desenhar: todos os dias até 1 ano; a partir daí o último dia de cada semana (o gráfico é mais
    estreito do que o nº de dias) e sempre o primeiro e o último pontos."""
    if period not in ("3A", "5A", "MAX"):
        return list(range(len(dates)))
    weeks = [date.fromisoformat(d).isocalendar()[:2] for d in dates]
    last = len(dates) - 1
    return [i for i in range(len(dates)) if i in (0, last) or weeks[i] != weeks[i + 1]]


def perf_payload(p, period, benchmarks=None):
    """Dados do gráfico de evolução da Visão Geral: só o que ele usa, arredondado e, nos períodos longos, semanal."""
    perf = p.performance(period, benchmarks, risk_free=data.risk_free())
    if not perf:
        return None
    keep = _sample(perf["dates"], period)

    def pick(xs, digits):
        return [round(xs[i], digits) for i in keep]
    holdings = p.series.holdings[len(p.series.holdings) - len(perf["dates"]):]
    return {"start": perf["start"].isoformat(), "dates": [perf["dates"][i] for i in keep],
            "gain": pick(perf["gain"], 2), "value": pick(perf["value"], 2),
            # o widget Carteira da Visão Geral segue o mesmo período: o gráfico de fundo (posições abertas), a
            # variação sem depósitos e o rendimento (TWR)
            "holdings": [float(f"{holdings[i]:.5g}") for i in keep],
            "summary": {"label": PERIOD_NAMES.get(period, period), "gain": round(perf["return_eur"], 2),
                        "gain_pct": perf["return_pct"], "twr": perf["twr_total"],
                        # com mais de 1 ano, também o rendimento anual (TWR anualizado, o CAGR de Desempenho)
                        "twr_annual": perf["cagr"] if perf["years"] > 1.02 else None},
            "benchmarks": [{"ticker": b["ticker"], "name": b["name"], "color": b["color"], "twr": pick(b["twr"], 5)}
                           for b in perf["benchmarks"]]}


# cores para as posições sem cor própria no gráfico "As minhas posições"
POSITION_COLORS = ["#14b8a6", "#ec4899", "#a78bfa", "#06b6d4", "#f97316", "#22c55e", "#eab308", "#ef4444"]


def positions_payload(p, period):
    """Ganho e valor das principais posições no período (o resto somado em "Outras"), como o gráfico da Visão Geral."""
    out = p.position_lines(period)
    if not out:
        return None
    keep = _sample([d.isoformat() for d in out["dates"]], period)

    def pick(xs):
        return [round(xs[i], 2) for i in keep]
    used, lines = set(), []
    for n, ln in enumerate(out["lines"]):
        a = ln["asset"]
        color = a.color if a.color and a.color not in ("#64748b", "#94a3b8", *used) else \
            next((c for c in POSITION_COLORS if c not in used), POSITION_COLORS[n % len(POSITION_COLORS)])
        used.add(color)
        lines.append({"ticker": a.ticker, "name": a.name, "color": color, "gain": pick(ln["gain"]),
                      "value": pick(ln["value"]), "total": round(ln["total"], 2),
                      "pct": None if ln["pct"] is None else round(ln["pct"], 4)})
    o = out["others"]
    if o:
        lines.append({"ticker": "", "name": f"Outras ({o['count']})", "color": "#94a3b8", "gain": pick(o["gain"]),
                      "value": pick(o["value"]), "total": round(o["total"], 2),
                      "pct": None if o["pct"] is None else round(o["pct"], 4), "others": True})
    return {"lines": lines}


@bp.route("/")
def overview():
    c = ctx.build("overview", "Visão Geral")
    p = c["p"]
    if not p.transactions:
        return render_template("pages/index.html", **c)
    movers = p.movers(8)
    held = [pos.asset.ticker for pos in p.open_positions]
    events = upcoming_events(held)
    today = date.today()
    week, two = today + timedelta(days=7), today + timedelta(days=14)
    instruments = {i.ticker: i for i in Instrument.query.filter(Instrument.ticker.in_({e.instrument for e in events} or {""}))}
    perf_ytd = perf_payload(p, "YTD", OVERVIEW_TICKERS)
    c.update(
        movers=movers, events_total=len(events),
        mover_charts={m.asset.ticker: ctx.js_json(_mover_chart(p, m)) for m in movers},
        event_groups=[("Próxima semana", [e for e in events if e.date <= week]),
                      ("Daqui a duas semanas", [e for e in events if week < e.date <= two]),
                      ("Mais tarde", [e for e in events if e.date > two][:10])],
        instruments=instruments, fired=_tracking_check(), portfolio_fired=portfolio_alerts.check(), perf=ctx.js_json(perf_ytd), hero=(perf_ytd or {}).get("summary"),
        benchmarks=[b for t in OVERVIEW_TICKERS for b in p.benchmarks if b.ticker == t], scores=insights.scores(p, c["broker"], c["broker_doc"].broker_name if c["broker_doc"] else None),
        networth=networth.summary(data.load_portfolio(None)) if networth.assets() else None,
        networth_late=len(networth.reminder()),
        insights_data=ctx.js_json({"wr": insights.weight_return(p), "alloc": insights.allocation(p, c["broker"])}),
    )
    return render_template("pages/index.html", **c)



def _mover_chart(p, pos, days=365):
    """Fechos do último ano de uma posição, com as datas e o preço médio de aquisição (na moeda do ativo)."""
    since = p.as_of - timedelta(days=days)
    rows = [(d, v) for d, v in p.book.recent(pos.asset.ticker, 400) if d > since]
    if len(rows) > 130:  # compacto: um em cada dois dias úteis chega para a forma da curva (fica sempre o último)
        rows = rows[::-1][::2][::-1]
    start = rows[0][0] if rows else p.as_of
    # as datas vão como dias desde a primeira ("s"), para a página não crescer com 8 ações × 1 ano
    return {"s": start.isoformat(), "o": [(d - start).days for d, _ in rows],
            "v": [float(f"{v:.5g}") for _, v in rows],
            "avg": round(pos.avg_price, 4) if pos.avg_price else None, "cur": pos.asset.currency}


def _market_bars(p):
    """Barras da «Carteira vs mercado»: os índices escolhidos, pela ordem escolhida (None = sem cotações)."""
    by_ticker = {b.ticker: b for b in p.benchmarks}
    out = []
    for t in market.market_indices():
        b = by_ticker.get(t)
        if b is not None:
            out.append((b.name, p.benchmark_day_change(b), b.color))
    return out


def _index_catalog():
    chosen = market.market_indices()
    groups = {}
    for group, ticker, name, _cur, color in market.INDEX_CATALOG:
        groups.setdefault(group, []).append({"ticker": ticker, "name": name, "color": color, "on": ticker in chosen})
    return {"groups": list(groups.items()), "chosen": chosen, "max": market.MAX_MARKET_INDICES}


def _market_alerts(c):
    """Para o painel «Alerta da carteira»: a variação de hoje de cada âmbito e os alertas guardados."""
    scopes = [{"id": "", "name": "Toda a carteira", "pct": data.load_portfolio(None).day_change()[1]}]
    scopes += [{"id": b.name, "name": b.broker_name, "pct": data.load_portfolio(b.name).day_change()[1]}
               for b in c["brokers"]]
    return {"scopes": scopes, "levels": [round(x * 100) for x in portfolio_alerts.LEVELS],
            "rows": portfolio_alerts.rows()}


@bp.route("/logo/<path:ticker>")
def logo(ticker):
    from .models import Logo
    from .services import logos
    row = db.session.get(Logo, ticker)
    if row is None or not row.data:
        abort(404)
    tag = logos.etag(row)
    if request.if_none_match and tag in request.if_none_match:
        return Response(status=304)
    resp = Response(row.data, mimetype=row.mime or "image/png")
    resp.set_etag(tag)
    resp.headers["Cache-Control"] = "private, max-age=604800"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"  # SVG sem scripts
    return resp


@bp.route("/carteira")
def carteira():
    c = ctx.build("carteira", "Carteira")
    p = c["p"]
    c.update(
        positions=p.open_positions, closed=p.closed_positions, sectors=p.sectors(),
        sparks={pos.asset.ticker: ctx.js_json(p.sparkline(pos.asset.ticker, 30)) for pos in p.open_positions},
        market_bars=_market_bars(p), index_catalog=_index_catalog(), market_alerts=_market_alerts(c),
        portfolio_fired=portfolio_alerts.check(),
        total={"invested": p.cost_basis, "value": p.holdings_value, "unrealized": p.unrealized,
               "dividends": sum(x.dividends_eur for x in p.open_positions),
               "fx": sum(x.fx_effect_eur for x in p.open_positions),
               "fees": sum(x.fees_eur for x in p.open_positions),
               "roi": sum(x.roi_eur for x in p.open_positions),
               # base do ROI % como nas linhas: tudo o que se investiu em cada ativo (incluindo partes já vendidas)
               "roi_base": sum((x.bought_eur or x.invested_eur) for x in p.open_positions)},
        alloc=ctx.js_json({k: p.allocation(k) for k in ("asset", "sector", "currency")}),
        crisis=stress.crisis_test(p), costs=_costs(p), valuations=_valuations(p),
        aaa_yield=_aaa_yield() or valuation.AAA_YIELD, xray=_xray(p),
    )
    return render_template("pages/carteira.html", **c)



def _dividend_per_share(p, ticker):
    """Dividendo anual médio por ação dos últimos 3 anos: o histórico do Yahoo ou, sem ele, os recebidos."""
    since = p.as_of - timedelta(days=3 * 365)
    rows = [(r.date, r.amount) for r in DividendHistory.query.filter(DividendHistory.instrument == ticker,
                                                                       DividendHistory.date > since)]
    if not rows:
        rows = [(t.date, t.amount / t.quantity) for t in p.transactions
                if t.type == "DIVIDEND" and t.asset is not None and t.asset.ticker == ticker and t.quantity
                and t.amount and t.date > since]
    if not rows:
        return None
    first = min(d for d, _ in rows)
    years = min(max((p.as_of - first).days / 365.25, 1.0), 3.0)  # histórico curto: a média do que há
    return sum(a for _, a in rows) / years


def _dividend_growth(ticker, as_of):
    """Crescimento anual dos dividendos por ação (histórico do Yahoo): entre o 1.º e o último de até 6 anos
    civis completos com pagamentos. None sem 3 anos."""
    years = {}
    for r in DividendHistory.query.filter(DividendHistory.instrument == ticker,
                                          DividendHistory.date >= date(as_of.year - 6, 1, 1),
                                          DividendHistory.date < date(as_of.year, 1, 1)):
        years[r.date.year] = years.get(r.date.year, 0.0) + r.amount
    full = [years[y] for y in sorted(years)]
    if len(full) < 3 or full[0] <= 0 or full[-1] <= 0:
        return None
    return (full[-1] / full[0]) ** (1 / (len(full) - 1)) - 1


def _aaa_yield():
    try:
        return float(Setting.get("aaa_yield")) / 100
    except (TypeError, ValueError):
        return None


def _valuations(p):
    """O valor de cada ação aberta (os vários métodos e o crescimento implícito)."""
    stocks = [pos for pos in p.open_positions if pos.asset.kind == "stock"]
    funds = {f.ticker: f for f in Fundamental.query.filter(Fundamental.ticker.in_([x.asset.ticker for x in stocks] or [""]))}
    out = []
    for pos in sorted(stocks, key=lambda x: -x.value_eur):
        f = funds.get(pos.asset.ticker)

        def pick(name, f=f):
            manual = getattr(f, "manual_" + name, None) if f else None
            return (manual, True) if manual is not None else ((getattr(f, name) if f else None), False)
        eps, eps_manual = pick("eps")
        bvps, bvps_manual = pick("bvps")
        fcf, fcf_manual = pick("fcf")
        growth, growth_manual = pick("growth")
        owner, owner_manual = pick("owner")
        nopat, nopat_manual = pick("nopat")
        net_cash, net_cash_manual = pick("net_cash")
        price = p.book.price(pos.asset.ticker, p.as_of)
        v = valuation.value_stock(price, eps=eps, eps_forward=f.eps_forward if f else None, bvps=bvps, fcf=fcf,
                                  growth=growth, dividends=_dividend_per_share(p, pos.asset.ticker),
                                  div_growth=_dividend_growth(pos.asset.ticker, p.as_of), owner_earnings=owner,
                                  nopat=nopat, net_cash=net_cash, aaa_yield=_aaa_yield() or valuation.AAA_YIELD)
        v.update(ticker=pos.asset.ticker, name=pos.asset.name, currency=pos.asset.currency, asset=pos.asset,
                 inputs={"eps": eps, "bvps": bvps, "fcf": fcf, "growth": growth, "owner": owner, "nopat": nopat,
                         "net_cash": net_cash},
                 manual={"eps": eps_manual, "bvps": bvps_manual, "fcf": fcf_manual, "growth": growth_manual,
                         "owner": owner_manual, "nopat": nopat_manual, "net_cash": net_cash_manual},
                 updated=f.updated if f else None)
        out.append(v)
    return out


def _xray(p):
    """Raio-X dos ETF (exposição real) e o estado da composição de cada ETF; nunca parte a página."""
    from .services import xray
    try:
        out = xray.xray(p)
        return out and {**out, "etfs": xray.status(p)}
    except Exception:
        current_app.logger.exception("raio-x dos ETF")
        return None


def _costs(p):
    """Os custos da carteira (comissões, TER dos ETF e retenções a mais), com o país de cada dividendo."""
    tickers = {t.asset.ticker: t.asset.currency for t in p.transactions if t.asset is not None}
    ters = {i.ticker: i.ter for i in Instrument.query.filter(Instrument.ticker.in_(list(tickers) or [""]))}
    return costs.cost_report(p, insights.countries_of(tickers), ters)


def _rating(value, thresholds, labels):
    if value is None:
        return "—"
    for t, label in zip(thresholds, labels):
        if value < t:
            return label
    return labels[-1]


@bp.route("/desempenho")
def desempenho():
    c = ctx.build("desempenho", "Desempenho")
    p = c["p"]
    period = (request.args.get("periodo") or "MAX").upper()
    period = period if period in dict(PERIODS) else "MAX"
    # os mesmos índices de comparação da Visão Geral; escolha múltipla, por omissão só a carteira (?bench=a,b)
    chosen = [t for t in (request.args.get("bench") or "").split(",") if t in OVERVIEW_TICKERS]
    perf = p.performance(period, OVERVIEW_TICKERS, risk_free=data.risk_free()) if p.transactions else None
    c.update(period=period, periods=PERIODS, period_label=dict(PERIODS)[period], bench_chosen=chosen, perf=perf,
             bench_options=[b for t in OVERVIEW_TICKERS for b in p.benchmarks if b.ticker == t])
    if perf:
        r = perf["risk"]
        good = ["Fraco", "Normal", "Bom", "Excelente"]
        heat = {}
        for key, ret in perf["monthly"]:
            y, m = key.split("-")
            heat.setdefault(int(y), {})[int(m)] = ret
        years = [k for k, _ in perf["yearly"]]
        # «E se tivesse investido no índice?»: o resumo de cada índice, para a tabela
        final = perf["value"][-1]
        shadows = [{"ticker": b["ticker"], "name": b["name"], "color": b["color"], "final": b["shadow"]["final"], "gain": b["shadow"]["gain"],
                    "irr": b["shadow"]["irr"], "diff": final - b["shadow"]["final"]}
                   for b in perf["benchmarks"] if b.get("shadow")]
        c.update(
            shadows=shadows,
            merit_name=next((x.name for x in p.benchmarks if x.ticker == MERIT_BENCHMARK), "S&P 500"),
            ratings={"sharpe": _rating(r["sharpe"], [0.5, 1, 2], good),
                     "sortino": _rating(r["sortino"], [0.5, 1.5, 3], good),
                     "calmar": _rating(r["calmar"], [0.5, 1, 3], good),
                     "volatility": _rating(r["volatility"], [0.10, 0.20], ["Baixa", "Moderada", "Alta"]),
                     "max_drawdown": _rating(-r["max_drawdown"], [0.10, 0.25], ["Baixo", "Moderado", "Elevado"])},
            heat=dict(sorted(heat.items())),
            chart=ctx.js_json(_round({
                "dates": perf["dates"], "twr": perf["twr"], "drawdown": perf["drawdown"], "yearly": perf["yearly"],
                "benches": [{"ticker": b["ticker"], "name": b["name"], "color": b["color"], "twr": b["twr"],
                             "drawdown": b["drawdown"], "total": b["total"], "cagr": b["cagr"],
                             "yearly": [dict(b["yearly"]).get(k) for k in years],
                             # o mesmo dinheiro, nos mesmos dias, no índice (valor em euros, arredondado ao euro)
                             "shadow": b["shadow"] and [round(x) for x in b["shadow"]["value"]]}
                            for b in perf["benchmarks"]],
                "value": [round(x) for x in perf["value"]],
                "chosen": chosen,
                "merit": perf["merit"] and {k: perf["merit"][k] for k in ("monthly_excess", "yearly_excess", "sorted")},
            })),
        )
    return render_template("pages/desempenho.html", **c)


@bp.route("/dividendos")
def dividendos():
    c = ctx.build("dividendos", "Dividendos")
    p = c["p"]
    announced = data.dividend_history()
    s = p.dividend_summary(announced) if p.transactions else None
    c["s"] = s
    if p.transactions:
        confirmed = {}
        for ev in Event.query.filter(Event.kind == "ex_dividend", Event.date > p.as_of):
            confirmed.setdefault(ev.instrument, []).append(ev.date)
        c["calendar"] = p.dividend_calendar(announced, confirmed)
    if s and s["records"]:
        today, years = p.as_of, s["years"]
        start = _int(request.args.get("desde"), years[0])
        start = start if start in years else years[0]
        cur, prev = today.year, today.year - 1
        per_asset = {}
        for d in s["records"]:
            if d.date.month <= today.month and d.date.year in (cur, prev):
                row = per_asset.setdefault(d.asset.ticker, [0.0, 0.0])
                row[0 if d.date.year == cur else 1] += d.net_eur
        ytd_cur = sum(v for (y, m), v in s["by_month"].items() if y == cur and m <= today.month)
        ytd_prev = sum(v for (y, m), v in s["by_month"].items() if y == prev and m <= today.month)
        by_year = s["by_year"]
        c.update(
            start_year=start, heat_years=[y for y in years if y >= start],
            max_month=max(s["by_month"].values()) if s["by_month"] else 1,
            growth={"cur": ytd_cur, "prev": ytd_prev, "diff": ytd_cur - ytd_prev,
                    "pct": (ytd_cur / ytd_prev - 1) if ytd_prev else None,
                    "assets": sorted(per_asset.items(), key=lambda kv: -(kv[1][0] - kv[1][1])), "month": today.month},
            chart=ctx.js_json({
                "labels": [str(y) for y in years] + [str(today.year + 1)],
                "received": [by_year.get(y, 0) for y in years] + [None],
                "projection": [None] * (len(years) - 1) + [max(s["projection_year"] - by_year.get(today.year, 0), 0),
                                                           s["forward_net"]],
            }),
        )
    return render_template("pages/dividendos.html", **c)


@bp.route("/fiscal")
def fiscal():
    c = ctx.build("fiscal", "Fiscal")
    years = c["p"].fiscal_years() if c["p"].transactions else {}
    sel = _int(request.args.get("ano"))
    year = sel if sel in years else (next(iter(years)) if years else None)
    y = years.get(year)
    # resumo por ativo: o detalhe de cada lote FIFO carrega-se a pedido (/fiscal/lotes) e vai inteiro no CSV
    groups = {}
    for sl in (y["sales"] if y else []):
        g = groups.setdefault(sl.asset.ticker, SimpleNamespace(asset=sl.asset, lots=0, qty=0.0, proceeds=0.0, cost=0.0))
        g.lots += 1
        g.qty += sl.qty
        g.proceeds += sl.proceeds_eur
        g.cost += sl.cost_eur
    c.update(years=years, year=year, y=y, groups=sorted(groups.values(), key=lambda g: g.asset.ticker),
             n_lots=len(y["sales"]) if y else 0, sim_positions=sale_sim.positions() if c["p"].transactions else [],
             year_balance=sale_sim.year_balance() if c["p"].transactions else 0.0,
             harvest_rows=sale_sim.harvest(sale_sim.year_balance()) if c["p"].transactions else [],
             this_year=date.today().year)
    return render_template("pages/fiscal.html", **c)


def _fiscal_sales(year, ticker=None):
    p = data.load_portfolio(data.selected_broker())
    y = p.fiscal_years().get(year)
    if y is None:
        abort(404)
    return [s for s in y["sales"] if ticker is None or s.asset.ticker == ticker]


@bp.route("/fiscal/lotes")
def fiscal_lotes():
    """Linhas FIFO de um ativo num ano (fragmento HTML para a janela de detalhe da página Fiscal)."""
    year, ticker = _int(request.args.get("ano")), request.args.get("ativo", "")
    sales = _fiscal_sales(year, ticker)
    if not sales:
        abort(404)
    return render_template("pages/_fiscal_lotes.html", sales=sales, year=year, ticker=ticker)


@bp.route("/fiscal.csv")
def fiscal_csv():
    """Todas as linhas FIFO das vendas de um ano, pela ordem do formulário (separador ; e UTF-8 com BOM)."""
    year = _int(request.args.get("ano"))
    sales = _fiscal_sales(year)
    out = ["Data venda;Ativo;Data aquisição;Quantidade;Valor realização;Valor aquisição;Mais/menos-valia"]
    for sl in sales:
        out.append(";".join([sl.date.isoformat(), '"' + sl.asset.ticker.replace('"', '""') + '"',
                             sl.acquired.isoformat() if sl.acquired else "anterior ao histórico", repr(sl.qty),
                             repr(round(sl.proceeds_eur, 2)), repr(round(sl.cost_eur, 2)),
                             repr(round(sl.gain_eur, 2))]))
    return Response("\ufeff" + "\n".join(out), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=mais-valias-{year}.csv"})


@bp.route("/relatorio")
def relatorio():
    """Relatório anual numa só página, para imprimir ou guardar em PDF (o PDF é o do browser)."""
    c = ctx.build("fiscal", "Relatório anual")
    p = c["p"]
    years = report.years(p)
    sel = _int(request.args.get("ano"))
    year = sel if sel in years else report.default_year(p)
    r = report.build(c["broker"], year) if years else None
    c.update(years=years, year=year, r=r, chart_data=ctx.js_json(r["chart"] | {"monthly_div": r["monthly_div"]}) if r else "null",
             generated=date.today())
    return render_template("pages/relatorio.html", **c)


@bp.route("/fiscal/simulacao.csv")
def fiscal_simulation_csv():
    """A simulação de venda em CSV: lotes FIFO, totais, imposto antes e depois e perdas por realizar."""
    from .api import ApiError, simulate_sale_result
    a = request.args
    try:
        r = simulate_sale_result(a.get("ativo", ""), a.get("qtd"), a.get("preco"), a.get("comissoes"))
    except ApiError as exc:
        return Response(str(exc), status=400, mimetype="text/plain")
    n = lambda v: repr(round(v, 2))  # noqa: E731
    q = lambda s: '"' + str(s).replace('"', '""') + '"'  # noqa: E731
    out = [f"Simulação de venda (não é uma venda real);{q(r['ticker'])};{q(r['broker'])};"
           f"quantidade {r['qty']!r};preço {r['price']!r} {r['currency']};comissões {r['fees']!r}",
           "Data aquisição;Quantidade;Valor aquisição;Valor realização;Mais/menos-valia"]
    for ln in r["lots"]:
        out.append(";".join([ln["acquired"] or "anterior ao histórico", repr(ln["qty"]), n(ln["cost_eur"]),
                             n(ln["proceeds_eur"]), n(ln["gain_eur"])]))
    out += [f"Total;{r['qty']!r};{n(r['cost'])};{n(r['proceeds'])};{n(r['gain'])}", "",
            f"Saldo de mais-valias {r['year']};antes;{n(r['balance_before'])};depois;{n(r['balance_after'])}",
            f"Imposto estimado ({round(r['rate'] * 100)}%);antes;{n(r['tax_before'])};depois;{n(r['tax_after'])};"
            f"diferença;{n(r['tax_delta'])}", "", "Perdas por realizar;Corretora;Menos-valia;Poupança no imposto;Acumulado"]
    for h in r["harvest"]:
        out.append(";".join([q(h["ticker"]), q(h["broker"]), n(h["loss"]), n(h["saving"]), n(h["cumulative"])]))
    name = "".join(ch for ch in r["ticker"] if ch.isalnum() or ch in "-._") or "ativo"
    return Response("\ufeff" + "\n".join(out), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=simulacao-venda-{name}.csv"})


def _radar_lists():
    """As listas de acompanhamento com o número de ações de cada uma (para os separadores e o «Guardar»)."""
    from .services import tracking
    lists = tracking.watch_lists()
    counts = dict(db.session.query(WatchItem.list_id, db.func.count(WatchItem.id)).group_by(WatchItem.list_id).all())
    return [SimpleNamespace(id=wl.id, title=wl.title, n=counts.get(wl.id, 0)) for wl in lists]


@bp.route("/radar/acompanhamento")
def acompanhamento():
    """Prospeção → uma lista de acompanhamento, em quadro: os estados (colunas) e as ações (cartões), com os
    parâmetros e os alertas de cada uma."""
    from .services import lenses, tracking, triage
    c = ctx.build("radar", "Prospeção")
    fired = tracking.check()
    lists = _radar_lists()
    sel = _int(request.args.get("lista"))
    current = next((wl for wl in lists if wl.id == sel), lists[0])
    states = tracking.states(current.id)
    currencies = {i.ticker: i for i in Instrument.query.all()}
    tab = {r["t"]: r for r in (triage.table() or {}).get("rows", [])}
    cards = {st.id: [] for st in states}
    count = 0
    for w in WatchItem.query.filter_by(list_id=current.id).order_by(WatchItem.position, WatchItem.id).all():
        inst = currencies.get(w.instrument)
        rules = WatchRule.query.filter_by(watch_id=w.id).order_by(WatchRule.id).all()
        t = tab.get(w.instrument)
        v = tracking.values(w)
        answers = triage.answers(w.instrument)
        cards.setdefault(w.state_id, []).append(SimpleNamespace(
            w=w, inst=inst, currency=inst.currency if inst else "", v=v, rules=rules, t=t,
            name=(t["n"] if t else None) or (inst.instrument_name if inst else None) or w.instrument,
            enters=[lenses.LENSES[k]["name"] for k in lenses.REAL if t and t["st"].get(k) == "entra"],
            method=lenses.LENSES.get(w.method) if w.method in lenses.REAL else None, answers=answers,
            answered=sum(1 for k, _, _ in triage.QUESTIONS if answers.get(k))))
        count += 1
    c.update(states=states, cards=cards, count=count, fired_now=fired, recent=tracking.recent(),
             kinds=tracking.KINDS, groups=tracking.GROUPS, describe=tracking.describe, chip=tracking.chip,
             method_short=tracking.METHOD_SHORT, evaluate=tracking.evaluate, lists=lists, current_list=current,
             priorities=tracking.PRIORITIES, questions=triage.QUESTIONS,
             rules_json=lambda rules: [{"kind": r.kind, "threshold": r.threshold, "alert": bool(r.alert)} for r in rules],
             portfolio_fired=portfolio_alerts.check(),
             instruments=Instrument.query.filter(Instrument.kind != "index").order_by(Instrument.ticker).all())
    return render_template("pages/acompanhamento.html", **c)


@bp.route("/radar/lista/<int:list_id>.json")
def lista_json(list_id):
    """«Exportar»: a lista num ficheiro JSON (estados, ações, notas, respostas e parâmetros)."""
    import json
    from .models import WatchList
    from .services import tracking
    wl = db.session.get(WatchList, list_id)
    if wl is None:
        abort(404)
    name = "".join(ch for ch in wl.title if ch.isalnum() or ch in "-_ ").strip().replace(" ", "-") or "lista"
    return Response(json.dumps(tracking.export_list(wl), ensure_ascii=False, indent=2), mimetype="application/json",
                    headers={"Content-Disposition": f"attachment; filename=lista-{name}.json"})


@bp.route("/oportunidades")
def oportunidades_antiga():
    """O endereço antigo das Oportunidades (agora a triagem, o primeiro separador de Prospeção)."""
    from flask import redirect
    return redirect("/radar")


def _short(v, digits=4):
    """Um número com poucos algarismos significativos (a tabela da triagem vai inteira para a página)."""
    if v is None:
        return None
    return float(f"{v:.{digits}g}")


@bp.route("/radar")
def triagem():
    """Prospeção → Ações: a triagem das ações do mundo pelas lentes dos grandes investidores. A tabela filtra-se
    na página; ao clicar numa ação, a ficha abre ao lado."""
    from .services import lenses, triage
    c = ctx.build("radar", "Prospeção")
    tab = triage.table()
    order = lenses.REAL + ["varias"]
    code = {"entra": "e", "quase": "q", "falha": "f", None: "-"}
    rows = []
    for r in (tab or {}).get("rows", []):
        rows.append([r["t"], r["n"], r["c"], r["g"], r["s"], r["cur"], _short(r["p"]), _short(r["cap"], 3),
                     _short(r["pe"], 3), _short(r["pb"], 3), _short(r["roe"], 3), _short(r["rg"], 3),
                     _short(r["dv"], 3), _short(r["de"], 3), "".join(code[r["st"][k]] for k in order), r["k"],
                     1 if r["full"] else 0])
    watched = {}
    for w in WatchItem.query.all():
        watched.setdefault(w.instrument, []).append(w.list_id)
    lens_list = [{"key": k, "name": v["name"], "sub": v["sub"], "text": v["text"]}
                 for k, v in lenses.LENSES.items()]
    c.update(tab=tab, lists=_radar_lists(), lens_list=lens_list,
             triage_json=ctx.js_json({"order": order, "rows": rows, "watched": watched}),
             regions=sorted({r["g"] for r in (tab or {}).get("rows", [])}),
             sectors=sorted({r["s"] for r in (tab or {}).get("rows", []) if r["s"]}))
    return render_template("pages/triagem.html", **c)


@bp.route("/radar/acao/<ticker>")
def triagem_acao(ticker):
    """A ficha completa de uma ação (o painel ao lado da tabela da triagem)."""
    from .services import lenses, moat, triage, yahoo
    ticker = ticker.strip().upper()[:32]
    try:
        d = triage.detail(ticker)
    except yahoo.YahooError as exc:
        return render_template("pages/_triagem_ficha.html", error=str(exc), ticker=ticker)
    in_lists = [w.list_id for w in WatchItem.query.filter_by(instrument=ticker).all()]
    return render_template("pages/_triagem_ficha.html", d=d, lenses=lenses.LENSES, real=lenses.REAL,
                           a=moat.get(ticker), u=moat.checklist(ticker), pillars=moat.PILLARS, tests=moat.TESTS,
                           lists=_radar_lists(), in_lists=in_lists, error=None, ticker=ticker)


def radar_instruments():
    """Os ativos seguidos em Prospeção, do mais recente para o mais antigo, sem repetir."""
    out = {}
    for w in WatchItem.query.order_by(WatchItem.creation.desc()).all():
        inst = db.session.get(Instrument, w.instrument)
        if inst is not None and inst.ticker not in out:
            out[inst.ticker] = inst
    return list(out.values())


def _news_sources():
    raw = Setting.get("news_sources")
    return list(news_svc.PROVIDERS) if raw is None else raw.split(",")


@bp.route("/noticias")
def noticias():
    """Notícias dos ativos da carteira selecionada no topo (ou de todas), do mercado e dos ativos do Radar: Finnhub,
    Google Notícias, Yahoo Finance e Marketaux."""
    from .services import news
    c = ctx.build("noticias", "Notícias")
    if not news.selected():  # todas as fontes desligadas em Definições: nada a pedir
        c.update(news_off=True)
        return render_template("pages/noticias.html", **c)
    p = c["p"]
    insts = [pos.asset for pos in p.open_positions]
    tickers = [a.ticker for a in insts]
    watch = radar_instruments()
    watch_tickers = [a.ticker for a in watch]
    errors = news.refresh([t for t in dict.fromkeys(tickers + watch_tickers) if not t.startswith("DEMO-")])
    rows = news.items(tickers)
    radar_rows = news.items(watch_tickers) if watch_tickers else []
    by_ticker = {a.ticker: a for a in watch + insts}
    c.update(news_rows=rows, market_rows=news.items(market=True), news_errors=errors, news_assets=insts,
             news_by_ticker=by_ticker, news_missing=news.without_news(insts, {n.ticker for n in rows}),
             news_providers=news.PROVIDERS, news_enabled=news.enabled(), news_has_key=bool(news.api_key()),
             news_counts={t: sum(1 for n in rows if n.ticker == t) for t in tickers},
             radar_rows=radar_rows, radar_assets=watch,
             radar_missing=news.without_news(watch, {n.ticker for n in radar_rows}),
             radar_counts={t: sum(1 for n in radar_rows if n.ticker == t) for t in watch_tickers})
    return render_template("pages/noticias.html", **c)


@bp.route("/importar")
def importar():
    c = ctx.build("importar", "Importar")
    names = {b.id: b.broker_name for b in Broker.query.all()}
    batches = ImportBatch.query.order_by(ImportBatch.creation.desc()).all()
    summary = {}
    for b in batches:
        s = summary.setdefault(b.broker, {"broker": names.get(b.broker, "?"), "count": 0, "first": None, "last": None})
        s["count"] += 1
        if b.first_date and (not s["first"] or b.first_date < s["first"]):
            s["first"] = b.first_date
        if b.last_date and (not s["last"] or b.last_date > s["last"]):
            s["last"] = b.last_date
    c.update(supported=BROKERS, instructions=INSTRUCTIONS, batches=batches, broker_names=names,
             summary=list(summary.values()))
    return render_template("pages/importar.html", **c)


@bp.route("/transacoes")
def transacoes():
    c = ctx.build("transacoes", "Transações")
    page_size = 100
    q = Transaction.query
    typ = request.args.get("tipo")
    if typ in LABELS:
        q = q.filter_by(type=typ)
    else:
        typ = None
    if c["broker"]:
        q = q.filter_by(broker=int(c["broker"]))
    total = q.count()
    pages = max((total + page_size - 1) // page_size, 1)
    page = min(max(_int(request.args.get("pagina"), 1), 1), pages)
    rows = (q.order_by(Transaction.date.desc(), Transaction.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    c.update(total=total, page=page, pages=pages, rows=rows,
             broker_names={b.id: b.broker_name for b in c["brokers"]}, labels=LABELS, tipo=typ,
             today=date.today().isoformat())
    return render_template("pages/transacoes.html", **c)


@bp.route("/definicoes")
def definicoes():
    from flask import current_app
    c = ctx.build("definicoes", "Definições")
    tickers = sorted({t.asset.ticker for t in c["p"].transactions if t.asset})
    c.update(instruments=_asset_rows(c["p"], tickers),
             last_price=db.session.query(db.func.max(Price.date)).scalar(),
             db_path=current_app.config["DB_PATH"], backups=backups.list_backups(current_app.config["DB_PATH"]),
             portable=is_portable(),
             yfinance=yfinance_available(),
             risk_free_pct=round(data.risk_free() * 100, 2), last_refresh=Setting.get("last_refresh"), refresh_report=Setting.get("refresh_report"),
             stale_days=ctx.stale_days(), widget_pages=widgets.customized(),
             finnhub_env=news_svc.key_from_env(), finnhub_saved=bool(Setting.get("finnhub_key")),
             marketaux_env=news_svc.marketaux_from_env(), marketaux_saved=bool(Setting.get("marketaux_key")),
             news_providers=news_svc.PROVIDERS, news_sources=_news_sources(), news_stats=news_svc.stats(), news_last=news_svc.last_results(),
             password_env=bool(auth.env_password()))
    return render_template("pages/definicoes.html", **c)


def _asset_rows(p, tickers):
    """Ativos das Definições com o estado das cotações; por omissão só se mostram os que precisam de atenção."""
    insts = Instrument.query.filter(Instrument.ticker.in_(tickers or [""])).order_by(Instrument.ticker).all()
    latest = db.session.query(Price.instrument, db.func.max(Price.date).label("d")).group_by(Price.instrument).subquery()
    last = {r.instrument: (r.date, r.close) for r in db.session.query(Price).join(
        latest, db.and_(Price.instrument == latest.c.instrument, Price.date == latest.c.d))}
    held = {pos.asset.ticker for pos in p.open_positions}
    missing = set(refresh_state()[2])
    rows = []
    for i in insts:
        date_, close = last.get(i.ticker, (None, None))
        is_held = i.ticker in held
        # "sem cotações": nenhuma guardada; numa posição aberta conta também o que a última atualização não encontrou
        # (nas vendidas essa lista pode estar desatualizada, por isso só se olha para as cotações guardadas)
        no_quotes = date_ is None or (is_held and i.ticker in missing)
        rows.append(SimpleNamespace(i=i, ticker=i.ticker, held=is_held, no_quotes=no_quotes,
                                    last_date=date_, last_close=close))
    return rows


@bp.route("/planeamento")
def planeamento():
    from .services import planning
    c = ctx.build("planeamento", "Planeamento")
    p = c["p"]
    if not p.transactions:
        return render_template("pages/planeamento.html", **c)
    plan = planning.build(p, request.args)
    if "chart" in plan:
        plan["chart"] = ctx.js_json(plan["chart"])
    c.update(plan=plan, cfg=plan["cfg"], q=lambda **kw: planning.query(plan["cfg"], **kw), duration=planning.duration,
             levels=planning.LEVELS)
    return render_template("pages/planeamento.html", **c)


@bp.route("/patrimonio")
def patrimonio():
    c = ctx.build("patrimonio", "Património")
    p_all = data.load_portfolio(None)  # o património conta sempre todas as corretoras
    summary = networth.summary(p_all, _saved_expenses())
    growth = networth.growth(p_all)
    items = networth.assets()
    previous = networth.previous_values(items)
    c.update(today=date.today(), late=networth.reminder(items), monthly=[
        {"name": a.name, "label": a.label, "cat": OTHER_CATEGORIES[a.category][0], "icon": OTHER_CATEGORIES[a.category][1],
         "color": OTHER_CATEGORIES[a.category][2], "debt": a.debt, "value": a.value, "updated": a.updated,
         "previous": previous.get(a.id)} for a in items])
    c.update(nw=summary, categories=OTHER_CATEGORIES, liquidity=LIQUIDITY, discounts=networth.SALE_DISCOUNTS,
             growth=growth, chart=ctx.js_json({"history": networth.history(p_all), "allocation": summary["allocation"],
                                               "growth": growth}))
    return render_template("pages/patrimonio.html", **c)


def _saved_expenses():
    """Despesas anuais guardadas no Planeamento (None se ainda não foram indicadas: não se adivinha)."""
    try:
        v = float(Setting.get("fire_expenses"))
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


THEME_COLORS = {"light": "#ffffff", "dark": "#212529", "purple": "#272236"}


@bp.route("/manifest.webmanifest")
def manifest():
    """O manifesto da aplicação instalada com a cor do tema escolhido (?tema=, ou o cookie pm_theme).

    Alguns browsers pintam a barra do sistema da aplicação instalada só com a cor do manifesto e ignoram a meta
    theme-color da página; por isso o manifesto acompanha o tema. No Automático fica a cor do tema claro."""
    import json
    theme = request.args.get("tema") or request.cookies.get("pm_theme")
    color = THEME_COLORS.get(theme, THEME_COLORS["light"])
    with current_app.open_resource("static/manifest.webmanifest") as f:
        data = json.load(f)
    data["theme_color"] = data["background_color"] = color
    resp = current_app.response_class(json.dumps(data, ensure_ascii=False), mimetype="application/manifest+json")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.route("/sw.js")
def service_worker():
    # servido na raiz para o service worker controlar todas as páginas da aplicação
    resp = current_app.send_static_file("js/sw.js")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Content-Type"] = "text/javascript; charset=utf-8"
    return resp


@bp.route("/ping")
def ping():
    """Resposta vazia: a página usa-a para saber se a aplicação está a correr (modo offline)."""
    return "", 204, {"Cache-Control": "no-store"}
