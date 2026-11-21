"""Planeamento (independência financeira): junta as hipóteses (guardadas e as da URL) com a carteira e prepara tudo
o que a página mostra. As contas estão em engine/fire.py; aqui só se escolhem os números e se arrumam os resultados.

Hipóteses guardadas (Setting):
- fire_expenses: rendimento anual pretendido, em euros de hoje e depois do IRS (sem ele, a página mostra o ecrã
  «Para começar»);
- fire_monthly: depósito por mês (sem ele, a média do dinheiro que entrou nas corretoras nos últimos 12 meses);
- fire_swr: levantamento por ano (3, 3.5, 4) ou «div» (só os dividendos, sem vender);
- fire_inflation: inflação por ano (para o ritmo da carteira em euros de hoje);
- fire_income: rendimentos fora da carteira, JSON [{"name", "monthly", "year"}];
- fire_items: despesas do mês, JSON [{"name", "amount"}].
Na URL: rend, dep, lev, inf, cenario e ano mudam a simulação sem gravar («Hipóteses por gravar»).
"""
import json
from datetime import date, timedelta

from ..engine import fire
from ..engine.portfolio import TAX_RATE
from ..models import Setting
from . import history_data, networth

LEVELS = ("3", "3.5", "4", "div")
DEFAULT_SWR = "3.5"
DEFAULT_INFLATION = 2.0
GOALS = (12000, 18000, 24000)
# despesas do mês de partida, em proporção do rendimento (somam 100%)
DEFAULT_ITEMS = (("Casa (renda ou prestação)", 0.433), ("Supermercado", 0.20), ("Lazer e férias", 0.11),
                 ("Transportes", 0.08), ("Luz, água e gás", 0.0735), ("Seguros", 0.04),
                 ("Telemóvel e internet", 0.03), ("Ginásio", 0.0235), ("Streaming", 0.01))
SCENARIO_NOTES = {"prudente": "Ações do mundo desde 2000", "central": "Ações do mundo desde 1900",
                  "otimista": "S&P 500 desde 1928"}


# ---------------------------------------------------------------------------------------------- hipóteses
def _float(v, default=None):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _json(key):
    try:
        v = json.loads(Setting.get(key) or "[]")
        return v if isinstance(v, list) else []
    except (TypeError, ValueError):
        return []


def level_key(v):
    """«4.0», «4», 4 → «4»; «div» → «div»; o resto → None."""
    if str(v).strip().lower() == "div":
        return "div"
    f = _float(v)
    if f is None:
        return None
    key = f"{f:g}"
    return key if key in LEVELS else None


def average_deposit(p):
    """Média mensal do dinheiro que entrou nas corretoras (depósitos menos levantamentos) nos últimos 12 meses."""
    s = p.series
    if not s.dates:
        return 0.0
    k = next((i for i, d in enumerate(s.dates) if d >= s.dates[-1] - timedelta(days=365)), 0)
    span = max((s.dates[-1] - s.dates[k]).days / 30.44, 1)
    return max((s.net_deposits[-1] - s.net_deposits[k]) / span, 0.0)


def saved():
    """As hipóteses guardadas (None nas que não existem)."""
    return {"income": _float(Setting.get("fire_expenses")), "monthly": _float(Setting.get("fire_monthly")),
            "swr": level_key(Setting.get("fire_swr")) if Setting.get("fire_swr") is not None else None,
            "inflation": _float(Setting.get("fire_inflation")), "incomes": _json("fire_income"),
            "items": _json("fire_items")}


