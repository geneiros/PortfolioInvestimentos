"""Modelos de dados (SQLite local). Aplicação pessoal: não há utilizadores."""
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy


def utcnow():
    """Data e hora UTC sem fuso (como ficam gravadas no SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
    last_quote = db.Column(db.Date)  # último fecho obtido do Yahoo com o data_symbol (atualização incremental)
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
    creation = db.Column(db.DateTime, default=utcnow)


class ImportBatch(NameMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    broker = db.Column(db.Integer, db.ForeignKey("broker.id"))
    source = db.Column(db.String(32), nullable=False)
    filename = db.Column(db.String(255))
    first_date = db.Column(db.Date)
    last_date = db.Column(db.Date)
    imported = db.Column(db.Integer, default=0)
    skipped = db.Column(db.Integer, default=0)
    creation = db.Column(db.DateTime, default=utcnow)


class WatchItem(NameMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    instrument = db.Column(db.String(32), db.ForeignKey("instrument.ticker"), nullable=False)
    target_price = db.Column(db.Float)
    note = db.Column(db.String(255))
    creation = db.Column(db.DateTime, default=utcnow)


class Alert(NameMixin, db.Model):
    KINDS = ("price_above", "price_below", "change_pct")

    id = db.Column(db.Integer, primary_key=True)
    instrument = db.Column(db.String(32), db.ForeignKey("instrument.ticker"), nullable=False)
    kind = db.Column(db.String(16), nullable=False)
    threshold = db.Column(db.Float, nullable=False)
    active = db.Column(db.Boolean, default=True)
    triggered_on = db.Column(db.DateTime)
    creation = db.Column(db.DateTime, default=utcnow)


class DividendHistory(db.Model):
    """Dividendos por ação de um ativo segundo o Yahoo (data ex-dividendo), para projetar posições recentes."""
    id = db.Column(db.Integer, primary_key=True)
    instrument = db.Column(db.String(32), db.ForeignKey("instrument.ticker", ondelete="CASCADE"), nullable=False,
                           index=True)
    date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Float, nullable=False)  # por ação, na moeda do ativo
    __table_args__ = (db.UniqueConstraint("instrument", "date"),)


class LoginFailure(db.Model):
    """Tentativas de login falhadas por endereço (na base de dados: valem para todos os processos e reinícios)."""
    ip = db.Column(db.String(64), primary_key=True)
    count = db.Column(db.Integer, nullable=False, default=0)
    since = db.Column(db.Float, nullable=False)  # instante (time.time) da primeira falha da janela


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


# níveis de liquidez do património: chave → (nome, descrição, cor)
LIQUIDITY = {
    "imediata": ("Imediata", "o que podes usar hoje", "#22c55e"),
    "curto": ("Curto prazo", "vende-se ou resgata-se em dias", "#3b82f6"),
    "iliquido": ("Ilíquido", "meses a vender, com custos e preço estimado", "#f59e0b"),
}

# outros ativos (fora das corretoras):
# chave → (nome, ícone, cor, conta no FIRE por omissão, é dívida, nível de liquidez por omissão)
OTHER_CATEGORIES = {
    "conta": ("Contas à ordem e poupança à vista", "bi-cash-coin", "#22c55e", True, False, "imediata"),
    "deposito": ("Depósitos a prazo", "bi-safe", "#06b6d4", True, False, "curto"),
    "aforro": ("Certificados de aforro / tesouro", "bi-bank", "#14b8a6", True, False, "curto"),
    "ppr": ("PPR", "bi-piggy-bank", "#a855f7", True, False, "curto"),
    "outro": ("Outros", "bi-box", "#64748b", True, False, "curto"),
    "imovel": ("Imóveis", "bi-house", "#f59e0b", False, False, "iliquido"),
    "credito": ("Créditos (dívidas)", "bi-credit-card", "#ef4444", False, True, None),
}


class OtherAsset(NameMixin, db.Model):
    """Ativo ou dívida fora das corretoras, com o valor indicado à mão (em euros)."""
    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(16), nullable=False)
    value = db.Column(db.Float, nullable=False, default=0.0)  # sempre positivo; o sinal vem da categoria
    fire = db.Column(db.Boolean, default=True)  # soma-se à carteira no Planeamento (FIRE)
    note = db.Column(db.String(255))
    updated = db.Column(db.Date)
    creation = db.Column(db.DateTime, default=utcnow)
    liquidity = db.Column(db.String(16))  # imediata | curto | iliquido; vazio = o da categoria
    home = db.Column(db.Boolean, default=False)  # imóvel: casa de habitação própria (não entra no FIRE)
    linked = db.Column(db.Integer)  # crédito: o imóvel que financia (abate ao valor dele)

    @property
    def debt(self):
        return OTHER_CATEGORIES.get(self.category, OTHER_CATEGORIES["outro"])[4]

    @property
    def level(self):
        """Nível de liquidez efetivo (None nas dívidas)."""
        if self.debt:
            return None
        if self.liquidity in LIQUIDITY:
            return self.liquidity
        return OTHER_CATEGORIES.get(self.category, OTHER_CATEGORIES["outro"])[5]

    @property
    def signed(self):
        return -self.value if self.debt else self.value


class OtherAssetValue(db.Model):
    """Valor de um outro ativo em cada mês (o último registado no mês), para a evolução do património."""
    id = db.Column(db.Integer, primary_key=True)
    asset = db.Column(db.Integer, db.ForeignKey("other_asset.id", ondelete="CASCADE"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False)
    value = db.Column(db.Float, nullable=False)
