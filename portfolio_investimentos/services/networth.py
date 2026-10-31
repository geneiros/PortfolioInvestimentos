"""Património: a carteira das corretoras mais os outros ativos e dívidas indicados à mão, por camadas de liquidez.

Nunca se mostra um único total sem distinguir a liquidez:
- imediata: contas à ordem e poupança à vista (o que podes usar hoje);
- curto prazo: corretoras (ETF/ações vendem-se em dias), certificados, depósitos a prazo, PPR;
- ilíquido: imóveis (meses a vender, com custos e preço estimado), já líquidos dos créditos ligados a eles e,
  se quiseres ser conservador, de um desconto para os custos de venda.

Património líquido total = imediata + curto prazo + ilíquido − dívidas sem imóvel.
Património líquido disponível = imediata + curto prazo − dívidas sem imóvel.
"""
from bisect import bisect_right
from datetime import date

from ..models import LIQUIDITY, OTHER_CATEGORIES, OtherAsset, OtherAssetValue, Setting, db

STALE_DAYS = 90  # valor sem atualizar há mais tempo do que isto: aviso na página
SALE_DISCOUNTS = (0, 5, 10)  # % para os custos de venda dos imóveis (opções da página)
BROKERS_KEY = "corretoras"


def assets():
    return OtherAsset.query.order_by(OtherAsset.category, OtherAsset.label).all()


def sale_discount():
    """Desconto para os custos de venda dos imóveis (fração: 0,05 = 5%)."""
    try:
        return min(max(float(Setting.get("networth_sale_discount") or 0), 0.0), 20.0) / 100
    except ValueError:
        return 0.0


def _homes(items):
    """Ids da casa de habitação própria (e de qualquer imóvel marcado como tal)."""
    return {a.id for a in items if a.category == "imovel" and a.home}


def fire_extra():
    """O que os outros ativos marcados para o FIRE somam à carteira.

    A casa própria nunca conta (não a vais vender), nem os créditos ligados a ela; as outras dívidas marcadas
    subtraem.
    """
    items = OtherAsset.query.all()
    homes = _homes(items)
    return sum(a.signed for a in items if a.fire and a.id not in homes and not (a.debt and a.linked in homes))


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


def _layers(brokers, items, values, discount):
    """Camadas a partir dos valores (`values`: id → valor). Devolve (imediata, curto, ilíquido, dívidas soltas)."""
    by_id = {a.id: a for a in items}
    property_ids = {a.id for a in items if not a.debt and a.level == "iliquido"}
    imediata, curto, iliquido, loose = 0.0, brokers, 0.0, 0.0
    for a in items:
        v = values.get(a.id)
        if v is None:
            continue
        if a.debt:
            if a.linked in property_ids and a.linked in by_id:
                iliquido -= v  # crédito do imóvel: abate ao valor dele
            else:
                loose += v
        elif a.level == "imediata":
            imediata += v
        elif a.level == "curto":
            curto += v
        else:
            iliquido += v * (1 - discount) if a.category == "imovel" else v
    return imediata, curto, iliquido, loose


def summary(p, expenses=None):
    """Património por camadas (`p` = carteira de todas as corretoras; `expenses` = despesas anuais)."""
    items = assets()
    by_id = {a.id: a for a in items}
    brokers = p.total_value if p.transactions else 0.0
    discount = sale_discount()
    imediata, curto, iliquido, loose = _layers(brokers, items, {a.id: a.value for a in items}, discount)
    total = imediata + curto + iliquido - loose
    available = imediata + curto - loose
    today = date.today()

    # créditos ligados a cada imóvel
    loans = {}
    for a in items:
        if a.debt and a.linked in by_id and not by_id[a.linked].debt and by_id[a.linked].level == "iliquido":
            loans.setdefault(a.linked, []).append(a)

    gross = brokers + sum(a.value for a in items if not a.debt)
    rows = []
    for a in items:
        cat = OTHER_CATEGORIES.get(a.category, OTHER_CATEGORIES["outro"])
        row = {"name": a.name, "id": a.id, "label": a.label, "category": a.category, "cat": cat[0], "icon": cat[1],
               "color": cat[2], "debt": a.debt, "value": a.value, "signed": a.signed, "fire": bool(a.fire),
               "note": a.note or "", "updated": a.updated, "level": a.level, "liquidity": a.liquidity or "",
               "home": bool(a.home), "linked": a.linked, "share": a.value / gross if gross and not a.debt else 0.0,
               "stale": bool(a.updated and (today - a.updated).days > STALE_DAYS),
               "linked_label": by_id[a.linked].label if a.debt and a.linked in by_id else None,
               "home_loan": bool(a.debt and a.linked in by_id and by_id[a.linked].home)}
        if a.category == "imovel":
            own = sum(c.value for c in loans.get(a.id, []))
            cut = a.value * discount if row["level"] == "iliquido" else 0.0
            row.update(discount=cut, loans=own, equity=a.value - cut - own)
        rows.append(row)

    # tabela agrupada por camada; os créditos de um imóvel vão por baixo dele
    groups = []
    for key, (name, desc, color) in LIQUIDITY.items():
        members = []
        if key == "curto":
            members.append({"brokers": True, "value": brokers, "share": brokers / gross if gross else 0.0})
        for r in rows:
            if r["level"] != key:
                continue
            members.append(r)
            members.extend(dict(x, child=True) for x in rows if x["debt"] and x["linked"] == r["id"]
                           and key == "iliquido")
        subtotal = {"imediata": imediata, "curto": curto, "iliquido": iliquido}[key]
        if members:
            groups.append({"key": key, "name": name, "desc": desc, "color": color, "subtotal": subtotal,
                           "rows": members})
    attached = {c.id for cs in loans.values() for c in cs}
    loose_rows = [r for r in rows if r["debt"] and r["id"] not in attached]
    if loose_rows:
        groups.append({"key": "dividas", "name": "Dívidas", "desc": "créditos sem imóvel associado",
                       "color": "#ef4444", "subtotal": -loose, "rows": loose_rows})

    monthly = expenses / 12 if expenses else None
    return {"assets": rows, "groups": groups, "brokers": brokers, "gross": gross,
            "imediata": imediata, "curto": curto, "iliquido": iliquido, "loose_debts": loose,
            "debts": sum(a.value for a in items if a.debt),
            "total": total, "available": available, "discount": discount,
            "reserve_months": imediata / monthly if monthly else None, "monthly_expenses": monthly,
            "fire_extra": fire_extra(), "allocation": allocation(brokers, items),
            "properties": [{"name": a.name, "label": a.label} for a in items if a.category == "imovel"]}