def settings(p, args=None):
    """As hipóteses em uso: as guardadas, com as alterações da URL por cima. `dirty`: há alterações por gravar."""
    args = args or {}
    s = saved()
    avg = round(average_deposit(p))
    base = {"income": s["income"], "monthly": s["monthly"] if s["monthly"] is not None else avg,
            "swr": s["swr"] or DEFAULT_SWR,
            "inflation": s["inflation"] if s["inflation"] is not None else DEFAULT_INFLATION}
    cur = dict(base)
    rend, dep, inf = _float(args.get("rend")), _float(args.get("dep")), _float(args.get("inf"))
    if rend is not None and rend > 0:
        cur["income"] = min(rend, 10_000_000)
    if dep is not None and dep >= 0:
        cur["monthly"] = min(dep, 1_000_000)
    if level_key(args.get("lev")):
        cur["swr"] = level_key(args.get("lev"))
    if inf is not None and -5 <= inf <= 20:
        cur["inflation"] = inf
    dirty = any(cur[k] != base[k] for k in cur)
    return {**cur, "average": avg, "incomes": s["incomes"], "items": s["items"], "goal": s["income"] is not None,
            "dirty": dirty, "saved": base}


def query(cfg, **change):
    """A URL do Planeamento com as hipóteses atuais e as mudanças `change` (para os botões e o «Experimentar»).
    Só leva o que é diferente do guardado."""
    cur = {"rend": cfg["income"], "dep": cfg["monthly"], "lev": cfg["swr"], "inf": cfg["inflation"],
           "cenario": cfg.get("scenario")}
    base = {"rend": cfg["saved"]["income"], "dep": cfg["saved"]["monthly"], "lev": cfg["saved"]["swr"],
            "inf": cfg["saved"]["inflation"], "cenario": "central"}
    cur.update(change)
    keep = [(k, f"{v:g}" if isinstance(v, float) else v) for k, v in cur.items() if v is not None and v != base[k]]
    return "/planeamento" + ("?" + "&".join(f"{k}={v}" for k, v in keep) if keep else "")


# ---------------------------------------------------------------------------------------------- a carteira
def dividends_12m(p, today=None):
    """Dividendos líquidos (depois dos impostos) recebidos nos últimos 12 meses."""
    today = today or date.today()
    since = today - timedelta(days=365)
    return sum(d.net_eur for d in p.dividends if since < d.date <= today)


def lot_tax(p, withdrawal):
    """Imposto efetivo de levantar `withdrawal` € vendendo primeiro os lotes mais antigos, aos preços de hoje: 28%
    da parte de ganho do que se vende. Sem posições, metade de ganho (14%)."""
    lots = []
    for pos in p.open_positions:
        if pos.asset.is_benchmark or pos.qty <= 1e-9 or pos.value_eur <= 0:
            continue
        unit = pos.value_eur / pos.qty
        lots += [(lot.date, lot.qty * unit, lot.cost_eur) for lot in pos.lots if lot.qty > 1e-9]
    if not lots or withdrawal <= 0:
        return TAX_RATE * 0.5
    proceeds = cost = 0.0
    for _, value, lot_cost in sorted(lots, key=lambda x: x[0]):
        take = min(value, withdrawal - proceeds)
        proceeds += take
        cost += lot_cost * take / value
        if proceeds >= withdrawal - 1e-6:
            break
    gain = max(proceeds - cost, 0.0)
    return TAX_RATE * gain / proceeds if proceeds > 0 else 0.0


def portfolio_cagr(p):
    """Rentabilidade anual da carteira (TWR) desde o início e a mesma acima da inflação em Portugal; None se houver
    menos de um ano de histórico."""
    s = p.series
    if not s.dates or s.twr[0] <= 0:
        return None
    years = (s.dates[-1] - s.dates[0]).days / 365.25
    if years < 1:
        return None
    total = s.twr[-1] / s.twr[0]
    infl = history_data.inflation_between(s.dates[0], s.dates[-1])
    return {"since": s.dates[0], "nominal": total ** (1 / years) - 1, "real": (total / (1 + infl)) ** (1 / years) - 1,
            "years": years}


