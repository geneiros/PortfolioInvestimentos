"""Motor de cálculo da carteira.

Processa as transações por ordem cronológica e produz:
  * posições abertas/fechadas (lotes FIFO, custo em EUR à taxa de câmbio da compra);
  * série diária de valor, depósitos líquidos e índice TWR;
  * métricas: retorno total, IRR (XIRR), TWR, CAGR, drawdown, retornos mensais/anuais;
  * dados fiscais: mais-valias realizadas (FIFO) e dividendos.

Todos os valores agregados estão na moeda base (EUR). Se faltar dinheiro em caixa
para uma compra, o valor em falta é tratado como depósito implícito, para que quem
só importa compras/vendas continue a obter retornos corretos.
"""
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

EPS = 1e-9
TRADING_DAYS = 252
MERIT_BENCHMARK = "^GSPC"  # referência para beta, captura e alfa
RISK_FREE = 0.02           # taxa sem risco anual por omissão (Sharpe, Sortino, alfa): ~ depósito do BCE
TAX_RATE = 0.28            # taxa liberatória/autónoma em Portugal (estimativa)


@dataclass
class Instrument:
    ticker: str
    name: str = ""
    kind: str = "stock"      # stock | etf | index
    sector: str = None
    currency: str = "EUR"
    color: str = "#64748b"

    @property
    def is_benchmark(self):
        return self.kind == "index"


@dataclass
class Tx:
    date: date
    type: str                # BUY SELL DIVIDEND DEPOSIT WITHDRAWAL FEE INTEREST
    asset: Instrument = None
    quantity: float = 0.0
    price: float = 0.0       # moeda do ativo
    amount: float = 0.0      # movimentos de caixa / dividendo bruto, na moeda `currency`
    fees: float = 0.0
    tax: float = 0.0         # retenção na fonte
    currency: str = "EUR"
    broker: str = None
    result: float = None     # resultado da venda indicado pela corretora (moeda `currency`)
    opening: bool = False    # posição de abertura estimada (anterior ao histórico importado)


class PriceBook:
    """Cotações e câmbios com preenchimento para a frente (último valor conhecido).

    prices: {ticker: [(data, fecho), ...]} · fx: {moeda: [(data, unidades por 1 EUR), ...]}
    """

    def __init__(self, prices=None, fx=None):
        self._prices = {k: self._split(v) for k, v in (prices or {}).items()}
        self._fx = {k: self._split(v) for k, v in (fx or {}).items()}

    @staticmethod
    def _split(rows):
        rows = sorted(rows)
        return [r[0] for r in rows], [float(r[1]) for r in rows]

    @staticmethod
    def _lookup(series, d):
        dates, values = series
        if not dates:
            return None
        i = bisect_right(dates, d) - 1
        return values[i] if i >= 0 else values[0]

    def price(self, ticker, d):
        return self._lookup(self._prices.get(ticker, ([], [])), d)

    def fx(self, currency, d):
        """Unidades de `currency` por 1 EUR."""
        if currency == "EUR":
            return 1.0
        return self._lookup(self._fx.get(currency, ([], [])), d) or 1.0

    def latest_fx(self, currency):
        values = self._fx.get(currency, ([], []))[1]
        return values[-1] if values else None

    def to_eur(self, amount, currency, d):
        return amount / self.fx(currency, d)

    def last_date(self, ticker):
        dates = self._prices.get(ticker, ([], []))[0]
        return dates[-1] if dates else None

    def previous_close(self, ticker, d):
        """Fecho da sessão anterior a `d`."""
        dates, values = self._prices.get(ticker, ([], []))
        i = bisect_right(dates, d) - 1
        return values[i - 1] if i >= 1 else None

    def closes(self, ticker, n):
        return self._prices.get(ticker, ([], []))[1][-n:]


@dataclass
class Lot:
    date: date
    qty: float
    cost_local: float  # custo total do lote (com comissões) na moeda do ativo
    cost_eur: float
    fx: float
    opening: bool = False


@dataclass
class Position:
    asset: Instrument
    lots: list = field(default_factory=list)
    realized_eur: float = 0.0
    dividends_eur: float = 0.0
    fees_eur: float = 0.0
    bought_eur: float = 0.0
    first_date: date = None
    last_date: date = None

    # preenchidos em `value()`
    price: float = None
    prev_close: float = None
    value_eur: float = 0.0
    day_change_eur: float = 0.0
    day_change_pct: float = 0.0
    fx_effect_eur: float = 0.0

    @property
    def qty(self):
        return sum(lot.qty for lot in self.lots)

    @property
    def is_open(self):
        return self.qty > 1e-6

    @property
    def invested_eur(self):
        return sum(lot.cost_eur for lot in self.lots)

    @property
    def avg_price(self):
        q = self.qty
        return sum(lot.cost_local for lot in self.lots) / q if q > EPS else 0.0

    @property
    def unrealized_eur(self):
        return self.value_eur - self.invested_eur

    @property
    def unrealized_pct(self):
        inv = self.invested_eur
        return self.unrealized_eur / inv if inv > EPS else 0.0

    @property
    def roi_eur(self):
        return self.unrealized_eur + self.realized_eur + self.dividends_eur

    @property
    def roi_pct(self):
        # sobre o total investido no ativo: o resultado inclui vendas parciais anteriores
        base = self.bought_eur or self.invested_eur
        return self.roi_eur / base if base > EPS else 0.0


