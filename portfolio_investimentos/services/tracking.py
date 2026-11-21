"""Listas de acompanhamento (Prospeção): as ações que juntaste (da triagem ou à mão), em uma ou mais listas, os
parâmetros que acompanhas em cada uma e os alertas.

Cada parâmetro é uma `WatchRule`:
- preço abaixo/acima de um valor, variação do dia acima de x%, x% ou mais abaixo do máximo de 52 semanas (cotações
  guardadas, atualizadas com as cotações);
- P/L abaixo de x, P/VP abaixo de x, dividendo acima de x% (indicadores do Yahoo, «Atualizar indicadores»);
- critérios da lente onde a ação foi encontrada (avisa quando deixa de os cumprir ou volta a cumprir);
- moat (avisa quando a leitura muda, ex.: de Largo para Estreito, ao reanalisar).
Os alertas verificam-se ao abrir a aplicação (Visão Geral, Carteira, Prospeção) e depois de cada atualização;
disparam quando a condição passa a verificar-se e voltam a ficar prontos quando deixa de se verificar.
"""
import json
from datetime import date, datetime, timedelta

from ..models import Instrument, Price, Setting, WatchItem, WatchList, WatchRule, WatchState, db
from . import lenses, moat

KINDS = {
    "price_below": ("Preço abaixo de", "price"),
    "price_above": ("Preço acima de", "price"),
    "change_pct": ("Variação do dia acima de", "%"),
    "from_high": ("Abaixo do máximo de 52 semanas em pelo menos", "%"),
    "pe_below": ("P/L abaixo de", ""),
    "pb_below": ("P/VP abaixo de", ""),
    "div_above": ("Dividendo acima de", "%"),
    "method": ("Critérios da lente", None),
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
    """Lê os indicadores ao Yahoo (P/L, P/VP, dividendo, máximo de 52 semanas) e avalia a ação em todas as lentes;
    guarda tudo. Reanalisa o moat se a análise tiver mais de 30 dias."""
    from . import triage
    fetch_info = fetch_info or moat.info_of
    info = fetch_info(ticker) or {}
    out = {"pe": info.get("trailingPE"), "pb": info.get("priceToBook"),
           "div": dividend_yield(info),
           "high52": info.get("fiftyTwoWeekHigh"), "low52": info.get("fiftyTwoWeekLow"),
           "price": info.get("regularMarketPrice") or info.get("currentPrice"), "currency": info.get("currency"),
           "at": (now or datetime.now()).isoformat(timespec="minutes")}
    m = triage.metrics({"ticker": ticker, "exchange_code": ""}, info)
    tab = triage.table() or {"rows": []}
    me = next((x for x in tab["rows"] if x["t"] == ticker), None)
    m["magic_q"] = me.get("mq") if me else None
    out["lenses"] = {}
    for k in lenses.REAL:
        status, rows = lenses.evaluate(k, m)
        out["lenses"][k] = [status, [[label, value, st] for label, _, value, st in rows]]
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
    lens = (snap.get("lenses") or {}).get(w.method) if w.method in lenses.REAL else None
    status = lens[0] if lens else None
    return {"price": price, "change": (price / prev - 1) if price and prev else None,
            "from_high": (price / high - 1) if price and high else None,
            "pe": snap.get("pe") if snap.get("pe") and snap["pe"] > 0 else None,
            "pb": snap.get("pb") if snap.get("pb") and snap["pb"] > 0 else None,
            "div": snap.get("div"), "method_met": None if status is None else status == "entra",
            "method_status": status, "method_details": lens[1] if lens else [], "moat": a, "snap_at": snap.get("at"),
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
METHOD_SHORT = {k: v["name"] for k, v in lenses.LENSES.items() if not v.get("meta")}


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


def _first_lower(text):
    """«Preço acima de 10 EUR» → «preço acima de 10 EUR»: só a primeira letra (as siglas e a moeda ficam como estão;
    «P/L» e «P/VP» também)."""
    if len(text) > 1 and (text[1] == "/" or text[1].isupper()):
        return text
    return text[:1].lower() + text[1:]


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
                msg = f"{w.instrument} {'volta a entrar' if met else 'deixou de entrar'} na lente " \
                      f"{METHOD_SHORT.get(w.method, w.method or '')}"
            elif r.kind == "moat":
                changed = bool(r.state) and state != r.state
                msg = f"{w.instrument}: o moat passou de {r.state} para {state}"
            else:
                changed = met and not r.met
                msg = f"{w.instrument}: {_first_lower(describe(r, currencies.get(w.instrument, '')))}"
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
    """Os parâmetros com que uma ação vinda da triagem começa: os critérios da lente e o moat, com alerta."""
    rules = []
    if w.method in lenses.REAL:
        rules.append(WatchRule(watch_id=w.id, kind="method", alert=True))
    if has_moat:
        rules.append(WatchRule(watch_id=w.id, kind="moat", alert=True))
    rules.append(WatchRule(watch_id=w.id, kind="from_high", threshold=20, alert=False))
    return rules


DEFAULT_LIST = "A minha lista"


def watch_lists():
    """As listas de acompanhamento (cria a primeira se ainda não houver nenhuma; as ações sem lista vão para ela)."""
    out = WatchList.query.order_by(WatchList.id).all()
    if not out:
        db.session.add(WatchList(title=DEFAULT_LIST))
        db.session.commit()
        out = WatchList.query.order_by(WatchList.id).all()
    if WatchItem.query.filter(WatchItem.list_id.is_(None)).count():
        WatchItem.query.filter(WatchItem.list_id.is_(None)).update({"list_id": out[0].id})
        db.session.commit()
    return out


DEFAULT_STATES = ("Por abrir", "A ler relatórios", "Em tese", "Parqueada", "Descartada")
PRIORITIES = {"alta": "Alta", "media": "Média", "baixa": "Baixa"}


def states(list_id):
    """Os estados (colunas) de uma lista, por ordem. Cria os de omissão se a lista ainda não tiver nenhum; as ações
    sem estado (ou com um estado de outra lista) vão para o primeiro."""
    out = WatchState.query.filter_by(list_id=list_id).order_by(WatchState.position, WatchState.id).all()
    if not out:
        db.session.add_all(WatchState(list_id=list_id, title=t, position=i) for i, t in enumerate(DEFAULT_STATES))
        db.session.commit()
        out = WatchState.query.filter_by(list_id=list_id).order_by(WatchState.position, WatchState.id).all()
    ids = {st.id for st in out}
    loose = [w for w in WatchItem.query.filter_by(list_id=list_id).all() if w.state_id not in ids]
    if loose:
        end = (db.session.query(db.func.max(WatchItem.position)).filter(WatchItem.state_id == out[0].id).scalar() or 0)
        for i, w in enumerate(sorted(loose, key=lambda w: w.creation or datetime.min), 1):
            w.state_id, w.position = out[0].id, end + i
        db.session.commit()
    return out


def next_position(state_id):
    return (db.session.query(db.func.max(WatchItem.position)).filter(WatchItem.state_id == state_id).scalar() or 0) + 1


def export_list(wl):
    """A lista num dicionário (para o ficheiro JSON de «Exportar»)."""
    from . import triage
    sts = states(wl.id)
    names = {st.id: st.title for st in sts}
    items = []
    for w in WatchItem.query.filter_by(list_id=wl.id).order_by(WatchItem.position).all():
        inst = db.session.get(Instrument, w.instrument)
        items.append({"ticker": w.instrument, "nome": inst.instrument_name if inst else None,
                      "moeda": inst.currency if inst else None, "lente": w.method, "estado": names.get(w.state_id),
                      "prioridade": w.priority or "media", "porque": w.reason, "notas": w.notes,
                      "preco_alvo": w.target_price,
                      "parametros": [{"kind": r.kind, "threshold": r.threshold, "alert": bool(r.alert)}
                                     for r in WatchRule.query.filter_by(watch_id=w.id).order_by(WatchRule.id)],
                      "respostas": triage.answers(w.instrument)})
    return {"formato": "portfolio-investimentos/lista", "versao": 1, "titulo": wl.title,
            "estados": [st.title for st in sts], "acoes": items}


def import_list(data, ensure_instrument):
    """Cria uma lista nova a partir de um ficheiro de «Exportar». `ensure_instrument(ticker, nome, moeda)` cria o
    ativo se faltar e devolve o ticker. Devolve a lista."""
    from . import lenses, triage
    if not isinstance(data, dict) or not isinstance(data.get("acoes"), list) or not data.get("titulo"):
        raise ValueError("O ficheiro não é uma lista exportada da aplicação.")
    title = str(data["titulo"]).strip()[:48]
    taken = {wl.title.lower() for wl in WatchList.query.all()}
    if title.lower() in taken:
        title = f"{title} (importada)"
        n = 2
        while title.lower() in taken:
            title = f"{str(data['titulo']).strip()[:44]} ({n})"
            n += 1
    wl = WatchList(title=title)
    db.session.add(wl)
    db.session.flush()
    titles = [str(t).strip()[:40] for t in data.get("estados") or [] if str(t).strip()] or list(DEFAULT_STATES)
    sts = [WatchState(list_id=wl.id, title=t, position=i) for i, t in enumerate(titles)]
    db.session.add_all(sts)
    db.session.flush()
    by_title = {st.title: st for st in sts}
    for pos, a in enumerate(data["acoes"][:500]):
        if not isinstance(a, dict) or not a.get("ticker"):
            continue
        ticker = ensure_instrument(str(a["ticker"]), a.get("nome"), a.get("moeda") or "EUR")
        if WatchItem.query.filter_by(instrument=ticker, list_id=wl.id).first():
            continue
        st = by_title.get(str(a.get("estado") or "").strip()[:40]) or sts[0]
        target = a.get("preco_alvo")
        w = WatchItem(instrument=ticker, list_id=wl.id, state_id=st.id, position=pos,
                      priority=a.get("prioridade") if a.get("prioridade") in PRIORITIES else "media",
                      method=a.get("lente") if a.get("lente") in lenses.REAL else None,
                      reason=(str(a["porque"])[:2000] if a.get("porque") else None),
                      notes=(str(a["notas"])[:5000] if a.get("notas") else None),
                      target_price=target if isinstance(target, (int, float)) else None)
        db.session.add(w)
        db.session.flush()
        for r in a.get("parametros") or []:
            if isinstance(r, dict) and r.get("kind") in WatchRule.KINDS:
                t = r.get("threshold")
                db.session.add(WatchRule(watch_id=w.id, kind=r["kind"], alert=bool(r.get("alert")),
                                         threshold=t if isinstance(t, (int, float)) else None))
        if isinstance(a.get("respostas"), dict) and a["respostas"] and not triage.answers(ticker):
            triage.save_answers(ticker, a["respostas"])
    db.session.commit()
    return wl
