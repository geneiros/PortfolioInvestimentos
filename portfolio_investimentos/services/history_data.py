"""Dados históricos anuais para o Planeamento (probabilidade de chegar lá e a carteira face à inflação).

Valores aproximados, em percentagem, arredondados a uma casa decimal. Confirmar e atualizar todos os anos:
- WORLD_EQUITY_EUR: retorno total anual do índice MSCI World (dividendos líquidos reinvestidos) em euros.
  Fonte: fichas do índice MSCI World (msci.com) e do iShares Core MSCI World em EUR.
- PT_INFLATION: variação média anual do Índice de Preços no Consumidor em Portugal.
  Fonte: INE / PORDATA («Taxa de inflação: IPC, variação média anual»).
"""

WORLD_EQUITY_EUR = {
    2000: -8.4, 2001: -14.6, 2002: -32.0, 2003: 10.8, 2004: 6.9, 2005: 26.8, 2006: 7.9, 2007: -1.7,
    2008: -37.6, 2009: 26.0, 2010: 20.1, 2011: -2.4, 2012: 14.0, 2013: 21.2, 2014: 19.5, 2015: 10.4,
    2016: 10.7, 2017: 7.5, 2018: -4.1, 2019: 30.0, 2020: 6.3, 2021: 31.1, 2022: -12.8, 2023: 19.6,
    2024: 26.6, 2025: 7.0,
}

PT_INFLATION = {
    2000: 2.9, 2001: 4.4, 2002: 3.6, 2003: 3.3, 2004: 2.4, 2005: 2.3, 2006: 3.1, 2007: 2.5,
    2008: 2.6, 2009: -0.8, 2010: 1.4, 2011: 3.7, 2012: 2.8, 2013: 0.3, 2014: -0.3, 2015: 0.5,
    2016: 0.6, 2017: 1.4, 2018: 1.0, 2019: 0.3, 2020: 0.0, 2021: 1.3, 2022: 7.8, 2023: 4.3,
    2024: 2.4, 2025: 2.3,
}


def real_returns():
    """Retorno real anual (fração) das ações do mundo em euros, descontada a inflação portuguesa."""
    return {y: (1 + WORLD_EQUITY_EUR[y] / 100) / (1 + PT_INFLATION[y] / 100) - 1
            for y in WORLD_EQUITY_EUR if y in PT_INFLATION}


def inflation_between(start, end):
    """Inflação acumulada em Portugal entre duas datas (fração), com os anos parciais proporcionais.
    Os anos que faltam na tabela contam com o último valor conhecido."""
    if end <= start:
        return 0.0
    last = PT_INFLATION[max(PT_INFLATION)]
    factor, y = 1.0, start.year
    while y <= end.year:
        a = start if y == start.year else start.replace(year=y, month=1, day=1)
        b = end if y == end.year else end.replace(year=y, month=12, day=31)
        frac = max((b - a).days, 0) / 365.25
        factor *= (1 + PT_INFLATION.get(y, last) / 100) ** frac
        y += 1
    return factor - 1
