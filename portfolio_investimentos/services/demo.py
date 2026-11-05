"""Dados de demonstração: empresas fictícias com preços sintéticos.

    python -m portfolio_investimentos --demo

Apaga as transações existentes e cria uma carteira de exemplo. Os preços dos índices de
referência só são gerados se ainda não existirem cotações reais para eles.
"""
import math
import random
from datetime import date, timedelta

from ..models import (Alert, Broker, Event, Fundamental, FxRate, ImportBatch, Instrument, OtherAsset, OtherAssetValue,
                      Price, Setting, Transaction, WatchItem, db)
from .market import DEFAULT_BENCHMARKS, ensure_benchmarks

START = date(2021, 6, 1)

# ticker, nome, tipo, setor, moeda, preço inicial, crescimento anual, volatilidade, dividendo/ação (trimestral)
INSTRUMENTS = [
    ("DEMO-NVTX", "Nova Tech (fictícia)", "stock", "Tecnologia", "USD", 120, 0.16, 0.32, 0.0),
    ("DEMO-SOLP", "Sol Pharma (fictícia)", "stock", "Farmacêutica", "USD", 85, 0.07, 0.22, 0.45),
    ("DEMO-ATLE", "Atlântico Energia (fictícia)", "stock", "Energia", "EUR", 14, 0.04, 0.25, 0.18),
    ("DEMO-LUSB", "Lusa Bank (fictício)", "stock", "Fintech", "EUR", 6, 0.10, 0.35, 0.06),
    ("DEMO-AUTO", "Motores do Norte (fictícia)", "stock", "Automóvel", "EUR", 22, -0.05, 0.38, 0.25),
    ("DEMO-WRLD", "ETF Ações Globais (fictício)", "etf", "Ações Globais", "EUR", 75, 0.09, 0.15, 0.0),
    ("DEMO-CASH", "ETF Monetário (fictício)", "etf", "Equivalentes de Caixa", "EUR", 100, 0.025, 0.004, 0.0),
]
DEMO_TER = {"DEMO-WRLD": 0.0020}  # custo anual de um dos ETF de exemplo (o outro fica por indicar)
BENCH_PARAMS = {"^GSPC": (4200, 0.11, 0.17), "^NDX": (13500, 0.14, 0.23), "URTH": (125, 0.09, 0.16)}
COLORS = ["#22c55e", "#3b82f6", "#f59e0b", "#06b6d4", "#ef4444", "#a855f7", "#94a3b8"]


