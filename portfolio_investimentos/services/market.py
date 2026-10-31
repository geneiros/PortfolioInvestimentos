"""Estado do mercado e atualização de dados (cotações, câmbios, notícias, eventos).

A atualização usa o pacote opcional `yfinance` (pip install yfinance). Sem ele, ou sem
rede, a aplicação continua a funcionar com as cotações já guardadas.
"""
import logging
import math
import threading
import warnings
import time as _time
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from statistics import median
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..engine.formatting import WEEKDAYS
from ..models import Alert, Event, FxRate, Instrument, News, Price, Setting, Transaction, db

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
    for ticker, name, color in DEFAULT_BENCHMARKS:
        if not db.session.get(Instrument, ticker):
            db.session.add(Instrument(ticker=ticker, instrument_name=name, kind="index", currency="USD",
                                      data_symbol=ticker, color=color))
    db.session.commit()


def upcoming_events(tickers, today=None, days=60):
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


def refresh_all(start=None, progress=None, only_open=False):
    """Atualiza cotações, câmbios, notícias e eventos. Devolve um resumo textual.

    `progress(linha)` é chamada a cada ativo, à medida que a atualização avança (ex.: para a consola).
    Com `only_open`, só se atualizam as posições abertas (e os índices de comparação); as fechadas ficam como estão.
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

        def note(line):
            report.append(line)
            if progress:
                progress(where[0] + line)
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
        quick = skipped = closed = 0
        _progress.update(done=0, total=len(insts), current="")
        for position, inst in enumerate(insts, 1):
            if inst in gone:
                continue
            if only_open and inst.kind != "index" and inst.ticker not in held:
                closed += 1
                continue
            where[0] = f"[{position}/{len(insts)}] "
            _progress.update(done=position - 1, current=inst.ticker)
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
        if only_open:  # só os câmbios dos ativos que se atualizaram
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

        news_new, news_empty, news_errors = 0, [], {}
        for inst in insts:
            # notícias, eventos e setor só interessam para as posições abertas; os ativos vendidos
            # podem já nem existir em bolsa (ex.: empresas compradas ou fundidas)
            if inst in gone or inst.kind == "index" or inst.ticker not in held:
                continue
            _progress["current"] = f"notícias de {inst.ticker}"
            t = yf.Ticker(inst.data_symbol or inst.ticker)
            if not inst.sector and inst.kind == "etf":
                inst.sector = "ETF"  # o Yahoo não tem "dados fundamentais" de ETF: o pedido só dava erro
            elif not inst.sector:
                try:
                    info = t.info or {}
                    inst.sector = info.get("sector") or ("ETF" if info.get("quoteType") == "ETF" else None)
                except Exception:  # informação opcional
                    pass
            try:
                items, err = _news_items(yf, t, inst)
                added = _store_news(inst.ticker, items)
                news_new += added
                if not items:
                    news_empty.append(inst.ticker)
                if err and not items:
                    news_errors.setdefault(err, []).append(inst.ticker)
            except Exception as exc:
                news_errors.setdefault(str(exc), []).append(inst.ticker)
            try:
                _store_calendar(inst.ticker, t.calendar or {})
            except Exception as exc:
                note(f"{inst.ticker} calendário: erro ({exc})")
        if news_new or news_empty or news_errors:
            note(f"Notícias: {news_new} novas" + (f"; sem notícias: {', '.join(news_empty[:12])}"
                                                           + ("…" if len(news_empty) > 12 else "") if news_empty else ""))
            for msg, tickers in news_errors.items():
                note(f"Notícias: erro em {len(tickers)} ativos ({msg[:200]})")
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


def refresh_in_background(app, only_open=False):
    """Corre a atualização numa thread e guarda o estado para as páginas o mostrarem."""
    if _lock.locked():
        return
    Setting.set("refresh_status", "running:" + datetime.now().isoformat(timespec="seconds"))

    def run():
        with app.app_context():
            for attempt in range(3):
                try:
                    log.info(refresh_all(only_open=only_open))
                    Setting.set("refresh_status", "")
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
                    Setting.set("refresh_status", f"error:{exc}")
                    return
    threading.Thread(target=run, daemon=True).start()


def refresh_state():
    """Estado da última atualização: (em curso, erro, tickers sem cotações)."""
    status = Setting.get("refresh_status") or ""
    error = status[len("error:"):] if status.startswith("error:") else None
    running = False
    if status.startswith("running:"):
        # se a aplicação foi fechada a meio, o estado fica para trás: ignora-o ao fim de 30 minutos
        running = datetime.now() - datetime.fromisoformat(status[len("running:"):]) < timedelta(minutes=30)
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


def _news_items(yf, t, inst):
    """Notícias de um ativo: as do yfinance e, se falhar ou vier vazio, as do acesso direto ao Yahoo."""
    items, err = [], None
    try:
        items = list(t.news or [])
    except Exception as exc:
        err = str(exc)
    if not items:
        from . import yahoo
        if yf is not yahoo:
            try:
                items = list(yahoo.Ticker(inst.data_symbol or inst.ticker).news or [])
            except Exception as exc:
                err = err or str(exc)
    return items, err


def _store_news(ticker, items):
    added = 0
    for item in items[:10]:
        content = item.get("content", item)
        url = (content.get("canonicalUrl") or {}).get("url") or content.get("link")
        title = content.get("title")
        if not url or not title or News.query.filter_by(url=url).first():
            continue
        published = content.get("pubDate") or content.get("providerPublishTime")
        if isinstance(published, (int, float)):
            published = datetime.fromtimestamp(published, timezone.utc).replace(tzinfo=None)
        elif isinstance(published, str):
            published = datetime.fromisoformat(published.replace("Z", "+00:00")).replace(tzinfo=None)
        source = (content.get("provider") or {}).get("displayName") or content.get("publisher")
        db.session.add(News(instrument=ticker, title=title[:500], url=url, source=source, published_on=published))
        added += 1
    return added


def _store_calendar(ticker, cal):
    def upsert(d, kind, **kw):
        if isinstance(d, datetime):
            d = d.date()
        if not isinstance(d, date):
            return
        ev = Event.query.filter_by(instrument=ticker, kind=kind, date=d).first() or \
            Event(instrument=ticker, kind=kind, date=d)
        for k, v in kw.items():
            setattr(ev, k, v)
        db.session.add(ev)

    earnings = cal.get("Earnings Date") or []
    if earnings:
        upsert(earnings[0], "earnings", title="Resultados",
               eps_estimate=cal.get("Earnings Average"), revenue_estimate=cal.get("Revenue Average"))
    if cal.get("Ex-Dividend Date"):
        upsert(cal["Ex-Dividend Date"], "ex_dividend", title="Ex-dividendo")
    if cal.get("Dividend Date"):
        upsert(cal["Dividend Date"], "dividend_pay", title="Pagamento")
