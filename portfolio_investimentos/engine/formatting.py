"""Filtros Jinja para números no formato português (€1 234,56 · +3,42%)."""
from datetime import date, datetime, timezone

from markupsafe import Markup

MONTHS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF ", "DKK": "kr "}


def number(value, decimals=2):
    if value is None:
        return "—"
    s = f"{abs(value):,.{decimals}f}".replace(",", " ").replace(".", ",")
    return ("-" if value < 0 and round(abs(value), decimals) else "") + s


def money(value, decimals=0, currency="EUR", sign=False):
    if value is None:
        return "—"
    sym = SYMBOLS.get(currency, currency + " ")
    prefix = ""
    if value < 0 and round(abs(value), decimals):
        prefix = "−"
    elif sign and value > 0:
        prefix = "+"
    return f"{prefix}{sym}{number(abs(value), decimals)}"


def pct(value, decimals=1, sign=True):
    if value is None:
        return "—"
    v = value * 100
    prefix = "+" if sign and v > 0 else ("−" if v < 0 and round(abs(v), decimals) else "")
    return f"{prefix}{number(abs(v), decimals)}%"


def tone(value):
    if value is None or abs(value) < 1e-9:
        return "text-secondary"
    return "text-up" if value > 0 else "text-down"


def ddmmyyyy(d):
    return d.strftime("%d/%m/%Y") if d else "—"


def ddmm(d):
    return d.strftime("%d/%m") if d else "—"


def month_label(d):
    return f"{MONTHS[d.month - 1]} {d.year}" if d else "—"


def ago(dt):
    if not dt:
        return ""
    delta = datetime.now(timezone.utc).replace(tzinfo=None) - dt
    if delta.days >= 30:
        n = delta.days // 30
        return f"há {n} {'mês' if n == 1 else 'meses'}"
    if delta.days >= 1:
        return f"há {delta.days} {'dia' if delta.days == 1 else 'dias'}"
    h = delta.seconds // 3600
    return f"há {h} h" if h else "agora"


def private(text):
    """Envolve valores monetários para poderem ser escondidos no modo privacidade."""
    return Markup(f'<span class="money">{Markup.escape(text)}</span>')


def register_filters(app):
    app.jinja_env.filters.update(
        number=number, money=money, pct=pct, tone=tone, ddmmyyyy=ddmmyyyy, ddmm=ddmm,
        month_label=month_label, ago=ago, private=private,
    )
    app.jinja_env.globals.update(MONTHS=MONTHS, today=date.today)
