"""Acompanhamento (Prospeção): as ações que juntaste (das Oportunidades ou à mão), os parâmetros que
acompanhas em cada uma e os alertas.

Cada parâmetro é uma `WatchRule`:
- preço abaixo/acima de um valor, variação do dia acima de x%, x% ou mais abaixo do máximo de 52 semanas (cotações
  guardadas, atualizadas com as cotações);
- P/L abaixo de x, P/VP abaixo de x, dividendo acima de x% (indicadores do Yahoo, «Atualizar indicadores»);
- critérios do método onde a ação foi encontrada (avisa quando deixa de os cumprir ou volta a cumprir);
- moat (avisa quando a leitura muda, ex.: de Largo para Estreito, ao reanalisar).
Os alertas verificam-se ao abrir a aplicação (Visão Geral, Carteira, Prospeção) e depois de cada atualização;
disparam quando a condição passa a verificar-se e voltam a ficar prontos quando deixa de se verificar.
"""
import json
from datetime import date, datetime, timedelta

from ..models import Instrument, Price, Setting, WatchItem, WatchRule, db
from . import moat, screener

KINDS = {
    "price_below": ("Preço abaixo de", "price"),
    "price_above": ("Preço acima de", "price"),
    "change_pct": ("Variação do dia acima de", "%"),
    "from_high": ("Abaixo do máximo de 52 semanas em pelo menos", "%"),
    "pe_below": ("P/L abaixo de", ""),
    "pb_below": ("P/VP abaixo de", ""),
    "div_above": ("Dividendo acima de", "%"),
    "method": ("Critérios do método", None),
    "moat": ("Leitura do moat", None),
}
GROUPS = (("Preço", ("price_below", "price_above", "change_pct", "from_high")),
          ("Valuation", ("pe_below", "pb_below", "div_above")),
          ("Qualidade", ("method", "moat")))
STALE = timedelta(hours=20)


def snapshot(ticker):
    """Os últimos indicadores do Yahoo guardados para a ação (None se nunca se atualizaram)."""
    try:
        return json.loads(Setting.get(f"track:{ticker}") or "null")
    except ValueError:
        return None


def refresh(ticker, fetch_info=None, now=None):
    """Lê os indicadores ao Yahoo (P/L, P/VP, dividendo, máximo de 52 semanas, critérios do método) e guarda-os.
    Reanalisa o moat se a análise tiver mais de 30 dias."""
    fetch_info = fetch_info or moat.info_of
    info = fetch_info(ticker) or {}
    w = WatchItem.query.filter_by(instrument=ticker).order_by(WatchItem.id).first()
    out = {"pe": info.get("trailingPE"), "pb": info.get("priceToBook"),
           "div": dividend_yield(info),
           "high52": info.get("fiftyTwoWeekHigh"), "low52": info.get("fiftyTwoWeekLow"),
           "price": info.get("regularMarketPrice") or info.get("currentPrice"), "currency": info.get("currency"),
           "at": (now or datetime.now()).isoformat(timespec="minutes")}
    if w and w.method in screener.METHODS:
        met, details = screener.check_info(w.method, _criteria(w), info)
        out["method_met"] = met
        out["method_details"] = [[label, v, ok] for label, v, ok in details]
    Setting.set(f"track:{ticker}", json.dumps(out, ensure_ascii=False))
    a = moat.get(ticker)
    if a and (date.today() - date.fromisoformat(a["date"])).days > 30:
        try:
            moat.analyse(ticker)
        except OSError:  # YahooError: fica a análise anterior
            pass
    return out


def dividend_yield(info):
    """Rendimento de dividendos (fração). O yfinance dá o «dividendYield» em % (0,45 = 0,45%) e o acesso direto em
    fração; o «trailingAnnualDividendYield» vem sempre em fração e é o preferido."""
    v = info.get("trailingAnnualDividendYield")
    if v is None and info.get("dividendYield") is not None:
        d = info["dividendYield"]
        v = d / 100 if d >= 0.2 or info.get("_yfinance") else d
    return v if v is not None and 0 <= v <= 0.25 else None


