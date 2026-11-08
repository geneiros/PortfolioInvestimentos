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
                     OtherAsset, OtherAssetValue, PortfolioAlert, Price, Setting, Transaction, WatchItem, db)
from . import auth
from .engine.formatting import parse_number
from .engine.portfolio import ASSET_TYPES
from .services import backups, cerne, data, importer, market

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
def add_alert(instrument, kind, threshold):
    if kind not in Alert.KINDS:
        raise ApiError("Condição inválida.")
    if not db.session.get(Instrument, instrument):
        raise ApiError("Ativo desconhecido.")
    a = Alert(instrument=instrument, kind=kind, threshold=_float(threshold), active=True)
    db.session.add(a)
    db.session.commit()
    return a.id


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
def toggle_alert(name, active):
    a = _get(Alert, name)
    a.active, a.triggered_on = str(active) in ("1", "true", "True"), None
    db.session.commit()


@action
def delete_alert(name):
    db.session.delete(_get(Alert, name))
    db.session.commit()


@action
def add_watch(instrument, target_price=None, note=None, currency="EUR", instrument_name=None):
    ticker = _ensure_instrument(instrument, instrument_name, currency)
    w = WatchItem(instrument=ticker, target_price=_float(target_price) or None, note=note)
    db.session.add(w)
    db.session.commit()
    return w.id


@action
def delete_watch(name):
    db.session.delete(_get(WatchItem, name))
    db.session.commit()


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
    if not chosen:
        raise ApiError("Escolhe pelo menos uma fonte de notícias.")
    Setting.set("news_sources", ",".join(chosen))
    Setting.set("news_fetched", None)
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


# ------------------------------------------------------------------ carteira cerne
@action
def save_core_plan(**values):
    """Ativo de cada papel da carteira cerne (ticker_<papel>; vazio = procurar pelo código). As misturas da
    tabela não mudam aqui; o intervalo de queda entre escalões muda-se em Definições."""
    plan = cerne.plan()
    p = data.load_portfolio(None)
    growth_before = cerne.resolve(p, plan).get("growth")
    for a in plan["assets"]:
        ticker = (values.get(f"ticker_{a['role']}") or "").strip()
        if ticker and db.session.get(Instrument, ticker) is None:
            raise ApiError(f"Ativo não encontrado: {ticker}")
        if ticker:
            a["ticker"] = ticker
        else:
            a.pop("ticker", None)
    cerne.save(plan)
    # o escalão atingido (só sobe) era do ETF de crescimento anterior: com outro ETF, recomeça da base
    if cerne.resolve(p, plan).get("growth") != growth_before:
        cerne.reset()
        return "Carteira cerne guardada. O ETF de crescimento mudou: a carteira cerne voltou ao alvo base."
    return "Carteira cerne guardada."


@action
def set_core_interval(percent):
    """Queda do ETF de crescimento que faz passar ao escalão seguinte da carteira cerne (as misturas não mudam)."""
    value = _float(percent)
    n = len(cerne.plan()["steps"])
    if not math.isfinite(value) or not 1 <= value <= 30 or n * value >= 100:
        raise ApiError(f"Indica um intervalo entre 1 e {min(30, math.ceil(100 / n) - 1)}%.")
    plan = cerne.plan()
    plan["interval"] = value / 100
    cerne.save(plan)
    drops = " / ".join(f"−{k * value:g}%".replace(".", ",") for k in range(1, n + 1))
    return f"Escalões da carteira cerne: {drops}."


@action
def set_core_enabled(enabled):
    plan = cerne.plan()
    plan["enabled"] = str(enabled) not in ("0", "", "false")
    cerne.save(plan)
    return "Carteira cerne ligada." if plan["enabled"] else "Carteira cerne desligada."


@action
def core_reset():
    cerne.reset()
    return "De volta ao alvo base."


@action
def core_ack(step):
    cerne.acknowledge(int(_float(step)))
    return "Aviso fechado."


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


@action
def save_fire(expenses, swr, tax, monthly, age="", until="90", pension="0", pension_age="67", stop_age=""):
    values = {"fire_expenses": _float(expenses), "fire_swr": _float(swr), "fire_tax": _float(tax),
              "fire_monthly": _float(monthly)}
    age_v = _float(age) if str(age).strip() else None
    if age_v is not None and not 15 <= age_v <= 100:
        raise ApiError("Indica uma idade entre 15 e 100 anos.")
    until_v, pension_v, pension_age_v = _float(until), _float(pension), _float(pension_age)
    if age_v is not None and not age_v < until_v <= 120:
        raise ApiError("A idade até quando o dinheiro tem de durar tem de ser maior do que a tua idade.")
    if pension_v < 0 or not 40 <= pension_age_v <= 80:
        raise ApiError("Indica uma pensão positiva e uma idade de reforma entre 40 e 80 anos.")
    stop_v = _float(stop_age) if str(stop_age).strip() else None
    if stop_v is not None and (age_v is None or not age_v < stop_v <= until_v):
        raise ApiError("A idade em que deixas de investir tem de estar entre a tua idade e a idade até quando dura.")
    if values["fire_expenses"] <= 0:
        raise ApiError("Indica as despesas anuais.")
    if not 0.5 <= values["fire_swr"] <= 10:
        raise ApiError("A taxa de levantamento deve estar entre 0,5% e 10%.")
    if not 0 <= values["fire_tax"] < 60:
        raise ApiError("O imposto deve estar entre 0% e 60%.")
    if values["fire_monthly"] < 0:
        raise ApiError("O investimento mensal não pode ser negativo.")
    values.update(fire_age=age_v, fire_until=until_v, fire_pension=pension_v, fire_pension_age=pension_age_v,
                  fire_stop_age=stop_v)
    for key, value in values.items():
        Setting.set(key, value)
    Setting.set("demo_fire_expenses", None)  # as despesas passam a ser tuas (não se apagam com a demonstração)
    return "Plano guardado."


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
    from .models import Fundamental, Logo, NewsItem
    for model in (NewsItem, Logo, Transaction, ImportBatch, Alert, PortfolioAlert, WatchItem, Event, DividendHistory, Price, FxRate,
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

    - carteira cerne: o escalão atingido (só sobe) e o aviso visto, e os ativos escolhidos para cada papel (podem
      já não existir); o intervalo dos escalões e «mostrar o cartão» são preferências e ficam;
    - o perfil de investidor de cada corretora (os ids das corretoras voltam a ser usados pelas novas); o de
      «todas as corretoras» é uma preferência e fica.
    A ordem dos cartões e os índices da «Carteira vs mercado» também são preferências e ficam.
    """
    from .services import cerne
    cerne.reset()
    plan = cerne.plan()
    for a in plan["assets"]:
        a.pop("ticker", None)
    cerne.save(plan)
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
