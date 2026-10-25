"""Modelos de dados (SQLite local). Aplicação pessoal: não há utilizadores."""
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class NameMixin:
    @property
    def name(self):
        """Identificador usado pelos templates e pela API."""
        return str(self.id)


class Setting(db.Model):
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text)

    @staticmethod
    def get(key, default=None):
        row = db.session.get(Setting, key)
        return row.value if row else default

    @staticmethod
    def set(key, value):
        row = db.session.get(Setting, key) or Setting(key=key)
        row.value = None if value is None else str(value)
        db.session.add(row)
        db.session.commit()


class Broker(NameMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    broker_name = db.Column(db.String(120), nullable=False, unique=True)
    color = db.Column(db.String(9), default="#3b82f6")


class Instrument(db.Model):
    ticker = db.Column(db.String(32), primary_key=True)
    instrument_name = db.Column(db.String(200))
    kind = db.Column(db.String(8), default="stock")  # stock | etf | index
    sector = db.Column(db.String(80))
    currency = db.Column(db.String(3), default="EUR", nullable=False)
    exchange = db.Column(db.String(40))
    isin = db.Column(db.String(12))
    data_symbol = db.Column(db.String(32))  # símbolo no Yahoo Finance
    color = db.Column(db.String(9), default="#64748b")

    @property
    def name(self):
        return self.ticker


class Price(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    instrument = db.Column(db.String(32), db.ForeignKey("instrument.ticker", ondelete="CASCADE"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    close = db.Column(db.Float, nullable=False)
    __table_args__ = (db.UniqueConstraint("instrument", "date"),)


class FxRate(db.Model):
    """Unidades de `currency` por 1 EUR (ex.: USD 1,1204)."""

    id = db.Column(db.Integer, primary_key=True)
    currency = db.Column(db.String(3), nullable=False)
    date = db.Column(db.Date, nullable=False)
    rate = db.Column(db.Float, nullable=False)
    __table_args__ = (db.UniqueConstraint("currency", "date"),)


class Transaction(NameMixin, db.Model):
    TYPES = ("BUY", "SELL", "DIVIDEND", "DEPOSIT", "WITHDRAWAL", "FEE", "INTEREST", "TRANSFER_IN", "TRANSFER_OUT", "CONVERT_IN", "CONVERT_OUT")

    id = db.Column(db.Integer, primary_key=True)
    broker = db.Column(db.Integer, db.ForeignKey("broker.id"), index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    type = db.Column(db.String(12), nullable=False)
    instrument = db.Column(db.String(32), db.ForeignKey("instrument.ticker"), index=True)
    quantity = db.Column(db.Float, default=0.0)
    price = db.Column(db.Float, default=0.0)
    amount = db.Column(db.Float, default=0.0)
    fees = db.Column(db.Float, default=0.0)
    tax = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(3), default="EUR", nullable=False)
    result = db.Column(db.Float)  # resultado da venda indicado pela corretora (moeda `currency`)
    note = db.Column(db.String(255))
    external_id = db.Column(db.String(64), index=True)
    import_batch = db.Column(db.Integer, db.ForeignKey("import_batch.id"))
    creation = db.Column(db.DateTime, default=datetime.utcnow)


class ImportBatch(NameMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    broker = db.Column(db.Integer, db.ForeignKey("broker.id"))
    source = db.Column(db.String(32), nullable=False)
    filename = db.Column(db.String(255))
    first_date = db.Column(db.Date)
    last_date = db.Column(db.Date)
    imported = db.Column(db.Integer, default=0)
    skipped = db.Column(db.Integer, default=0)
    creation = db.Column(db.DateTime, default=datetime.utcnow)


class WatchItem(NameMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    instrument = db.Column(db.String(32), db.ForeignKey("instrument.ticker"), nullable=False)
    target_price = db.Column(db.Float)
    note = db.Column(db.String(255))
    creation = db.Column(db.DateTime, default=datetime.utcnow)


class Alert(NameMixin, db.Model):
    KINDS = ("price_above", "price_below", "change_pct")

    id = db.Column(db.Integer, primary_key=True)
    instrument = db.Column(db.String(32), db.ForeignKey("instrument.ticker"), nullable=False)
    kind = db.Column(db.String(16), nullable=False)
    threshold = db.Column(db.Float, nullable=False)
    active = db.Column(db.Boolean, default=True)
    triggered_on = db.Column(db.DateTime)
    creation = db.Column(db.DateTime, default=datetime.utcnow)


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    instrument = db.Column(db.String(32), db.ForeignKey("instrument.ticker", ondelete="CASCADE"), nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    kind = db.Column(db.String(16), nullable=False)  # earnings | ex_dividend | dividend_pay
    title = db.Column(db.String(120))
    timing = db.Column(db.String(40))
    eps_estimate = db.Column(db.Float)
    revenue_estimate = db.Column(db.Float)
    amount = db.Column(db.Float)
    estimated = False


class News(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    instrument = db.Column(db.String(32), db.ForeignKey("instrument.ticker", ondelete="CASCADE"), index=True)
    title = db.Column(db.String(500), nullable=False)
    url = db.Column(db.String(1000), unique=True)
    source = db.Column(db.String(120))
    published_on = db.Column(db.DateTime, index=True)


def migrate():
    """Acrescenta colunas novas a bases de dados criadas por versões anteriores (SQLite)."""
    added = {"transaction": {"result": "FLOAT"}}
    with db.engine.begin() as conn:
        for table, cols in added.items():
            existing = {r[1] for r in conn.exec_driver_sql(f'PRAGMA table_info("{table}")')}
            for col, typ in cols.items():
                if existing and col not in existing:
                    conn.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN {col} {typ}')