def _criteria(w):
    try:
        v = json.loads(w.criteria or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def _prices(ticker):
    """Último preço, o anterior e o máximo de 52 semanas, pelas cotações guardadas."""
    rows = Price.query.filter_by(instrument=ticker).order_by(Price.date.desc()).limit(2).all()
    if not rows:
        return None, None, None
    since = rows[0].date - timedelta(days=365)
    high = db.session.query(db.func.max(Price.close)).filter(Price.instrument == ticker, Price.date >= since).scalar()
    return rows[0].close, (rows[1].close if len(rows) > 1 else None), high


def values(w):
    """Os valores atuais de uma ação em acompanhamento (o que os parâmetros comparam)."""
    price, prev, high = _prices(w.instrument)
    snap = snapshot(w.instrument) or {}
    if price is None:
        price = snap.get("price")
    high = max(x for x in (high, snap.get("high52")) if x) if (high or snap.get("high52")) else None
    a = moat.get(w.instrument)
    return {"price": price, "change": (price / prev - 1) if price and prev else None,
            "from_high": (price / high - 1) if price and high else None,
            "pe": snap.get("pe") if snap.get("pe") and snap["pe"] > 0 else None,
            "pb": snap.get("pb") if snap.get("pb") and snap["pb"] > 0 else None,
            "div": snap.get("div"), "method_met": snap.get("method_met"),
            "method_details": snap.get("method_details") or [], "moat": a, "snap_at": snap.get("at"),
            "stale": not snap.get("at") or datetime.now() - datetime.fromisoformat(snap["at"]) > STALE}


def evaluate(rule, v):
    """(verifica-se, texto) de um parâmetro com os valores atuais; verifica-se é None quando falta o valor."""
    t, k = rule.threshold, rule.kind
    if k == "price_below":
        return (None if v["price"] is None or t is None else v["price"] <= t), None
    if k == "price_above":
        return (None if v["price"] is None or t is None else v["price"] >= t), None
    if k == "change_pct":
        return (None if v["change"] is None or t is None else abs(v["change"]) * 100 >= t), None
    if k == "from_high":
        return (None if v["from_high"] is None or t is None else -v["from_high"] * 100 >= t), None
    if k == "pe_below":
        return (None if v["pe"] is None or t is None else v["pe"] <= t), None
    if k == "pb_below":
        return (None if v["pb"] is None or t is None else v["pb"] <= t), None
    if k == "div_above":
        return (None if v["div"] is None or t is None else v["div"] * 100 >= t), None
    if k == "method":
        return v["method_met"], None
    if k == "moat":
        a = v["moat"]
        return (None if not a else a["verdict"] in ("Largo",)), (a["verdict"] if a else None)
    return None, None


SHORT = {"price_below": "Preço ≤", "price_above": "Preço ≥", "change_pct": "Dia ±", "from_high": "Do máximo ≤ −",
         "pe_below": "P/L ≤", "pb_below": "P/VP ≤", "div_above": "Dividendo ≥"}
METHOD_SHORT = {"graham": "Graham", "buffett": "Buffett", "lynch": "Lynch", "greenblatt": "Greenblatt",
                "oneil": "O'Neil", "templeton": "Templeton", "resumo": "Resumo"}


def chip(rule, currency=""):
    """O texto curto de um parâmetro (a etiqueta na lista)."""
    if rule.kind not in SHORT or rule.threshold is None:
        return describe(rule, currency)
    if rule.kind == "from_high":
        return f"−{rule.threshold:g}% do máximo".replace(".", ",")
    unit = KINDS[rule.kind][1]
    if unit == "price":
        return f"{SHORT[rule.kind]} {rule.threshold:,.2f} {currency}".replace(",", " ").replace(".", ",").strip()
    return f"{SHORT[rule.kind]} {rule.threshold:g}{unit}".replace(".", ",")


def describe(rule, currency=""):
    label, unit = KINDS.get(rule.kind, (rule.kind, ""))
    if unit is None or rule.threshold is None:
        return label
    if unit == "price":
        return f"{label} {rule.threshold:,.2f} {currency}".replace(",", " ").replace(".", ",").strip()
    return f"{label} {rule.threshold:g}{unit}".replace(".", ",")


def check(now=None):
    """Verifica todos os parâmetros e devolve os alertas que dispararam agora."""
    now = now or datetime.now()
    fired = []
    currencies = {i.ticker: i.currency for i in Instrument.query.all()}
    for w in WatchItem.query.all():
        rules = WatchRule.query.filter_by(watch_id=w.id).all()
        if not rules:
            continue
        v = values(w)
        for r in rules:
            met, state = evaluate(r, v)
            if met is None:
                continue
            changed = False
            if r.kind == "method":
                changed = r.met is not None and met != r.met
                msg = f"{w.instrument} {'volta a cumprir' if met else 'deixou de cumprir'} os critérios de " \
                      f"{screener.METHODS.get(w.method, {}).get('investor', 'o método')}"
            elif r.kind == "moat":
                changed = bool(r.state) and state != r.state
                msg = f"{w.instrument}: o moat passou de {r.state} para {state}"
            else:
                changed = met and not r.met
                msg = f"{w.instrument}: {describe(r, currencies.get(w.instrument, '')).lower()}"
            if changed and r.alert:
                r.triggered_on, r.message = now, msg
                fired.append(r)
            r.met = met
            if state is not None:
                r.state = state
    db.session.commit()
    return fired


def recent(days=3, now=None):
    """Os alertas disparados nos últimos dias (para o aviso no topo das páginas)."""
    since = (now or datetime.now()) - timedelta(days=days)
    return WatchRule.query.filter(WatchRule.triggered_on.isnot(None), WatchRule.triggered_on >= since,
                                  WatchRule.alert.is_(True)).order_by(WatchRule.triggered_on.desc()).all()


def default_rules(w, has_moat=False):
    """Os parâmetros com que uma ação vinda das Oportunidades começa: os critérios do método e o moat, com alerta."""
    rules = []
    if w.method in screener.METHODS:
        rules.append(WatchRule(watch_id=w.id, kind="method", alert=True))
    if has_moat:
        rules.append(WatchRule(watch_id=w.id, kind="moat", alert=True))
    rules.append(WatchRule(watch_id=w.id, kind="from_high", threshold=20, alert=False))
    return rules