# ---------------------------------------------------------------------------------------------- texto
def duration(months):
    """43 → «3 anos e 7 meses»; 24 → «2 anos»; 5 → «5 meses»."""
    if months is None:
        return "—"
    months = max(int(round(months)), 0)
    y, m = divmod(months, 12)
    parts = []
    if y:
        parts.append(f"{y} ano" if y == 1 else f"{y} anos")
    if m or not y:
        parts.append(f"{m} mês" if m == 1 else f"{m} meses")
    return " e ".join(parts)


def _incomes(cfg, start):
    out = []
    for r in cfg["incomes"]:
        monthly, year = _float(r.get("monthly"), 0.0), int(_float(r.get("year"), start.year))
        if monthly > 0:
            out.append((monthly, max(fire.months_between(start, date(year, 1, 1)), 0)))
    return out


def items(cfg):
    """As despesas do mês (nome, €), na escala do rendimento escolhido: as guardadas ou as de partida."""
    monthly = (cfg["income"] or 0) / 12
    rows = [(str(r.get("name", "")).strip()[:60], _float(r.get("amount"), 0.0)) for r in cfg["items"]]
    rows = [(n, a) for n, a in rows if n and a > 0]
    if not rows:
        return [(n, round(monthly * share)) for n, share in DEFAULT_ITEMS], False
    total = sum(a for _, a in rows)
    return [(n, round(a * monthly / total)) for n, a in rows], True


