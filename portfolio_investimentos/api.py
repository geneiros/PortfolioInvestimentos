"""Ações chamadas pelas páginas (POST /api/<ação>, protegido com token CSRF)."""
import inspect
import io
import json
import math
import os
import sqlite3
import tempfile
from datetime import date

from flask import Blueprint, Response, abort, current_app, jsonify, request, send_file, session

from .models import (LIQUIDITY, OTHER_CATEGORIES, Alert, Broker, DividendHistory, Event, FxRate, ImportBatch, Instrument,
                     OtherAsset, OtherAssetValue, PortfolioAlert, Price, Setting, Transaction, WatchItem, WatchList, WatchRule,
                     db)
from . import auth
from .engine.formatting import parse_number
from .engine.portfolio import ASSET_TYPES
from .services import backups, data, importer, market, sale_sim

bp = Blueprint("api", __name__, url_prefix="/api")


class ApiError(Exception):
    pass


@bp.errorhandler(ApiError)
def _api_error(exc):
    return jsonify(error=str(exc)), 400


@bp.before_request
def _csrf():
    # impede que outro site aberto no browser faça pedidos à aplicação local
    expected = session.get("csrf")
    if request.method == "POST" and (not expected or request.headers.get("X-CSRF-Token") != expected):
        abort(403)


def _args():
    out = request.form.to_dict()
    if request.is_json:
        out.update(request.get_json(silent=True) or {})
    return out