@dataclass
class Sale:
    date: date
    asset: Instrument
    qty: float
    proceeds_eur: float
    cost_eur: float
    acquired: date           # None quando a compra é anterior ao histórico importado

    @property
    def gain_eur(self):
        return self.proceeds_eur - self.cost_eur


@dataclass
class DividendRecord:
    date: date
    asset: Instrument
    gross_eur: float
    tax_eur: float

    @property
    def net_eur(self):
        return self.gross_eur - self.tax_eur


@dataclass
class Series:
    dates: list
    value: list           # valor total (posições + caixa)
    holdings: list        # valor só das posições
    net_deposits: list    # depósitos líquidos acumulados
    flows: list           # fluxo externo de cada dia
    twr: list             # índice TWR (começa em 1.0)


# tipos de transação que dizem respeito a um ativo (os restantes são só movimentos de dinheiro)
ASSET_TYPES = {"BUY", "SELL", "DIVIDEND", "TRANSFER_IN", "TRANSFER_OUT", "CONVERT_IN", "CONVERT_OUT"}


class Portfolio:
    def __init__(self, transactions, book, benchmarks=(), as_of=None):
        order = {"DEPOSIT": 0, "INTEREST": 1, "DIVIDEND": 1, "BUY": 2, "TRANSFER_IN": 2, "CONVERT_OUT": 2.4,
                 "CONVERT_IN": 2.5, "SELL": 3, "TRANSFER_OUT": 3, "FEE": 4, "WITHDRAWAL": 5}
        self.warnings = []
        # uma transação de ativo sem ativo (dado inválido) não pode bloquear a aplicação inteira
        orphans = [t for t in transactions if t.type in ASSET_TYPES and not t.asset]
        if orphans:
            self.warnings.append(f"{len(orphans)} transações sem ativo foram ignoradas (apaga-as em Transações).")
            transactions = [t for t in transactions if t.type not in ASSET_TYPES or t.asset]
        txs = sorted(transactions, key=lambda t: (t.date, order.get(t.type, 9)))
        self.book = book
        self.opening = self._opening_positions(txs)
        self.transactions = sorted(self.opening + txs, key=lambda t: (t.date, order.get(t.type, 9)))
        self.book = book
        self.benchmarks = list(benchmarks)
        held = {t.asset.ticker for t in self.transactions if t.asset}
        held_dates = [d for d in (book.last_date(a) for a in held) if d]
        self.as_of = as_of or (max(held_dates) if held_dates else date.today())

        self.positions = {}
        self.sales = []
        self.dividends = []
        self.cash = 0.0
        self.interest_eur = 0.0
        self.fees_eur = 0.0
        self.implicit_deposits = 0.0
        self._converting = []  # lotes retirados por CONVERT_OUT à espera do CONVERT_IN
        self.series = self._run()
        self._value_positions()

    # ------------------------------------------------------------------ núcleo
    def _opening_positions(self, txs):
        """Cria posições de abertura para vendas de ações compradas antes do histórico importado.

        O custo é estimado a partir do resultado que a corretora indica na venda (custo = valor
        da venda - comissões - resultado); sem esse dado, assume-se custo igual ao preço de venda.
        """
        if not txs:
            return []
        start = txs[0].date
        held = defaultdict(float)
        openings = {}
        dividend_tickers = set()
        for t in txs:
            if not t.asset:
                continue
            k = t.asset.ticker
            if t.type in ("BUY", "TRANSFER_IN", "CONVERT_IN"):
                held[k] += t.quantity
            elif t.type in ("SELL", "TRANSFER_OUT", "CONVERT_OUT"):
                short = t.quantity - held[k]
                if short > 1e-6:
                    # custo por ação na moeda do ativo, convertido de modo a que o custo em EUR
                    # (ao câmbio do início do histórico) iguale valor da venda - resultado em EUR
                    fx_sale, fx_start = self.book.fx(t.currency, t.date), self.book.fx(t.currency, start)
                    if t.type in ("SELL", "CONVERT_OUT") and t.result is not None and t.quantity > 0:
                        cost_eur = (t.quantity * t.price - (t.fees or 0.0) - t.result) / fx_sale
                        cps = cost_eur / t.quantity * fx_start
                    else:
                        cps = t.price * fx_start / fx_sale
                    o = openings.setdefault(k, [t.asset, 0.0, 0.0, t.currency])
                    o[1] += short
                    o[2] += short * max(cps, 0.0)
                    held[k] = 0.0
                else:
                    held[k] -= t.quantity
            elif t.type == "DIVIDEND":
                dividend_tickers.add(k)
        out = [Tx(start, "BUY", a, q, cost / q, currency=cur, opening=True)
               for a, q, cost, cur in openings.values() if q > 0]
        if out:
            names = ", ".join(sorted(t.asset.ticker for t in out))
            self.warnings.append(
                f"{len(out)} posições já existiam antes do primeiro movimento importado ({names}). "
                "O custo foi estimado a partir do resultado indicado pela corretora nas vendas. "
                "Importa os extratos dos anos anteriores para teres o histórico completo.")
        # dividendos recebidos depois de vender tudo são normais (data ex-dividendo anterior à venda);
        # só falta histórico se o ativo nunca foi comprado
        ever_held = {t.asset.ticker for t in txs if t.asset and t.type in ("BUY", "TRANSFER_IN", "CONVERT_IN")}
        missing = dividend_tickers - ever_held - set(openings)
        if missing:
            self.warnings.append(
                f"Recebeste dividendos de ativos sem compras no histórico ({', '.join(sorted(missing))}). "
                "Essas posições não aparecem na carteira: importa os extratos dos anos anteriores.")
        return out

    def _take_lots(self, pos, qty):
        """Retira `qty` unidades dos lotes (FIFO); devolve [(lote, quantidade, custo EUR, custo local)]."""
        taken, remaining = [], qty
        while remaining > 1e-9 and pos.lots:
            lot = pos.lots[0]
            take = min(lot.qty, remaining)
            frac = take / lot.qty
            cost_eur, cost_local = lot.cost_eur * frac, lot.cost_local * frac
            taken.append((lot, take, cost_eur, cost_local))
            lot.cost_eur -= cost_eur
            lot.cost_local -= cost_local
            lot.qty -= take
            remaining -= take
            if lot.qty <= 1e-9:
                pos.lots.pop(0)
        return taken

    def _position(self, asset):
        pos = self.positions.get(asset.ticker)
        if pos is None:
            pos = self.positions[asset.ticker] = Position(asset=asset)
        return pos

    def _apply(self, t):
        """Aplica uma transação; devolve o fluxo externo (depósitos/levantamentos) em EUR."""
        book, d = self.book, t.date
        fx = book.fx(t.currency, d)
        fees_eur = (t.fees or 0.0) / fx
        flow = 0.0

        if t.type == "BUY":
            pos = self._position(t.asset)
            cost_local = t.quantity * t.price + (t.fees or 0.0)
            cost_eur = cost_local / fx
            pos.lots.append(Lot(d, t.quantity, cost_local, cost_eur, fx, t.opening))
            pos.fees_eur += fees_eur
            pos.bought_eur += cost_eur
            pos.first_date = pos.first_date or d
            pos.last_date = d
            self.fees_eur += fees_eur
            self.cash -= cost_eur
        elif t.type == "SELL":
            pos = self._position(t.asset)
            proceeds_eur = (t.quantity * t.price - (t.fees or 0.0)) / fx
            for lot, take, cost_eur, _ in self._take_lots(pos, t.quantity):
                share = proceeds_eur * take / t.quantity
                self.sales.append(Sale(d, pos.asset, take, share, cost_eur, None if lot.opening else lot.date))
                pos.realized_eur += share - cost_eur
            pos.fees_eur += fees_eur
            pos.last_date = d
            self.fees_eur += fees_eur
            self.cash += proceeds_eur
        elif t.type == "CONVERT_OUT":
            # conversão, fusão ou split: as unidades saem deste ativo com o custo e as datas de compra
            pos = self._position(t.asset)
            self._converting += [(d, lot, take, cost_eur, cost_local)
                                 for lot, take, cost_eur, cost_local in self._take_lots(pos, t.quantity)]
            pos.last_date = d
        elif t.type == "CONVERT_IN":
            pos = self._position(t.asset)
            moved = [c for c in self._converting if c[0] == d]
            self._converting = [c for c in self._converting if c[0] != d]
            total = sum(c[2] for c in moved)
            if total > 1e-12:
                factor = t.quantity / total
                for _, lot, take, cost_eur, cost_local in moved:
                    pos.lots.append(Lot(lot.date, take * factor, cost_local, cost_eur, lot.fx, lot.opening))
                    pos.bought_eur += cost_eur
                pos.lots.sort(key=lambda lot_: lot_.date)
            else:  # sem saída correspondente (ex.: ações oferecidas): unidades sem custo
                pos.lots.append(Lot(d, t.quantity, 0.0, 0.0, fx))
            pos.first_date = pos.first_date or d
            pos.last_date = d
        elif t.type in ("TRANSFER_OUT", "TRANSFER_IN"):
            # ações que saem/entram da corretora: não há venda nem mais-valia; o valor conta
            # como fluxo externo, como um levantamento/depósito em espécie
            pos = self._position(t.asset)
            value_eur = t.quantity * t.price / fx
            if t.type == "TRANSFER_OUT":
                self._take_lots(pos, t.quantity)
                flow = -value_eur
            else:
                pos.lots.append(Lot(d, t.quantity, t.quantity * t.price, value_eur, fx))
                pos.bought_eur += value_eur
                pos.first_date = pos.first_date or d
                flow = value_eur
            pos.last_date = d
        elif t.type == "DIVIDEND":
            gross = t.amount or (t.quantity or 0) * (t.price or 0)
            gross_eur, tax_eur = gross / fx, (t.tax or 0.0) / fx
            pos = self._position(t.asset)
            pos.dividends_eur += gross_eur - tax_eur
            self.dividends.append(DividendRecord(d, t.asset, gross_eur, tax_eur))
            self.cash += gross_eur - tax_eur
        elif t.type == "DEPOSIT":
            flow = t.amount / fx
            self.cash += flow
        elif t.type == "WITHDRAWAL":
            flow = -t.amount / fx
            self.cash += flow
        elif t.type == "FEE":
            self.cash -= t.amount / fx
            self.fees_eur += t.amount / fx
        elif t.type == "INTEREST":
            net = (t.amount - (t.tax or 0.0)) / fx
            self.interest_eur += net
            self.cash += net
        return flow

    def _holdings_value(self, d):
        total = 0.0
        for pos in self.positions.values():
            if not pos.lots:  # posição fechada (a maioria, ao fim de uns anos): evita somar lotes
                continue
            q = pos.qty
            if q <= 1e-9:
                continue
            p = self.book.price(pos.asset.ticker, d)
            if p is None:  # sem cotação: usa o custo
                total += pos.invested_eur
            else:
                total += q * p / self.book.fx(pos.asset.currency, d)
        return total

    def _run(self):
        txs = self.transactions
        if not txs:
            return Series([], [], [], [], [], [])
        start = txs[0].date
        end = max(self.as_of, txs[-1].date)
        tx_days = {t.date for t in txs}

        dates, values, holdings, netdep, flows, twr = [], [], [], [], [], []
        i, cum, idx, prev_v, pending = 0, 0.0, 1.0, 0.0, 0.0
        d = start
        while d <= end:
            while i < len(txs) and txs[i].date == d:
                pending += self._apply(txs[i])
                i += 1
            if self.cash < -0.005:  # depósito implícito
                pending += -self.cash
                self.implicit_deposits += -self.cash
                self.cash = 0.0
            # fins de semana sem movimentos não geram ponto; o fluxo passa para o dia seguinte
            if d.weekday() < 5 or d in tx_days or d == end:
                h = self._holdings_value(d)
                v = h + self.cash
                idx *= _day_return(prev_v, v, pending)
                cum += pending
                dates.append(d)
                values.append(v)
                holdings.append(h)
                netdep.append(cum)
                flows.append(pending)
                twr.append(idx)
                prev_v, pending = v, 0.0
            d += timedelta(days=1)
        return Series(dates, values, holdings, netdep, flows, twr)

    def _value_positions(self):
        d = self.as_of
        for pos in self.positions.values():
            if not pos.is_open:
                continue
            aid, cur = pos.asset.ticker, pos.asset.currency
            p = self.book.price(aid, d)
            pos.price = p
            if p is None:
                pos.value_eur = pos.invested_eur
                continue
            fx_now = self.book.fx(cur, d)
            q = pos.qty
            pos.value_eur = q * p / fx_now
            # variação face ao dia útil anterior (mesma base que a variação da carteira);
            # em euros inclui o efeito cambial, em % é a variação do preço na moeda do ativo
            k, j = self._market_days()
            prev_day = self.series.dates[j] if j is not None else None
            prev = self.book.price(aid, prev_day) if prev_day else None
            pos.prev_close = prev
            if prev:
                pos.day_change_pct = p / prev - 1
                pos.day_change_eur = pos.value_eur - q * prev / self.book.fx(cur, prev_day)
            # efeito cambial = valor atual - valor atual convertido às taxas de compra
            at_buy_fx = sum(lot.qty * p / lot.fx for lot in pos.lots)
            pos.fx_effect_eur = pos.value_eur - at_buy_fx

    # ------------------------------------------------------------- resumos
    @property
    def open_positions(self):
        ps = [p for p in self.positions.values() if p.is_open]
        return sorted(ps, key=lambda p: -p.value_eur)

    @property
    def closed_positions(self):
        ps = [p for p in self.positions.values() if not p.is_open and p.bought_eur > 0]
        return sorted(ps, key=lambda p: p.last_date or date.min, reverse=True)

    @property
    def holdings_value(self):
        return sum(p.value_eur for p in self.open_positions)

    @property
    def total_value(self):
        return self.holdings_value + self.cash

    @property
    def net_deposits(self):
        return self.series.net_deposits[-1] if self.series.dates else 0.0

    @property
    def cost_basis(self):
        return sum(p.invested_eur for p in self.open_positions)

    @property
    def unrealized(self):
        return sum(p.unrealized_eur for p in self.open_positions)

    @property
    def realized(self):
        return sum(s.gain_eur for s in self.sales)

    @property
    def dividends_total(self):
        return sum(d.net_eur for d in self.dividends)

    @property
    def total_return(self):
        return self.total_value - self.net_deposits

    @property
    def total_return_pct(self):
        """Ganho em euros sobre o máximo de capital líquido que chegou a estar investido.

        Usa os mesmos euros do retorno total. Dividir pelo líquido depositado no fim dava valores absurdos
        a quem levantou lucros ou transferiu ações (+211% com 3 900 € na conta), e o TWR não se relaciona
        com os euros (dá o mesmo peso a um mês com 300 € investidos e a um mês com 60 000 €).
        """
        s = self.series
        if not s.dates:
            return 0.0
        peak = max(s.net_deposits)
        return self.total_return / peak if peak > EPS else s.twr[-1] - 1

    def _market_days(self):
        """Índices na série do último dia de mercado (`as_of`) e do dia útil anterior.

        A série pode acabar depois do último fecho (ex.: juros ou um levantamento ao sábado); comparar esse
        dia com o anterior dava sempre ~0%, porque ao fim de semana não há cotações.
        """
        s = self.series
        k = bisect_right(s.dates, self.as_of) - 1
        while k >= 1 and s.dates[k].weekday() >= 5:
            k -= 1
        j = k - 1
        while j >= 1 and s.dates[j].weekday() >= 5:
            j -= 1
        return (k, j) if j >= 0 else (None, None)

    def day_change(self):
        s = self.series
        k, j = self._market_days()
        if k is None:
            return 0.0, 0.0
        diff = s.value[k] - s.value[j] - sum(s.flows[j + 1:k + 1])
        base = s.value[j]
        return diff, (diff / base if base > EPS else 0.0)

    def year_to_date(self):
        s = self.series
        if not s.dates:
            return 0.0, 0.0
        jan1 = date(s.dates[-1].year, 1, 1)
        k = self._index_before(jan1)
        v0 = s.value[k] if k is not None else 0.0
        year_flows = [f for d, f in zip(s.dates, s.flows) if d >= jan1]
        gain = s.value[-1] - v0 - sum(year_flows)
        i0 = s.twr[k] if k is not None else 1.0
        # como no retorno total: ganho sobre o capital investido (valor a 1 de janeiro + entradas do ano)
        return gain, _peak_capital_return(v0, year_flows, gain, s.twr[-1] / i0 - 1)

    def _index_before(self, d):
        """Índice do último ponto da série estritamente antes de `d`."""
        i = bisect_right(self.series.dates, d - timedelta(days=1)) - 1
        return i if i >= 0 else None

    def all_time_high(self, mode="value"):
        s = self.series
        if not s.dates:
            return None
        vals = s.holdings if mode == "value" else [v - n for v, n in zip(s.value, s.net_deposits)]
        k = max(range(len(vals)), key=vals.__getitem__)
        current = vals[-1]
        # máximo anterior: o recorde em vigor 30 dias antes do máximo atual
        cutoff = s.dates[k] - timedelta(days=30)
        prev = [(vals[j], s.dates[j]) for j in range(k) if s.dates[j] <= cutoff]
        prev_best = max(prev) if prev else None
        ath = vals[k]
        return {
            "value": ath, "date": s.dates[k], "current": current,
            "vs_ath_pct": (current / ath - 1) if ath > EPS else 0.0,
            "to_recover": max(ath - current, 0.0),
            "position_pct": current / ath if ath > EPS else 0.0,
            "previous": prev_best,
        }

    def movers(self, n=5):
        ps = [p for p in self.open_positions if p.prev_close]
        return sorted(ps, key=lambda p: -abs(p.day_change_pct))[:n]

    def sectors(self):
        return sorted({p.asset.sector for p in self.open_positions if p.asset.sector})

    def allocation(self, by="asset"):
        groups = defaultdict(float)
        for p in self.open_positions:
            key = {"asset": p.asset.ticker, "sector": p.asset.sector or "Outros",
                   "currency": p.asset.currency, "kind": p.asset.kind.upper()}[by]
            groups[key] += p.value_eur
        if self.cash > 0.5 and by != "asset":
            groups["Caixa"] += self.cash
        return sorted(groups.items(), key=lambda kv: -kv[1])

    def sparkline(self, ticker, n=30):
        return self.book.closes(ticker, n)

    def _bench_closes(self, bench, dates):
        """Fechos do índice convertidos para euros ao câmbio de cada dia.

        A carteira é medida em euros; comparar com o índice na moeda dele (ex.: S&P 500 em dólares)
        atribuía à carteira o efeito cambial, como se fosse mérito ou demérito.
        """
        out = []
        for d in dates:
            price = self.book.price(bench.ticker, d)
            out.append(price / self.book.fx(bench.currency, d) if price is not None else None)
        return out

    def benchmark_day_change(self, bench):
        """Variação do índice, em euros, nos mesmos dias que a variação da carteira."""
        if not self.book.last_date(bench.ticker):
            return None
        k, j = self._market_days()
        if k is None:
            return None
        p, prev = self._bench_closes(bench, [self.series.dates[k], self.series.dates[j]])
        return p / prev - 1 if p and prev else None

    # ----------------------------------------------------------- dividendos
    def dividend_summary(self, announced=None):
        divs = self.dividends
        today = self.as_of
        gross = sum(d.gross_eur for d in divs)
        tax = sum(d.tax_eur for d in divs)
        net = gross - tax
        by_asset = defaultdict(float)
        by_year = defaultdict(float)
        by_month = defaultdict(float)  # (ano, mês) -> líquido
        for d in divs:
            by_asset[d.asset.ticker] += d.net_eur
            by_year[d.date.year] += d.net_eur
            by_month[(d.date.year, d.date.month)] += d.net_eur

        first = self.series.dates[0] if self.series.dates else today
        n_months = (today.year - first.year) * 12 + today.month - first.month + 1
        years_span = max((today - first).days / 365.25, 1 / 12)
        top = max(by_asset.items(), key=lambda kv: kv[1]) if by_asset else None

        # projeção: dividendos por ação dos últimos 12 meses × quantidade atual
        ttm_start = today - timedelta(days=365)
        per_share = defaultdict(float)
        per_share_month = defaultdict(lambda: defaultdict(float))  # ativo -> mês do pagamento -> por ação
        for t in self.transactions:
            if t.type == "DIVIDEND" and t.date > ttm_start and t.asset:
                pos = self.positions.get(t.asset.ticker)
                qty_then = t.quantity or (pos.qty if pos else 0)
                if qty_then > EPS:
                    g = t.amount or qty_then * (t.price or 0)
                    eur = self.book.to_eur(g, t.currency, t.date) / qty_then
                    per_share[t.asset.ticker] += eur
                    per_share_month[t.asset.ticker][t.date.month] += eur
        # dividendos por ação segundo o Yahoo (`announced`: ativo -> [(data ex-dividendo, valor na moeda do ativo)]):
        # valem para as posições abertas e são o ano inteiro, mesmo para posições compradas há poucos meses
        source = {t: "recebidos" for t in per_share}
        for p in self.open_positions:
            rows = [(d, a) for d, a in (announced or {}).get(p.asset.ticker, []) if ttm_start < d <= today]
            if rows:
                per_share[p.asset.ticker] = 0.0
                per_share_month[p.asset.ticker] = defaultdict(float)
                for d, a in rows:
                    eur = self.book.to_eur(a, p.asset.currency, d)
                    per_share[p.asset.ticker] += eur
                    per_share_month[p.asset.ticker][d.month] += eur
                source[p.asset.ticker] = "Yahoo"
        forward_gross = sum(per_share[p.asset.ticker] * p.qty for p in self.open_positions)
        tax_ratio = tax / gross if gross > EPS else 0.0
        forward_net = forward_gross * (1 - tax_ratio)
        # mapa do próximo ano: cada posição volta a pagar nos mesmos meses dos últimos 12, com as quantidades atuais
        forward_by_month = defaultdict(float)
        for p in self.open_positions:
            for month, eur in per_share_month[p.asset.ticker].items():
                forward_by_month[month] += eur * p.qty * (1 - tax_ratio)
        # de onde vem a projeção: posições abertas que pagaram dividendos nos últimos 12 meses
        forward_by_asset = sorted(((p.asset.ticker, per_share[p.asset.ticker] * p.qty * (1 - tax_ratio),
                                    source.get(p.asset.ticker, "recebidos"))
                                   for p in self.open_positions if per_share[p.asset.ticker] > EPS),
                                  key=lambda kv: -kv[1])

        # projeção do ano corrente = recebido até hoje + restantes meses do ano pela média TTM
        received_ytd = by_year.get(today.year, 0.0)
        remaining = 12 - today.month
        projection_year = received_ytd + forward_net * remaining / 12

        full_years = sorted(y for y in by_year if y < today.year)
        growth = None
        if len(full_years) >= 2 and by_year[full_years[0]] > EPS:
            y0, y1 = full_years[0], full_years[-1]
            growth = ((by_year[y1] / by_year[y0]) ** (1 / (y1 - y0)) - 1, y0, y1)

        yield_on_cost = []
        for p in self.open_positions:
            annual = per_share.get(p.asset.ticker, 0.0) * p.qty
            if annual > EPS:
                yield_on_cost.append((p, annual, annual / p.invested_eur if p.invested_eur else 0,
                                      annual / p.value_eur if p.value_eur else 0))
        yield_on_cost.sort(key=lambda x: -x[1])

        return {
            "net": net, "gross": gross, "tax": tax,
            "avg_month": net / n_months if n_months else 0.0,
            "payers": len(by_asset),
            "top": top, "top_share": top[1] / net if top and net > EPS else 0.0,
            "months_with": len(by_month), "months_total": n_months,
            "annualized": net / years_span,
            "projection_year": projection_year, "forward_net": forward_net, "forward_gross": forward_gross,
            "forward_by_asset": forward_by_asset, "forward_by_month": dict(forward_by_month),
            "growth": growth,
            "by_year": dict(sorted(by_year.items())),
            "by_month": by_month,
            "by_asset": sorted(by_asset.items(), key=lambda kv: -kv[1]),
            "years": list(range(first.year, today.year + 1)),
            "yield_on_cost": yield_on_cost,
            "records": sorted(divs, key=lambda d: d.date, reverse=True),
        }

    # ---------------------------------------------------------------- fiscal
    def fiscal_years(self):
        years = defaultdict(lambda: {"sales": [], "gains": 0.0, "losses": 0.0,
                                     "div_gross": 0.0, "div_tax": 0.0, "tax_dividends": 0.0, "interest": 0.0})
        for s in self.sales:
            y = years[s.date.year]
            y["sales"].append(s)
            if s.gain_eur >= 0:
                y["gains"] += s.gain_eur
            else:
                y["losses"] += s.gain_eur
        for d in self.dividends:
            years[d.date.year]["div_gross"] += d.gross_eur
            years[d.date.year]["div_tax"] += d.tax_eur
            # crédito por dupla tributação limitado ao imposto português sobre ESTE dividendo:
            # a retenção a mais num dividendo não abate o imposto de outro
            years[d.date.year]["tax_dividends"] += max(d.gross_eur * TAX_RATE - d.tax_eur, 0.0)
        for t in self.transactions:
            if t.type == "INTEREST":
                years[t.date.year]["interest"] += self.book.to_eur(t.amount, t.currency, t.date)
        out = {}
        for year, y in sorted(years.items(), reverse=True):
            balance = y["gains"] + y["losses"]
            y["balance"] = balance
            y["tax_gains"] = max(balance, 0.0) * TAX_RATE
            y["tax_interest"] = y["interest"] * TAX_RATE
            out[year] = y
        return out

    # ----------------------------------------------------------- desempenho
    PERIODS = {"1M": 30, "3M": 91, "6M": 182, "YTD": None, "1A": 365, "3A": 1095, "5A": 1826, "MAX": None}

    def period_start(self, period):
        s = self.series
        if not s.dates:
            return None
        end = s.dates[-1]
        period = (period or "MAX").upper()
        if period == "YTD":
            return date(end.year, 1, 1)
        days = self.PERIODS.get(period)
        return end - timedelta(days=days) if days else s.dates[0]

    def performance(self, period="MAX", benchmarks=None, risk_free=None):
        """Dados para os gráficos e cartões da página Desempenho."""
        rf = RISK_FREE if risk_free is None else risk_free
        s = self.series
        if not s.dates:
            return None
        start = self.period_start(period)
        k0 = max(self._index_before(start) or 0, 0) if start > s.dates[0] else 0
        dates = s.dates[k0:]
        base_idx = s.twr[k0]
        twr = [x / base_idx - 1 for x in s.twr[k0:]]
        v0, nd0 = s.value[k0], s.net_deposits[k0]
        gain = [(v - v0) - (n - nd0) for v, n in zip(s.value[k0:], s.net_deposits[k0:])]

        twr_total = twr[-1]
        years = max((dates[-1] - dates[0]).days / 365.25, 1 / 365.25)
        cagr = (1 + twr_total) ** (1 / years) - 1 if years >= 1 else twr_total
        ret_eur = gain[-1]
        ret_pct = _peak_capital_return(v0, s.flows[k0 + 1:], ret_eur, twr_total)

        flows = [(dates[0], -v0)] if v0 > EPS else []
        flows += [(d, -f) for d, f in zip(dates[1:], s.flows[k0 + 1:]) if abs(f) > EPS]
        if v0 <= EPS and abs(s.flows[k0]) > EPS:
            flows.insert(0, (dates[0], -s.flows[k0]))
        flows.append((dates[-1], s.value[-1]))
        irr = xirr(flows)

        index = [1 + x for x in twr]
        monthly = period_returns(dates, index, "month")
        yearly = period_returns(dates, index, "year")

        bench_data = []
        for b in self.benchmarks:
            if benchmarks is not None and b.ticker not in benchmarks:
                continue
            closes = self._bench_closes(b, dates)
            if not closes or closes[0] is None:
                continue
            bidx = [c / closes[0] for c in closes]
            b_total = bidx[-1] - 1
            bench_data.append({
                "ticker": b.ticker, "name": b.name, "color": b.color,
                "twr": [x - 1 for x in bidx],
                "drawdown": drawdown(bidx),
                "total": b_total,
                "cagr": (1 + b_total) ** (1 / years) - 1 if years >= 1 else b_total,
                "yearly": period_returns(dates, bidx, "year"),
            })

        # o mês e o ano ainda a decorrer não contam para o melhor/pior nem para a sequência atual
        full_months = _complete(monthly, dates[-1], "month")
        full_years = _complete(yearly, dates[-1], "year")
        best_m = max(full_months, key=lambda m: m[1]) if full_months else None
        worst_m = min(full_months, key=lambda m: m[1]) if full_months else None
        best_y = max(full_years, key=lambda m: m[1]) if full_years else None
        worst_y = min(full_years, key=lambda m: m[1]) if full_years else None

        risk = risk_metrics(index, cagr, drawdown(index), yearly, dates, rf)
        ref = next((b for b in bench_data if b["ticker"] == MERIT_BENCHMARK), None)
        if ref is None:
            ref_asset = next((b for b in self.benchmarks if b.ticker == MERIT_BENCHMARK), None)
            if ref_asset:
                closes = self._bench_closes(ref_asset, dates)
                if closes and closes[0]:
                    bidx = [c / closes[0] for c in closes]
                    b_total = bidx[-1] - 1
                    ref = {"ticker": ref_asset.ticker, "name": ref_asset.name, "twr": [x - 1 for x in bidx],
                           "total": b_total,
                           "cagr": (1 + b_total) ** (1 / years) - 1 if years >= 1 else b_total,
                           "yearly": period_returns(dates, bidx, "year")}
        merit = None
        if ref:
            bidx = [1 + x for x in ref["twr"]]
            ref_monthly = period_returns(dates, bidx, "month")
            merit = merit_metrics(monthly, ref_monthly, yearly, ref["yearly"], cagr, ref["cagr"], rf)
            merit["name"] = ref["name"]
            merit["volatility"] = annualized_vol(bidx, dates)

        return {
            "risk": risk, "merit": merit,
            "start": dates[0], "end": dates[-1],
            "dates": [d.isoformat() for d in dates],
            "twr": twr, "gain": gain, "value": s.value[k0:],
            "drawdown": drawdown(index),
            "return_eur": ret_eur, "return_pct": ret_pct, "irr": irr,
            "twr_total": twr_total, "cagr": cagr,
            "monthly": monthly, "yearly": yearly,
            "best_year": best_y, "worst_year": worst_y,
            "best_month": best_m, "worst_month": worst_m,
            "streak": streak(full_months),
            "risk_free": rf,
            "partial_month": monthly[-1][0] if monthly and len(full_months) < len(monthly) else None,
            "benchmarks": bench_data,
        }


