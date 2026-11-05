"""Carteira cerne: plano guardado (Setting `core_plan`), os ETF de cada papel, o escalão atingido e o aviso.

O escalão atingido (`core_reached`) só sobe: quando o ETF de crescimento passa um escalão, fica guardado e os
pesos alvo mantêm-se mesmo que ele recupere; voltar à base é manual (`reset`). `core_ack` é o escalão cujo
aviso no topo já foi visto.
"""
import copy
import json
import re

from ..engine import core
from ..models import Instrument, Price, Setting, db


def plan():
    """O plano guardado, sobre o de omissão (ERNX 45% · FWIA 30% · XEON 25%, escalões de −10% em −10%)."""
    out = copy.deepcopy(core.DEFAULT_PLAN)
    try:
        saved = json.loads(Setting.get("core_plan") or "{}")
    except ValueError:
        saved = {}
    by_role = {a["role"]: a for a in out["assets"]}
    for a in saved.get("assets", []):
        if a.get("role") in by_role:
            by_role[a["role"]].update({k: a[k] for k in ("code", "base", "ticker") if k in a})
    try:  # as misturas são sempre as da tabela; só muda a queda entre escalões
        interval = float(saved.get("interval") or core.DEFAULT_INTERVAL)
    except (TypeError, ValueError):
        interval = core.DEFAULT_INTERVAL
    out["interval"] = interval
    out["steps"] = core.steps_for_interval(interval)
    out["enabled"] = saved.get("enabled", True)
    return out


def save(new_plan):
    data = {"assets": [{k: a[k] for k in ("role", "code", "base", "ticker") if k in a} for a in new_plan["assets"]],
            "interval": new_plan.get("interval", core.DEFAULT_INTERVAL), "enabled": new_plan.get("enabled", True)}
    Setting.set("core_plan", json.dumps(data))


def _matches(code, inst):
    code = code.upper()
    names = [inst.ticker or "", inst.data_symbol or ""]
    return any(n.upper() == code or re.match(rf"^{re.escape(code)}([.:]|$)", n.upper()) for n in names)


def resolve(p, the_plan=None):
    """Papel → ticker do ativo na aplicação (o escolhido no plano ou, sem ele, pelo código; primeiro os detidos)."""
    the_plan = the_plan or plan()
    held = {pos.asset.ticker for pos in p.open_positions}
    insts = Instrument.query.filter(Instrument.kind != "index").all()
    out = {}
    for a in the_plan["assets"]:
        chosen = a.get("ticker")
        if chosen and any(i.ticker == chosen for i in insts):
            out[a["role"]] = chosen
            continue
        found = sorted((i for i in insts if _matches(a["code"], i)), key=lambda i: i.ticker not in held)
        out[a["role"]] = found[0].ticker if found else None
    return out


def _price_eur(p, ticker):
    pos = next((x for x in p.open_positions if x.asset.ticker == ticker), None)
    if pos and pos.qty:
        return pos.value_eur / pos.qty
    row = Price.query.filter_by(instrument=ticker).order_by(Price.date.desc()).first()
    inst = db.session.get(Instrument, ticker) if row else None
    if not row:
        return None
    return row.close / p.book.fx(inst.currency if inst else "EUR", row.date)


def status(p, new_money=0.0, remember=True):
    """O estado da carteira cerne (ver `core.core_status`), com os tickers de cada papel. None sem o ETF de
    crescimento e o de reserva."""
    the_plan = plan()
    if not the_plan.get("enabled", True):
        return None
    tickers = resolve(p, the_plan)
    if not tickers.get("growth") or not tickers.get("reserve"):
        return {"missing": [a["code"] for a in the_plan["assets"] if not tickers.get(a["role"])], "plan": the_plan,
                "tickers": tickers}
    values = {role: sum(x.value_eur for x in p.open_positions if x.asset.ticker == t) if t else 0.0
              for role, t in tickers.items()}
    prices = {role: _price_eur(p, t) for role, t in tickers.items() if t}
    closes = [(r.date, r.close) for r in Price.query.filter_by(instrument=tickers["growth"]).order_by(Price.date)]
    try:
        reached = int(Setting.get("core_reached") or 0)
    except ValueError:
        reached = 0
    out = core.core_status(the_plan, values, prices, closes, reached=min(reached, len(the_plan["steps"])),
                           new_money=new_money)
    if remember and out["step_now"] > reached:  # o escalão atingido só sobe (fica até voltar à base à mão)
        Setting.set("core_reached", out["step_now"])
    out.update(plan=the_plan, tickers=tickers, missing=[a["code"] for a in the_plan["assets"]
                                                        if not tickers.get(a["role"])])
    return out


def banner(p):
    """O aviso no topo quando a carteira cerne está num escalão cujo aviso ainda não foi visto."""
    try:
        st = status(p)
    except Exception:  # o aviso nunca pode partir uma página
        return None
    if not st or "rows" not in st or not st.get("step"):
        return None
    try:
        ack = int(Setting.get("core_ack") or 0)
    except ValueError:
        ack = 0
    return st if st["step"] > ack else None


def acknowledge(step):
    Setting.set("core_ack", int(step))


def reset():
    """Volta ao alvo base (o escalão atingido recomeça do escalão atual da queda)."""
    Setting.set("core_reached", 0)
    Setting.set("core_ack", 0)
