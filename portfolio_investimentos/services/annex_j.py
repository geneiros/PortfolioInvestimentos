"""Dados de apoio aos quadros 8A e 9.2A do Anexo J."""
from collections import defaultdict
from types import SimpleNamespace

from ..models import Instrument
from .insights import COUNTRY_BY_ISIN


COUNTRY_NUMERIC_CODES = {
    "AT": "040", "AU": "036", "BE": "056", "BM": "060", "BR": "076", "CA": "124",
    "CH": "756", "CN": "156", "DK": "208", "DE": "276", "ES": "724", "FI": "246",
    "FR": "250", "GB": "826", "HK": "344", "IE": "372", "IL": "376", "IN": "356",
    "IT": "380", "JE": "832", "JP": "392", "KR": "410", "KY": "136", "LU": "442",
    "NL": "528", "NO": "578", "PT": "620", "SE": "752", "TW": "158", "US": "840",
}
COUNTRIES = {code: (numeric, COUNTRY_BY_ISIN[code]) for code, numeric in COUNTRY_NUMERIC_CODES.items()
             if code in COUNTRY_BY_ISIN}
COUNTRY_OPTIONS = sorted(((code, label) for code, (_, label) in COUNTRIES.items()), key=lambda row: row[1])


def _country_for_isin(isin):
    isin = (isin or "").strip().upper()
    if len(isin) != 12:
        return None
    return COUNTRIES.get(isin[:2])


def build(p, broker, year):
    """Prepara linhas em EUR; países de contraparte não disponíveis ficam vazios, sem inferências."""
    data = {"dividends": [], "interest": [], "sales": [], "warnings": []}
    warnings = set()

    dividends = defaultdict(lambda: {"gross": 0.0, "tax": 0.0, "assets": set()})
    dividend_tickers = {d.asset.ticker for d in p.dividends if d.date.year == year}
    instruments = {i.ticker: i for i in Instrument.query.filter(Instrument.ticker.in_(dividend_tickers or [""])).all()}
    for dividend in p.dividends:
        if dividend.date.year != year:
            continue
        ticker = dividend.asset.ticker
        country = _country_for_isin(instruments.get(ticker).isin if ticker in instruments else None)
        code = "E11" if dividend.tax_eur > 0 else "E10"
        if country is None:
            warnings.add(f"Não foi possível identificar o país da fonte do dividendo de {ticker}; confirma o ISIN.")
            key = (code, None, ticker)
        else:
            key = (code, country[0], "")
        row = dividends[key]
        row["country"] = country
        row["gross"] += dividend.gross_eur
        row["tax"] += dividend.tax_eur
        row["assets"].add(ticker)

    for (code, numeric_country, _), row in sorted(
            dividends.items(), key=lambda item: (item[0][1] or "999", item[0][0], item[0][2])):
        data["dividends"].append(SimpleNamespace(
            code=code, country_code=numeric_country or "", country_name=row["country"][1] if row["country"] else "",
            gross=round(row["gross"], 2), tax=round(row["tax"], 2), assets=", ".join(sorted(row["assets"])),
        ))

    interest = defaultdict(lambda: {"gross": 0.0, "tax": 0.0})
    for transaction in p.transactions:
        if transaction.date.year == year and transaction.type == "INTEREST":
            gross = p.book.to_eur(transaction.amount, transaction.currency, transaction.date)
            tax = p.book.to_eur(transaction.tax, transaction.currency, transaction.date)
            if gross:
                code = "E99" if tax / gross >= 0.35 else "E21"
                interest[code]["gross"] += gross
                interest[code]["tax"] += tax
    if interest:
        country = COUNTRIES.get((getattr(broker, "country", None) or "").upper())
        if country is None:
            warnings.add("Configura o país da fonte dos juros em Definições → Corretoras; o campo ficará vazio.")
        for code, amounts in sorted(interest.items()):
            data["interest"].append(SimpleNamespace(
                code=code, country_code=country[0] if country else "",
                country_name=country[1] if country else "", gross=round(amounts["gross"], 2),
                tax=round(amounts["tax"], 2),
            ))
    if data["dividends"] or data["interest"]:
        warnings.add("Os códigos de rendimento são sugestões baseadas na retenção registada; confirma as instruções oficiais do ano.")

    fiscal_year = p.fiscal_years().get(year)
    for sale in fiscal_year["sales"] if fiscal_year else []:
        data["sales"].append(SimpleNamespace(
            sale=sale, realization=round(sale.realization_eur, 2),
            acquisition=round(sale.acquisition_value_eur, 2), expenses=round(sale.expenses_eur, 2),
        ))
    if data["sales"]:
        warnings.add("O país da contraparte compradora não consta dos dados da venda; fica em branco e não é inferido pelo ISIN.")
    if any(not row.sale.acquired for row in data["sales"]):
        warnings.add("Algumas datas de aquisição são anteriores ao histórico importado; confirma as datas e os custos.")
    data["warnings"] = sorted(warnings)
    return data