def _business_days(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def _walk(rng, days, p0, mu, sigma, market):
    """Movimento browniano geométrico correlacionado com um fator de mercado comum."""
    dt = 1 / 252
    p, out = p0, []
    for i, d in enumerate(days):
        shock = 0.6 * market[i] + 0.8 * rng.gauss(0, 1)
        p *= math.exp((mu - sigma ** 2 / 2) * dt + sigma * math.sqrt(dt) * shock)
        out.append((d, round(p, 4)))
    return out


def _insert_series(model, key_field, key, value_field, rows):
    model.query.filter(getattr(model, key_field) == key).delete()
    db.session.bulk_insert_mappings(model, [{key_field: key, "date": d, value_field: v} for d, v in rows])
    db.session.commit()


def create_demo(seed=42):
    rng = random.Random(seed)
    today = date.today()
    days = list(_business_days(START, today))
    market = [rng.gauss(0, 1) for _ in days]

    ensure_benchmarks()
    for ticker, *_ in DEFAULT_BENCHMARKS:
        if not Price.query.filter_by(instrument=ticker).first():
            p0, mu, sigma = BENCH_PARAMS[ticker]
            _insert_series(Price, "instrument", ticker, "close", _walk(rng, days, p0, mu, sigma, market))

    fx, r = [], 1.18
    for d in days:
        r *= math.exp(rng.gauss(0, 0.004))
        fx.append((d, round(r, 5)))
    if not FxRate.query.filter_by(currency="USD").first():
        _insert_series(FxRate, "currency", "USD", "rate", fx)

    prices = {}
    for i, (ticker, name, kind, sector, cur, p0, mu, sigma, _div) in enumerate(INSTRUMENTS):
        if not db.session.get(Instrument, ticker):
            db.session.add(Instrument(ticker=ticker, instrument_name=name, kind=kind, sector=sector,
                                      currency=cur, data_symbol="", color=COLORS[i],
                                      ter=DEMO_TER.get(ticker)))
            db.session.commit()
        series = _walk(rng, days, p0, mu, sigma, market)
        _insert_series(Price, "instrument", ticker, "close", series)
        prices[ticker] = dict(series)

    for model in (Transaction, ImportBatch, Alert, WatchItem, OtherAssetValue, OtherAsset):
        model.query.delete()
    Broker.query.delete()
    db.session.commit()
    brokers = {}
    for name, color in (("Corretora A", "#0ea5e9"), ("Corretora B", "#ef4444")):
        b = Broker(broker_name=name, color=color)
        db.session.add(b)
        db.session.flush()
        brokers[name] = b.id

    def tx(**kw):
        db.session.add(Transaction(**kw))

    def price_on(ticker, d):
        series = prices[ticker]
        while d not in series:
            d -= timedelta(days=1)
        return series[d]

    fx_map = dict(fx)
    holdings = {t[0]: 0.0 for t in INSTRUMENTS}
    in_broker = {(b, t[0]): 0.0 for b in brokers.values() for t in INSTRUMENTS}  # ações em cada corretora
    meta = {t[0]: t for t in INSTRUMENTS}
    month = date(START.year, START.month, 1)
    first = True
    while month <= today:
        d = month
        while d.weekday() >= 5:
            d += timedelta(days=1)
        if d > today:
            break
        broker = brokers["Corretora A"] if month.month % 3 else brokers["Corretora B"]
        deposit = 5000 if first else 750
        tx(broker=broker, date=d, type="DEPOSIT", amount=deposit, currency="EUR")
        first = False
        budget = deposit * 0.95
        picks = rng.sample([t[0] for t in INSTRUMENTS], 2)
        for ticker in picks:
            cur = meta[ticker][4]
            p = price_on(ticker, d)
            eur_price = p / (fx_map.get(d, 1.18) if cur == "USD" else 1)
            qty = round(budget / 2 / eur_price, 3)
            if qty <= 0:
                continue
            tx(broker=broker, date=d, type="BUY", instrument=ticker, quantity=qty, price=p, fees=1.0, currency=cur)
            holdings[ticker] += qty
            in_broker[(broker, ticker)] += qty
        # venda ocasional para gerar mais/menos-valias (cada corretora só vende o que lá tem)
        if month.month in (3, 11) and month.year < today.year:
            ticker = max(holdings, key=lambda t: in_broker[(broker, t)])
            qty = round(in_broker[(broker, ticker)] * 0.3, 3)
            if qty > 0:
                tx(broker=broker, date=d + timedelta(days=7), type="SELL", instrument=ticker, quantity=qty,
                   price=price_on(ticker, d + timedelta(days=7)), fees=1.0, currency=meta[ticker][4])
                holdings[ticker] -= qty
                in_broker[(broker, ticker)] -= qty
        # dividendos trimestrais
        if month.month in (3, 6, 9, 12):
            pay = d + timedelta(days=14)
            if pay <= today:
                for ticker, qty in holdings.items():
                    dps = meta[ticker][8]
                    if dps and qty > 0:
                        gross = round(qty * dps, 2)
                        tax = round(gross * (0.15 if meta[ticker][4] == "USD" else 0.28), 2)
                        tx(broker=brokers["Corretora A"], date=pay, type="DIVIDEND", instrument=ticker,
                           quantity=qty, amount=gross, tax=tax, currency=meta[ticker][4])
                tx(broker=brokers["Corretora B"], date=pay, type="INTEREST", amount=round(rng.uniform(2, 12), 2),
                   currency="EUR")
        month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)

    db.session.commit()

    # eventos futuros e alertas de exemplo
    Event.query.filter(Event.instrument.like("DEMO-%")).delete(synchronize_session=False)
    for i, ticker in enumerate(("DEMO-NVTX", "DEMO-SOLP", "DEMO-LUSB")):
        db.session.add(Event(instrument=ticker, date=today + timedelta(days=4 + 9 * i), kind="earnings",
                             title="(demo)", timing="antes da abertura",
                             eps_estimate=round(rng.uniform(-0.1, 2.5), 2),
                             revenue_estimate=round(rng.uniform(1e8, 5e10), -6)))
    db.session.add(Alert(instrument="DEMO-NVTX", kind="price_below",
                         threshold=round(prices["DEMO-NVTX"][days[-1]] * 0.9, 2), active=True))
    db.session.add(WatchItem(instrument="DEMO-ATLE", target_price=round(prices["DEMO-ATLE"][days[-1]] * 0.95, 2),
                             note="Comprar abaixo do alvo"))
    _other_assets(rng, today)
    _fundamentals(prices, days[-1], today)
    db.session.commit()
    Setting.set("demo", "1")
    return "Dados de demonstração criados."


