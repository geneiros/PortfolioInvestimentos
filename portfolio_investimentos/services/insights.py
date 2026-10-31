"""Dados dos cartões da Visão Geral: notas (perfil de investidor), peso vs retorno e alocação."""
from datetime import timedelta

from ..engine.scores import PROFILES, Scorer, profile_list
from ..models import Broker, DividendHistory, Instrument, Setting, Transaction, db
from . import data

COUNTRY_BY_ISIN = {
    "US": "EUA", "IE": "Irlanda", "DE": "Alemanha", "FR": "França", "NL": "Países Baixos", "LU": "Luxemburgo",
    "GB": "Reino Unido", "PT": "Portugal", "ES": "Espanha", "IT": "Itália", "CH": "Suíça", "DK": "Dinamarca",
    "SE": "Suécia", "NO": "Noruega", "FI": "Finlândia", "BE": "Bélgica", "AT": "Áustria", "CA": "Canadá",
    "JP": "Japão", "CN": "China", "HK": "Hong Kong", "KY": "Ilhas Caimão", "BM": "Bermudas", "JE": "Jersey",
    "AU": "Austrália", "BR": "Brasil", "IL": "Israel", "TW": "Taiwan", "KR": "Coreia do Sul", "IN": "Índia",
}
# sem ISIN (ex.: XTB): o país da bolsa pelo sufixo do ticker
COUNTRY_BY_SUFFIX = {
    "US": "EUA", "DE": "Alemanha", "F": "Alemanha", "FR": "França", "PA": "França", "NL": "Países Baixos",
    "AS": "Países Baixos", "UK": "Reino Unido", "L": "Reino Unido", "IT": "Itália", "MI": "Itália", "ES": "Espanha",
    "MC": "Espanha", "PT": "Portugal", "LS": "Portugal", "CH": "Suíça", "SW": "Suíça", "DK": "Dinamarca",
    "CO": "Dinamarca", "BE": "Bélgica", "BR": "Bélgica", "SE": "Suécia", "ST": "Suécia", "NO": "Noruega",
    "OL": "Noruega", "FI": "Finlândia", "HE": "Finlândia", "PL": "Polónia", "WA": "Polónia",
}
KIND_LABELS = {"stock": "Ações", "etf": "ETF"}


def countries(p):
    """País de cada posição: o do ISIN (domicílio) ou, sem ele, o da bolsa (sufixo do ticker)."""
    tickers = [pos.asset.ticker for pos in p.open_positions]
    insts = {i.ticker: i for i in Instrument.query.filter(Instrument.ticker.in_(tickers or [""]))}
    out = {}
    for pos in p.open_positions:
        inst = insts.get(pos.asset.ticker)
        isin = (inst.isin if inst else None) or ""
        symbol = ((inst.data_symbol if inst else None) or pos.asset.ticker).upper()
        if len(isin) == 12 and isin[:2] in COUNTRY_BY_ISIN:
            out[pos.asset.ticker] = COUNTRY_BY_ISIN[isin[:2]]
        elif "." in symbol:
            out[pos.asset.ticker] = COUNTRY_BY_SUFFIX.get(symbol.rsplit(".", 1)[1], "Outros")
        elif len(symbol) == 12 and symbol[:2] in COUNTRY_BY_ISIN:
            out[pos.asset.ticker] = COUNTRY_BY_ISIN[symbol[:2]]
        else:
            out[pos.asset.ticker] = "EUA" if pos.asset.currency == "USD" else "Outros"
    return out


def payers(p):
    """Posições abertas que pagaram dividendos nos últimos 12 meses (recebidos ou segundo o Yahoo)."""
    since = p.as_of - timedelta(days=365)
    held = {pos.asset.ticker for pos in p.open_positions}
    got = {t for (t,) in db.session.query(Transaction.instrument).filter(
        Transaction.type == "DIVIDEND", Transaction.date > since, Transaction.instrument.in_(held or {""}))}
    yahoo = {t for (t,) in db.session.query(DividendHistory.instrument).filter(
        DividendHistory.date > since, DividendHistory.instrument.in_(held or {""}))}
    return got | yahoo


def scores(p):
    scorer = Scorer(p, countries(p), payers(p), risk_free=data.risk_free())
    if not scorer.ok:
        return None
    suggested, why = scorer.suggest()
    chosen = Setting.get("investor_profile")
    profile = chosen if chosen in PROFILES else suggested
    return {"profile": profile, "profile_name": PROFILES[profile][0], "chosen": chosen in PROFILES,
            "suggested": suggested, "suggested_name": PROFILES[suggested][0], "why": why,
            "investor": scorer.investor(profile), "portfolio": scorer.portfolio(), "profiles": profile_list()}


def weight_return(p):
    """Peso (no valor das posições) e retorno total de cada posição aberta."""
    total = sum(pos.value_eur for pos in p.open_positions)
    rows = []
    for pos in p.open_positions:
        w = pos.value_eur / total if total else 0.0
        rows.append({"ticker": pos.asset.ticker, "name": pos.asset.name, "value": round(pos.value_eur, 2),
                     "weight": round(w, 5), "ret": round(pos.roi_pct, 4), "gain": round(pos.roi_eur, 2)})
    return sorted(rows, key=lambda r: -r["value"])


def allocation(p, broker=None):
    """Alocação por setor, geografia, classe e corretora: [(nome, nº de posições, valor)] por vista."""
    ctry = countries(p)
    views = {"sector": {}, "country": {}, "kind": {}}
    for pos in p.open_positions:
        keys = {"sector": "ETF" if pos.asset.kind == "etf" else (pos.asset.sector or "Sem setor"),
                "country": ctry.get(pos.asset.ticker, "Outros"),
                "kind": KIND_LABELS.get(pos.asset.kind, pos.asset.kind)}
        for view, key in keys.items():
            n, v = views[view].get(key, (0, 0.0))
            views[view][key] = (n + 1, v + pos.value_eur)
    if p.cash > 0.5:
        n, v = views["kind"].get("Caixa", (0, 0.0))
        views["kind"]["Caixa"] = (0, v + p.cash)
    brokers = {}
    if broker:
        b = db.session.get(Broker, int(broker))
        brokers[b.broker_name if b else "Corretora"] = (len(p.open_positions), p.holdings_value)
    else:
        for b in Broker.query.order_by(Broker.id):
            bp = data.load_portfolio(str(b.id))
            if bp.holdings_value > 0.5:
                brokers[b.broker_name] = (len(bp.open_positions), bp.holdings_value)
    views["broker"] = brokers
    return {k: [{"name": name, "count": n, "value": round(v, 2)} for name, (n, v) in
                sorted(rows.items(), key=lambda kv: -kv[1][1])] for k, rows in views.items()}
