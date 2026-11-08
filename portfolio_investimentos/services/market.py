"""Estado do mercado e atualização de dados (cotações, câmbios, eventos).

A atualização usa o pacote opcional `yfinance` (pip install yfinance). Sem ele, ou sem
rede, a aplicação continua a funcionar com as cotações já guardadas.
"""
import logging
import math
import threading
import warnings
import time as _time
from datetime import date, datetime, time, timedelta, tzinfo
from statistics import median
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..engine.formatting import WEEKDAYS
from . import yahoo
from ..models import (Alert, DividendHistory, Event, Fundamental, FxRate, Instrument, Price, Setting, Transaction,
                      db)

log = logging.getLogger(__name__)


class _LisbonFallback(tzinfo):
    """Hora de Portugal continental sem base de dados de fusos (ex.: Android/Termux sem `tzdata`).

    Regra europeia: UTC+0 no inverno e UTC+1 entre o último domingo de março e o último domingo de
    outubro, com a mudança à 01:00 UTC.
    """

    @staticmethod
    def _last_sunday(year, month):
        d = date(year, month, 31)
        return d - timedelta(days=(d.weekday() + 1) % 7)

    def _summer(self, utc):
        start = datetime.combine(self._last_sunday(utc.year, 3), time(1))
        end = datetime.combine(self._last_sunday(utc.year, 10), time(1))
        return start <= utc < end

    def utcoffset(self, dt):
        if dt is None:
            return timedelta(0)
        return timedelta(hours=1) if self._summer(dt.replace(tzinfo=None) - timedelta(hours=1)) else timedelta(0)

    def dst(self, dt):
        return self.utcoffset(dt)

    def tzname(self, dt):
        return "WEST" if self.utcoffset(dt) else "WET"

    def fromutc(self, dt):
        utc = dt.replace(tzinfo=None)
        return (utc + (timedelta(hours=1) if self._summer(utc) else timedelta(0))).replace(tzinfo=self)


def _lisbon():
    try:
        return ZoneInfo("Europe/Lisbon")
    except ZoneInfoNotFoundError:  # sistema sem base de fusos e sem o pacote tzdata
        return _LisbonFallback()


LISBON = _lisbon()
OPEN, CLOSE = time(8, 0), time(16, 30)  # Euronext, hora de Lisboa

DEFAULT_BENCHMARKS = [
    ("^GSPC", "S&P 500", "#f97316"),
    ("^NDX", "Nasdaq 100", "#8b5cf6"),
    ("URTH", "MSCI World", "#eab308"),
]
# comparação do gráfico de evolução da Visão Geral: (ticker, nome, cor, moeda). O FTSE All-World não está no
# Yahoo: usa as cotações do ETF da Vanguard em euros (VWCE.DE), com um ticker próprio para não se confundir com
# quem tenha esse ETF na carteira; o STOXX Europe 600 é o índice (^STOXX)
OVERVIEW_BENCHMARKS = [
    ("^GSPC", "S&P 500", "#f97316", "USD"),
    ("URTH", "MSCI World", "#eab308", "USD"),
    ("FTSE-AW", "FTSE All-World", "#0ea5e9", "EUR"),
    ("^STOXX", "STOXX Europe 600", "#22c55e", "EUR"),
]
INDEX_SYMBOLS = {"FTSE-AW": "VWCE.DE"}  # ticker do índice → símbolo no Yahoo, quando são diferentes

# índices que se podem escolher na Carteira («Carteira vs mercado»): (grupo, ticker, nome, moeda, cor)
INDEX_CATALOG = [
    ("Global", "URTH", "MSCI World", "USD", "#eab308"),
    ("Global", "FTSE-AW", "FTSE All-World", "EUR", "#0ea5e9"),
    ("EUA", "^GSPC", "S&P 500", "USD", "#f97316"),
    ("EUA", "^DJI", "Dow Jones", "USD", "#0ea5e9"),
    ("EUA", "^NDX", "Nasdaq 100", "USD", "#8b5cf6"),
    ("EUA", "^RUT", "Russell 2000", "USD", "#ec4899"),
    ("EUA", "BTC-USD", "Bitcoin", "USD", "#f59e0b"),
    ("Europa", "^FTSE", "FTSE 100", "GBP", "#14b8a6"),
    ("Europa", "^FCHI", "CAC 40", "EUR", "#6366f1"),
    ("Europa", "^GDAXI", "DAX", "EUR", "#ef4444"),
    ("Europa", "^STOXX", "STOXX Europe 600", "EUR", "#16a34a"),
    ("Europa", "^STOXX50E", "Euro STOXX 50", "EUR", "#22c55e"),
    ("Europa", "^AEX", "AEX", "EUR", "#f43f5e"),
    ("Europa", "^N100", "Euronext 100", "EUR", "#06b6d4"),
]
MAX_MARKET_INDICES = 5


def market_indices():
    """Índices escolhidos para a «Carteira vs mercado» (por omissão os de comparação)."""
    import json
    known = {t for _, t, *_ in INDEX_CATALOG}
    try:
        chosen = json.loads(Setting.get("market_indices") or "null")
    except ValueError:
        chosen = None
    if not isinstance(chosen, list):
        return [t for t, *_ in DEFAULT_BENCHMARKS]
    return [t for t in chosen if t in known][:MAX_MARKET_INDICES]


def set_market_indices(tickers):
    """Guarda os índices escolhidos e cria os que ainda não existem (as cotações chegam na atualização)."""
    import json
    catalog = {t: (name, cur, color) for _, t, name, cur, color in INDEX_CATALOG}
    if len(tickers) > MAX_MARKET_INDICES or len(set(tickers)) != len(tickers) or any(t not in catalog for t in tickers):
        raise ValueError(f"Escolhe até {MAX_MARKET_INDICES} índices da lista.")
    for t in tickers:
        if not db.session.get(Instrument, t):
            name, cur, color = catalog[t]
            db.session.add(Instrument(ticker=t, instrument_name=name, kind="index", currency=cur,
                                      data_symbol=INDEX_SYMBOLS.get(t, t), color=color))
    Setting.set("market_indices", json.dumps(tickers))


