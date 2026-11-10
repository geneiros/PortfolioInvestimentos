"""Objetivos de poupança: quanto já há, quanto falta, o esforço mensal até à data e a data prevista ao ritmo
dos últimos 12 meses.

Esforço mensal com rendimento r ao ano (i = r/12 ao mês) e n meses: o que hoje existe cresce até
atual × (1+i)^n e cada entrada mensal P junta P × ((1+i)^n − 1) / i; P é o que falta para chegar ao alvo.
"""
import json
from datetime import date, timedelta

from ..models import Broker, OtherAsset, OtherAssetValue, SavingsGoal, Setting, db
from . import data

RATES = (0.0, 0.03, 0.05, 0.07)
MAX_MONTHS = 600


def _ids(raw):
    try:
        out = json.loads(raw or "[]")
    except ValueError:
        return []
    return [int(x) for x in out if str(x).isdigit()] if isinstance(out, list) else []


def months_between(a, b):
    """Meses inteiros de `a` até `b` (0 se `b` já passou)."""
    return max((b.year - a.year) * 12 + (b.month - a.month) - (1 if b.day < a.day else 0), 0)


def monthly_needed(current, target, months, rate):
    """Entrada mensal para chegar a `target` em `months` meses, a render `rate` ao ano. 0 se já chega."""
    if target <= current:
        return 0.0
    if months <= 0:
        return target - current
    i = rate / 12
    if i <= 0:
        return (target - current) / months
    g = (1 + i) ** months
    return max((target - current * g) * i / (g - 1), 0.0)


def months_to_reach(current, target, monthly, rate):
    """Meses até chegar a `target` com `monthly` por mês a render `rate` ao ano; None se não chega em 50 anos."""
    if current >= target:
        return 0
    i, value = rate / 12, current
    for m in range(1, MAX_MONTHS + 1):
        value = value * (1 + i) + monthly
        if value >= target:
            return m
    return None


def monthly_expenses():
    try:
        return float(Setting.get("fire_expenses") or 0) / 12
    except ValueError:
        return 0.0


def _asset_value_ago(asset, when):
    row = (OtherAssetValue.query.filter(OtherAssetValue.asset == asset.id, OtherAssetValue.date <= when)
           .order_by(OtherAssetValue.date.desc()).first())
    return row.value if row else None


def evaluate(goal, today=None):
    today = today or date.today()
    asset_ids, broker_ids = _ids(goal.assets), _ids(goal.brokers)
    assets = OtherAsset.query.filter(OtherAsset.id.in_(asset_ids or [0])).all()
    brokers = {b.id: b for b in Broker.query.filter(Broker.id.in_(broker_ids or [0]))}
    parts, pace = [], 0.0
    year_ago = today - timedelta(days=365)
    for a in assets:
        if a.debt:
            continue
        parts.append({"name": a.label, "value": a.value})
        before = _asset_value_ago(a, year_ago)
        if before is not None:
            pace += (a.value - before) / 12
    for bid, b in brokers.items():
        p = data.load_portfolio(str(bid))
        parts.append({"name": b.broker_name, "value": p.total_value})
        s = p.series
        if s.dates:  # o dinheiro posto nos últimos 12 meses (depósitos − levantamentos)
            k = next((j for j, d in enumerate(s.dates) if d >= year_ago), 0)
            pace += (s.net_deposits[-1] - (s.net_deposits[k - 1] if k > 0 else 0.0)) / 12
    if goal.fixed:
        parts.append({"name": "Valor fixo", "value": goal.fixed})
    current = sum(x["value"] for x in parts)
    expenses = monthly_expenses()
    target = goal.target if goal.months is None else goal.months * expenses
    target = target or 0.0
    months = months_between(today, goal.deadline) if goal.deadline else None
    rate = goal.rate or 0.0
    needed = monthly_needed(current, target, months, rate) if months is not None else None
    reach = months_to_reach(current, target, pace, rate) if pace > 0 or current >= target else None
    eta = None
    if reach is not None:
        y, m = divmod(today.month - 1 + reach, 12)
        eta = date(today.year + y, m + 1, 1)
    return {"id": goal.id, "name": goal.name, "label": goal.label, "target": target, "months": goal.months,
            "expenses": expenses, "deadline": goal.deadline, "current": current, "parts": parts,
            "progress": min(current / target, 1.0) if target > 0 else 0.0, "missing": max(target - current, 0.0),
            "months_left": months, "needed": needed, "rate": rate, "pace": pace, "eta": eta,
            "on_track": (eta is not None and goal.deadline is not None and eta <= goal.deadline) or current >= target,
            "asset_ids": asset_ids, "broker_ids": broker_ids, "fixed": goal.fixed or 0.0}


def all_goals(today=None):
    return [evaluate(g, today) for g in SavingsGoal.query.order_by(SavingsGoal.deadline.is_(None),
                                                                     SavingsGoal.deadline, SavingsGoal.id)]


def options():
    """Ativos do Património (sem dívidas) e corretoras que se podem ligar a um objetivo."""
    return {"assets": [a for a in OtherAsset.query.order_by(OtherAsset.label) if not a.debt],
            "brokers": Broker.query.order_by(Broker.broker_name).all(), "rates": RATES}


def forget_links():
    """Depois de apagar os dados: os objetivos ficam, sem as ligações a ativos e corretoras que já não existem."""
    for g in SavingsGoal.query.all():
        g.assets, g.brokers = "[]", "[]"
    db.session.commit()