# ---------------------------------------------------------------- utilitários
MIN_BASE = 1.0  # EUR: abaixo disto a carteira está praticamente vazia e não serve de base ao TWR


def _peak_capital_return(v0, flows, gain, fallback):
    """Ganho sobre o máximo de capital líquido que esteve investido no período.

    Dividir pelo líquido depositado no fim dá percentagens absurdas a quem levantou lucros ou transferiu
    ações para outra corretora (o denominador fica perto de zero); o máximo não sofre desse problema.
    """
    capital = peak = v0
    for f in flows:
        capital += f
        peak = max(peak, capital)
    return gain / peak if peak > EPS else fallback


def _day_return(prev_v, v, flow):
    """Fator de crescimento de um dia para o TWR.

    Por omissão o fluxo externo conta no fim do dia: (V - F) / V_anterior. Se a carteira estava
    praticamente vazia (ex.: depois de vender tudo), conta no início: V / (V_anterior + F); se nem
    assim houver base, o dia não conta. Evita retornos absurdos ao dividir por valores residuais.
    """
    if prev_v >= MIN_BASE:
        return (v - flow) / prev_v
    base = prev_v + flow
    return v / base if base >= MIN_BASE else 1.0
def period_returns(dates, index, granularity):
    """[(chave, retorno)] por mês ('2024-03') ou ano ('2024') a partir de um índice."""
    out, prev_end, cur_key, last_val = [], index[0], None, None
    for d, v in zip(dates, index):
        key = f"{d.year}-{d.month:02d}" if granularity == "month" else str(d.year)
        if cur_key is not None and key != cur_key:
            out.append((cur_key, last_val / prev_end - 1))
            prev_end = last_val
        cur_key, last_val = key, v
    if cur_key is not None:
        out.append((cur_key, last_val / prev_end - 1))
    return out


