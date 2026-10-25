"""Ponte entre a base de dados SQLite e o motor de cálculo (Python puro)."""
import threading
from collections import defaultdict
from datetime import date
from types import SimpleNamespace

from flask import g
from sqlalchemy import event, func
from sqlalchemy.orm import Session

from ..engine.portfolio import Instrument as EngineInstrument, Portfolio, PriceBook, Tx
from ..models import Broker, FxRate, Instrument, Price, Setting, Transaction, db


def instruments(tickers=None):
    q = Instrument.query
    if tickers is not None:
        if not tickers:
            return {}
        q = q.filter(Instrument.ticker.in_(list(tickers)))
    return {i.ticker: EngineInstrument(i.ticker, i.instrument_name or i.ticker, i.kind or "stock", i.sector,
                                       i.currency or "EUR", i.color or "#64748b") for i in q.all()}


def _series(sql):
    """Lê (chave, data, valor) diretamente do SQLite: com centenas de milhares de cotações, o ORM é lento."""
    out, days = defaultdict(list), {}
    cursor = db.session.connection().connection.cursor()  # cursor do sqlite3: devolve tuplos simples
    try:
        rows = cursor.execute(sql).fetchall()
    finally:
        cursor.close()
    for key, d, v in rows:
        day = days.get(d)
        if day is None:
            day = days[d] = date.fromisoformat(d) if isinstance(d, str) else d
        out[key].append((day, v))
    return out


def _market_data():
    """Todas as cotações e câmbios, partilhados por todas as corretoras até os dados mudarem."""
    rev = _state["rev"]
    with _lock:
        shared = _cache.get(("market", rev))
    if shared is None:
        shared = (_series("SELECT instrument, date, close FROM price"),
                  _series("SELECT currency, date, rate FROM fx_rate"))
        with _lock:
            if rev == _state["rev"]:
                _cache[("market", rev)] = shared
    return shared


def _prices(tickers):
    prices = _market_data()[0]
    return defaultdict(list, {t: list(prices[t]) for t in tickers if t in prices})


def _fx(currencies):
    fx = _market_data()[1]
    return defaultdict(list, {c: fx[c] for c in currencies if c and c != "EUR" and c in fx})


TRADE_TYPES = ("BUY", "SELL", "TRANSFER_IN", "TRANSFER_OUT")


def _with_trade_prices(prices, insts, fx_book):
    """Completa as cotações com os preços das transações (de todas as corretoras).

    Só preenchem os dias sem cotação real e são convertidos para a moeda do ativo; assim os
    gráficos funcionam sem internet e o resultado não depende da ordem de importação.
    """
    rows = (db.session.query(Transaction.instrument, Transaction.date, Transaction.price, Transaction.currency)
            .filter(Transaction.instrument.in_(list(insts)), Transaction.type.in_(TRADE_TYPES),
                    Transaction.price > 0).all())
    have = {}  # dias com cotação real, só para os ativos com transações
    extra = {}
    for ticker, d, price, cur in rows:
        days = have.get(ticker)
        if days is None:
            days = have[ticker] = {day for day, _ in prices.get(ticker, ())}
        if d in days:
            continue
        target = insts[ticker].currency
        if cur != target:
            price = price / fx_book.fx(cur, d) * fx_book.fx(target, d)
        extra[(ticker, d)] = price  # vários no mesmo dia: fica o último
    for (ticker, d), price in extra.items():
        prices[ticker].append((d, price))
    return prices


def transactions(broker=None):
    q = Transaction.query
    if broker:
        q = q.filter_by(broker=int(broker))
    return q.order_by(Transaction.date, Transaction.id).all()


# ------------------------------------------------------------------ cache entre pedidos
# Calcular a carteira lê todas as cotações (centenas de milhares de linhas depois de atualizar) e refaz o
# valor dia a dia desde a primeira transação: ~2 s. Como os dados só mudam ao importar, editar ou
# atualizar cotações, a carteira calculada fica em memória até haver uma escrita nessas tabelas.
_TRACKED = (Transaction, Price, FxRate, Instrument, Broker)
_lock = threading.Lock()
_state = {"rev": 0}
_cache = {}  # (broker, revisão, dia) -> Portfolio


_warm = {"app": None, "timer": None}