def _easter(year):
    """Domingo de Páscoa (algoritmo gregoriano anónimo)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month, day = divmod(h + el - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year, month, weekday, n):
    """n-ésimo dia da semana do mês (n = -1: o último)."""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(d):
    """Feriado que calha ao fim de semana: sábado passa para sexta, domingo para segunda (regra da NYSE)."""
    return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d


def eu_holidays(year):
    """Feriados em que a Euronext (e a Xetra) está fechada."""
    easter = _easter(year)
    return {date(year, 1, 1), easter - timedelta(days=2), easter + timedelta(days=1), date(year, 5, 1),
            date(year, 12, 25), date(year, 12, 26)}


def us_holidays(year):
    """Feriados da NYSE e da Nasdaq."""
    days = {_nth_weekday(year, 1, 0, 3), _nth_weekday(year, 2, 0, 3), _easter(year) - timedelta(days=2),
            _nth_weekday(year, 5, 0, -1), _observed(date(year, 6, 19)), _observed(date(year, 7, 4)),
            _nth_weekday(year, 9, 0, 1), _nth_weekday(year, 11, 3, 4), _observed(date(year, 12, 25))}
    if date(year, 1, 1).weekday() != 5:  # 1 de janeiro ao sábado: a bolsa abre na sexta, 31 de dezembro
        days.add(_observed(date(year, 1, 1)))
    return days


def _new_york():
    try:
        return ZoneInfo("America/New_York")
    except ZoneInfoNotFoundError:
        return None


REGIONS = {"EU": "Europa", "US": "EUA"}


def _session(region, day):
    """Abertura e fecho (hora de Lisboa) da sessão de um dia, ou None se a bolsa está fechada."""
    if day.weekday() >= 5:
        return None
    if region == "EU":
        if day in eu_holidays(day.year):
            return None
        return datetime.combine(day, OPEN, LISBON), datetime.combine(day, CLOSE, LISBON)
    if day in us_holidays(day.year):
        return None
    ny = _new_york()
    if ny is None:  # sem base de fusos: horário habitual em Lisboa
        return datetime.combine(day, time(14, 30), LISBON), datetime.combine(day, time(21, 0), LISBON)
    # sessão de 9:30 às 16:00 em Nova Iorque (13:00 na sexta a seguir ao Dia de Ação de Graças e a 24 de dezembro)
    early = day == _nth_weekday(day.year, 11, 3, 4) + timedelta(days=1) or day == date(day.year, 12, 24)
    return (datetime.combine(day, time(9, 30), ny).astimezone(LISBON),
            datetime.combine(day, time(13, 0) if early else time(16, 0), ny).astimezone(LISBON))


def _region_status(region, now):
    """(aberta, detalhe, versão curta, próxima abertura) de uma região num instante."""
    today = now.date()
    sess = _session(region, today)
    if sess and sess[0] <= now < sess[1]:
        return True, f"fecha às {sess[1]:%H:%M}", f"aberto até às {sess[1]:%H:%M}", None
    for ahead in range(0, 12):
        day = today + timedelta(days=ahead)
        sess = _session(region, day)
        if sess and sess[0] > now:
            when = "hoje" if ahead == 0 else ("amanhã" if ahead == 1 else WEEKDAYS[day.weekday()])
            return False, f"Abre {when} às {sess[0]:%H:%M}", "fechado", sess[0]
    return False, "", "fechado", None


def market_status(now=None, regions=("EU",)):
    """Estado das bolsas onde há posições: Europa (Euronext) e/ou EUA, com os feriados de cada uma."""
    now = (now or datetime.now(LISBON)).astimezone(LISBON)
    regions = [r for r in REGIONS if r in regions] or ["EU"]
    states = [(r, *_region_status(r, now)) for r in regions]
    if len(states) == 1:
        _, is_open, detail, _, _ = states[0]
        return {"open": is_open, "label": "Aberto" if is_open else "Fechado", "detail": detail}
    is_open = any(s[1] for s in states)
    label = " · ".join(f"{REGIONS[r]}: {short}" for r, _, _, short, _ in states)
    # fechadas todas: diz quando abre a primeira
    soonest = min((s_ for s_ in states if s_[4]), key=lambda s_: s_[4], default=None)
    detail = "" if is_open or soonest is None else f"{soonest[2]} ({REGIONS[soonest[0]]})"
    return {"open": is_open, "label": label, "detail": detail}


def ensure_benchmarks():
    wanted = [(t, n, c, "USD") for t, n, c in DEFAULT_BENCHMARKS] + OVERVIEW_BENCHMARKS
    for ticker, name, color, currency in wanted:
        if not db.session.get(Instrument, ticker):
            db.session.add(Instrument(ticker=ticker, instrument_name=name, kind="index", currency=currency,
                                      data_symbol=INDEX_SYMBOLS.get(ticker, ticker), color=color))
    db.session.commit()


def upcoming_events(tickers, today=None, days=90):
    """Eventos guardados + próximos dividendos estimados pelo intervalo habitual."""
    today = today or date.today()
    if not tickers:
        return []
    events = (Event.query.filter(Event.instrument.in_(list(tickers)),
                                 Event.date.between(today, today + timedelta(days=days)))
              .order_by(Event.date).all())
    have = {(e.instrument, e.kind) for e in events}
    out = list(events)
    for ticker in tickers:
        if (ticker, "dividend_pay") in have:
            continue
        dates = sorted({d for (d,) in db.session.query(Transaction.date)
                       .filter_by(instrument=ticker, type="DIVIDEND")})
        if len(dates) < 2:
            continue
        gap = median((b - a).days for a, b in zip(dates, dates[1:]))
        if gap < 20:
            continue
        nxt = dates[-1] + timedelta(days=gap)
        while nxt < today:
            nxt += timedelta(days=gap)
        if nxt <= today + timedelta(days=days):
            out.append(SimpleNamespace(instrument=ticker, date=nxt, kind="dividend_pay", title="estimado",
                                       estimated=True, timing=None, eps_estimate=None, revenue_estimate=None,
                                       amount=None))
    return sorted(out, key=lambda e: e.date)


def check_alerts(p):
    """Marca como disparados os alertas cujas condições se verificam nas últimas cotações."""
    fired = []
    for a in Alert.query.filter_by(active=True).all():
        last = p.book.last_date(a.instrument)
        if not last:
            row = Price.query.filter_by(instrument=a.instrument).order_by(Price.date.desc()).limit(2).all()
            if not row:
                continue
            price, prev = row[0].close, (row[1].close if len(row) > 1 else None)
        else:
            price, prev = p.book.price(a.instrument, last), p.book.previous_close(a.instrument, last)
        hit = (a.kind == "price_above" and price >= a.threshold) or \
              (a.kind == "price_below" and price <= a.threshold) or \
              (a.kind == "change_pct" and prev and abs(price / prev - 1) * 100 >= a.threshold)
        if hit:
            a.active, a.triggered_on = False, datetime.now()
            fired.append(a)
    if fired:
        db.session.commit()
    return fired


# --------------------------------------------------------------------- yfinance
_lock = threading.Lock()
_background = {"on": False, "only_open": False}  # atualização lançada pela página (só essa deixa sinal de vida no estado)
_progress = {"done": 0, "total": 0, "current": ""}  # ativo em curso da atualização (para a página mostrar)


def yfinance_available():
    """Há sempre forma de obter cotações: o yfinance, se instalado, ou o acesso direto (`yahoo.py`)."""
    return True


def _yahoo_client():
    """O yfinance quando está instalado; senão o acesso direto, só com a biblioteca padrão (ex.: Android)."""
    try:
        import yfinance
        # o yfinance 1.x usa opções do pandas 3 já obsoletas e o aviso aparece a cada pedido (o pandas volta a
        # ativá-lo depois do PYTHONWARNINGS); não é um erro e não depende de nós, por isso cala-se só o dele
        warnings.filterwarnings("ignore", module=r"yfinance(\.|$)")
        return yfinance
    except ImportError:
        from . import yahoo
        return yahoo


def refresh_all(start=None, progress=None, only_open=False, only=None, phases=("quotes", "fx", "events"),
                stats=None):
    """Atualiza cotações, câmbios e eventos. Devolve um resumo textual.

    `progress(linha)` é chamada a cada ativo, à medida que a atualização avança (ex.: para a consola).
    Com `only_open`, só se atualizam as posições abertas (e os índices de comparação); as fechadas ficam como estão.
    Aos bocados (`refresh_step`): `only` limita aos tickers indicados, `phases` às fases indicadas e, com `stats`,
    o resultado (sem cotações, atualizados) fica nesse dicionário em vez de ser gravado como o da atualização.
    """
    yf = _yahoo_client()
    if not _lock.acquire(blocking=False):
        return "Já existe uma atualização em curso."
    try:
        ensure_benchmarks()
        first_tx = db.session.query(db.func.min(Transaction.date)).scalar()
        full = start is not None  # com data de início explícita pede-se o histórico todo
        start = start or (first_tx - timedelta(days=7) if first_tx else date.today() - timedelta(days=365))
        report, missing, updated = [], [], 0
        where = [""]  # "[n/total] " do ativo em curso
        started = [0.0]

        def note(line):
            report.append(line)
            if progress:
                # com o tempo que o ativo levou, para se ver qual é o lento (ex.: o Yahoo a limitar os pedidos)
                took = f" ({_time.monotonic() - started[0]:.1f} s)" if where[0] else ""
                progress(where[0] + line + took)
        # os erros do yfinance (ex.: "No fundamentals data found") já ficam no resumo por ativo
        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        from .data import load_portfolio
        held = {pos.asset.ticker for pos in load_portfolio(None).open_positions}
        # os ativos de demonstração são fictícios: não existem no Yahoo Finance
        insts = [i for i in Instrument.query.all() if not i.ticker.startswith("DEMO-")]
        gone = []  # ativos juntados com outro durante a atualização
        tx_span = {t: (lo, hi) for t, lo, hi in db.session.query(
            Transaction.instrument, db.func.min(Transaction.date), db.func.max(Transaction.date)
        ).group_by(Transaction.instrument)}
        price_min = dict(db.session.query(Price.instrument, db.func.min(Price.date)).group_by(Price.instrument))
        quick = skipped = 0
        # só com as posições abertas, a fila são elas (e os índices): o contador [n/total] conta só esses
        queue = [i for i in insts if not only_open or i.kind == "index" or i.ticker in held]
        closed = len(insts) - len(queue)
        if only is not None:
            queue = [i for i in queue if i.ticker in only]
        if "quotes" not in phases:
            queue = []
        _progress.update(done=0, total=len(queue), current="")
        for position, inst in enumerate(queue, 1):
            if inst in gone:
                continue
            where[0] = f"[{position}/{len(queue)}] "
            started[0] = _time.monotonic()
            _progress.update(done=position - 1, current=inst.ticker)
            _beat()
            problems = []
            mode = _plan(inst, held, tx_span, price_min, full)
            if mode == "skip":  # posição fechada com as cotações já completas
                skipped += 1
                continue
            found = _incremental(yf, inst, inst.last_quote - timedelta(days=5)) if mode == "incremental" else None
            if found is not None:
                quick += 1
            else:
                try:
                    found = _resolve_symbol(yf, inst, start, problems)
                except Exception as exc:  # um símbolo inválido não deve parar o resto
                    missing.append(inst.ticker)
                    note(f"{inst.ticker}: erro ({exc})")
                    continue
                if found is None:
                    missing.append(inst.ticker)
                    why = "; ".join(dict.fromkeys(problems)) if problems else "nenhum símbolo encontrado"
                    note(f"{inst.ticker}: sem cotações em {inst.currency} ({why[:300]})")
                    continue
            symbol, hist, scale = found
            twin = _twin(inst, symbol, insts)
            if twin:  # o mesmo título já existe com o ticker da bolsa (ex.: comprado também na XTB)
                from .importer import merge_instruments
                note(f"{inst.ticker}: é o mesmo título que {twin.ticker}; ativos juntados")
                held.add(twin.ticker)
                gone.append(inst)
                merge_instruments(inst, twin)
                db.session.commit()
                continue
            if symbol != inst.data_symbol:
                # cotações guardadas com outro símbolo podem estar noutra moeda
                Price.query.filter_by(instrument=inst.ticker).delete()
                inst.data_symbol = symbol
            try:
                n = _upsert(Price, "instrument", inst.ticker, "close", hist, scale)
                closes = _closes(hist, scale)
                if closes:
                    inst.last_quote = closes[-1][0]
            except Exception as exc:  # um ativo com dados inválidos não deve parar o resto
                db.session.rollback()
                missing.append(inst.ticker)
                note(f"{symbol}: erro ao guardar ({exc})")
                continue
            updated += inst.kind != "index" and n > 0
            last = f" · último fecho {closes[-1][1]:.2f} {inst.currency} ({closes[-1][0]:%d/%m/%Y})" if closes else ""
            note(f"{symbol}: {n} cotações{last}")

        where[0] = ""
        if "fx" not in phases:
            currencies = set()
        elif only_open:  # só os câmbios dos ativos que se atualizaram
            currencies = {i.currency for i in insts if i.kind == "index" or i.ticker in held}
        else:
            currencies = {i.currency for i in insts} | {c for (c,) in db.session.query(Transaction.currency).distinct()}
        for cur in sorted(c for c in currencies if c and c != "EUR"):
            fx_start = start
            if not full:  # só os dias novos, se o histórico guardado já cobre o início
                lo, hi = db.session.query(db.func.min(FxRate.date), db.func.max(FxRate.date)).filter(
                    FxRate.currency == cur).one()
                if hi and lo <= start + timedelta(days=7):
                    fx_start = max(start, hi - timedelta(days=5))
            try:
                n = _upsert(FxRate, "currency", cur, "rate", yf.Ticker(f"EUR{cur}=X").history(start=fx_start))
                note(f"EUR/{cur}: {n} taxas")
            except Exception as exc:
                db.session.rollback()
                note(f"EUR/{cur}: erro ({exc})")

        where[0] = ""
        # eventos (resultados, dividendos) e setor só interessam para as posições abertas; os ativos vendidos
        # podem já nem existir em bolsa (ex.: empresas compradas ou fundidas)
        open_queue = [i for i in insts if i not in gone and i.kind != "index" and i.ticker in held
                      and "events" in phases and (only is None or i.ticker in only)]
        payers = 0
        _progress.update(done=0, total=len(open_queue), current="")
        for k, inst in enumerate(open_queue, 1):
            _progress.update(done=k - 1, current=f"eventos de {inst.ticker}")
            _beat()
            step_started = _time.monotonic()
            t = yf.Ticker(inst.data_symbol or inst.ticker)
            if not inst.sector and inst.kind == "etf":
                inst.sector = "ETF"  # o Yahoo não tem "dados fundamentais" de ETF: o pedido só dava erro
            elif inst.kind != "etf" and (not inst.sector or _fundamentals_due(inst.ticker)):
                try:
                    info = t.info or {}
                except Exception as exc:  # o yfinance falha muitas vezes aqui (crumb, 429): há a segunda fonte
                    info = {}
                    note(f"{inst.ticker} info do Yahoo: erro ({str(exc)[:120]})")
                if not inst.sector:
                    inst.sector = info.get("sector") or ("ETF" if info.get("quoteType") == "ETF" else None)
                if info.get("quoteType", "EQUITY") == "EQUITY" and _fundamentals_due(inst.ticker):
                    try:
                        got = _store_fundamentals(inst, info, inst.data_symbol or inst.ticker)
                        if not got:
                            note(f"{inst.ticker} dados fundamentais: o Yahoo não devolveu dados (tenta-se de novo "
                                 "na próxima atualização; podes indicá-los à mão na Carteira)")
                    except Exception as exc:  # informação opcional (valor de cada ação)
                        db.session.rollback()
                        note(f"{inst.ticker} dados fundamentais: erro ({str(exc)[:120]})")
            try:
                _store_calendar(inst.ticker, t.calendar or {})
            except Exception as exc:
                note(f"{inst.ticker} calendário: erro ({exc})")
            try:
                payers += _store_dividends(yf, inst) > 0
            except Exception as exc:  # opcional: só serve à projeção de dividendos
                db.session.rollback()
                note(f"{inst.ticker} dividendos: erro ({str(exc)[:120]})")
            if progress:
                progress(f"[eventos {k}/{len(open_queue)}] {inst.ticker} ({_time.monotonic() - step_started:.1f} s)")
        if stats is not None:  # um bocado de uma atualização feita aos bocados: o resumo junta-se no fim
            db.session.commit()
            stats.update(missing=missing, updated=updated, closed=closed, quick=quick, skipped=skipped,
                         payers=payers)
            return "\n".join(report)
        if open_queue:
            note(f"Dividendos por ação (Yahoo, últimos 12 meses): {payers} de {len(open_queue)} posições abertas pagam.")
        if closed:
            note(f"Só posições abertas: {closed} ativos fechados não foram atualizados.")
        if quick or skipped:
            note(f"Atualização incremental: {quick} ativos só com os últimos dias; "
                          f"{skipped} posições fechadas sem pedidos.")
        db.session.commit()
        Setting.set("refresh_missing", ",".join(missing))
        Setting.set("refresh_updated", updated)
        Setting.set("refresh_report", "\n".join(report))
        Setting.set("last_refresh", datetime.now().isoformat(timespec="seconds"))
        return "\n".join(report)
    finally:
        _progress.update(done=0, total=0, current="")
        _lock.release()


# bolsas europeias por ordem de preferência para ativos em EUR (a Trading 212 usa a Xetra)
EUR_SUFFIXES = (".DE", ".PA", ".AS", ".MI", ".MC", ".LS", ".BR", ".F")
# o Yahoo cota algumas bolsas em subunidades (pence)
SUBUNITS = {"GBp": ("GBP", 0.01), "GBX": ("GBP", 0.01), "ZAc": ("ZAR", 0.01), "ILA": ("ILS", 0.01)}


def _candidates(yf, inst):
    """Símbolos a experimentar: o definido, os encontrados pelo ISIN e o ticker com sufixos de bolsa."""
    found = []
    if inst.data_symbol:
        found.append(inst.data_symbol)
    if inst.isin:
        try:
            quotes = yf.Search(inst.isin, max_results=10).quotes or []
        except Exception:
            quotes = []
        found += [q["symbol"] for q in quotes if q.get("symbol")]
    base = inst.ticker.strip().upper()
    if base != (inst.isin or "").upper():  # a Trade Republic usa o ISIN como ticker
        found.append(base)
        if inst.currency == "EUR":
            found += [base + s for s in EUR_SUFFIXES]
    if inst.currency == "EUR":  # as bolsas europeias primeiro: o ISIN devolve muitas vezes a cotação dos EUA
        found.sort(key=lambda s: (s != inst.data_symbol, not any(s.endswith(x) for x in EUR_SUFFIXES)))
    return list(dict.fromkeys(found))[:12]


def _reference_price(inst):
    """Último preço de transação na moeda do ativo, para confirmar o nível das cotações."""
    t = (Transaction.query.filter(Transaction.instrument == inst.ticker, Transaction.price > 0,
                                  Transaction.currency == inst.currency)
         .order_by(Transaction.date.desc()).first())
    return (t.date, t.price) if t else None


def _plan(inst, held, tx_span, price_min, full):
    """"full" (símbolo e histórico todos), "incremental" (só os dias novos) ou "skip" (nada a pedir)."""
    if full or not inst.data_symbol or not inst.last_quote:
        return "full"  # símbolo ainda por validar
    first, last = tx_span.get(inst.ticker, (None, None))
    lowest = price_min.get(inst.ticker)
    if first and (lowest is None or lowest > first + timedelta(days=7)):
        return "full"  # transações mais antigas do que as cotações guardadas
    if inst.kind != "index" and inst.ticker not in held and last and inst.last_quote >= last:
        return "skip"  # posição fechada: o histórico já cobre todas as transações
    return "incremental"


def _incremental(yf, inst, since):
    """Cotações desde `since` com o símbolo já validado; None se for preciso o histórico todo."""
    try:
        t = yf.Ticker(inst.data_symbol)
        hist = t.history(start=since, auto_adjust=False)
        if hist is None or hist.empty:
            return None
        cur = (getattr(t, "history_metadata", None) or {}).get("currency")
        cur, scale = SUBUNITS.get(cur, (cur, 1.0))
        if cur and cur != inst.currency:
            return None
        if any(split for _, row in hist.iterrows() for split in [_split(row)]):
            return None  # desdobramento recente: as cotações antigas têm de ser ajustadas outra vez
        return inst.data_symbol, hist, scale
    except Exception:
        return None


def _split(row):
    try:
        v = float(row.get("Stock Splits", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) else 0.0


def _twin(inst, symbol, insts):
    """Outro ativo que é o mesmo título: `inst` só tem o ISIN como ticker e o símbolo encontrado é o do outro."""
    from .importer import _ISIN
    if not (inst.isin and _ISIN.match(inst.ticker)):
        return None
    return next((o for o in insts if o is not inst and o.kind != "index" and not _ISIN.match(o.ticker)
                 and o.currency == inst.currency and o.isin in (None, inst.isin)
                 and symbol in (o.data_symbol, o.ticker)), None)


def _resolve_symbol(yf, inst, start, problems=None):
    """Escolhe o símbolo cujas cotações estão na moeda do ativo e perto dos preços das transações.

    Devolve (símbolo, histórico, fator) ou None. O fator converte subunidades (ex.: pence) na moeda.
    """
    ref = _reference_price(inst)
    fallback = None
    for symbol in _candidates(yf, inst):
        t = yf.Ticker(symbol)
        try:
            hist = t.history(start=start, auto_adjust=False)
        except Exception as exc:  # guardado para o resumo: sem isto só se via "sem cotações"
            if problems is not None:
                problems.append(f"{symbol}: {exc}")
            continue
        if hist is None or hist.empty:
            if problems is not None:
                problems.append(f"{symbol}: sem dados")
            continue
        cur = (getattr(t, "history_metadata", None) or {}).get("currency")
        cur, scale = SUBUNITS.get(cur, (cur, 1.0))
        if cur and cur != inst.currency:
            if problems is not None:
                problems.append(f"{symbol}: cotado em {cur}")
            continue
        if ref is None:
            return symbol, hist, scale
        ref_date, ref_price = ref
        closes = _closes(hist)
        if not closes:
            continue
        close = next((c for d, c in reversed(closes) if d <= ref_date), closes[0][1]) * scale
        if close > 0 and 0.6 <= ref_price / close <= 1.6:
            return symbol, hist, scale
        fallback = fallback or (symbol, hist, scale)
    # nenhum perto do preço das transações (ex.: um desdobramento): usa o primeiro na moeda certa
    return fallback


def _set_status(value):
    """Grava o estado da atualização; uma base ocupada não pode deixar a página a rodar para sempre."""
    for _ in range(3):
        try:
            Setting.set("refresh_status", value)
            return True
        except Exception:
            db.session.rollback()
            _time.sleep(2)
    return False


def _running_status(only_open, done=0, total=0, current=""):
    """"running:<hora>|<só abertas>|<feitos>|<total>|<ativo>": a hora serve de sinal de vida e o resto, de progresso
    para qualquer processo do servidor (a página pode ser servida por outro que não o da atualização)."""
    return (f"running:{datetime.now().isoformat(timespec='seconds')}|{int(only_open)}|{done}|{total}|"
            f"{current.replace('|', ' ')}")


def _beat():
    """Sinal de vida da atualização lançada pela página: sem ele, o estado "a atualizar" caduca em 5 minutos."""
    if _background["on"]:
        try:
            Setting.set("refresh_status", _running_status(_background["only_open"], **_progress))
        except Exception:  # só um sinal de vida: se a base estiver ocupada, o do ativo seguinte chega
            db.session.rollback()


# ------------------------------------------------------------- atualização aos bocados (pela página)
# Em servidores que não deixam correr threads da aplicação (ex.: PythonAnywhere), a atualização em segundo plano
# só avançava enquanto a página fazia pedidos e morria quando o servidor reciclava o processo. A página passa a
# pedir a atualização aos bocados: cada pedido faz alguns ativos (~10 s) e o progresso fica guardado na base de
# dados, por isso mudar de página ou recarregar continua do sítio onde ficou.
STEP_BUDGET = 10.0  # segundos de trabalho por pedido
JOB_STALE = timedelta(minutes=30)  # um trabalho parado há mais do que isto recomeça do início


def _job():
    import json
    try:
        job = json.loads(Setting.get("refresh_job") or "null")
    except ValueError:
        return None
    if not isinstance(job, dict):
        return None
    try:
        if datetime.now() - datetime.fromisoformat(job["touched"]) > JOB_STALE:
            return None
    except (KeyError, ValueError):
        return None
    return job


def _save_job(job):
    import json
    job["touched"] = datetime.now().isoformat(timespec="seconds")
    Setting.set("refresh_job", json.dumps(job) if job.get("steps") is not None else None)


def current_job():
    """O trabalho por terminar (para a página o continuar), ou None."""
    job = _job()
    return {"only_open": job["only_open"], "done": job["i"], "total": len(job["steps"])} if job else None


def _new_job(only_open):
    """Os passos: as cotações de cada ativo, os câmbios e os eventos de cada posição aberta."""
    from .data import load_portfolio
    ensure_benchmarks()
    held = {pos.asset.ticker for pos in load_portfolio(None).open_positions}
    insts = [i for i in Instrument.query.order_by(Instrument.ticker).all() if not i.ticker.startswith("DEMO-")]
    quotes = [i.ticker for i in insts if not only_open or i.kind == "index" or i.ticker in held]
    events = [i.ticker for i in insts if i.kind != "index" and i.ticker in held]
    steps = [["quotes", t] for t in quotes] + [["fx", ""]] + [["events", t] for t in events]
    return {"only_open": bool(only_open), "steps": steps, "i": 0, "report": [], "missing": [], "updated": 0,
            "quick": 0, "skipped": 0, "payers": 0, "closed": 0, "started": datetime.now().isoformat(timespec="seconds")}


def _step_label(step):
    phase, ticker = step
    return "câmbios" if phase == "fx" else (f"eventos de {ticker}" if phase == "events" else ticker)


def refresh_step(only_open=False, restart=False, budget=STEP_BUDGET):
    """Faz o bocado seguinte da atualização (cerca de `budget` segundos) e devolve o progresso.

    {"done", "total", "current", "finished"} e, no fim, {"updated", "missing", "report"}."""
    job = None if restart else _job()
    if job is None or job["only_open"] != bool(only_open) and job["i"] == 0:
        job = _new_job(only_open)
    t0 = _time.monotonic()
    total = len(job["steps"])
    did = 0  # pelo menos um passo por pedido
    while job["i"] < total and (did == 0 or _time.monotonic() - t0 < budget):
        did += 1
        phase, ticker = job["steps"][job["i"]]
        Setting.set("refresh_status", _running_status(job["only_open"], job["i"], total, _step_label(job["steps"][job["i"]])))
        stats = {}
        out = refresh_all(only_open=job["only_open"], only={ticker} if ticker else set(), phases=(phase,), stats=stats)
        if not stats:  # outra atualização a correr (ex.: na consola): tenta-se no pedido seguinte
            _save_job(job)
            return {"done": job["i"], "total": total, "current": _step_label(job["steps"][job["i"]]),
                    "finished": False, "busy": out}
        job["report"] += [ln for ln in out.split("\n") if ln]
        job["missing"] += stats.get("missing", [])
        job["updated"] += stats.get("updated", 0)
        for k in ("quick", "skipped", "payers"):
            job[k] += stats.get(k, 0)
        job["closed"] = max(job["closed"], stats.get("closed", 0))
        job["i"] += 1
        _save_job(job)
    if job["i"] < total:
        return {"done": job["i"], "total": total, "current": _step_label(job["steps"][job["i"]]), "finished": False}
    report = job["report"]
    events = sum(1 for p, _ in job["steps"] if p == "events")
    if events:
        report.append(f"Dividendos por ação (Yahoo, últimos 12 meses): {job['payers']} de {events} posições abertas pagam.")
    if job["only_open"] and job["closed"]:
        report.append(f"Só posições abertas: {job['closed']} ativos fechados não foram atualizados.")
    if job["quick"] or job["skipped"]:
        report.append(f"Atualização incremental: {job['quick']} ativos só com os últimos dias; "
                      f"{job['skipped']} posições fechadas sem pedidos.")
    Setting.set("refresh_missing", ",".join(job["missing"]))
    Setting.set("refresh_updated", job["updated"])
    Setting.set("refresh_report", "\n".join(report))
    Setting.set("last_refresh", datetime.now().isoformat(timespec="seconds"))
    Setting.set("refresh_job", None)
    _set_status("")
    return {"done": total, "total": total, "current": "", "finished": True, "updated": job["updated"],
            "missing": job["missing"]}


def refresh_in_background(app, only_open=False):
    """Corre a atualização numa thread e guarda o estado para as páginas o mostrarem."""
    if _lock.locked():
        return
    Setting.set("refresh_status", _running_status(only_open))

    def run():
        with app.app_context():
            _background.update(on=True, only_open=only_open)
            try:
                for attempt in range(3):
                    try:
                        log.info(refresh_all(only_open=only_open))
                        _set_status("")
                        return
                    except Exception as exc:  # sem isto o erro perdia-se na thread e o aviso nunca saía
                        db.session.rollback()
                        if "database is locked" in str(exc) and attempt < 2:
                            # outra escrita (ex.: uma atualização na consola) segurava a base de dados: a
                            # atualização é idempotente, por isso espera-se e repete-se
                            log.warning("Base de dados ocupada; nova tentativa em 15 s")
                            _time.sleep(15)
                            continue
                        log.exception("Falha na atualização de cotações")
                        _set_status(f"error:{exc}")
                        return
            finally:
                _background["on"] = False
    threading.Thread(target=run, daemon=True).start()


def refresh_progress():
    """Progresso da atualização em curso, lido do estado (vale para qualquer processo do servidor)."""
    status = Setting.get("refresh_status") or ""
    parts = status.split("|")
    if not status.startswith("running:") or len(parts) < 5:
        return {"only_open": False, "done": 0, "total": 0, "current": ""}
    return {"only_open": parts[1] == "1", "done": int(parts[2] or 0), "total": int(parts[3] or 0),
            "current": parts[4]}


def refresh_state():
    """Estado da última atualização: (em curso, erro, tickers sem cotações)."""
    status = Setting.get("refresh_status") or ""
    error = status[len("error:"):] if status.startswith("error:") else None
    running = False
    if status.startswith("running:"):
        # a atualização renova este estado a cada ativo; se a aplicação foi fechada a meio (ex.: o servidor
        # recarregou), o estado fica para trás e ignora-se ao fim de 5 minutos sem sinal de vida
        stamp = status[len("running:"):].split("|")[0]
        running = datetime.now() - datetime.fromisoformat(stamp) < timedelta(minutes=5)
    missing = [t for t in (Setting.get("refresh_missing") or "").split(",") if t]
    return running, error, missing


def _closes(hist, scale=1.0):
    """Fechos (data, preço) tal como negociados em cada dia, sem dias vazios.

    O Yahoo ajusta o histórico aos desdobramentos (ex.: depois de um 10:1, os preços antigos aparecem
    divididos por 10), mas as quantidades vêm das transações, que não são ajustadas. Desfazer o ajuste
    evita que a posição valha 10× menos (ou, num reagrupamento, 15× mais) antes da data do desdobramento.
    """
    rows = []
    for ts, row in hist.iterrows():
        try:
            split = float(row.get("Stock Splits", 0) or 0)
        except (TypeError, ValueError):
            split = 0.0
        rows.append((ts.date(), float(row["Close"]) * scale, split if math.isfinite(split) else 0.0))
    out, factor = [], 1.0
    for d, close, split in reversed(rows):
        if math.isfinite(close) and close > 0:  # o Yahoo devolve por vezes dias sem fecho (NaN)
            out.append((d, close * factor))
        if split > 0:
            factor *= split  # os dias anteriores ao desdobramento negociaram a outro preço
    return out[::-1]


def _upsert(model, key_field, key, value_field, hist, scale=1.0):
    existing = {r.date: r for r in model.query.filter(getattr(model, key_field) == key).all()}
    n = 0
    for d, v in _closes(hist, scale):
        rec = existing.get(d)
        if rec is None:
            rec = model(**{key_field: key, "date": d})
            db.session.add(rec)
        setattr(rec, value_field, v)
        n += 1
    db.session.commit()
    return n


def _store_dividends(yf, inst):
    """Guarda os dividendos por ação dos últimos ~13 meses segundo o Yahoo; devolve quantos."""
    if not inst.data_symbol:
        return 0
    t = yf.Ticker(inst.data_symbol)
    hist = t.history(start=date.today() - timedelta(days=400), auto_adjust=False)
    cur = (getattr(t, "history_metadata", None) or {}).get("currency")
    cur, scale = SUBUNITS.get(cur, (cur, 1.0))
    if cur and cur != inst.currency:
        return 0
    found = {}
    for ts, row in hist.iterrows():
        try:
            amount = float(row.get("Dividends", 0) or 0)
        except (TypeError, ValueError):
            continue
        if math.isfinite(amount) and amount > 0:
            day = ts.date()
            found[day] = found.get(day, 0.0) + amount * scale
    DividendHistory.query.filter_by(instrument=inst.ticker).delete()
    for day, amount in found.items():
        db.session.add(DividendHistory(instrument=inst.ticker, date=day, amount=amount))
    db.session.flush()
    return len(found)


FUNDAMENTALS_DAYS = 7  # os dados fundamentais mudam pouco: no máximo um pedido por semana e ação


def _fundamentals_due(ticker):
    """Pedir de novo: sem dados guardados (nem que tenha havido uma tentativa vazia) ou com mais de uma semana."""
    row = db.session.get(Fundamental, ticker)
    if row is None or row.updated is None or all(v is None for v in (row.eps, row.eps_forward, row.bvps, row.fcf,
                                                                       row.owner, row.nopat)):
        return True
    return (date.today() - row.updated).days >= FUNDAMENTALS_DAYS


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _per_eur(currency):
    """Unidades de `currency` por 1 EUR (o câmbio mais recente guardado)."""
    currency = (currency or "EUR").upper()
    if currency == "EUR":
        return 1.0
    row = FxRate.query.filter_by(currency=currency).order_by(FxRate.date.desc()).first()
    return row.rate if row else None


def _convert(value, source, target):
    """`value` de `source` para `target` (None se faltar o câmbio)."""
    if value is None:
        return None
    source, target = (source or target).upper(), target.upper()
    if source == target:
        return value
    a, b = _per_eur(source), _per_eur(target)
    return value / a * b if a and b else None


def _latest(series, kind):
    rows = series.get(kind) or []
    return rows[-1] if rows else None


def _from_timeseries(series, target):
    """Lucro por ação, valor contabilístico, cash flow livre por ação e crescimento a partir das demonstrações."""
    eps = _latest(series, "trailingDilutedEPS")
    shares = _latest(series, "annualOrdinarySharesNumber") or _latest(series, "annualShareIssued")
    equity = _latest(series, "annualStockholdersEquity")
    fcf = _latest(series, "trailingFreeCashFlow") or _latest(series, "annualFreeCashFlow")
    out = {"eps": _convert(eps[1], eps[2], target) if eps else None, "bvps": None, "fcf": None, "growth": None}
    if shares and shares[1] > 0:
        if equity:
            out["bvps"] = _convert(equity[1] / shares[1], equity[2], target)
        if fcf:
            out["fcf"] = _convert(fcf[1] / shares[1], fcf[2], target)
    annual = [v for _, v, _ in (series.get("annualDilutedEPS") or [])][-4:]
    if len(annual) >= 3 and annual[0] > 0 and annual[-1] > 0:  # crescimento médio anual do lucro por ação
        out["growth"] = (annual[-1] / annual[0]) ** (1 / (len(annual) - 1)) - 1
    out.update(owner=None, nopat=None, net_cash=None)
    if not shares or shares[1] <= 0:
        return out
    n = shares[1]
    # Owner Earnings (Buffett): lucro líquido + amortizações − CAPEX de manutenção ± fundo de maneio. O CAPEX de
    # manutenção não é publicado: usa-se o menor entre o CAPEX e as amortizações. A variação do fundo de maneio
    # da demonstração de fluxos de caixa já vem com o sinal do efeito no caixa.
    income = _latest(series, "annualNetIncome")
    dep = _latest(series, "annualDepreciationAndAmortization") or _latest(series, "annualReconciledDepreciation")
    capex = _latest(series, "annualCapitalExpenditure")
    wc = _latest(series, "annualChangeInWorkingCapital")
    if income and dep:
        maintenance = min(abs(capex[1]), dep[1]) if capex else dep[1]
        owner = income[1] + dep[1] - maintenance + (wc[1] if wc else 0.0)
        out["owner"] = _convert(owner / n, income[2], target)
    # Earnings Power Value (Greenwald): NOPAT normalizado = resultado operacional médio (até 5 anos) × (1 − imposto)
    ebit = [(v, c) for _, v, c in (series.get("annualEBIT") or [])][-5:]
    if ebit:
        rates = [v for _, v, _ in (series.get("annualTaxRateForCalcs") or [])][-5:]
        tax = min(max(sum(rates) / len(rates), 0.0), 0.4) if rates else 0.21
        out["nopat"] = _convert(sum(v for v, _ in ebit) / len(ebit) * (1 - tax) / n, ebit[-1][1], target)
    cash = _latest(series, "annualCashCashEquivalentsAndShortTermInvestments") or \
        _latest(series, "annualCashAndCashEquivalents")
    debt = _latest(series, "annualTotalDebt")
    if cash or debt:
        currency = (cash or debt)[2]
        out["net_cash"] = _convert(((cash[1] if cash else 0.0) - (debt[1] if debt else 0.0)) / n, currency, target)
    return out


def _symbols_for(inst, symbol):
    """O símbolo da cotação e, pelo ISIN, outras cotações da mesma empresa (ex.: a principal, nos EUA)."""
    found = [symbol]
    if inst.isin:
        try:
            found += [q["symbol"] for q in (yahoo.Search(inst.isin, max_results=6).quotes or [])
                      if q.get("symbol") and q.get("quoteType", "EQUITY") == "EQUITY"]
        except Exception:
            pass
    return list(dict.fromkeys(found))[:4]


def _store_fundamentals(inst, info, symbol=None):
    """Lucro por ação (atual e previsto), valor contabilístico, cash flow livre por ação e crescimento, na moeda da
    cotação guardada (`inst.currency`).

    Primeiro o `info` (quoteSummary); o que faltar vem das séries das demonstrações financeiras (outro serviço do
    Yahoo, a única fonte de owner earnings, NOPAT e caixa líquida), do símbolo da cotação ou de outra cotação da
    mesma empresa (pelo ISIN). Os valores vêm na moeda
    em que o Yahoo os dá e convertem-se ao câmbio mais recente (ex.: Adobe cotada em EUR com contas em USD).
    Sem nenhum dado não grava nada e devolve False (tenta-se de novo na próxima atualização).
    """
    target = (inst.currency or "EUR").upper()
    quote = (info.get("currency") or target).upper()
    report = (info.get("financialCurrency") or quote).upper()
    shares = _num(info.get("sharesOutstanding"))
    fcf_total = _num(info.get("freeCashflow"))
    growths = [g for g in (_num(info.get("earningsGrowth")), _num(info.get("revenueGrowth"))) if g is not None]
    values = {"eps": _convert(_num(info.get("trailingEps")), quote, target),
              "eps_forward": _convert(_num(info.get("forwardEps")), quote, target),
              "bvps": _convert(_num(info.get("bookValue")), report, target),
              "fcf": _convert(fcf_total / shares, report, target) if fcf_total is not None and shares else None,
              "growth": sum(growths) / len(growths) if growths else None,
              "owner": None, "nopat": None, "net_cash": None}
    # as demonstrações completam o que o info não trouxe (e são a única fonte de owner earnings, NOPAT e caixa
    # líquida): do símbolo da cotação ou, sem dados, de outra cotação da mesma empresa (pelo ISIN)
    if symbol:
        for candidate in _symbols_for(inst, symbol):
            try:
                series = yahoo.fundamentals(candidate)
            except Exception:
                continue
            extra = _from_timeseries(series, target)
            if any(v is not None for v in extra.values()):
                for key, value in extra.items():
                    if values.get(key) is None:
                        values[key] = value
                break
    if all(values[k] is None for k in ("eps", "eps_forward", "bvps", "fcf", "owner", "nopat")):
        return False
    row = db.session.get(Fundamental, inst.ticker) or Fundamental(ticker=inst.ticker)
    for key, value in values.items():
        setattr(row, key, value)
    row.updated = date.today()
    db.session.add(row)
    return True


def _store_calendar(ticker, cal, today=None):
    """Guarda os próximos eventos do calendário do Yahoo (yfinance): resultados, data ex-dividendo e pagamento.

    Uma data que mudou (ex.: resultados estimados para 12/11 e depois anunciados para 13/11) substitui a anterior,
    em vez de ficarem as duas.
    """
    today = today or date.today()

    def as_date(d):
        return d.date() if isinstance(d, datetime) else d if isinstance(d, date) else None

    def upsert(d, kind, **kw):
        d = as_date(d)
        if d is None:
            return
        for old in Event.query.filter(Event.instrument == ticker, Event.kind == kind, Event.date >= today,
                                      Event.date != d):
            db.session.delete(old)
        ev = Event.query.filter_by(instrument=ticker, kind=kind, date=d).first() or \
            Event(instrument=ticker, kind=kind, date=d)
        for k, v in kw.items():
            setattr(ev, k, v)
        db.session.add(ev)

    earnings = [d for d in (as_date(x) for x in (cal.get("Earnings Date") or [])) if d]
    if earnings:
        # duas datas = o Yahoo ainda só tem uma estimativa (um intervalo); uma = a data anunciada
        ranged = len(earnings) > 1 and earnings[-1] != earnings[0]
        upsert(earnings[0], "earnings", title=None,
               timing=f"estimado: {earnings[0]:%d/%m}–{earnings[-1]:%d/%m}" if ranged else None,
               eps_estimate=cal.get("Earnings Average"), revenue_estimate=cal.get("Revenue Average"))
    if cal.get("Ex-Dividend Date"):
        upsert(cal["Ex-Dividend Date"], "ex_dividend", title="Ex-dividendo")
    if cal.get("Dividend Date"):
        upsert(cal["Dividend Date"], "dividend_pay", title="Pagamento")
