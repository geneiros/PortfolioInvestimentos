"""Ações chamadas pelas páginas (POST /api/<ação>, protegido com token CSRF)."""
import inspect
import json
from datetime import date

from flask import Blueprint, Response, abort, current_app, jsonify, request, send_file, session

from .models import (Alert, Broker, Event, FxRate, ImportBatch, Instrument, News, Price, Setting, Transaction,
                     WatchItem, db)
from . import auth
from .services import data, importer, market

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
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else 0.0
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
        return jsonify(message=fn(**args))
    except TypeError as exc:
        raise ApiError("Faltam dados no pedido.") from exc


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
        benchmarks = json.loads(benchmarks)
    return perf_payload(data.load_portfolio(data.selected_broker()), (period or "MAX").upper(), benchmarks)


# --------------------------------------------------------------- transações
@action
def add_transaction(**kw):
    typ = kw.get("type")
    if typ not in Transaction.TYPES:
        raise ApiError("Tipo inválido.")
    instrument = None
    if typ in ("BUY", "SELL", "DIVIDEND"):
        instrument = _ensure_instrument(kw.get("instrument"), kw.get("instrument_name"), kw.get("currency"))
    qty, amount = _float(kw.get("quantity")), _float(kw.get("amount"))
    if typ in ("BUY", "SELL") and qty <= 0:
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
        b.broker_name, b.color = broker_name, color or b.color
        db.session.commit()
        return b.id
    bid = importer.get_or_create_broker(broker_name, color or "#3b82f6")
    db.session.commit()
    return bid


@action
def delete_broker(name):
    b = _get(Broker, name)
    if Transaction.query.filter_by(broker=b.id).first():
        raise ApiError("Esta corretora tem transações. Apaga primeiro os extratos/transações.")
    db.session.delete(b)
    db.session.commit()
    if Setting.get("broker") == str(b.id):
        Setting.set("broker", None)


@action
def update_instrument(ticker, instrument_name=None, sector=None, data_symbol=None, kind=None, color=None):
    inst = db.session.get(Instrument, ticker)
    if inst is None:
        raise ApiError("Ativo desconhecido.")
    for k, v in {"instrument_name": instrument_name, "sector": sector, "data_symbol": data_symbol,
                 "color": color}.items():
        if v is not None:
            setattr(inst, k, v.strip() or None)
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


# --------------------------------------------------------- dados e mercado
@action
def refresh_market():
    if not market.yfinance_available():
        raise ApiError("Instala o pacote yfinance para obter cotações (pip install yfinance).")
    market.refresh_in_background(current_app._get_current_object())
    return "Atualização de cotações em curso. Pode demorar alguns minutos; o aviso na Visão Geral desaparece quando terminar."


@action
def set_risk_free(rate):
    value = _float(rate)
    if not 0 <= value <= 20:
        raise ApiError("Indica uma taxa entre 0 e 20%.")
    Setting.set("risk_free", value)
    return f"Taxa sem risco: {value:g}%."


@action
def refresh_status():
    running, error, missing = market.refresh_state()
    indices = {t for (t,) in db.session.query(Instrument.ticker).filter_by(kind="index")}
    return {"running": running, "error": error, "missing": [t for t in missing if t not in indices], "last_refresh": Setting.get("last_refresh"),
            "updated": int(Setting.get("refresh_updated") or 0)}


@action
def load_demo():
    from .services.demo import create_demo
    return create_demo()


@action
def reset_data(confirm=""):
    if confirm != "APAGAR":
        raise ApiError('Escreve APAGAR para confirmar.')
    for model in (Transaction, ImportBatch, Alert, WatchItem, Event, News, Price, FxRate):
        model.query.delete()
    Broker.query.delete()
    Instrument.query.filter(Instrument.kind != "index").delete()
    for key in ("broker", "demo"):
        Setting.set(key, None)
    db.session.commit()
    return "Todos os dados foram apagados."


@bp.route("/backup")
def backup():
    """Descarrega uma cópia do ficheiro da base de dados."""
    db.session.commit()
    return send_file(current_app.config["DB_PATH"], as_attachment=True,
                     download_name=f"portfolio-{date.today().isoformat()}.db")


# ------------------------------------------------------------------ segurança
@action
def set_password(new_password, confirm, current_password=""):
    if auth.env_password():
        raise ApiError("A palavra-passe está definida na variável PORTFOLIO_PASSWORD: muda-a no servidor.")
    if auth.password_enabled() and not auth.check_password(current_password):
        raise ApiError("A palavra-passe atual está errada.")
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
    if not auth.check_password(current_password):
        raise ApiError("A palavra-passe atual está errada.")
    if not auth.is_local_request():
        raise ApiError("Só podes remover a palavra-passe no computador onde a aplicação corre.")
    auth.clear_password()
    return "Palavra-passe removida."


@action
def logout():
    session.clear()
