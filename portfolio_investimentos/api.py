"""Ações chamadas pelas páginas (POST /api/<ação>, protegido com token CSRF)."""
import inspect
import io
import json
import os
import sqlite3
import tempfile
from datetime import date

from flask import Blueprint, Response, abort, current_app, jsonify, request, send_file, session

from .models import (Alert, Broker, DividendHistory, Event, FxRate, ImportBatch, Instrument, Price, Setting,
                     Transaction, WatchItem, db)
from . import auth
from .engine.portfolio import ASSET_TYPES
from .services import backups, data, importer, market

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
    Setting.set("investor_profile", profile)
    return f"Perfil: {PROFILES[profile][0]}."


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
    db.session.delete(b)
    db.session.commit()
    if Setting.get("broker") == str(b.id):
        Setting.set("broker", None)


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
def refresh_market(only_open=""):
    if not market.yfinance_available():
        raise ApiError("Instala o pacote yfinance para obter cotações (pip install yfinance).")
    market.refresh_in_background(current_app._get_current_object(),
                                 only_open=str(only_open).lower() in ("1", "true", "on", "sim"))
    return "Atualização de cotações em curso. Pode demorar alguns minutos; o aviso na Visão Geral desaparece quando terminar."


@action
def set_offline(enabled):
    on = str(enabled).lower() in ("1", "true", "on", "sim")
    Setting.set("offline_enabled", "1" if on else None)
    return "Disponível offline: a cópia das páginas é guardada neste dispositivo." if on else \
        "Modo offline desligado: a cópia guardada neste dispositivo foi apagada."


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
    return "Plano guardado."


@action
def refresh_status():
    running, error, missing = market.refresh_state()
    indices = {t for (t,) in db.session.query(Instrument.ticker).filter_by(kind="index")}
    return {"running": running, "error": error, "missing": [t for t in missing if t not in indices], "last_refresh": Setting.get("last_refresh"),
            "updated": int(Setting.get("refresh_updated") or 0), "progress": market.refresh_progress()}


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
    for model in (Transaction, ImportBatch, Alert, WatchItem, Event, DividendHistory, Price, FxRate):
        model.query.delete()
    Broker.query.delete()
    Instrument.query.filter(Instrument.kind != "index").delete()
    # também o estado da atualização de cotações (senão o aviso "ainda não atualizaste" deixava de aparecer)
    for key in ("broker", "demo", "last_refresh", "refresh_missing", "refresh_updated", "refresh_report",
                "refresh_status", "hide_banner"):
        Setting.set(key, None)
    db.session.commit()
    return "Todos os dados foram apagados."


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