def allocation(brokers, items):
    """Alocação dos ativos (sem as dívidas) por camada e por categoria, com e sem a casa própria."""
    homes = _homes(items)
    out = {}
    for variant, skip in (("with_home", set()), ("without_home", homes)):
        rows = [(a, a.value) for a in items if not a.debt and a.id not in skip]
        gross = brokers + sum(v for _, v in rows)
        layers = {k: 0.0 for k in LIQUIDITY}
        layers["curto"] += brokers
        cats = {BROKERS_KEY: brokers} if brokers else {}
        for a, v in rows:
            layers[a.level] += v
            cats[a.category] = cats.get(a.category, 0.0) + v
        out[variant] = {
            "gross": round(gross, 2),
            "layers": [{"key": k, "name": LIQUIDITY[k][0], "color": LIQUIDITY[k][2], "value": round(v, 2),
                        "share": v / gross if gross else 0.0} for k, v in layers.items() if v],
            "categories": [{"key": k, "name": "Corretoras" if k == BROKERS_KEY else OTHER_CATEGORIES[k][0],
                            "color": "#3b82f6" if k == BROKERS_KEY else OTHER_CATEGORIES[k][2],
                            "value": round(v, 2), "share": v / gross if gross else 0.0}
                           for k, v in sorted(cats.items(), key=lambda kv: -kv[1]) if v],
        }
    out["has_home"] = bool(homes)
    return out


def history(p):
    """Património no fim de cada mês, por camada: carteira + último valor conhecido de cada outro ativo.

    Os meses são os da carteira e os dos registos dos outros ativos, até ao mês atual. O nível de liquidez e as
    ligações são os de hoje. Devolve {"months", "imediata", "curto", "iliquido", "debts" (a negativo), "total",
    "available"}.
    """
    sdates, svalues = (p.series.dates, p.series.value) if p.transactions else ([], [])
    items = OtherAsset.query.all()
    known = {a.id for a in items}
    per_asset = {}
    for r in OtherAssetValue.query.order_by(OtherAssetValue.date):
        if r.asset in known:
            dates, values = per_asset.setdefault(r.asset, ([], []))
            dates.append(r.date)
            values.append(r.value)
    today = date.today()
    months = {(d.year, d.month) for d in sdates}
    for dates, _ in per_asset.values():
        months.update((d.year, d.month) for d in dates)
    months.add((today.year, today.month))
    discount = sale_discount()
    out = {k: [] for k in ("months", "imediata", "curto", "iliquido", "debts", "total", "available")}
    for y, m in sorted(months):
        end = min(_month_last_day(date(y, m, 1)), today)
        i = bisect_right(sdates, end) - 1
        brokers = svalues[i] if i >= 0 else 0.0
        values = {}
        for aid, (dates, vals) in per_asset.items():
            j = bisect_right(dates, end) - 1
            if j >= 0:
                values[aid] = vals[j]
        imediata, curto, iliquido, loose = _layers(brokers, items, values, discount)
        out["months"].append(f"{y}-{m:02d}")
        out["imediata"].append(round(imediata, 2))
        out["curto"].append(round(curto, 2))
        out["iliquido"].append(round(iliquido, 2))
        out["debts"].append(round(-loose, 2))
        out["total"].append(round(imediata + curto + iliquido - loose, 2))
        out["available"].append(round(imediata + curto - loose, 2))
    return out


def _month_last_day(d):
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)