def invalidate():
    """Esquece as carteiras calculadas (chamado automaticamente a cada escrita nos dados)."""
    with _lock:
        _state["rev"] += 1
        _cache.clear()
    schedule_warm()


def schedule_warm(app=None, delay=1.5):
    """Calcula a carteira em segundo plano, para a próxima página a encontrar pronta.

    Espera um pouco depois da última alteração: uma atualização de cotações grava ativo a ativo.
    """
    if app is not None:
        _warm["app"] = app
    app = _warm["app"]
    if app is None or app.config.get("TESTING"):
        return
    with _lock:
        if _warm["timer"]:
            _warm["timer"].cancel()
        _warm["timer"] = t = threading.Timer(delay, _warm_now, args=(app,))
        t.daemon = True
        t.start()


def _warm_now(app):
    with app.app_context():
        try:
            load_portfolio(None)
            broker = Setting.get("broker")
            if broker:
                load_portfolio(broker)
        except Exception:  # é só uma antecipação: o pedido seguinte calcula de novo se for preciso
            db.session.rollback()


@event.listens_for(Session, "after_flush")
def _mark_flush(session, _ctx):
    if any(isinstance(o, _TRACKED) for o in (*session.new, *session.dirty, *session.deleted)):
        session.info["pm_changed"] = True


@event.listens_for(Session, "do_orm_execute")
def _mark_bulk(state):
    # query.delete() / query.update() não passam pelo flush
    if state.is_delete or state.is_update or state.is_insert:
        state.session.info["pm_changed"] = True


@event.listens_for(Session, "after_commit")
def _bump(session):
    if session.info.pop("pm_changed", False):
        invalidate()


@event.listens_for(Session, "after_rollback")
def _forget(session):
    session.info.pop("pm_changed", None)


def load_portfolio(broker=None):
    """Carrega a carteira (cache por pedido e entre pedidos, até os dados mudarem)."""
    cache = g.setdefault("pm_portfolios", {})
    if broker in cache:
        return cache[broker]
    key = (broker, _state["rev"], date.today())
    with _lock:
        p = _cache.get(key)
    if p is None:
        p = _compute_portfolio(broker)
        with _lock:
            if key[1] == _state["rev"]:  # só guarda se nada mudou entretanto
                _cache[key] = p
    cache[broker] = p
    return p


def _compute_portfolio(broker):
    rows = transactions(broker)
    benches = [i.ticker for i in Instrument.query.filter_by(kind="index").order_by(Instrument.ticker).all()]
    order = {"^GSPC": 0, "^NDX": 1, "URTH": 2}
    benches.sort(key=lambda t: order.get(t, 9))
    insts = instruments({r.instrument for r in rows if r.instrument} | set(benches))
    txs = [Tx(r.date, r.type, insts.get(r.instrument), r.quantity or 0.0, r.price or 0.0, r.amount or 0.0,
              r.fees or 0.0, r.tax or 0.0, r.currency or "EUR", r.broker, r.result) for r in rows]
    currencies = {r.currency for r in rows} | {i.currency for i in insts.values()} | {"USD"}
    fx = _fx(currencies)
    book = PriceBook(_with_trade_prices(_prices(list(insts)), insts, PriceBook(fx=fx)), fx)
    return Portfolio(txs, book, [insts[b] for b in benches if b in insts])


def brokers():
    """Corretoras com nº de posições abertas e data da primeira transação."""
    since = dict(db.session.query(Transaction.broker, func.min(Transaction.date)).group_by(Transaction.broker))
    qty = defaultdict(float)
    for b, inst, typ, q in db.session.query(Transaction.broker, Transaction.instrument, Transaction.type,
                                            Transaction.quantity).filter(Transaction.type.in_(("BUY", "SELL"))):
        qty[(b, inst)] += (q or 0) if typ == "BUY" else -(q or 0)
    open_by = defaultdict(int)
    for (b, _), q in qty.items():
        if q > 1e-6:
            open_by[b] += 1
    return [SimpleNamespace(name=str(b.id), id=b.id, broker_name=b.broker_name, color=b.color,
                            since=since.get(b.id), positions=open_by.get(b.id, 0))
            for b in Broker.query.order_by(Broker.id).all()]


def selected_broker():
    b = Setting.get("broker")
    if b and b.isdigit() and db.session.get(Broker, int(b)):
        return b
    return None
