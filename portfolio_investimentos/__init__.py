"""Portfolio Investimentos: gestor de carteira de investimentos que corre localmente."""
import functools
import mimetypes
import os
import secrets
import sys
from datetime import timedelta
from pathlib import Path

from flask import Flask, session

__version__ = "0.4.8"


def _adopt_legacy(old, new):
    """Passa a pasta de dados das versões anteriores para o nome novo, sem perder os dados.

    Se não for possível mudar o nome (ex.: ficheiro aberto noutro programa), continua a usar a antiga.
    """
    if old.is_dir() and not new.exists():
        try:
            old.rename(new)
        except OSError:
            return old
    return new


PORTABLE_NAME = "PortfolioInvestimentos-dados"


def _is_removable(path):
    """O caminho está num disco amovível (pen USB)? Só no Windows; nos outros sistemas, não se sabe (False)."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        drive = os.path.splitdrive(str(path))[0]
        return bool(drive) and ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == 2  # DRIVE_REMOVABLE
    except Exception:
        return False


@functools.lru_cache(maxsize=1)
def portable_dir():
    """Modo portátil (só no executável): a pasta PortfolioInvestimentos-dados ao lado do executável, se já existir
    ou se o executável estiver numa pen USB (Windows). None se não se aplica ou se não for possível escrever lá
    (pen protegida): nesse caso ficam na pasta habitual."""
    if not getattr(sys, "frozen", False):
        return None
    folder = Path(sys.executable).resolve().parent / PORTABLE_NAME
    if not folder.is_dir() and not _is_removable(folder):
        return None
    try:
        folder.mkdir(exist_ok=True)
        probe = folder / ".escrita"
        probe.write_text("ok")
        probe.unlink()
        return folder
    except OSError as exc:
        print(f"Não é possível escrever em {folder} ({exc}); os dados ficam na pasta habitual.")
        return None


def is_portable():
    return not os.environ.get("PORTFOLIO_DATA_DIR") and portable_dir() is not None


def data_dir():
    """Pasta dos dados do utilizador: PORTFOLIO_DATA_DIR; senão, no executável numa pen (ou com a pasta
    PortfolioInvestimentos-dados ao lado), essa pasta; senão a habitual do sistema."""
    custom = os.environ.get("PORTFOLIO_DATA_DIR")
    if custom:
        path = Path(custom)
    elif portable_dir() is not None:
        path = portable_dir()
    elif os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", Path.home()))
        path = _adopt_legacy(appdata / "PortfolioManager", appdata / "PortfolioInvestimentos")
    else:
        path = _adopt_legacy(Path.home() / ".portfolio-manager", Path.home() / ".portfolio-investimentos")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _secret_key(folder):
    key_file = folder / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
    return key_file.read_text().strip()


mimetypes.add_type("application/manifest+json", ".webmanifest")  # manifesto da aplicação instalável


# páginas de consulta que o modo "Disponível offline" pode guardar (não Importar nem Definições)
OFFLINE_PAGES = {"pages.overview", "pages.carteira", "pages.desempenho", "pages.dividendos", "pages.fiscal",
                 "pages.radar", "pages.transacoes", "pages.planeamento", "pages.patrimonio"}


def create_app(config=None):
    from .engine import formatting
    from .models import db

    folder = data_dir()
    db_path = str(folder / "portfolio.db")
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=_secret_key(folder),
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        # o SQLite espera até 30 s por uma escrita de outro processo/thread (por omissão 5 s: a atualização de
        # cotações e as páginas escrevem ao mesmo tempo, e em servidores lentos "database is locked" saía logo)
        SQLALCHEMY_ENGINE_OPTIONS={"connect_args": {"timeout": 30}},
        DB_PATH=db_path,
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,
        SESSION_COOKIE_SAMESITE="Strict",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        # em HTTPS (ex.: na cloud) o cookie de sessão só segue por ligações cifradas
        SESSION_COOKIE_SECURE=os.environ.get("PORTFOLIO_HTTPS") == "1",
    )
    if config:
        app.config.update(config)
        if "SQLALCHEMY_DATABASE_URI" in config and config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///"):
            app.config["DB_PATH"] = config["SQLALCHEMY_DATABASE_URI"][len("sqlite:///"):]

    db.init_app(app)

    # atrás de um proxy (PythonAnywhere, nginx): PORTFOLIO_PROXY=n confia nos cabeçalhos X-Forwarded-* dos n
    # proxies à frente, para o endereço do pedido ser o do visitante (limite de tentativas de login por pessoa)
    proxies = os.environ.get("PORTFOLIO_PROXY", "").strip()
    if proxies.isdigit() and int(proxies) > 0:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=int(proxies), x_proto=int(proxies))

    def static_max_age(filename):
        # bibliotecas e ícones não mudam entre páginas: sem validade em cache, o browser voltava a pedir
        # a fonte dos ícones a cada página e estes desapareciam por instantes
        if filename and filename.replace("\\", "/").startswith(("vendor/", "icons/")):
            return 7 * 24 * 3600
        return None
    app.get_send_file_max_age = static_max_age

    from .api import bp as api_bp
    from .auth import bp as auth_bp
    from .views import bp as pages_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp)
    # extensões instaladas à parte (ver plugins.py e docs/plugins.md); antes das migrações, para as tabelas
    # dos plugins também serem criadas
    from . import plugins
    plugins.load(app)

    from .services.importer import broker_logo
    app.jinja_env.globals["broker_logo"] = broker_logo
    from .services import logos as _logos
    app.jinja_env.globals["logo_url"] = _logos.url
    app.jinja_env.filters.update(
        money=formatting.money, pct=formatting.pct, number=formatting.number, tone=formatting.tone,
        ddmmyyyy=formatting.ddmmyyyy, ddmm=formatting.ddmm, month_label=formatting.month_label,
        ago=formatting.ago,
    )

    @app.context_processor
    def _csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        return {"csrf_token": session["csrf"]}

    @app.context_processor
    def _offline():
        from datetime import datetime
        from .models import Setting
        from flask import request
        theme = request.cookies.get("pm_theme")
        return {"theme_pref": theme if theme in ("light", "dark", "purple") else None,
                "offline_enabled": Setting.get("offline_enabled") == "1",
                "quick_quotes": Setting.get("quick_quotes") == "1",
                "generated_at": datetime.now().isoformat(timespec="minutes")}

    @app.context_processor
    def _updates():
        # aviso de versão nova: só no executável único (o código da pasta atualiza-se com git pull)
        from .services import updates
        exe = updates.is_executable()
        return {"app_version": __version__, "is_executable": exe,
                "update_available": updates.available() if exe else None,
                "update_notice": updates.notice_enabled()}

    @app.after_request
    def _mark_offline_pages(resp):
        # só as páginas de consulta, com o modo offline ligado, podem ficar na cache do service worker
        # (nunca o login, as páginas de erro nem o que é pedido com o modo desligado)
        from flask import request
        from .models import Setting
        if (resp.status_code == 200 and resp.mimetype == "text/html" and request.endpoint in OFFLINE_PAGES
                and Setting.get("offline_enabled") == "1"):
            resp.headers["X-PM-Offline"] = "1"
        return resp

    with app.app_context():
        from .migrations import upgrade
        upgrade(app)
        from .services.market import ensure_benchmarks
        ensure_benchmarks()
    from .services.data import schedule_warm
    schedule_warm(app, delay=0.5)  # prepara a carteira enquanto o browser abre
    return app