# ---------------------------------------------------------------------------------------------- a página
def build(p, args=None, today=None):
    today = today or date.today()
    start = today.replace(day=1)
    cfg = settings(p, args)
    args = args or {}
    s = p.series
    others = networth.fire_extra()
    value = p.total_value + others
    history = list(zip(s.dates, s.value))
    divs = dividends_12m(p, today)
    out = {"cfg": cfg, "value": value, "others": others, "dividends": divs, "goals": GOALS,
           "first": s.dates[0] if s.dates else today, "as_of": s.dates[-1] if s.dates else today,
           "history": history}
    if not cfg["goal"] and not args.get("rend"):
        out["timeline"] = timeline(out["first"], today, {}, today.year + 6)
        return out
    income = cfg["income"]
    # levantamento: uma taxa (com o IRS dos lotes) ou só os dividendos (já líquidos, nunca se vende)
    if cfg["swr"] == "div":
        rate_w = divs / value if value > 0 else 0.0
        tax = 0.0
    else:
        rate_w = float(cfg["swr"]) / 100
        tax = lot_tax(p, income / (1 - TAX_RATE / 2))
    incomes = _incomes(cfg, start)
    cagr = portfolio_cagr(p)
    rates = [(k, label, r) for k, label, r in fire.SCENARIOS]
    if cagr:
        rates.append(("ritmo", "Ritmo da carteira", min(max((1 + cagr["nominal"]) / (1 + cfg["inflation"] / 100) - 1,
                                                            0.0), 0.12)))
    chosen = args.get("cenario") if args.get("cenario") in {k for k, _, _ in rates} else "central"
    cfg["scenario"] = chosen
    sc = {k: dict(fire.scenario(value, cfg["monthly"], income, rate_w, tax, incomes, r), key=k, label=label)
          for k, label, r in rates}
    for v in sc.values():
        v["date"] = fire.add_months(start, v["month"]) if v["month"] is not None else None
    cur = sc[chosen]
    number = cur["number"]
    half_m = fire.reach(cur["values"], number / 2)
    out.update(income=income, rate_w=rate_w, tax=tax, scenarios=sc, chosen=chosen, cur=cur, number=number,
               done=value / number if number else 0.0, div_share=divs / income if income else 0.0,
               half={"date": fire.add_months(start, half_m) if half_m is not None else None, "value": number / 2},
               cagr=cagr, notes=SCENARIO_NOTES, incomes=cfg["incomes"])
    # escolher o ano: o depósito mensal que lá chega
    year = _float(args.get("ano"))
    if year and today.year < year <= today.year + fire.MAX_YEARS:
        target = fire.months_between(start, date(int(year), 12, 1))
        out["pick"] = {"year": int(year), "monthly": fire.monthly_needed(value, income, rate_w, tax, incomes,
                                                                        cur["rate"], target)}
    # o que já está pago
    rows, custom = items(cfg)
    out["coverage"] = fire.coverage(rows, cur["values"], rate_w, tax, incomes, start)
    out["items_custom"] = custom
    out["items_rows"] = [{"name": n, "amount": a} for n, a in sorted(rows, key=lambda r: -r[1])]
    out["items_total"] = sum(a for _, a in rows)
    out["items_count"] = len(rows)
    # quanto demora cada €100 000
    ms = fire.milestones(history, cur["values"], start, until=number)
    for m in ms:
        m["future"] = m["date"] is None or m["date"] > start
    current = next((m for m in ms if m["future"]), None)
    if current:
        current["so_far"] = fire.months_between(current["since"], start)
        current["missing"] = max(current["level"] - value, 0.0)
        to = fire.reach(cur["values"], current["level"])
        current["left"] = to
    out["milestones"] = ms
    # o que mexe na data
    out["levers"] = levers(value, cfg, income, rate_w, tax, incomes, cur, start)
    # o número FIRE e o IRS
    if cfg["swr"] != "div":
        out["irs"] = {"none": fire.fire_number(income, rate_w, 0.0), "lots": fire.fire_number(income, rate_w, tax),
                      "all": fire.fire_number(income, rate_w, TAX_RATE)}
    # a probabilidade de chegar lá (anos verdadeiros desde 2000, sem depender do cenário)
    need = fire.need_curve(income, rate_w, tax, incomes, 0.05)
    paths = fire.historical_paths(value, cfg["monthly"], need, history_data.real_returns())
    reached = sorted(p_["month"] for p_ in paths if p_["month"] is not None)
    median = reached[len(paths) // 2] if len(reached) > len(paths) // 2 else None
    flag = int(year) if year and "pick" in out else None
    flag_m = (fire.months_between(start, date(flag, 12, 1)) if flag else
              median if median is not None else cur["month"] if cur["month"] is not None else 30 * 12)
    out["prob"] = {"paths": paths, "month": flag_m, "share": fire.probability(paths, flag_m),
                   "year": fire.add_months(start, flag_m).year, "n": len(paths),
                   "first": min(history_data.WORLD_EQUITY_EUR)}
    if cur["month"] is not None:
        out["prob"]["miss_at_date"] = 1 - fire.probability(paths, cur["month"])
    out["chart"] = chart(out, start)
    marks = {"half": out["half"]["date"], "fire": cur["date"], "low": sc["otimista"]["date"],
             "high": sc["prudente"]["date"]}
    last = max([d.year for d in marks.values() if d] or [today.year + 30])
    out["timeline"] = timeline(out["first"], today, marks, min(last + 1, today.year + fire.MAX_YEARS))
    return out


def timeline(first, today, marks, end_year):
    """Posições (0–100%) na linha do tempo do topo: hoje, as marcas e os anos de referência."""
    a = first.year + (first.month - 1) / 12
    b = max(end_year + 1, today.year + 2)

    def pos(d):
        return None if d is None else round(min(max((d.year + (d.month - 1) / 12 - a) / (b - a), 0), 1) * 100, 2)
    span = b - a
    step = 2 if span <= 20 else 4 if span <= 40 else 6
    ticks = [{"year": y, "pos": pos(date(y, 1, 1))} for y in range(int(a) + 1, int(b) + 1) if y % step == 0]
    return {"today": pos(today), "marks": {k: pos(v) for k, v in marks.items()}, "ticks": ticks}


def levers(value, cfg, income, rate_w, tax, incomes, cur, start):
    """Quatro mudanças e o efeito de cada uma na data FIRE do cenário escolhido."""
    base_m = cur["month"]
    rate = cur["rate"]

    def month(income_=income, monthly=cfg["monthly"], rate_w_=rate_w, tax_=tax, incomes_=incomes):
        return fire.scenario(value, monthly, income_, rate_w_, tax_, incomes_, rate)["month"]
    out = []
    pension_year = (fire.add_months(start, base_m).year if base_m is not None else start.year + 20)
    m = month(incomes_=incomes + [(500.0, fire.months_between(start, date(pension_year, 1, 1)))])
    out.append({"key": "pension", "title": f"Contar com €500 por mês de reforma a partir de {pension_year}",
                "text": f"Uma sugestão. Depois de {pension_year}, a carteira só paga a diferença. Ajusta-a depois de a "
                        "juntar.", "month": m, "year": pension_year})
    if income > 6000:
        m = month(income_=income - 4000)
        out.append({"key": "income", "title": f"Viver com €{income - 4000:,.0f} por ano".replace(",", " "),
                    "text": "€4 000 a menos por ano, já depois do IRS.", "month": m,
                    "href": query(cfg, rend=income - 4000)})
    more = max(round(cfg["monthly"] * 1.1 / 10) * 10, cfg["monthly"] + 50)
    m = month(monthly=more)
    out.append({"key": "monthly", "title": f"Depositar €{more:,.0f} por mês".replace(",", " "),
                "text": f"Mais €{more - cfg['monthly']:,.0f} por mês do que hoje.".replace(",", " "), "month": m,
                "href": query(cfg, dep=float(more))})
    if cfg["swr"] != "div":
        step = {"4": "3.5", "3.5": "3", "3": "3.5"}[cfg["swr"]]
        m = month(rate_w_=float(step) / 100)
        out.append({"key": "swr", "title": f"Levantar {step.replace('.', ',')}% por ano",
                    "text": "Tirar menos aguenta mais anos maus." if float(step) < float(cfg["swr"])
                    else "Tirar mais chega mais cedo, mas aguenta menos anos maus.", "month": m,
                    "href": query(cfg, lev=step)})
    for lv in out:
        lv["date"] = fire.add_months(start, lv["month"]) if lv["month"] is not None else None
        lv["delta"] = (base_m - lv["month"]) if base_m is not None and lv["month"] is not None else None
    return out


def chart(out, start):
    """Dados dos gráficos (em anos decimais): histórico, cenário escolhido, faixa prudente–otimista, número FIRE,
    escada das despesas e simulações históricas."""
    def year(d):
        return round(d.year + (d.month - 1) / 12 + (d.day - 1) / 365, 3)

    def yearly(values, end):
        return [{"x": year(fire.add_months(start, m)), "y": round(v)} for m, v in enumerate(values)
                if m % 12 == 0 and fire.add_months(start, m).year <= end]
    sc = out["scenarios"]
    cur = out["cur"]
    dates = [v["date"] for v in sc.values() if v["date"]]
    last = max([d.year for d in dates] or [start.year + 30])
    end = min(max(last + 2, start.year + 10), start.year + fire.MAX_YEARS)
    hist = out["history"]
    return {
        "start": year(hist[0][0]) if hist else start.year, "end": end, "today": year(start),
        "history": [{"x": year(d), "y": round(v)} for i, (d, v) in enumerate(hist) if i % 5 == 0 or i == len(hist) - 1],
        "projection": yearly(cur["values"], end),
        "low": yearly(sc["prudente"]["values"], end), "high": yearly(sc["otimista"]["values"], end),
        "need": yearly(cur["need"], end),
        "marks": [{"x": year(v["date"]), "label": v["date"].year, "key": k} for k, v in sc.items()
                  if v["date"] and k in ("prudente", out["chosen"], "otimista")],
        "number": round(out["number"]),
        "paths": [{"from": p["from"], "month": p["month"],
                   "data": [{"x": year(fire.add_months(start, 12 * i)), "y": round(v)} for i, v in enumerate(p["values"])
                            if start.year + i <= end]} for p in out["prob"]["paths"]],
        "probStart": start.year, "probMonth": out["prob"]["month"],
    }
