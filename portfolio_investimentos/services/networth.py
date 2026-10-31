"""Património: a carteira das corretoras mais os outros ativos e dívidas indicados à mão."""
from bisect import bisect_right
from datetime import date

from ..models import OTHER_CATEGORIES, OtherAsset, OtherAssetValue, db

STALE_DAYS = 90  # valor sem atualizar há mais tempo do que isto: aviso na página


def assets():
    return OtherAsset.query.order_by(OtherAsset.category, OtherAsset.label).all()


def fire_extra():
    """O que os outros ativos marcados para o FIRE somam à carteira (as dívidas marcadas subtraem)."""
    return sum(a.signed for a in OtherAsset.query.filter_by(fire=True))


def record(asset, on=None):
    """Guarda o valor do mês (um registo por ativo e mês: fica o último do mês)."""
    on = on or date.today()
    first = on.replace(day=1)
    row = OtherAssetValue.query.filter(OtherAssetValue.asset == asset.id, OtherAssetValue.date >= first,
                                       OtherAssetValue.date <= _month_last_day(on)).first()
    if row is None:
        row = OtherAssetValue(asset=asset.id)
        db.session.add(row)
    row.date, row.value = on, asset.value


def summary(p):
    """Totais do património (`p` = carteira de todas as corretoras)."""
    items = assets()
    brokers = p.total_value if p.transactions else 0.0
    by_cat = {}
    for a in items:
        by_cat[a.category] = by_cat.get(a.category, 0.0) + a.value
    others = sum(a.value for a in items if not a.debt)
    debts = sum(a.value for a in items if a.debt)
    net = brokers + others - debts
    today = date.today()
    rows = [{"name": a.name, "label": a.label, "category": a.category, "cat": OTHER_CATEGORIES[a.category][0],
             "icon": OTHER_CATEGORIES[a.category][1], "color": OTHER_CATEGORIES[a.category][2], "debt": a.debt,
             "value": a.value, "signed": a.signed, "fire": bool(a.fire), "note": a.note or "", "updated": a.updated,
             "stale": bool(a.updated and (today - a.updated).days > STALE_DAYS)} for a in items]
    gross = brokers + others
    for r in rows:
        r["share"] = r["value"] / gross if gross else 0.0
    cats = [{"key": k, "name": v[0], "color": v[2], "value": round(by_cat[k], 2), "debt": v[4]}
            for k, v in OTHER_CATEGORIES.items() if by_cat.get(k)]
    return {"assets": rows, "brokers": brokers, "brokers_share": brokers / gross if gross else 0.0,
            "others": others, "debts": debts, "net": net, "gross": gross,
            "fire_extra": sum(r["signed"] for r in rows if r["fire"]), "categories": cats}


def history(p):
    """Património líquido no fim de cada mês: carteira + último valor conhecido de cada outro ativo.

    Os meses são os da carteira e os dos registos dos outros ativos, até ao mês atual. Devolve
    {"months": [...], "brokers": [...], "others": [...], "debts": [...], "net": [...]} (dívidas a negativo).
    """
    sdates, svalues = (p.series.dates, p.series.value) if p.transactions else ([], [])
    kinds = {a.id: a.debt for a in OtherAsset.query}
    per_asset = {}
    for r in OtherAssetValue.query.order_by(OtherAssetValue.date):
        if r.asset in kinds:
            dates, values = per_asset.setdefault(r.asset, ([], []))
            dates.append(r.date)
            values.append(r.value)
    today = date.today()
    months = {(d.year, d.month) for d in sdates}
    for dates, _ in per_asset.values():
        months.update((d.year, d.month) for d in dates)
    months.add((today.year, today.month))
    out = {"months": [], "brokers": [], "others": [], "debts": [], "net": []}
    for y, m in sorted(months):
        end = min(_month_last_day(date(y, m, 1)), today)
        i = bisect_right(sdates, end) - 1
        brokers = svalues[i] if i >= 0 else 0.0
        others = debts = 0.0
        for aid, (dates, values) in per_asset.items():
            j = bisect_right(dates, end) - 1
            if j >= 0:
                if kinds[aid]:
                    debts += values[j]
                else:
                    others += values[j]
        out["months"].append(f"{y}-{m:02d}")
        out["brokers"].append(round(brokers, 2))
        out["others"].append(round(others, 2))
        out["debts"].append(round(-debts, 2))
        out["net"].append(round(brokers + others - debts, 2))
    return out


def _month_last_day(d):
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)
