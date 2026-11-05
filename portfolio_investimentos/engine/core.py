"""Carteira cerne: pesos alvo de 3 ETF, com escalões que dão mais peso ao ETF de crescimento quando ele cai face
ao seu máximo.

Exemplo (o do utilizador): base ERNX 45% · FWIA 30% · XEON 25%; com o FWIA −10%, −20%, −30%, −40% e −50% abaixo
do máximo, a mistura passa para 40/35/25, 35/40/25, 30/50/20, 25/60/15 e 20/70/10. O escalão atingido mantém-se
quando o FWIA recupera (só sobe); voltar à base é uma decisão manual.

Retorno esperado e volatilidade de cada mistura com os pressupostos de cada ETF (média ponderada e correlação
perto de zero, como na tabela do utilizador); «pior ano típico» ≈ percentil 10 de uma normal, μ − 1,3 σ (o
arredondamento da tabela; o valor exato de uma normal é 1,2816).
"""
from math import sqrt

P10_Z = 1.3
ROLES = ("reserve", "growth", "stable")


def _mix(reserve, growth, stable):
    return {"reserve": reserve, "growth": growth, "stable": stable}


DEFAULT_PLAN = {
    "assets": [  # papel, código (procura do ticker), peso base, retorno esperado, volatilidade
        {"role": "reserve", "code": "ERNX", "base": 0.45, "mu": 0.0322, "vol": 0.0063},
        {"role": "growth", "code": "FWIA", "base": 0.30, "mu": 0.0700, "vol": 0.1317},
        {"role": "stable", "code": "XEON", "base": 0.25, "mu": 0.0291, "vol": 0.0024},
    ],
}
# as misturas de cada escalão (a tabela do utilizador); o escalão k chega com uma queda de k × intervalo
STEP_MIXES = [_mix(0.40, 0.35, 0.25), _mix(0.35, 0.40, 0.25), _mix(0.30, 0.50, 0.20), _mix(0.25, 0.60, 0.15),
              _mix(0.20, 0.70, 0.10)]
DEFAULT_INTERVAL = 0.10


def steps_for_interval(interval):
    """Escalões [{"drop", "weights"}] com as misturas da tabela, a cada `interval` de queda (0,10 = −10/−20/…)."""
    return [{"drop": round(k * interval, 6), "weights": dict(w)} for k, w in enumerate(STEP_MIXES, 1)]


DEFAULT_PLAN["steps"] = steps_for_interval(DEFAULT_INTERVAL)
ROLE_NAMES = {"reserve": "Reserva", "growth": "Crescimento", "stable": "Estável"}


def step_for(drawdown, steps):
    """Escalão (0 = base) para uma queda `drawdown` (fração negativa, ex.: −0,23)."""
    k = 0
    for i, s in enumerate(steps, 1):
        if -drawdown >= s["drop"] - 1e-12:
            k = i
    return k


def target_weights(plan, step):
    """Pesos alvo por papel no escalão `step` (0 = os pesos base)."""
    if step:
        return dict(plan["steps"][step - 1]["weights"])
    return {a["role"]: a["base"] for a in plan["assets"]}


def mix_stats(plan, weights):
    """Retorno esperado, volatilidade e pior ano típico (P10) de uma mistura, com os pressupostos do plano."""
    mu = sum(weights.get(a["role"], 0.0) * a["mu"] for a in plan["assets"])
    vol = sqrt(sum((weights.get(a["role"], 0.0) * a["vol"]) ** 2 for a in plan["assets"]))
    return {"mu": mu, "vol": vol, "ratio": mu / vol if vol else None, "p10": mu - P10_Z * vol}


def drawdown_of(closes):
    """(queda face ao máximo, máximo, data do máximo, último) de [(data, fecho)]."""
    if not closes:
        return None
    peak_date, peak = max(closes, key=lambda x: x[1])
    last = closes[-1][1]
    return {"drawdown": last / peak - 1 if peak else 0.0, "peak": peak, "peak_date": peak_date, "last": last}


def core_status(plan, values, prices, growth_closes, reached=0, new_money=0.0):
    """Estado da carteira cerne.

    `values`: papel → valor atual em EUR; `prices`: papel → preço atual em EUR (para as unidades);
    `growth_closes`: [(data, fecho)] do ETF de crescimento; `reached`: escalão já atingido (guardado);
    `new_money`: dinheiro novo a investir (EUR). Sem dinheiro novo, `delta` é a ordem para chegar ao alvo
    (comprar/vender); com ele, `buy` distribui só o dinheiro novo pelos que estão abaixo do alvo, sem vender.
    """
    dd = drawdown_of(growth_closes)
    now = step_for(dd["drawdown"], plan["steps"]) if dd else 0
    step = max(now, min(reached, len(plan["steps"])))
    target = target_weights(plan, step)
    total = sum(values.values())
    money = max(new_money, 0.0)
    after = total + money
    gaps = {a["role"]: max(target.get(a["role"], 0.0) * after - values.get(a["role"], 0.0), 0.0)
            for a in plan["assets"]}
    gap_sum = sum(gaps.values())
    rows = []
    for a in plan["assets"]:
        role = a["role"]
        value = values.get(role, 0.0)
        delta = target.get(role, 0.0) * after - value
        buy = money * gaps[role] / gap_sum if gap_sum else money * target.get(role, 0.0)
        price = prices.get(role)
        rows.append({"role": role, "name": ROLE_NAMES[role], "code": a["code"], "value": value,
                     "weight": value / total if total else 0.0, "base": a["base"], "target": target.get(role, 0.0),
                     "deviation": (value / total if total else 0.0) - target.get(role, 0.0),
                     "delta": delta, "units": delta / price if price else None,
                     "buy": buy, "buy_units": buy / price if price else None})
    current = {r["role"]: r["weight"] for r in rows}
    ladder = []
    for k in range(len(plan["steps"]) + 1):
        w = target_weights(plan, k)
        ladder.append({"step": k, "drop": plan["steps"][k - 1]["drop"] if k else 0.0, "weights": w,
                       "stats": mix_stats(plan, w)})
    nxt = plan["steps"][step] if step < len(plan["steps"]) else None
    return {"step": step, "step_now": now, "reached": reached, "new_step": now > reached, "drawdown": dd,
            "rows": rows, "total": total, "new_money": money, "ladder": ladder,
            "next_drop": nxt["drop"] if nxt else None,
            "next_price": dd["peak"] * (1 - nxt["drop"]) if nxt and dd else None,
            "target_stats": mix_stats(plan, target), "current_stats": mix_stats(plan, current) if total else None}
