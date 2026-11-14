"""Simulador de venda (Fiscal): os lotes FIFO que saem, a mais-valia, o imposto do ano antes e depois e as perdas por
realizar que o compensariam. É só uma simulação: não grava nada."""
from datetime import date

from ..engine.portfolio import TAX_RATE, simulate_sale, tax_delta
from . import data


class SimulationError(ValueError):
    """Pedido inválido (ativo que não existe, quantidade acima da detida...): a mensagem é para o utilizador."""


def _brokers():
    return [(b.name, b.broker_name) for b in data.brokers()]


def positions():
    """As posições abertas por corretora (o FIFO conta conta a conta), para a lista do simulador."""
    out = []
    for bid, bname in _brokers():
        p = data.load_portfolio(bid)
        for pos in p.open_positions:
            if pos.asset.is_benchmark:
                continue
            out.append({"key": f"{bid}:{pos.asset.ticker}", "ticker": pos.asset.ticker,
                        "name": pos.asset.name or pos.asset.ticker, "broker": bname, "qty": pos.qty,
                        "price": pos.price, "currency": pos.asset.currency})
    return sorted(out, key=lambda r: (r["ticker"], r["broker"]))


def year_balance(year=None):
    """Saldo de mais-valias do ano (todas as corretoras: o imposto é do contribuinte, não de cada conta)."""
    year = year or date.today().year
    fy = data.load_portfolio(None).fiscal_years().get(year)
    return fy["balance"] if fy else 0.0


def _open_losses(skip=None):
    """Posições abertas com menos-valia latente, de todas as corretoras, da maior perda para a menor."""
    out = []
    for bid, bname in _brokers():
        for pos in data.load_portfolio(bid).open_positions:
            key = f"{bid}:{pos.asset.ticker}"
            if key == skip or pos.asset.is_benchmark:
                continue
            loss = pos.value_eur - pos.invested_eur
            if loss < -0.005:
                out.append({"key": key, "ticker": pos.asset.ticker, "name": pos.asset.name or pos.asset.ticker,
                            "broker": bname, "qty": pos.qty, "loss": loss})
    return sorted(out, key=lambda r: r["loss"])


def harvest(balance, skip=None):
    """Quanto cada perda por realizar baixaria o imposto do ano: sozinha e acumulada (pela ordem da maior perda).

    As perdas só abatem até o saldo chegar a zero: depois disso não poupam mais nada este ano (salvo englobamento)."""
    rows, running, saved = [], balance, 0.0
    for r in _open_losses(skip):
        alone = -tax_delta(balance, r["loss"])["delta"]
        step = -tax_delta(running, r["loss"])["delta"]
        running += r["loss"]
        saved += step
        rows.append({**r, "saving": alone, "cumulative": saved, "balance_after": running})
    return rows


def simulate(key, qty=None, price=None, fees=0.0, today=None):
    """Simula a venda de `qty` (None = tudo) da posição `key` («corretora:ticker») ao `price` (None = o último)."""
    today = today or date.today()
    bid, _, ticker = (key or "").partition(":")
    names = dict(_brokers())
    if bid not in names or not ticker:
        raise SimulationError("Escolhe a posição a simular.")
    p = data.load_portfolio(bid)
    pos = p.positions.get(ticker)
    if pos is None or not pos.is_open:
        raise SimulationError(f"Não há posição aberta em {ticker} na {names[bid]}.")
    held = pos.qty
    qty = held if qty is None else qty
    if qty <= 0:
        raise SimulationError("A quantidade tem de ser maior do que zero.")
    if qty > held + 1e-9:
        raise SimulationError(f"Só tens {held:g} {ticker} na {names[bid]}.")
    price = pos.price if price is None else price
    if not price or price <= 0:
        raise SimulationError(f"Sem preço para {ticker}: indica o preço de venda.")
    fees = fees or 0.0
    if fees < 0:
        raise SimulationError("As comissões não podem ser negativas.")
    currency = pos.asset.currency
    fx = p.book.fx(currency, today) if currency != "EUR" else 1.0
    lots = simulate_sale(pos.lots, qty, price, fx, fees)
    gain = sum(r["gain_eur"] for r in lots)
    balance = year_balance(today.year)
    tax = tax_delta(balance, gain)
    return {
        "key": key, "ticker": ticker, "name": pos.asset.name or ticker, "broker": names[bid], "qty": qty,
        "held": held, "price": price, "currency": currency, "fx": fx, "fees": fees, "year": today.year,
        "lots": [{**r, "acquired": r["acquired"].isoformat() if r["acquired"] else None} for r in lots],
        "estimated": any(r["acquired"] is None for r in lots),
        "cost": sum(r["cost_eur"] for r in lots), "proceeds": sum(r["proceeds_eur"] for r in lots), "gain": gain,
        "balance_before": balance, "balance_after": balance + gain,
        "tax_before": tax["before"], "tax_after": tax["after"], "tax_delta": tax["delta"], "rate": TAX_RATE,
        "harvest": harvest(balance + gain, skip=key),
    }
