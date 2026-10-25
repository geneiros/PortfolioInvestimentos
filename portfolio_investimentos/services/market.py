"""Estado do mercado e atualização de dados (cotações, câmbios, notícias, eventos).

A atualização usa o pacote opcional `yfinance` (pip install yfinance). Sem ele, ou sem
rede, a aplicação continua a funcionar com as cotações já guardadas.
"""
import logging
import math
import threading
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


def market_status(now=None):
    now = (now or datetime.now(LISBON)).astimezone(LISBON)
    if now.weekday() < 5 and OPEN <= now.time() < CLOSE:
        return {"open": True, "label": "Aberto", "detail": f"Fecha às {CLOSE:%H:%M}"}
    nxt = now.date()
    if now.weekday() >= 5 or now.time() >= CLOSE:
        nxt += timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    when = "hoje" if nxt == now.date() else ("amanhã" if nxt == now.date() + timedelta(days=1)
                                             else WEEKDAYS[nxt.weekday()])
    return {"open": False, "label": "Fechado", "detail": f"Abre {when} às {OPEN:%H:%M}"}


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


def yfinance_available():
    try:
        import yfinance  # noqa: F401
        return True
    except ImportError:
        return False


def refresh_all(start=None):
    """Atualiza cotações, câmbios, notícias e eventos. Devolve um resumo textual."""
    try:
        import yfinance as yf
    except ImportError:
        return "O pacote yfinance não está instalado (pip install yfinance)."
    if not _lock.acquire(blocking=False):
        return "Já existe uma atualização em curso."
    try:
        ensure_benchmarks()
        first_tx = db.session.query(db.func.min(Transaction.date)).scalar()
        start = start or (first_tx - timedelta(days=7) if first_tx else date.today() - timedelta(days=365))
        report, missing, updated = [], [], 0
        # os erros do yfinance (ex.: "No fundamentals data found") já ficam no resumo por ativo
        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        from .data import load_portfolio
        held = {pos.asset.ticker for pos in load_portfolio(None).open_positions}
        # os ativos de demonstração são fictícios: não existem no Yahoo Finance
        insts = [i for i in Instrument.query.all() if not i.ticker.startswith("DEMO-")]
        for inst in insts:
            try:
                found = _resolve_symbol(yf, inst, start)
            except Exception as exc:  # um símbolo inválido não deve parar o resto
                missing.append(inst.ticker)
                report.append(f"{inst.ticker}: erro ({exc})")
                continue
            if found is None:
                missing.append(inst.ticker)
                report.append(f"{inst.ticker}: sem cotações em {inst.currency} (define o símbolo de dados em Ativos)")
                continue
            symbol, hist, scale = found
            if symbol != inst.data_symbol:
                # cotações guardadas com outro símbolo podem estar noutra moeda
                Price.query.filter_by(instrument=inst.ticker).delete()
                inst.data_symbol = symbol
            try:
                n = _upsert(Price, "instrument", inst.ticker, "close", hist, scale)
            except Exception as exc:  # um ativo com dados inválidos não deve parar o resto
                db.session.rollback()
                missing.append(inst.ticker)
                report.append(f"{symbol}: erro ao guardar ({exc})")
                continue
            updated += inst.kind != "index" and n > 0
            report.append(f"{symbol}: {n} cotações")

        currencies = {i.currency for i in insts} | {c for (c,) in db.session.query(Transaction.currency).distinct()}
        for cur in sorted(c for c in currencies if c and c != "EUR"):
            try:
                n = _upsert(FxRate, "currency", cur, "rate", yf.Ticker(f"EUR{cur}=X").history(start=start))
                report.append(f"EUR/{cur}: {n} taxas")
            except Exception as exc:
                db.session.rollback()
                report.append(f"EUR/{cur}: erro ({exc})")

        for inst in insts:
            # notícias, eventos e setor só interessam para as posições abertas; os ativos vendidos
            # podem já nem existir em bolsa (ex.: empresas compradas ou fundidas)
            if inst.kind == "index" or inst.ticker not in held:
                continue
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
                _store_news(inst.ticker, t.news or [])
            except Exception as exc:
                report.append(f"{inst.ticker} notícias: erro ({exc})")
            try:
                _store_calendar(inst.ticker, t.calendar or {})
            except Exception as exc:
                report.append(f"{inst.ticker} calendário: erro ({exc})")
        db.session.commit()
        Setting.set("refresh_missing", ",".join(missing))
        Setting.set("refresh_updated", updated)
        Setting.set("refresh_report", "\n".join(report))
        Setting.set("last_refresh", datetime.now().isoformat(timespec="seconds"))
        return "\n".join(report)
    finally:
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


def _resolve_symbol(yf, inst, start):
    """Escolhe o símbolo cujas cotações estão na moeda do ativo e perto dos preços das transações.

    Devolve (símbolo, histórico, fator) ou None. O fator converte subunidades (ex.: pence) na moeda.
    """
    ref = _reference_price(inst)
    fallback = None
    for symbol in _candidates(yf, inst):
        t = yf.Ticker(symbol)
        try:
            hist = t.history(start=start, auto_adjust=False)
        except Exception:
            continue
        if hist is None or hist.empty:
            continue
        cur = (getattr(t, "history_metadata", None) or {}).get("currency")
        cur, scale = SUBUNITS.get(cur, (cur, 1.0))
        if cur and cur != inst.currency:
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


def refresh_in_background(app):
    """Corre a atualização numa thread e guarda o estado para as páginas o mostrarem."""
    if _lock.locked():
        return
    Setting.set("refresh_status", "running:" + datetime.now().isoformat(timespec="seconds"))

    def run():
        with app.app_context():
            try:
                log.info(refresh_all())
                Setting.set("refresh_status", "")
            except Exception as exc:  # sem isto o erro perdia-se na thread e o aviso nunca saía
                log.exception("Falha na atualização de cotações")
                db.session.rollback()
                Setting.set("refresh_status", f"error:{exc}")
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


def _store_news(ticker, items):
    for item in items[:10]:
        content = item.get("content", item)
        url = (content.get("canonicalUrl") or {}).get("url") or content.get("link")
        title = content.get("title")
        if not url or not title or News.query.filter_by(url=url).first():
            continue
        published = content.get("pubDate") or content.get("providerPublishTime")
        if isinstance(published, (int, float)):
            published = datetime.utcfromtimestamp(published)
        elif isinstance(published, str):
            published = datetime.fromisoformat(published.replace("Z", "+00:00")).replace(tzinfo=None)
        source = (content.get("provider") or {}).get("displayName") or content.get("publisher")
        db.session.add(News(instrument=ticker, title=title[:500], url=url, source=source, published_on=published))


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
