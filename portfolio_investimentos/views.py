"""Páginas da aplicação."""
from datetime import date, timedelta
from types import SimpleNamespace

from flask import Blueprint, current_app, render_template, request

from .engine.portfolio import MERIT_BENCHMARK
from .models import Alert, Broker, ImportBatch, Instrument, News, Price, Setting, Transaction, WatchItem, db
from . import auth
from .services import context as ctx
from .services import data
from .services.importer import BROKERS, INSTRUCTIONS
from .services.market import check_alerts, refresh_state, upcoming_events, yfinance_available

bp = Blueprint("pages", __name__)

PERIODS = [("1M", "1 mês"), ("3M", "3 meses"), ("6M", "6 meses"), ("YTD", "Ano corrente"),
           ("1A", "1 ano"), ("3A", "3 anos"), ("5A", "5 anos"), ("MAX", "Máx")]
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


def perf_payload(p, period, benchmarks=None):
    perf = p.performance(period, benchmarks, risk_free=data.risk_free())
    if not perf:
        return None
    perf["start"], perf["end"] = perf["start"].isoformat(), perf["end"].isoformat()
    return perf


@bp.route("/")
def overview():
    c = ctx.build("overview", "Visão Geral")
    p = c["p"]
    if not p.transactions:
        return render_template("pages/index.html", **c)
    movers = p.movers(5)
    news = {m.asset.ticker: News.query.filter_by(instrument=m.asset.ticker).order_by(News.published_on.desc()).first()
            for m in movers}
    held = [pos.asset.ticker for pos in p.open_positions]
    events = upcoming_events(held)
    today = date.today()
    week, two = today + timedelta(days=7), today + timedelta(days=14)
    instruments = {i.ticker: i for i in Instrument.query.filter(Instrument.ticker.in_({e.instrument for e in events} or {""}))}
    c.update(
        hero_spark=ctx.js_json(p.series.holdings[-120:]), ytd=p.year_to_date(),
        ath={"value": p.all_time_high("value"), "return": p.all_time_high("return")},
        movers=movers, mover_news=news, events_total=len(events),
        event_groups=[("Próxima semana", [e for e in events if e.date <= week]),
                      ("Daqui a duas semanas", [e for e in events if week < e.date <= two]),
                      ("Mais tarde", [e for e in events if e.date > two][:4])],
        instruments=instruments, fired=check_alerts(p), perf=ctx.js_json(perf_payload(p, "MAX")),
        benchmarks=p.benchmarks,
    )
    return render_template("pages/index.html", **c)


@bp.route("/carteira")
def carteira():
    c = ctx.build("carteira", "Carteira")
    p = c["p"]
    c.update(
        positions=p.open_positions, closed=p.closed_positions, sectors=p.sectors(),
        sparks={pos.asset.ticker: ctx.js_json(p.sparkline(pos.asset.ticker, 30)) for pos in p.open_positions},
        market_bars=[(b.name, p.benchmark_day_change(b), b.color) for b in p.benchmarks],
        total={"invested": p.cost_basis, "value": p.holdings_value, "unrealized": p.unrealized,
               "dividends": sum(x.dividends_eur for x in p.open_positions),
               "fx": sum(x.fx_effect_eur for x in p.open_positions),
               "fees": sum(x.fees_eur for x in p.open_positions),
               "roi": sum(x.roi_eur for x in p.open_positions)},
        alloc=ctx.js_json({k: p.allocation(k) for k in ("asset", "sector", "currency")}),
    )
    return render_template("pages/carteira.html", **c)


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
            chart=ctx.js_json({
                "dates": perf["dates"], "twr": perf["twr"], "drawdown": perf["drawdown"], "yearly": perf["yearly"],
                "bench": b and {"name": b["name"], "color": b["color"], "twr": b["twr"], "drawdown": b["drawdown"],
                                "yearly": [by.get(k) for k, _ in perf["yearly"]]},
                "merit": perf["merit"] and {k: perf["merit"][k] for k in ("monthly_excess", "yearly_excess", "sorted")},
            }),
        )
    return render_template("pages/desempenho.html", **c)


@bp.route("/dividendos")
def dividendos():
    c = ctx.build("dividendos", "Dividendos")
    p = c["p"]
    s = p.dividend_summary() if p.transactions else None
    c["s"] = s
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
    c.update(years=years, year=year, y=years.get(year))
    return render_template("pages/fiscal.html", **c)


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
             alerts=Alert.query.order_by(Alert.active.desc(), Alert.creation.desc()).all(),
             instruments=Instrument.query.filter(Instrument.kind != "index").order_by(Instrument.ticker).all())
    return render_template("pages/radar.html", **c)


@bp.route("/noticias")
def noticias():
    c = ctx.build("noticias", "Notícias")
    held = [pos.asset.ticker for pos in c["p"].open_positions]
    ticker = request.args.get("ticker")
    ticker = ticker if ticker in held else None
    tickers = [ticker] if ticker else held
    news = (News.query.filter(News.instrument.in_(tickers or [""])).order_by(News.published_on.desc()).limit(100).all())
    c.update(held=held, ticker=ticker, news=news, yfinance=yfinance_available())
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
             db_path=current_app.config["DB_PATH"], yfinance=yfinance_available(),
             risk_free_pct=round(data.risk_free() * 100, 2), last_refresh=Setting.get("last_refresh"), refresh_report=Setting.get("refresh_report"),
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
        no_quotes = i.ticker in missing or date_ is None
        rows.append(SimpleNamespace(i=i, ticker=i.ticker, held=i.ticker in held, no_quotes=no_quotes,
                                    last_date=date_, last_close=close,
                                    attention=i.ticker in held or no_quotes))
    return rows


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
