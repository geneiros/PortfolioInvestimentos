"""Portfolio Investimentos: gestor de carteira de investimentos que corre localmente."""
import mimetypes
import os
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask, session

__version__ = "0.2.0"


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


def data_dir():
    """Pasta dos dados do utilizador (pode ser alterada com PORTFOLIO_DATA_DIR)."""
    custom = os.environ.get("PORTFOLIO_DATA_DIR")
    if custom:
        path = Path(custom)
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


def create_app(config=None):
    from .engine import formatting
    from .models import db

    folder = data_dir()
    db_path = str(folder / "portfolio.db")
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=_secret_key(folder),
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
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

    from .services.importer import broker_logo
    app.jinja_env.globals["broker_logo"] = broker_logo
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

    with app.app_context():
        from .models import migrate
        db.create_all()
        migrate()
        from .services.market import ensure_benchmarks
        ensure_benchmarks()
    from .services.data import schedule_warm
    schedule_warm(app, delay=0.5)  # prepara a carteira enquanto o browser abre
    return app