def _last_business_day(year, month):
    d = (date(year + month // 12, month % 12 + 1, 1) if month else date(year + 1, 1, 1)) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _complete(periods, end, granularity):
    """Retira o último período (mês ou ano) se ainda não terminou na data `end`."""
    if not periods:
        return []
    month = end.month if granularity == "month" else 12
    return periods if end >= _last_business_day(end.year, month) else periods[:-1]


def drawdown(index):
    out, peak = [], 0.0
    for v in index:
        peak = max(peak, v)
        out.append(v / peak - 1 if peak > EPS else 0.0)
    return out


def streak(monthly):
    """(número de meses, 'up'|'down') da sequência atual de meses positivos/negativos."""
    if not monthly:
        return 0, None
    sign = monthly[-1][1] >= 0
    n = 0
    for _, r in reversed(monthly):
        if (r >= 0) != sign:
            break
        n += 1
    return n, "up" if sign else "down"


def xirr(flows):
    """Taxa interna de rentabilidade anual para fluxos irregulares [(data, valor)]."""
    if len(flows) < 2 or not any(v > 0 for _, v in flows) or not any(v < 0 for _, v in flows):
        return None
    t0 = flows[0][0]

    def npv(rate):
        return sum(v / (1 + rate) ** ((d - t0).days / 365.0) for d, v in flows)

    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def daily_returns(index, dates=None):
    """Retornos entre pontos consecutivos; com `dates`, só entre dias úteis.

    A série tem pontos ao fim de semana quando há movimentos (ex.: juros diários da Trading 212 e da
    XTB): sem bolsa, entram com variação ~0 e, anualizados com 252 dias, baixavam a volatilidade.
    """
    if dates is not None:
        index = [v for d, v in zip(dates, index) if d.weekday() < 5]
    return [b / a - 1 for a, b in zip(index, index[1:]) if a > EPS]


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs):
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def annualized_vol(index, dates=None):
    return _std(daily_returns(index, dates)) * TRADING_DAYS ** 0.5


def risk_metrics(index, cagr, dd, yearly, dates=None, rf=RISK_FREE):
    rets = daily_returns(index, dates)
    vol = _std(rets) * TRADING_DAYS ** 0.5
    downside = [min(r, 0.0) for r in rets]
    down_dev = (sum(r * r for r in downside) / len(downside)) ** 0.5 * TRADING_DAYS ** 0.5 if downside else 0.0
    max_dd = min(dd) if dd else 0.0
    return {
        "volatility": vol,
        "sharpe": (cagr - rf) / vol if vol > EPS else None,
        "sortino": (cagr - rf) / down_dev if down_dev > EPS else None,
        "calmar": cagr / abs(max_dd) if max_dd < -EPS else None,
        "max_drawdown": max_dd,
        "avg_year": _mean([r for _, r in yearly]),
        "years": len(yearly),
    }


def merit_metrics(monthly, ref_monthly, yearly, ref_yearly, cagr, ref_cagr, rf=RISK_FREE):
    """Comparação mês a mês com o índice de referência (captura, beta, alfa)."""
    ref = dict(ref_monthly)
    pairs = [(k, r, ref[k]) for k, r in monthly if k in ref]
    up = [(p, b) for _, p, b in pairs if b > 0]
    down = [(p, b) for _, p, b in pairs if b < 0]
    up_capture = _mean([p for p, _ in up]) / _mean([b for _, b in up]) if up else None
    down_capture = _mean([p for p, _ in down]) / _mean([b for _, b in down]) if down else None

    ps, bs = [p for _, p, _ in pairs], [b for _, _, b in pairs]
    mp, mb = _mean(ps), _mean(bs)
    var_b = sum((b - mb) ** 2 for b in bs)
    beta = sum((p - mp) * (b - mb) for p, b in zip(ps, bs)) / var_b if var_b > EPS else None
    alpha = (cagr - rf) - beta * (ref_cagr - rf) if beta is not None else None

    ref_y = dict(ref_yearly)
    yearly_excess = [(k, r - ref_y[k]) for k, r in yearly if k in ref_y]
    beat_m = sum(1 for _, p, b in pairs if p > b)
    beat_y = sum(1 for _, e in yearly_excess if e > 0)
    return {
        "up_capture": up_capture, "down_capture": down_capture, "beta": beta, "alpha": alpha,
        "excess_cagr": cagr - ref_cagr,
        "avg_yearly_excess": _mean([e for _, e in yearly_excess]),
        "years": len(yearly_excess),
        "beat_months": beat_m, "months": len(pairs),
        "beat_years": beat_y, "n_years": len(yearly_excess),
        "monthly_excess": [(k, p - b) for k, p, b in pairs],
        "yearly_excess": yearly_excess,
        "sorted": sorted(((p, b) for _, p, b in pairs), key=lambda x: x[0]),
    }
