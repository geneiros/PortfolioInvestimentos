"""Alertas da variação do dia da carteira (toda ou de uma corretora), criados na Carteira («Carteira vs mercado»)."""
from ..models import Broker, PortfolioAlert, db
from . import data

LEVELS = (0.01, 0.02, 0.03, 0.05)


def _scope_name(alert, names):
    return names.get(alert.broker, "a carteira") if alert.broker else "Toda a carteira"


def check():
    """Verifica os alertas ativos com a variação do último dia de mercado. Devolve os disparados nesse dia
    (os de agora e os de antes, no mesmo dia), para o aviso no topo."""
    names = {b.id: b.broker_name for b in Broker.query.all()}
    out, changed = [], False
    for a in PortfolioAlert.query.filter_by(active=True).order_by(PortfolioAlert.id).all():
        p = data.load_portfolio(str(a.broker) if a.broker else None)
        if not p.transactions or not p.series.dates:
            continue
        day = p.as_of
        _, pct = p.day_change()
        for side, hit, field in (("up", pct >= a.threshold, "last_up"), ("down", pct <= -a.threshold, "last_down")):
            if a.direction not in (side, "both"):
                continue
            if hit and getattr(a, field) != day:  # no máximo uma vez por dia e por sentido
                setattr(a, field, day)
                changed = True
            if getattr(a, field) == day:
                out.append({"id": a.id, "scope": _scope_name(a, names), "side": side, "pct": pct,
                            "threshold": a.threshold, "day": day})
    if changed:
        db.session.commit()
    return out


def rows():
    """Alertas guardados, para a lista no painel."""
    names = {b.id: b.broker_name for b in Broker.query.all()}
    return [{"id": a.id, "scope": _scope_name(a, names), "threshold": a.threshold, "direction": a.direction,
             "active": a.active} for a in PortfolioAlert.query.order_by(PortfolioAlert.id).all()]