# outros ativos (Património): valor inicial, entrada mensal e rendimento anual, há 36 meses
OTHER_ASSETS = [
    ("Conta à ordem (fictícia)", "conta", 6000, 50, 0.0, True),
    ("Depósito a prazo (fictício)", "deposito", 4000, 0, 0.015, True),
    ("Certificados de aforro (fictícios)", "aforro", 10000, 0, 0.025, True),
    ("PPR (fictício)", "ppr", 6000, 100, 0.05, True),
    ("Casa (fictícia)", "imovel", 210000, 0, 0.03, False),
    ("Crédito habitação (fictício)", "credito", 150000, -450, 0.0, False),
]
DEMO_EXPENSES = 24000  # despesas anuais de exemplo (meses de reserva), só se ainda não houver


def _other_assets(rng, today):
    house = None
    for label, category, v0, monthly, rate, fire in OTHER_ASSETS:
        asset = OtherAsset(label=label, category=category, value=v0, fire=fire, updated=today,
                           home=category == "imovel", linked=house.id if category == "credito" and house else None)
        db.session.add(asset)
        db.session.flush()
        if category == "imovel":
            house = asset
        v = v0
        for k in range(36, -1, -1):
            y, m = divmod(today.year * 12 + today.month - 1 - k, 12)
            d = today if k == 0 else date(y, m + 1, 28)
            db.session.add(OtherAssetValue(asset=asset.id, date=d, value=round(v, 2)))
            v = v * (1 + rate) ** (1 / 12) * (1 + rng.gauss(0, 0.002)) + monthly
        asset.value = db.session.query(OtherAssetValue.value).filter_by(asset=asset.id).order_by(
            OtherAssetValue.date.desc()).first()[0]
    if Setting.get("fire_expenses") is None:
        Setting.set("fire_expenses", DEMO_EXPENSES)
        Setting.set("demo_fire_expenses", "1")  # apagado com os dados de demonstração


# dados fundamentais de exemplo (valor de cada ação), como múltiplos do preço final:
# ticker → (preço/lucro, preço/lucro previsto, preço/valor contabilístico, preço/cash flow livre, crescimento,
#           preço/owner earnings, preço/NOPAT, caixa − dívida em % do preço)
DEMO_FUNDAMENTALS = {
    "DEMO-NVTX": (38, 30, 9, 42, 0.15, 36, 40, 0.05),
    "DEMO-SOLP": (17, 15, 4, 19, 0.05, 16, 15, -0.10),
    "DEMO-ATLE": (11, 12, 1.3, 9, 0.02, 10, 12, -0.40),
    "DEMO-LUSB": (9, 8, 1.1, None, 0.07, None, None, None),
    "DEMO-AUTO": (-25, 40, 0.8, None, -0.02, None, 30, -0.60),
}


def _fundamentals(prices, last_day, today):
    for ticker, (pe, pe_fwd, pb, pfcf, growth, poe, pnopat, cash) in DEMO_FUNDAMENTALS.items():
        price = prices[ticker][last_day]
        db.session.merge(Fundamental(ticker=ticker, eps=round(price / pe, 4), eps_forward=round(price / pe_fwd, 4),
                                     bvps=round(price / pb, 4), fcf=round(price / pfcf, 4) if pfcf else None,
                                     growth=growth, owner=round(price / poe, 4) if poe else None,
                                     nopat=round(price / pnopat, 4) if pnopat else None,
                                     net_cash=round(price * cash, 4) if cash is not None else None, updated=today))
