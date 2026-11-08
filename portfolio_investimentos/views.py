"""Páginas da aplicação."""
import math
from datetime import date, timedelta
from types import SimpleNamespace

from flask import Blueprint, Response, abort, current_app, render_template, request

from .engine import costs, stress, valuation
from .engine.formatting import parse_number
from .engine.portfolio import MERIT_BENCHMARK
from .models import (LIQUIDITY, OTHER_CATEGORIES, Alert, Broker, DividendHistory, Event, Fundamental, ImportBatch,
                     Instrument, Price, Setting, Transaction, WatchItem, db)
from . import auth
from .services import context as ctx
from .services import backups, cerne, data, insights, market, networth, portfolio_alerts, widgets
from .services import news as news_svc
from .services.importer import BROKERS, INSTRUCTIONS
from .services.market import check_alerts, refresh_state, upcoming_events, yfinance_available

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
ALERT_KINDS = {"price_above": "Preço acima de", "price_below": "Preço abaixo de",
               "change_pct": "Variação diária (±%) superior a"}


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
                        "gain_pct": perf["return_pct"], "twr": perf["twr_total"]},
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
        instruments=instruments, fired=check_alerts(p), portfolio_fired=portfolio_alerts.check(), perf=ctx.js_json(perf_ytd), hero=(perf_ytd or {}).get("summary"),
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
        aaa_yield=_aaa_yield() or valuation.AAA_YIELD,
        core=_core(p), core_instruments=Instrument.query.filter(Instrument.kind != "index").order_by(Instrument.ticker).all(),
    )
    return render_template("pages/carteira.html", **c)


