"""Login com palavra-passe.

No próprio computador a palavra-passe é opcional. Quando a aplicação é acedida de outro dispositivo
(rede local, cloud ou atrás de um proxy) só abre depois de definida uma palavra-passe, em Definições
ou na variável de ambiente PORTFOLIO_PASSWORD.

Depois de MAX_FAILS tentativas erradas do mesmo endereço, esse endereço fica bloqueado LOCK_SECONDS. As
tentativas ficam na base de dados. Atrás de um proxy (ex.: PythonAnywhere, nginx), define PORTFOLIO_PROXY=1
para o endereço ser o do visitante e não o do proxy (senão um visitante bloqueava toda a gente).
"""
import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlsplit

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .models import LoginFailure, Setting, db

bp = Blueprint("auth", __name__)
LOCAL = {"127.0.0.1", "::1"}
MIN_LENGTH = 8
MAX_FAILS, LOCK_SECONDS = 5, 300
OPEN_ENDPOINTS = {"auth.login", "static", "pages.service_worker", "pages.ping"}


def env_password():
    return os.environ.get("PORTFOLIO_PASSWORD") or None


def password_enabled():
    return bool(env_password() or Setting.get("password_hash"))


def check_password(password):
    env = env_password()
    if env:
        return hmac.compare_digest(password.encode(), env.encode())
    stored = Setting.get("password_hash")
    return bool(stored) and check_password_hash(stored, password)


def set_password(password):
    Setting.set("password_hash", generate_password_hash(password))
    session["auth"] = _version()


def clear_password():
    Setting.set("password_hash", None)


def _version():
    """Identifica a palavra-passe atual: ao mudá-la, as sessões abertas noutros dispositivos terminam."""
    source = env_password() or Setting.get("password_hash") or ""
    return hashlib.sha256(source.encode()).hexdigest()[:16]


def is_local_request():
    # atrás de um proxy (ex.: nginx no mesmo servidor) o endereço é 127.0.0.1, mas o pedido vem de fora
    return request.remote_addr in LOCAL and "X-Forwarded-For" not in request.headers


def logged_in():
    return password_enabled() and session.get("auth") == _version()


@bp.before_app_request
def _guard():
    if request.endpoint in OPEN_ENDPOINTS:
        return None
    if not password_enabled():
        if is_local_request():
            return None
        return render_template("pages/sem_password.html"), 403
    if logged_in():
        return None
    if request.path.startswith("/api/"):
        return jsonify(error="A sessão terminou: entra de novo."), 401
    return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))


def _safe_next(target):
    # só caminhos internos, para o login não poder redirecionar para outro site
    parts = urlsplit(target or "")
    # os browsers tratam "/\" como "//" (outro site)
    if not target or not target.startswith("/") or target[1:2] in ("/", "\\") or parts.netloc:
        return "/"
    return target


def client_ip():
    return request.remote_addr or ""


def locked(ip):
    """Se o endereço tem tentativas erradas a mais na janela atual (e limpa as janelas já expiradas)."""
    now = time.time()
    LoginFailure.query.filter(LoginFailure.since < now - LOCK_SECONDS).delete(synchronize_session=False)
    db.session.commit()
    row = db.session.get(LoginFailure, ip)
    return bool(row and row.count >= MAX_FAILS)


def register_failure(ip):
    now = time.time()
    row = db.session.get(LoginFailure, ip)
    if row is None or now - row.since > LOCK_SECONDS:
        row = row or LoginFailure(ip=ip)
        row.count, row.since = 0, now
    row.count += 1
    db.session.add(row)
    db.session.commit()


def clear_failures(ip):
    LoginFailure.query.filter_by(ip=ip).delete(synchronize_session=False)
    db.session.commit()


def verify_current_password(password):
    """Verifica a palavra-passe atual (Definições) com o mesmo limite de tentativas do login.

    Devolve None se estiver certa, ou a mensagem de erro."""
    ip = client_ip()
    if locked(ip):
        return "Demasiadas tentativas. Espera alguns minutos e tenta de novo."
    if not check_password(password or ""):
        register_failure(ip)
        return "A palavra-passe atual está errada."
    clear_failures(ip)
    return None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not password_enabled():
        return redirect("/")
    error = None
    if request.method == "POST":
        expected = session.get("csrf")
        if not expected or not hmac.compare_digest(request.form.get("csrf_token", ""), expected):
            abort(403)
        ip = client_ip()
        if locked(ip):
            error = "Demasiadas tentativas. Espera alguns minutos e tenta de novo."
        elif check_password(request.form.get("password", "")):
            clear_failures(ip)
            session.clear()
            session.permanent = True
            session["auth"] = _version()
            session["csrf"] = secrets.token_hex(16)
            return redirect(_safe_next(request.args.get("next")))
        else:
            register_failure(ip)
            error = "Palavra-passe errada."
    return render_template("pages/login.html", error=error), 401 if error else 200
