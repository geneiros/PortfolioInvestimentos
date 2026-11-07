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


_SPACES = " \u00a0\u202f\u2009'"  # espaços (também os não separáveis) e apóstrofo como separadores de milhares


def parse_number(text):
    """Número escrito por uma pessoa, à portuguesa ou não: «1 000», «1.000», «1.000,50», «1000,5», «1000.5»,
    «1,000.50». Levanta ValueError se não for um número.

    Regras: os espaços separam milhares; com ponto e vírgula, o último é o decimal; uma vírgula sozinha é decimal;
    vários pontos (ou várias vírgulas) separam milhares; um ponto sozinho seguido de exatamente 3 algarismos, com
    parte inteira diferente de 0, separa milhares («1.000» = 1000, mas «0.125» e «2.5» são decimais).
    Os campos numéricos do browser (type=number) chegam com vírgula decimal (o pm.js converte-os), por isso um
    «12.345» escrito num desses campos não é lido como milhares.
    """
    if isinstance(text, bool):
        raise ValueError(text)
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip()
    for ch in _SPACES:
        s = s.replace(ch, "")
    if not s:
        raise ValueError(text)
    sign = ""
    if s[0] in "+-−":
        sign, s = ("-" if s[0] != "+" else ""), s[1:]
    if not s or any(c not in "0123456789.," for c in s):
        raise ValueError(text)
    def ungroup(whole, sep):  # «1.234.567» → «1234567»; os grupos de milhares têm de ter 3 algarismos
        groups = whole.split(sep)
        if not 1 <= len(groups[0]) <= 3 or any(len(g) != 3 for g in groups[1:]):
            raise ValueError(text)
        return "".join(groups)
    dots, commas = s.count("."), s.count(",")
    if dots and commas:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        sep = "," if dec == "." else "."
        if s.count(dec) > 1:
            raise ValueError(text)
        whole, frac = s.split(dec)
        s = ungroup(whole, sep) + "." + frac
    elif commas:
        s = ungroup(s, ",") if commas > 1 else s.replace(",", ".")
    elif dots > 1:
        s = ungroup(s, ".")
    elif dots == 1:
        whole, frac = s.split(".")
        if len(frac) == 3 and whole not in ("", "0"):
            s = whole + frac
    if s.count(".") > 1 or s in (".", ""):
        raise ValueError(text)
    return float(sign + s)


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