def _core(p):
    """A carteira cerne, com o dinheiro novo de ?investir= (vazio ou inválido = 0)."""
    try:
        money = parse_number(request.args.get("investir") or "0")
    except ValueError:
        money = 0.0
    if not math.isfinite(money) or money < 0:
        money = 0.0
    try:
        return cerne.status(p, new_money=money)
    except Exception:  # o cartão nunca pode partir a página
        current_app.logger.exception("carteira cerne")
        return None


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
    bench = request.args.get("bench") or "URTH"
    perf = p.performance(period, risk_free=data.risk_free()) if p.transactions else None
    c.update(period=period, periods=PERIODS, period_label=dict(PERIODS)[period], bench_ticker=bench, perf=perf)
    if perf:
        b = next((x for x in perf["benchmarks"] if x["ticker"] == bench), None)
        r = perf["risk"]
        good = ["Fraco", "Normal", "Bom", "Excelente"]
        heat = {}
        for key, ret in perf["monthly"]:
            y, m = key.split("-")
            heat.setdefault(int(y), {})[int(m)] = ret
        by = dict(b["yearly"]) if b else {}
        c.update(
            bench=b, merit_name=next((x.name for x in p.benchmarks if x.ticker == MERIT_BENCHMARK), "S&P 500"),
            ratings={"sharpe": _rating(r["sharpe"], [0.5, 1, 2], good),
                     "sortino": _rating(r["sortino"], [0.5, 1.5, 3], good),
                     "calmar": _rating(r["calmar"], [0.5, 1, 3], good),
                     "volatility": _rating(r["volatility"], [0.10, 0.20], ["Baixa", "Moderada", "Alta"]),
                     "max_drawdown": _rating(-r["max_drawdown"], [0.10, 0.25], ["Baixo", "Moderado", "Elevado"])},
            heat=dict(sorted(heat.items())),
            chart=ctx.js_json(_round({
                "dates": perf["dates"], "twr": perf["twr"], "drawdown": perf["drawdown"], "yearly": perf["yearly"],
                "bench": b and {"name": b["name"], "color": b["color"], "twr": b["twr"], "drawdown": b["drawdown"],
                                "yearly": [by.get(k) for k, _ in perf["yearly"]]},
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
             n_lots=len(y["sales"]) if y else 0)
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


@bp.route("/radar")
def radar():
    c = ctx.build("radar", "Radar e alertas")
    p = c["p"]
    fired = check_alerts(p)
    watch = []
    for w in WatchItem.query.order_by(WatchItem.creation.desc()).all():
        rows = Price.query.filter_by(instrument=w.instrument).order_by(Price.date.desc()).limit(2).all()
        price = rows[0].close if rows else None
        change = (rows[0].close / rows[1].close - 1) if len(rows) == 2 else None
        inst = db.session.get(Instrument, w.instrument)
        watch.append(SimpleNamespace(name=w.name, instrument=w.instrument, note=w.note, target_price=w.target_price,
                                     price=price, change=change, currency=inst.currency if inst else "EUR",
                                     distance=(price / w.target_price - 1) if price and w.target_price else None))
    c.update(fired_now=fired, watch=watch, kinds=ALERT_KINDS,
             portfolio_fired=portfolio_alerts.check(), portfolio_alert_rows=portfolio_alerts.rows(),
             alerts=Alert.query.order_by(Alert.active.desc(), Alert.creation.desc()).all(),
             instruments=Instrument.query.filter(Instrument.kind != "index").order_by(Instrument.ticker).all())
    return render_template("pages/radar.html", **c)


def _news_sources():
    raw = Setting.get("news_sources")
    return list(news_svc.PROVIDERS) if raw is None else raw.split(",")


@bp.route("/noticias")
def noticias():
    """Notícias dos ativos da carteira selecionada no topo (ou de todas) e do mercado: Finnhub e Marketaux."""
    from .services import news
    c = ctx.build("noticias", "Notícias")
    p = c["p"]
    insts = [pos.asset for pos in p.open_positions]
    tickers = [a.ticker for a in insts]
    errors = news.refresh([t for t in tickers if not t.startswith("DEMO-")])
    rows = news.items(tickers)
    shown = {n.ticker for n in rows}
    by_ticker = {a.ticker: a for a in insts}
    c.update(news_rows=rows, market_rows=news.items(market=True), news_errors=errors, news_assets=insts,
             news_by_ticker=by_ticker, news_missing=news.without_news(insts, shown), news_providers=news.PROVIDERS,
             news_enabled=news.enabled(), news_has_key=bool(news.api_key()),
             news_counts={t: sum(1 for n in rows if n.ticker == t) for t in tickers})
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
    page = max(_int(request.args.get("pagina"), 1), 1)
    rows = (q.order_by(Transaction.date.desc(), Transaction.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    c.update(total=total, page=page, pages=max((total + page_size - 1) // page_size, 1), rows=rows,
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
             yfinance=yfinance_available(),
             risk_free_pct=round(data.risk_free() * 100, 2), last_refresh=Setting.get("last_refresh"), refresh_report=Setting.get("refresh_report"),
             stale_days=ctx.stale_days(), core_plan=cerne.plan(), widget_pages=widgets.customized(),
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


def fire_settings(p):
    """Parâmetros do plano FIRE: os guardados em Planeamento ou, por omissão, valores a partir da carteira."""
    def get(key, default):
        try:
            return float(Setting.get(key))
        except (TypeError, ValueError):
            return default
    s = p.series
    monthly = 0.0
    if s.dates:
        k = next((i for i, d in enumerate(s.dates) if d >= s.dates[-1] - timedelta(days=365)), 0)
        span = max((s.dates[-1] - s.dates[k]).days / 30.44, 1)
        monthly = max((s.net_deposits[-1] - s.net_deposits[k]) / span, 0.0)
    gains = sum(pos.unrealized_eur for pos in p.open_positions)
    gain_share = min(max(gains / p.holdings_value, 0.0), 1.0) if p.holdings_value > 0 else 0.5
    return {"expenses": get("fire_expenses", 12000.0), "swr": get("fire_swr", 4.0),
            "tax": get("fire_tax", round(28 * max(gain_share, 0.5), 1)), "monthly": get("fire_monthly", round(monthly)),
            "custom": Setting.get("fire_expenses") is not None,
            "age": get("fire_age", None), "until": get("fire_until", 90.0), "pension": get("fire_pension", 0.0),
            "pension_age": get("fire_pension_age", 67.0), "stop_age": get("fire_stop_age", None)}


@bp.route("/planeamento")
def planeamento():
    from .engine import fire
    c = ctx.build("planeamento", "Planeamento")
    p = c["p"]
    if not p.transactions:
        return render_template("pages/planeamento.html", **c)
    cfg = fire_settings(p)
    age = cfg["age"] or None
    pension = cfg["pension"] * 14 if age and cfg["pension"] else 0.0  # pensão mensal líquida × 14 meses
    pension_age = cfg["pension_age"] if pension else None
    stop_age = cfg["stop_age"] if age and cfg["stop_age"] else None
    others = networth.fire_extra()  # outros ativos (Património) marcados para o FIRE
    value = p.total_value + others
    plan = fire.plan(value, cfg["expenses"], cfg["swr"] / 100, cfg["tax"] / 100, cfg["monthly"], age=age,
                     pension=pension, pension_age=pension_age, stop_age=stop_age,
                     horizon_age=cfg["until"] if age else None)
    with_pension = None
    if age and pension:
        with_pension = fire.pension_plan(value, cfg["expenses"], cfg["swr"] / 100, cfg["tax"] / 100,
                                         cfg["monthly"], age, pension, pension_age, cfg["until"], stop_age=stop_age)
    life = None
    if age:
        life = fire.lifetime_plan(value, cfg["expenses"], cfg["tax"] / 100, cfg["monthly"], age,
                                  cfg["until"], pension, pension_age, stop_age=stop_age)
    s = p.series
    history = [(d, v) for d, v in zip(s.dates, s.value)]
    shown = life or plan  # com a idade, o gráfico mostra a vida inteira até à idade indicada
    if age:
        end_year = date.today().year + int(cfg["until"] - age)
    else:
        last = plan["date"] or plan["latest"] or plan["earliest"]
        end_year = min((last.year if last else date.today().year) + 30, date.today().year + fire.MAX_YEARS)
    year = lambda d: round(d.year + (d.month - 1) / 12 + (d.day - 1) / 365, 3)  # noqa: E731
    chart = {
        "history": [{"x": year(d), "y": round(v)} for i, (d, v) in enumerate(history)
                    if i % 5 == 0 or i == len(history) - 1],
        "scenarios": [{"name": sc["name"], "rate": sc["rate"], "fire": year(sc["date"]) if sc["date"] else None,
                       "data": [{"x": year(d), "y": round(v)} for d, v in sc["points"] if d.year <= end_year]}
                      for sc in shown["scenarios"]],
        "target": round(plan["number"]), "start": year(history[0][0]) if history else date.today().year,
        "end": end_year,
    }
    # números FIRE como linhas horizontais (o valor na data FIRE do cenário base)
    targets = [{"label": "Para sempre", "value": round(plan["number"]), "color": "#f59e0b"}]
    if with_pension and with_pension["number"] is not None:
        targets.append({"label": f"Para sempre, com a pensão aos {int(pension_age)}",
                        "value": round(with_pension["number"]), "color": "#a855f7"})
    if life and life["number"] is not None:
        label = f"Até aos {int(cfg['until'])} anos" + (f", com a pensão aos {int(pension_age)}" if pension else "")
        targets.append({"label": label, "value": round(life["number"]), "color": "#ec4899"})
    chart["targets"] = targets
    # quando cada cenário chega a cada número FIRE (a investir até lá); no gráfico, um ponto por número e cenário
    calcs = [("Para sempre", "#f59e0b", plan)]
    if with_pension:
        calcs.append((f"Para sempre, com a pensão aos {int(pension_age)}", "#a855f7", with_pension))
    if life:
        calcs.append((f"Até aos {int(cfg['until'])} anos" + (f", com a pensão aos {int(pension_age)}" if pension else ""),
                      "#ec4899", life))
    reach = [{"label": label, "color": color,
              "cells": [{"name": sc["name"], "date": sc["date"], "age": sc["age"], "number": sc["number"]}
                        for sc in calc["scenarios"]]} for label, color, calc in calcs]
    chart["markers"] = [{"label": r["label"], "color": r["color"],
                         "data": [{"x": year(cell["date"]), "y": round(cell["number"]), "s": cell["name"],
                                   "age": None if cell["age"] is None else int(cell["age"])}
                                  for cell in r["cells"] if cell["date"] and cell["date"].year <= end_year]}
                        for r in reach]
    # depois da data FIRE desenhada, a curva "se continuasses a investir" até ao último número que o cenário alcança
    start = date.today().replace(day=1)
    for sc, out in zip(shown["scenarios"], chart["scenarios"]):
        dates = [cell["date"] for r in reach for cell in r["cells"]
                 if cell["name"] == sc["name"] and cell["date"] and cell["date"].year <= end_year]
        last = max(dates, default=None)
        if not last or not sc["date"] or last <= sc["date"]:  # sem data FIRE, a curva já só acumula
            continue
        months = (last.year - start.year) * 12 + last.month - start.month
        pts, _, _ = fire.simulate(value, cfg["monthly"], sc["rate"], start, months, lambda m, v: False,
                                  cfg["expenses"], cfg["tax"] / 100, age, pension, pension_age, stop_age)
        first = year(sc["date"])
        keep = [(d, v) for i, (d, v) in enumerate(pts)
                if year(d) >= first or (i + 1 < len(pts) and year(pts[i + 1][0]) > first)]
        extra = [{"x": m["x"], "y": m["y"]} for mk in chart["markers"] for m in mk["data"]
                 if m["s"] == sc["name"] and m["x"] > first]
        out["more"] = sorted([{"x": year(d), "y": round(v)} for d, v in keep] + extra, key=lambda q: q["x"])
    c.update(fire_extra=others, cfg=cfg, plan=plan, life=life, with_pension=with_pension, chart=ctx.js_json(chart), reach=reach,
             track=fire.monthly_track(s.dates, s.value, plan["number"]))
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