def _float(v):
    """Número de um formulário, à portuguesa («1.000,50», «1 000») ou não (ver `formatting.parse_number`)."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return 0.0
    try:
        return parse_number(v)
    except ValueError as exc:
        raise ApiError(f"Número inválido: {v}") from exc


def _get(model, ident):
    obj = db.session.get(model, int(ident)) if str(ident).isdigit() else None
    if obj is None:
        raise ApiError("Não encontrado.")
    return obj


def _ensure_instrument(ticker, name=None, currency="EUR"):
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise ApiError("Indica o ticker.")
    if not db.session.get(Instrument, ticker):
        db.session.add(Instrument(ticker=ticker, instrument_name=name or ticker,
                                  currency=(currency or "EUR").upper(), data_symbol=ticker))
    return ticker


def _backup(reason):
    """Cópia automática antes de uma operação que muda muitos dados; se falhar, a operação não avança."""
    try:
        backups.auto_backup(reason)
    except (OSError, sqlite3.Error) as exc:
        raise ApiError(f"Não foi possível criar a cópia de segurança antes de continuar: {exc}") from exc


ACTIONS = {}


def action(fn):
    ACTIONS[fn.__name__] = fn
    return fn


@bp.route("/<name>", methods=["POST"])
def call(name):
    fn = ACTIONS.get(name)
    if fn is None:
        abort(404)
    args = _args()
    params = inspect.signature(fn).parameters
    if not any(p.kind == p.VAR_KEYWORD for p in params.values()):
        args = {k: v for k, v in args.items() if k in params}
    try:
        inspect.signature(fn).bind(**args)
    except TypeError as exc:  # só a falta de argumentos; erros dentro da ação não se escondem aqui
        raise ApiError("Faltam dados no pedido.") from exc
    return jsonify(message=fn(**args))


# ------------------------------------------------------------------ navegação
@action
def set_broker(broker=""):
    if broker:
        _get(Broker, broker)
    Setting.set("broker", broker or None)


@action
def hide_banner():
    Setting.set("hide_banner", "1")


@action
def performance(period="MAX", benchmarks=None):
    from .views import perf_payload
    if isinstance(benchmarks, str):
        try:
            benchmarks = json.loads(benchmarks)
        except ValueError as exc:
            raise ApiError("Índices de comparação inválidos.") from exc
    return perf_payload(data.load_portfolio(data.selected_broker()), (period or "MAX").upper(), benchmarks)


@action
def set_profile(profile):
    from .engine.scores import PROFILES
    if profile not in PROFILES:
        raise ApiError("Perfil desconhecido.")
    from .services import insights
    broker = data.selected_broker()
    Setting.set(insights.profile_key(broker), profile)
    where = _get(Broker, broker).broker_name if broker else "todas as corretoras"
    return f"Perfil para {where}: {PROFILES[profile][0]}."


@action
def positions(period="MAX"):
    """Linhas das principais posições para o gráfico da Visão Geral ("As minhas posições")."""
    from .views import positions_payload
    return positions_payload(data.load_portfolio(data.selected_broker()), (period or "MAX").upper())


# --------------------------------------------------------------- transações
def _held(ticker, broker, on):
    """Unidades de um ativo detidas numa data (numa corretora, ou em todas se `broker` for None)."""
    q = Transaction.query.filter(Transaction.instrument == ticker, Transaction.date <= on)
    if broker is not None:
        q = q.filter(Transaction.broker == broker)
    plus, minus = ("BUY", "TRANSFER_IN", "CONVERT_IN"), ("SELL", "TRANSFER_OUT", "CONVERT_OUT")
    return sum((t.quantity or 0.0) * (1 if t.type in plus else -1) for t in q if t.type in plus + minus)


@action
def add_transaction(**kw):
    typ = kw.get("type")
    if typ not in Transaction.TYPES:
        raise ApiError("Tipo inválido.")
    instrument = None
    if typ in ASSET_TYPES:
        instrument = _ensure_instrument(kw.get("instrument"), kw.get("instrument_name"), kw.get("currency"))
    qty, amount = _float(kw.get("quantity")), _float(kw.get("amount"))
    if typ in ASSET_TYPES - {"DIVIDEND"} and qty <= 0:
        raise ApiError("A quantidade tem de ser positiva.")
    if typ in ("DEPOSIT", "WITHDRAWAL", "FEE", "INTEREST") and amount <= 0:
        raise ApiError("O montante tem de ser positivo.")
    broker = kw.get("broker") or None
    if broker:
        _get(Broker, broker)
    try:
        d = date.fromisoformat(kw.get("date") or "")
    except ValueError as exc:
        raise ApiError("Data inválida.") from exc
    if typ in ("SELL", "TRANSFER_OUT", "CONVERT_OUT"):
        held = _held(instrument, int(broker) if broker else None, d)
        if qty > held + 1e-6:
            raise ApiError(f"Só tens {held:g} unidades de {instrument} em {d:%d/%m/%Y}.")
    t = Transaction(broker=int(broker) if broker else None, instrument=instrument, date=d, type=typ,
                    quantity=qty, price=_float(kw.get("price")), amount=amount, fees=_float(kw.get("fees")),
                    tax=_float(kw.get("tax")), currency=(kw.get("currency") or "EUR").upper()[:3],
                    note=kw.get("note"))
    db.session.add(t)
    db.session.commit()
    return t.id


@action
def delete_transaction(name):
    db.session.delete(_get(Transaction, name))
    db.session.commit()


@bp.route("/export_transactions")
def export_transactions():
    rows = data.transactions()
    insts = data.instruments({r.instrument for r in rows if r.instrument})
    brokers = {b.id: b.broker_name for b in Broker.query.all()}
    return Response(importer.export_csv(rows, insts, brokers), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=transacoes.csv"})


# ---------------------------------------------------------------- importação
@action
def upload_statement(broker_key, broker_name=None):
    files = request.files.getlist("file")
    if not files:
        raise ApiError("Escolhe pelo menos um ficheiro.")
    _backup("importar")
    if Setting.get("demo") == "1":  # os dados reais substituem a demonstração
        reset_data("APAGAR")
    out = []
    for f in files:
        try:
            batch = importer.import_file(broker_key, f.filename, f.read(), broker_name or None)
        except importer.ImportError_ as exc:
            raise ApiError(f"{f.filename}: {exc}") from exc
        out.append({"file": f.filename, "imported": batch.imported, "skipped": batch.skipped,
                    "ignored": getattr(batch, "ignored", {})})
    return out


@action
def delete_import(name):
    batch = _get(ImportBatch, name)
    _backup("apagar-importacao")
    Transaction.query.filter_by(import_batch=batch.id).delete()
    db.session.delete(batch)
    db.session.commit()


# ---------------------------------------------------------- corretoras/ativos
@action
def save_broker(broker_name, color=None, name=None):
    broker_name = (broker_name or "").strip()
    if not broker_name:
        raise ApiError("Indica o nome da corretora.")
    if name:
        b = _get(Broker, name)
        if Broker.query.filter(Broker.broker_name == broker_name, Broker.id != b.id).first():
            raise ApiError("Já existe uma corretora com esse nome.")
        b.broker_name, b.color = broker_name, color or b.color
        db.session.commit()
        return b.id
    bid = importer.get_or_create_broker(broker_name, color or "#3b82f6")
    db.session.commit()
    return bid


@action
def merge_instruments(source, target):
    """Junta dois tickers do mesmo título num só (o ativo `source` desaparece)."""
    old, new = db.session.get(Instrument, source or ""), db.session.get(Instrument, target or "")
    if old is None or new is None:
        raise ApiError("Ativo não encontrado.")
    if old is new:
        raise ApiError("Escolhe dois ativos diferentes.")
    if "index" in (old.kind, new.kind):
        raise ApiError("Os índices de comparação não se juntam.")
    if old.currency != new.currency:
        raise ApiError(f"Moedas diferentes ({old.currency} e {new.currency}): não é o mesmo ativo.")
    importer.merge_instruments(old, new)
    db.session.commit()
    return f"{old.ticker} juntado em {new.ticker}."


@action
def delete_broker(name):
    b = _get(Broker, name)
    if Transaction.query.filter_by(broker=b.id).first():
        raise ApiError("Esta corretora tem transações. Apaga primeiro os extratos/transações.")
    PortfolioAlert.query.filter_by(broker=b.id).delete()
    db.session.delete(b)
    db.session.commit()
    if Setting.get("broker") == str(b.id):
        Setting.set("broker", None)
    from .services import insights
    Setting.set(insights.profile_key(str(b.id)), None)  # o id pode voltar a ser usado por outra corretora


@action
def update_instrument(ticker, instrument_name=None, sector=None, data_symbol=None, kind=None, color=None):
    inst = db.session.get(Instrument, ticker)
    if inst is None:
        raise ApiError("Ativo desconhecido.")
    old_symbol = inst.data_symbol
    for k, v in {"instrument_name": instrument_name, "sector": sector, "data_symbol": data_symbol,
                 "color": color}.items():
        if v is not None:
            setattr(inst, k, v.strip() or None)
    if data_symbol is not None and inst.data_symbol != old_symbol:
        inst.last_quote = None  # outro símbolo: a próxima atualização volta a pedir o histórico todo
    if kind in ("stock", "etf"):
        inst.kind = kind
    db.session.commit()


# ---------------------------------------------------------- radar e alertas
@action
def add_portfolio_alert(threshold, direction="down", broker=""):
    """Alerta da variação do dia da carteira (toda ou de uma corretora), em %."""
    from .services.portfolio_alerts import LEVELS
    value = _float(threshold) / 100
    if not any(abs(value - x) < 1e-9 for x in LEVELS):
        raise ApiError("Escolhe uma variação de 1, 2, 3 ou 5%.")
    if direction not in PortfolioAlert.DIRECTIONS:
        raise ApiError("Sentido inválido.")
    b = _get(Broker, broker).id if broker else None
    if PortfolioAlert.query.filter_by(broker=b, threshold=value, direction=direction).first():
        raise ApiError("Já existe um alerta igual.")
    db.session.add(PortfolioAlert(broker=b, threshold=value, direction=direction, active=True))
    db.session.commit()
    return "Alerta da carteira criado."


@action
def toggle_portfolio_alert(name, active):
    a = _get(PortfolioAlert, name)
    a.active = str(active) in ("1", "true", "True")
    db.session.commit()
    return "Alerta reativado." if a.active else "Alerta pausado."


@action
def delete_portfolio_alert(name):
    db.session.delete(_get(PortfolioAlert, name))
    db.session.commit()
    return "Alerta apagado."


# ------------------------------------------------------------------ logótipos
def _logo_instrument(ticker):
    inst = db.session.get(Instrument, ticker or "")
    if inst is None:
        raise ApiError("Ativo desconhecido.")
    return inst


@action
def set_logo_site(ticker, site):
    """Procura o logótipo pelo site indicado (ex.: apple.com) e guarda-o."""
    from .services import logos
    _logo_instrument(ticker)
    try:
        logos.set_site(ticker, site)
    except ValueError as exc:
        raise ApiError(str(exc)) from exc
    return "Logótipo guardado."


@action
def upload_logo(ticker):
    from .services import logos
    _logo_instrument(ticker)
    f = request.files.get("file")
    if f is None:
        raise ApiError("Escolhe uma imagem.")
    mime = (f.mimetype or "").lower()
    try:
        logos.set_image(ticker, mime, f.read(logos.MAX_BYTES + 1))
    except ValueError as exc:
        raise ApiError(str(exc)) from exc
    return "Logótipo guardado."


# ------------------------------------------------------------------ Raio-X dos ETF
def _etf(ticker):
    inst = db.session.get(Instrument, (ticker or "").strip())
    if inst is None or inst.kind != "etf":
        raise ApiError("Escolhe um ETF.")
    return inst


@action
def upload_etf_holdings(ticker):
    """Composição de um ETF a partir do ficheiro de posições do emitente (CSV ou XLSX)."""
    from .services import xray
    inst = _etf(ticker)
    f = request.files.get("file")
    if f is None:
        raise ApiError("Escolhe o ficheiro das posições do ETF.")
    try:
        n = xray.save(inst.ticker, xray.parse_holdings(f.read(xray.MAX_BYTES + 1), f.filename or ""), "ficheiro")
    except ValueError as exc:
        raise ApiError(f"Não foi possível ler o ficheiro: {exc}") from exc
    return f"Composição de {inst.ticker} guardada: {n} posições."


@action
def fetch_etf_holdings(ticker, url):
    """Composição de um ETF descarregada do site do emitente (o endereço fica guardado para atualizar)."""
    from .services import xray
    inst = _etf(ticker)
    try:
        n = xray.save(inst.ticker, xray.parse_holdings(xray.download(url)), "url", url.strip())
    except ValueError as exc:
        raise ApiError(str(exc)) from exc
    return f"Composição de {inst.ticker} descarregada: {n} posições."


@action
def refresh_etf_holdings():
    from .services import xray
    res = xray.refresh_urls()
    if not res:
        return "Nenhuma composição foi descarregada de um endereço."
    bad = {k: v for k, v in res.items() if isinstance(v, str)}
    ok = len(res) - len(bad)
    msg = f"{ok} {'composição atualizada' if ok == 1 else 'composições atualizadas'}."
    return msg + ("" if not bad else " Falhou: " + "; ".join(f"{k}: {v}" for k, v in bad.items()))


@action
def remove_etf_holdings(ticker):
    from .services import xray
    xray.remove(_etf(ticker).ticker)
    return "Composição apagada."


@action
def remove_logo(ticker):
    """Tira o logótipo: ficam as iniciais."""
    from .services import logos
    _logo_instrument(ticker)
    logos.remove(ticker)
    return "Logótipo retirado."


@action
def set_market_indices(tickers=""):
    """Índices da «Carteira vs mercado» (até 5), separados por vírgulas."""
    names = [t for t in str(tickers).split(",") if t]
    try:
        market.set_market_indices(names)
    except ValueError as exc:
        raise ApiError(str(exc)) from exc
    return "Índices guardados."


@action
def add_watch(instrument, target_price=None, note=None, currency="EUR", instrument_name=None, method=None,
              list_id=None):
    """Junta uma ação a uma lista de acompanhamento (a primeira, se não se indicar). Da triagem vem a lente onde a
    ação entrou, e começa com os parâmetros dessa lente e do moat."""
    from .services import lenses, moat, tracking
    ticker = _ensure_instrument(instrument, instrument_name, currency)
    lists = tracking.watch_lists()
    wl = _get(WatchList, list_id) if list_id not in (None, "") else lists[0]
    if WatchItem.query.filter_by(instrument=ticker, list_id=wl.id).first():
        raise ApiError(f"{ticker} já está em «{wl.title}».")
    w = WatchItem(instrument=ticker, target_price=_float(target_price) or None, note=note or None, list_id=wl.id)
    if method in lenses.REAL:
        w.method = method
    db.session.add(w)
    db.session.flush()
    if w.method:
        db.session.add_all(tracking.default_rules(w, has_moat=moat.get(ticker) is not None))
    if w.target_price:
        db.session.add(WatchRule(watch_id=w.id, kind="price_below", threshold=w.target_price, alert=False))
    db.session.commit()
    return f"{ticker} guardada em «{wl.title}»."


@action
def create_watch_list(title):
    """Uma lista de acompanhamento nova. Devolve {"id", "title"}."""
    from .services import tracking
    title = (title or "").strip()[:60]
    if not title:
        raise ApiError("Dá um nome à lista.")
    tracking.watch_lists()
    if WatchList.query.filter(db.func.lower(WatchList.title) == title.lower()).first():
        raise ApiError(f"Já há uma lista «{title}».")
    wl = WatchList(title=title)
    db.session.add(wl)
    db.session.commit()
    return {"id": wl.id, "title": wl.title}


@action
def rename_watch_list(name, title):
    wl = _get(WatchList, name)
    title = (title or "").strip()[:60]
    if not title:
        raise ApiError("Dá um nome à lista.")
    wl.title = title
    db.session.commit()
    return "Lista renomeada."


@action
def delete_watch_list(name):
    """Apaga uma lista e as ações dela (com os parâmetros). A última lista não se apaga."""
    wl = _get(WatchList, name)
    if WatchList.query.count() <= 1:
        raise ApiError("Tem de ficar pelo menos uma lista.")
    for w in WatchItem.query.filter_by(list_id=wl.id).all():
        WatchRule.query.filter_by(watch_id=w.id).delete()
        db.session.delete(w)
    db.session.delete(wl)
    db.session.commit()
    return f"Lista «{wl.title}» apagada."


@action
def delete_watch(name):
    w = _get(WatchItem, name)
    WatchRule.query.filter_by(watch_id=w.id).delete()
    db.session.delete(w)
    db.session.commit()


@action
def save_watch_rules(name, rules="[]", note=None):
    """Os parâmetros a acompanhar numa ação: [{"kind", "threshold", "alert"}]. Substitui os que havia (os que já
    existiam mantêm o estado, para não voltarem a disparar)."""
    from .services import tracking
    w = _get(WatchItem, name)
    try:
        data = json.loads(rules) if isinstance(rules, str) else rules
    except ValueError as exc:
        raise ApiError("Lista inválida.") from exc
    if not isinstance(data, list) or len(data) > 30:
        raise ApiError("Lista inválida.")
    old = {(r.kind, r.threshold): r for r in WatchRule.query.filter_by(watch_id=w.id).all()}
    keep = []
    for r in data:
        kind = str(r.get("kind", ""))
        if kind not in WatchRule.KINDS:
            raise ApiError("Parâmetro desconhecido.")
        needs = tracking.KINDS[kind][1] is not None
        raw = r.get("threshold")
        threshold = _float(raw) if needs and str(raw if raw is not None else "").strip() else None
        if needs and threshold is None:
            raise ApiError(f"Indica o valor de «{tracking.KINDS[kind][0]}».")
        alert = str(r.get("alert")).lower() in ("1", "true", "on")
        rule = old.pop((kind, threshold), None) or WatchRule(watch_id=w.id, kind=kind, threshold=threshold)
        rule.alert = alert
        keep.append(rule)
    for r in old.values():
        db.session.delete(r)
    db.session.add_all(keep)
    if note is not None:
        w.note = str(note).strip()[:255] or None
    db.session.commit()
    tracking.check()
    return "Parâmetros guardados."


@action
def refresh_tracking(ticker):
    """Atualiza os indicadores do Yahoo de uma ação em acompanhamento (P/L, P/VP, dividendo, critérios das lentes)."""
    from .services import tracking, yahoo
    ticker = (ticker or "").strip().upper()
    if not WatchItem.query.filter_by(instrument=ticker).first():
        raise ApiError("Essa ação não está em Acompanhamento.")
    try:
        tracking.refresh(ticker)
    except yahoo.YahooError as exc:
        raise ApiError(f"Não foi possível ler os dados de {ticker} no Yahoo: {exc}") from exc
    fired = tracking.check()
    return f"{ticker} atualizada." + (f" {len(fired)} alerta(s) disparado(s)." if fired else "")


@action
def save_ters(**values):
    """Custo anual (TER) dos ETF, em % (campos ter_<ticker>); vazio apaga o TER."""
    changed = 0
    for key, raw in values.items():
        if not key.startswith("ter_"):
            continue
        inst = db.session.get(Instrument, key[4:])
        if inst is None:
            raise ApiError(f"Ativo desconhecido: {key[4:]}")
        raw = str(raw or "").strip().replace("%", "")
        if not raw:
            inst.ter = None
        else:
            pct = _float(raw)
            if not math.isfinite(pct) or not 0 <= pct <= 3:
                raise ApiError(f"{inst.ticker}: o TER tem de estar entre 0% e 3% ao ano.")
            inst.ter = round(pct / 100, 6)
        changed += 1
    if not changed:
        raise ApiError("Sem valores para guardar.")
    db.session.commit()
    return "Custos dos ETF guardados."


@action
def set_aaa_yield(percent):
    """Rendimento das obrigações AAA (Y) da fórmula de crescimento de Graham, em %."""
    value = _float(percent)
    if not math.isfinite(value) or not 0.5 <= value <= 15:
        raise ApiError("O rendimento das obrigações AAA tem de estar entre 0,5% e 15%.")
    Setting.set("aaa_yield", value)
    return f"Obrigações AAA a {value:g}%."


@action
def save_fundamentals(ticker, eps="", bvps="", fcf="", growth="", owner="", nopat="", net_cash=""):
    """Correções manuais aos dados fundamentais de uma ação (vazio: volta ao valor do Yahoo). Crescimento em %."""
    from .models import Fundamental
    inst = db.session.get(Instrument, (ticker or "").strip())
    if inst is None:
        raise ApiError("Ativo desconhecido.")
    row = db.session.get(Fundamental, inst.ticker) or Fundamental(ticker=inst.ticker)
    for field, raw in (("eps", eps), ("bvps", bvps), ("fcf", fcf), ("growth", growth), ("owner", owner),
                       ("nopat", nopat), ("net_cash", net_cash)):
        raw = str(raw or "").strip().replace("%", "").replace(" ", "")
        if not raw:
            setattr(row, "manual_" + field, None)
            continue
        value = _float(raw)
        if not math.isfinite(value):
            raise ApiError(f"Número inválido: {raw}")
        if field == "growth":
            if not -10 <= value <= 25:
                raise ApiError("O crescimento tem de estar entre −10% e 25% ao ano.")
            value /= 100
        setattr(row, "manual_" + field, value)
    db.session.add(row)
    db.session.commit()
    return f"Dados de {inst.ticker} guardados."


# --------------------------------------------------------- património (outros ativos)
def _flag(v):
    return str(v).lower() in ("1", "true", "on", "sim")


@action
def save_other_asset(label, category, value, fire="", note="", name="", liquidity="", home="", linked=""):
    from .services import networth
    label = (label or "").strip()
    if not label:
        raise ApiError("Indica o nome.")
    if category not in OTHER_CATEGORIES:
        raise ApiError("Categoria desconhecida.")
    amount = _float(value)
    if not math.isfinite(amount) or amount < 0:
        raise ApiError("O valor tem de ser um número positivo (as dívidas também: o sinal vem da categoria).")
    liquidity = (liquidity or "").strip()
    if liquidity and liquidity not in LIQUIDITY:
        raise ApiError("Nível de liquidez desconhecido.")
    debt = OTHER_CATEGORIES[category][4]
    asset = _get(OtherAsset, name) if name else OtherAsset()
    target = None
    if linked not in (None, ""):
        if not debt:
            raise ApiError("Só um crédito se pode ligar a um imóvel.")
        target = _get(OtherAsset, linked)
        if target.category != "imovel" or target.id == asset.id:
            raise ApiError("O crédito só se pode ligar a um imóvel.")
    asset.label, asset.category, asset.value = label[:120], category, round(amount, 2)
    asset.fire = _flag(fire)
    asset.note = (note or "").strip()[:255] or None
    asset.liquidity = None if debt else (liquidity or None)
    asset.home = category == "imovel" and _flag(home)
    asset.linked = target.id if target else None
    asset.updated = date.today()
    db.session.add(asset)
    db.session.flush()
    networth.record(asset)
    db.session.commit()
    return "Guardado."


@action
def save_other_asset_values(**values):
    """Formulário mensal: o valor atual de todos os ativos e dívidas de uma vez (campos v_<id>)."""
    from .services import networth
    parsed = {}
    for key, raw in values.items():
        raw = str(raw or "").replace(" ", "").replace("\u00a0", "").replace("\u202f", "").replace("€", "")
        if not key.startswith("v_") or not key[2:].isdigit() or not raw:  # vazio: fica como está
            continue
        amount = _float(raw)
        if not math.isfinite(amount) or amount < 0:
            asset = db.session.get(OtherAsset, int(key[2:]))
            raise ApiError(f"{asset.label if asset else 'Valor'}: tem de ser um número positivo.")
        parsed[int(key[2:])] = round(amount, 2)
    if not parsed:
        raise ApiError("Sem valores para guardar.")
    today = date.today()
    for ident, amount in parsed.items():
        asset = _get(OtherAsset, ident)
        asset.value, asset.updated = amount, today
        networth.record(asset)
    db.session.commit()
    return f"{len(parsed)} valores atualizados."


@action
def set_other_asset_fire(name, fire):
    asset = _get(OtherAsset, name)
    asset.fire = _flag(fire)
    db.session.commit()


@action
def delete_other_asset(name):
    asset = _get(OtherAsset, name)
    OtherAsset.query.filter_by(linked=asset.id).update({"linked": None})  # créditos deste imóvel ficam soltos
    OtherAssetValue.query.filter_by(asset=asset.id).delete()
    db.session.delete(asset)
    db.session.commit()


@action
def set_sale_discount(percent):
    value = _float(percent)
    if not math.isfinite(value) or not 0 <= value <= 20:
        raise ApiError("O desconto para os custos de venda tem de estar entre 0% e 20%.")
    Setting.set("networth_sale_discount", value)
    return f"Imóveis com {value:g}% de desconto para custos de venda." if value else "Imóveis pelo valor de mercado."


# --------------------------------------------------------- dados e mercado
@action
def refresh_market(only_open=""):
    if not market.yfinance_available():
        raise ApiError("Instala o pacote yfinance para obter cotações (pip install yfinance).")
    market.refresh_in_background(current_app._get_current_object(),
                                 only_open=str(only_open).lower() in ("1", "true", "on", "sim"))
    return "Atualização de cotações em curso. Pode demorar alguns minutos; o aviso na Visão Geral desaparece quando terminar."


def quick_quotes_now(force=False):
    """Atualização rápida dos preços das posições abertas (de todas as corretoras). Para a página e para a tarefa
    em segundo plano do computador."""
    from .services.context import _regions
    p_all = data.load_portfolio(None)
    tickers = [pos.asset.ticker for pos in p_all.open_positions if not pos.asset.ticker.startswith("DEMO-")]
    insts = Instrument.query.filter(Instrument.ticker.in_(tickers or [""])).all()
    if not insts:
        return {"updated": 0, "fx": 0, "at": Setting.get("quick_quotes_at"), "skipped": "empty"}
    return market.quick_quotes(insts, regions=_regions(p_all), force=force)


def _sim_args(asset, qty, price, fees):
    """Argumentos do simulador de venda: quantidade vazia ou «tudo» = toda a posição; preço vazio = o último."""
    q = None if str(qty or "").strip().lower() in ("", "tudo", "all") else _float(qty)
    px = None if not str(price or "").strip() else _float(price)
    return asset, q, px, _float(fees)


def simulate_sale_result(asset, qty=None, price=None, fees=None):
    try:
        return sale_sim.simulate(*_sim_args(asset, qty, price, fees))
    except sale_sim.SimulationError as exc:
        raise ApiError(str(exc)) from exc


@action
def simulate_sale(asset="", qty="", price="", fees=""):
    """Simulador de venda (Fiscal): lotes FIFO, mais-valia, imposto do ano antes e depois e perdas por realizar."""
    return simulate_sale_result(asset, qty, price, fees)


@action
def harvest_list(asset="", qty="", price="", fees=""):
    """Posições com menos-valia e quanto cada uma baixaria o imposto, a partir do saldo do ano depois da venda
    simulada no formulário de cima (sem ela, a partir do saldo do ano)."""
    if not asset:
        balance = sale_sim.year_balance()
        return {"balance": balance, "rows": sale_sim.harvest(balance)}
    sale = simulate_sale_result(asset, qty, price, fees)
    return {"balance": sale["balance_after"], "rows": sale_sim.harvest(sale["balance_after"], skip=asset)}


@action
def simulate_harvest(keys="", fee="", fx_pct="", rebuy="1", asset="", qty="", price="", fees=""):
    """Vender (e voltar a comprar) as posições com menos-valia escolhidas: poupança no imposto do ano, custos e
    imposto adiado. O saldo de partida inclui a venda simulada no formulário de cima, se houver."""
    base = sale_sim.year_balance()
    if asset:
        base = simulate_sale_result(asset, qty, price, fees)["balance_after"]
    ks = [k for k in (keys.split(",") if isinstance(keys, str) else keys) if k]
    try:
        return sale_sim.harvest_plan(ks, base, _float(fee), _float(fx_pct),
                                     str(rebuy).lower() in ("1", "true", "on", "sim"))
    except sale_sim.SimulationError as exc:
        raise ApiError(str(exc)) from exc


@action
def dismiss_update(tag=""):
    """Fecha o aviso de versão nova até haver uma versão a seguir a esta."""
    Setting.set("update_dismissed", (tag or "").strip()[:32] or None)


@action
def set_update_notice(enabled):
    on = str(enabled).lower() in ("1", "true", "on", "sim")
    Setting.set("update_notice", None if on else "0")
    return "Vais ser avisado quando houver uma versão nova." if on else "Aviso de versão nova desligado."


@action
def check_update():
    """«Ver agora» (Definições): pergunta já ao GitHub pela última release."""
    from .services import updates
    state = updates.check(force=True)
    found = updates.available()
    if found:
        return f"Há uma versão nova: {found['tag']}."
    if not state.get("tag"):
        return "Não foi possível saber a última versão (sem ligação ao GitHub?)."
    return f"Tens a versão mais recente ({state['tag']})."


@action
def quick_quotes():
    """Chamada pela página de 5 em 5 minutos (com a opção ligada): atualiza os preços de hoje das posições abertas,
    se as bolsas estiverem abertas, e devolve os valores do cartão Carteira e da variação do dia."""
    if not market.quick_quotes_enabled():
        return {"enabled": False}
    res = quick_quotes_now()
    from flask import g
    g.pop("pm_portfolios", None)  # a carteira deste pedido foi calculada antes das cotações novas
    p = data.load_portfolio(data.selected_broker())
    eur, pct = p.day_change()
    at = res.get("at")
    return {"enabled": True, **res, "at_label": at[11:16] if at else None,
            "holdings": p.holdings_value, "total_return": p.total_return, "total_return_pct": p.total_return_pct,
            "day": eur, "day_pct": pct, "as_of": p.as_of.strftime("%d/%m") if p.as_of else None}


@action
def set_quick_quotes(enabled):
    on = str(enabled).lower() in ("1", "true", "on", "sim")
    Setting.set("quick_quotes", "1" if on else None)
    return ("Os preços das posições abertas atualizam-se de 5 em 5 minutos, com o mercado aberto."
            if on else "Atualização automática dos preços desligada.")


@action
def refresh_step(only_open="", restart=""):
    """Faz o bocado seguinte da atualização de cotações (a página chama até terminar; sem threads no servidor)."""
    if not market.yfinance_available():
        raise ApiError("Instala o pacote yfinance para obter cotações (pip install yfinance).")
    res = market.refresh_step(only_open=str(only_open).lower() in ("1", "true", "on", "sim"),
                              restart=str(restart).lower() in ("1", "true"))
    if res.get("finished"):
        indices = {t for (t,) in db.session.query(Instrument.ticker).filter_by(kind="index")}
        res["missing"] = [t for t in res.get("missing", []) if t not in indices]
    return res


def _news_tickers():
    """Os ativos das posições abertas da carteira selecionada e os do Radar, sem repetir (sem os da demonstração)."""
    from .views import radar_instruments
    held = [pos.asset.ticker for pos in data.load_portfolio(data.selected_broker()).open_positions]
    return [t for t in dict.fromkeys(held + [i.ticker for i in radar_instruments()]) if not t.startswith("DEMO-")]


@action
def refresh_news():
    """Pede outra vez todas as notícias (sem esperar pela validade) num só pedido."""
    from .services import news
    errors = news.refresh(_news_tickers(), force=True)
    return "Notícias atualizadas." if not errors else "Notícias atualizadas, com falhas: " + "; ".join(
        f"{k}: {v}" for k, v in list(errors.items())[:3])


@action
def news_plan():
    """Os passos de «Atualizar todas as fontes»: o mercado e cada ativo da carteira selecionada."""
    return {"steps": ["", *_news_tickers()]}


@action
def refresh_news_step(ticker=""):
    """Um passo de «Atualizar todas as fontes»: as notícias do mercado (ticker vazio) ou de um ativo, de todas as
    fontes ligadas, sem esperar pela validade. A página mostra o progresso entre passos."""
    from .services import news
    if ticker and ticker not in _news_tickers():
        raise ApiError("Ativo fora da carteira selecionada.")
    errors = news.refresh([ticker] if ticker else [], force=True, market=not ticker)
    return {"errors": [f"{k}: {v}" for k, v in errors.items()]}


@action
def set_finnhub_key(key=""):
    """Chave da API do Finnhub (vazia apaga)."""
    from .services import news
    key = (key or "").strip()
    if key and not news.KEY_RE.match(key):
        raise ApiError("A chave do Finnhub não parece válida (só letras, números, - e _).")
    Setting.set("finnhub_key", key or None)
    Setting.set("news_fetched", None)  # com outra chave, pede-se tudo outra vez
    Setting.set("finnhub_symbols", None)
    return "Chave do Finnhub guardada." if key else "Chave do Finnhub apagada."


@action
def set_marketaux_key(key=""):
    """Chave da API do Marketaux (vazia apaga)."""
    from .services import news
    key = (key or "").strip()
    if key and not news.KEY_RE.match(key):
        raise ApiError("A chave do Marketaux não parece válida (só letras, números, - e _).")
    Setting.set("marketaux_key", key or None)
    return "Chave do Marketaux guardada." if key else "Chave do Marketaux apagada."


@action
def set_news_sources(**values):
    """Fontes de notícias ligadas (campos source_<fonte>=1)."""
    from .services import news
    chosen = [p for p in news.PROVIDERS if str(values.get(f"source_{p}", "")) in ("1", "on", "true")]
    # sem nenhuma fonte fica "" (diferente de «sem valor», que é todas): o menu Notícias deixa de aparecer
    Setting.set("news_sources", ",".join(chosen))
    Setting.set("news_fetched", None)
    if not chosen:
        return "Notícias desligadas: o menu Notícias fica escondido até ligares uma fonte."
    return "Fontes de notícias guardadas."


@action
def set_offline(enabled):
    on = str(enabled).lower() in ("1", "true", "on", "sim")
    Setting.set("offline_enabled", "1" if on else None)
    return "Disponível offline: a cópia das páginas é guardada neste dispositivo." if on else \
        "Modo offline desligado: a cópia guardada neste dispositivo foi apagada."


@action
def set_stale_days(days):
    """Dias sem atualizar as cotações a partir dos quais aparece o aviso no topo (0 = nunca)."""
    value = _float(days)
    if not math.isfinite(value) or value != int(value) or not 0 <= value <= 90:
        raise ApiError("Indica um número inteiro de dias entre 0 (nunca avisar) e 90.")
    Setting.set("stale_days", int(value))
    return "Sem aviso de cotações antigas." if not value else f"Aviso quando as cotações tiverem mais de {int(value)} dias."


# ------------------------------------------------------------------ ordem dos widgets
@action
def save_widget_order(page, grid, order):
    """Ordem dos cartões de uma grelha de uma página (mudada com um clique longo e arrastar);
    `order`: nomes separados por vírgulas."""
    from .services import widgets
    names = order if isinstance(order, list) else [x for x in str(order).split(",") if x]
    try:
        widgets.save(page, grid, names)
    except ValueError as exc:
        raise ApiError(str(exc)) from exc
    return "Ordem guardada."


@action
def reset_widget_order(page=""):
    from .services import widgets
    if page and not widgets.valid_page(page):
        raise ApiError("Página inválida.")
    widgets.reset(page or None)
    return "Ordem dos cartões reposta."


@action
def delete_backup(name):
    path = current_app.config["DB_PATH"]
    try:
        backups.delete(path, name)
    except FileNotFoundError as exc:
        raise ApiError("Cópia não encontrada.") from exc
    return "Cópia eliminada."


@action
def set_risk_free(rate):
    value = _float(rate)
    if not 0 <= value <= 20:
        raise ApiError("Indica uma taxa entre 0 e 20%.")
    Setting.set("risk_free", value)
    return f"Taxa sem risco: {value:g}%."


PLAN_KEYS = ("fire_expenses", "fire_monthly", "fire_swr", "fire_inflation", "fire_income", "fire_items")


def _plan_income(value):
    v = _float(value)
    if not 1000 <= v <= 10_000_000:
        raise ApiError("Indica um rendimento por ano entre €1 000 e €10 000 000.")
    return v


@action
def set_plan_goal(income):
    """Planeamento, «Para começar»: o rendimento por ano que queres receber (abre o plano completo)."""
    Setting.set("fire_expenses", _plan_income(income))
    Setting.set("demo_fire_expenses", None)  # passa a ser teu (não se apaga com a demonstração)
    return "Objetivo escolhido."


@action
def save_plan(income, monthly, swr, inflation):
    """Guarda as hipóteses do Planeamento (as que estavam «por gravar»)."""
    from .services.planning import level_key
    level = level_key(swr)
    if level is None:
        raise ApiError("Escolhe o levantamento: 3%, 3,5%, 4% ou Dividendos.")
    m, infl = _float(monthly), _float(inflation)
    if not 0 <= m <= 1_000_000:
        raise ApiError("O depósito por mês tem de estar entre €0 e €1 000 000.")
    if not -5 <= infl <= 20:
        raise ApiError("A inflação tem de estar entre -5% e 20%.")
    for key, value in (("fire_expenses", _plan_income(income)), ("fire_monthly", m), ("fire_swr", level),
                       ("fire_inflation", infl)):
        Setting.set(key, value)
    Setting.set("demo_fire_expenses", None)
    return "Objetivo guardado."


@action
def reset_plan():
    """Planeamento: apaga o objetivo e as hipóteses (volta ao ecrã «Para começar»)."""
    for key in PLAN_KEYS + ("demo_fire_expenses",):
        Setting.set(key, None)
    return "Planeamento recomeçado."


def _json_rows(rows):
    try:
        data = json.loads(rows) if isinstance(rows, str) else rows
    except ValueError as exc:
        raise ApiError("Lista inválida.") from exc
    if not isinstance(data, list) or len(data) > 30:
        raise ApiError("Lista inválida.")
    return data


@action
def save_plan_income(rows):
    """Rendimentos fora da carteira (pensão, rendas): [{"name", "monthly", "year"}]."""
    out = []
    for r in _json_rows(rows):
        name = str(r.get("name", "")).strip()[:60]
        monthly, year = _float(r.get("monthly")), _float(r.get("year"))
        if not name and not monthly:
            continue
        if not name or monthly <= 0:
            raise ApiError("Indica o nome e o valor por mês de cada rendimento.")
        if not 1990 <= year <= date.today().year + 70:
            raise ApiError(f"Indica o ano em que começa «{name}».")
        out.append({"name": name, "monthly": monthly, "year": int(year)})
    Setting.set("fire_income", json.dumps(out, ensure_ascii=False) if out else None)
    return "Rendimentos guardados."


@action
def save_plan_items(rows):
    """Despesas do mês: [{"name", "amount"}]. O rendimento por ano passa a ser a soma × 12."""
    out = []
    for r in _json_rows(rows):
        name, amount = str(r.get("name", "")).strip()[:60], _float(r.get("amount"))
        if not name and not amount:
            continue
        if not name or amount <= 0:
            raise ApiError("Indica o nome e o valor de cada despesa.")
        out.append({"name": name, "amount": amount})
    if not out:
        Setting.set("fire_items", None)
        return "Voltaram as despesas de partida."
    Setting.set("fire_items", json.dumps(out, ensure_ascii=False))
    Setting.set("fire_expenses", _plan_income(sum(r["amount"] for r in out) * 12))
    Setting.set("demo_fire_expenses", None)
    return "Despesas guardadas."


@action
def refresh_status():
    running, error, missing = market.refresh_state()
    indices = {t for (t,) in db.session.query(Instrument.ticker).filter_by(kind="index")}
    return {"running": running, "error": error, "missing": [t for t in missing if t not in indices], "last_refresh": Setting.get("last_refresh"),
            "updated": int(Setting.get("refresh_updated") or 0), "progress": market.refresh_progress(),
            "job": market.current_job()}


@action
def load_demo():
    from .services.demo import create_demo
    _backup("demonstracao")
    return create_demo()


@action
def reset_data(confirm=""):
    if confirm != "APAGAR":
        raise ApiError('Escreve APAGAR para confirmar.')
    _backup("apagar-tudo")
    from .models import EtfHolding, Fundamental, Logo, NewsItem
    for row in Setting.query.filter(Setting.key.like("xray:%")).all():
        db.session.delete(row)
    for model in (EtfHolding, NewsItem, Logo, Transaction, ImportBatch, Alert, PortfolioAlert, WatchRule, WatchItem, Event, DividendHistory, Price, FxRate,
                  OtherAssetValue, OtherAsset, Fundamental):
        model.query.delete()
    Broker.query.delete()
    Instrument.query.filter(Instrument.kind != "index").delete()
    if Setting.get("demo_fire_expenses") == "1":  # despesas de exemplo da demonstração (não as tuas)
        Setting.set("fire_expenses", None)
        Setting.set("demo_fire_expenses", None)
    # também o estado da atualização de cotações (senão o aviso "ainda não atualizaste" deixava de aparecer)
    for key in ("broker", "demo", "last_refresh", "refresh_missing", "refresh_updated", "refresh_report",
                "refresh_status", "hide_banner"):
        Setting.set(key, None)
    _reset_data_settings()
    db.session.commit()
    return "Todos os dados foram apagados."


def _reset_data_settings():
    """Definições que dependem dos dados apagados: senão passavam para os dados novos.

    - o perfil de investidor de cada corretora (os ids das corretoras voltam a ser usados pelas novas); o de
      «todas as corretoras» é uma preferência e fica.
    A ordem dos cartões e os índices da «Carteira vs mercado» também são preferências e ficam.
    """
    for row in Setting.query.filter(Setting.key.like("investor_profile:%")).all():
        if row.key != "investor_profile:all":
            Setting.set(row.key, None)


@action
def create_backup():
    saved = backups.make_backup(current_app.config["DB_PATH"], "manual")
    return f"Cópia guardada: {saved.name}"


@action
def restore_backup(name):
    from . import migrations
    path = current_app.config["DB_PATH"]
    try:
        backups.backup_path(path, name)
    except FileNotFoundError as exc:
        raise ApiError("Cópia não encontrada.") from exc
    db.session.remove()
    db.engine.dispose()
    try:
        backups.restore(path, name)
    except ValueError as exc:
        raise ApiError(f"Não foi possível restaurar: {exc}.") from exc
    except sqlite3.Error as exc:
        raise ApiError(f"Não foi possível restaurar: {exc}") from exc
    migrations.upgrade(current_app)  # a cópia pode ser de uma versão anterior da aplicação
    data.invalidate()
    return "Cópia restaurada."


@bp.route("/backup")
def backup():
    """Descarrega uma cópia consistente da base de dados (API de backup do SQLite, mesmo com escritas em curso)."""
    db.session.commit()
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src, dst = sqlite3.connect(current_app.config["DB_PATH"]), sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        with open(tmp, "rb") as f:
            blob = io.BytesIO(f.read())
    finally:
        os.remove(tmp)
    return send_file(blob, as_attachment=True, mimetype="application/octet-stream",
                     download_name=f"portfolio-{date.today().isoformat()}.db")


# ------------------------------------------------------------------ segurança
@action
def set_password(new_password, confirm, current_password=""):
    if auth.env_password():
        raise ApiError("A palavra-passe está definida na variável PORTFOLIO_PASSWORD: muda-a no servidor.")
    if auth.password_enabled():
        problem = auth.verify_current_password(current_password)
        if problem:
            raise ApiError(problem)
    if len(new_password) < auth.MIN_LENGTH:
        raise ApiError(f"A palavra-passe tem de ter pelo menos {auth.MIN_LENGTH} caracteres.")
    if new_password != confirm:
        raise ApiError("As palavras-passe não coincidem.")
    auth.set_password(new_password)
    return "Palavra-passe guardada."


@action
def remove_password(current_password=""):
    if auth.env_password():
        raise ApiError("A palavra-passe está definida na variável PORTFOLIO_PASSWORD: remove-a no servidor.")
    problem = auth.verify_current_password(current_password)
    if problem:
        raise ApiError(problem)
    if not auth.is_local_request():
        raise ApiError("Só podes remover a palavra-passe no computador onde a aplicação corre.")
    auth.clear_password()
    return "Palavra-passe removida."


@action
def logout():
    session.clear()


# ---------------------------------------------------------------- Triagem (Prospeção → Ações)
@action
def triage_refresh():
    """Um passo da recolha do universo da triagem (as pesquisas de cada lente ao Yahoo). A página chama-o até
    `done`."""
    from .services import triage, yahoo
    try:
        return triage.refresh_step()
    except yahoo.YahooError as exc:
        raise ApiError(f"Não foi possível procurar no Yahoo: {exc}") from exc


@action
def triage_enrich():
    """Um passo do completar dos dados das ações da triagem (ROE, margens, dívida...). A página chama-o até `done`
    (e espera `wait` segundos quando o Yahoo limita os pedidos)."""
    from .services import triage
    return triage.enrich_step()


@action
def save_triage_notes(ticker, answers="{}"):
    """As respostas às perguntas «Se entrar na lista» de uma ação."""
    from .services import triage
    ticker = (ticker or "").strip().upper()
    try:
        data = json.loads(answers) if isinstance(answers, str) else answers
    except ValueError as exc:
        raise ApiError("Respostas inválidas.") from exc
    if not ticker or not isinstance(data, dict):
        raise ApiError("Respostas inválidas.")
    triage.save_answers(ticker, data)
    return "Respostas guardadas."


@action
def analyse_moat(ticker):
    """2.º passo: a prova do moat nos números de uma empresa e a fonte provável."""
    from .services import moat, yahoo
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise ApiError("Indica o ticker.")
    try:
        out = moat.analyse(ticker)
    except yahoo.YahooError as exc:
        raise ApiError(f"Não foi possível ler os dados de {ticker} no Yahoo: {exc}") from exc
    return f"{ticker}: moat {out['verdict'].lower()}" + (f" ({out['score']}/100)." if out["score"] is not None else ".")


@action
def save_moat_checklist(ticker, pillars="[]", tests="[]", note=""):
    """O que confirmaste sobre o moat de uma empresa (os 5 pilares e os 3 testes de Buffett)."""
    from .services import moat
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise ApiError("Indica o ticker.")
    try:
        p = json.loads(pillars) if isinstance(pillars, str) else pillars
        t = json.loads(tests) if isinstance(tests, str) else tests
    except ValueError as exc:
        raise ApiError("Lista inválida.") from exc
    moat.save_checklist(ticker, p or [], t or [], note)
    return "Checklist guardado."
