"""Notas da carteira (0-100) por perfil de investidor: Investor Score e Portfolio Score.

As notas são uma leitura indicativa, com fórmulas simples e explicadas na página; não são uma recomendação.
O perfil escolhido decide o que conta (e quanto) no Investor Score. A janela é a dos últimos 3 anos (ou todo
o histórico, se for mais curto).
"""
import math
from datetime import timedelta

from .portfolio import EPS, period_returns

SP500, NASDAQ, WORLD = "^GSPC", "^NDX", "URTH"
GROWTH_SECTORS = {"technology", "tecnologia", "communication services", "comunicações", "consumer cyclical"}

METRICS = {  # chave -> (nome, explicação curta)
    "market": ("Superação do Mercado", "Retorno anual da carteira menos o do S&P 500 (em euros), nos últimos 3 anos. "
               "0 pontos a −10 p.p., 50 empatado, 100 a +10 p.p."),
    "index": ("Superação do Índice", "Retorno anual da carteira menos o do MSCI World (em euros), nos últimos 3 anos. "
              "0 pontos a −10 p.p., 50 empatado, 100 a +10 p.p."),
    "nasdaq": ("Superação do Nasdaq", "Retorno anual da carteira menos o do Nasdaq 100 (em euros), nos últimos 3 "
               "anos. 0 pontos a −10 p.p., 50 empatado, 100 a +10 p.p."),
    "fidelity": ("Fidelidade ao Índice", "Desvio (tracking error) entre os retornos mensais da carteira e os do "
                 "MSCI World. 100 pontos sem desvio, 0 a partir de 15% ao ano."),
    "discipline": ("Disciplina", "Metade: meses com compras face ao total. Metade: nos meses em que o mercado caiu "
                   "mais de 3%, em quantos não vendeste mais de 2% da carteira."),
    "patience": ("Paciência", "Quanto tempo, em média, cada euro fica investido (vendas por ano face ao valor da "
                 "carteira). 0 pontos a 1 mês, 100 a 3 anos ou mais."),
    "risk": ("Retorno pelo Risco", "Rácio de Sharpe dos retornos mensais (retorno acima da taxa sem risco a dividir "
             "pela volatilidade). 0 pontos a 0 ou menos, 100 a partir de 1,5."),
    "coherence": ("Coerência", "Parte da carteira coerente com o perfil: em ETF (Passive Index) ou em ativos que "
                  "pagaram dividendos nos últimos 12 meses (Income Focus)."),
    "winners": ("Grandes Vencedores", "Parte das posições (com pelo menos 0,5% do investido) que já valorizaram "
                "100% ou mais. 100 pontos a partir de 1 em cada 5."),
    "asymmetry": ("Assimetria", "Ganho médio das posições vencedoras a dividir pela perda média das perdedoras. "
                  "0 pontos a 0,5 ou menos, 100 a partir de 3."),
    "hit": ("Acerto", "Parte das posições que renderam mais do que o MSCI World no mesmo período em que as tiveste. "
            "0 pontos a 20%, 100 a partir de 70%."),
    "profit_factor": ("Fator de Lucro", "Ganhos das vendas a dividir pelas perdas das vendas, nos últimos 3 anos. "
                      "0 pontos a 0,8 ou menos, 100 a partir de 2."),
    "cut_losses": ("Corte das Perdas", "Tempo médio com as vendas que deram ganho a dividir pelo tempo com as que "
                   "deram perda (cortar as perdas depressa e deixar correr os ganhos). 0 pontos a 0,5, 100 a 2."),
    "concentration": ("Concentração", "Número efetivo de posições (1 / soma dos pesos ao quadrado): 100 pontos a "
                      "partir de 10 posições do mesmo peso, 0 com uma só."),
    "diversification": ("Diversificação", "Número efetivo de setores e de países (domicílio, pelo ISIN ou pela "
                        "bolsa): 0 pontos com 1, 100 a partir de 5."),
    "volatility": ("Volatilidade", "Volatilidade anual dos retornos mensais: 100 pontos até 10%, 0 a partir de 40%."),
    "costs": ("Custos", "Comissões pagas nos últimos 12 meses face ao valor médio da carteira: 100 pontos sem "
              "custos, 0 a partir de 1%. Não inclui o custo anual (TER) dos fundos."),
    "proximity": ("Proximidade ao Índice", "Correlação dos retornos mensais com o MSCI World: 100 pontos a partir "
                  "de 0,95, 0 até 0,3."),
}

PROFILES = {  # chave -> (nome, subtítulo, descrição, pesos do Investor Score)
    "passive": ("Passive Index", "Sigo o mercado a baixo custo",
                "Investes em ETFs amplos que replicam mercados inteiros. Não tentas bater o mercado: segui-lo barato "
                "é a estratégia. O sucesso mede-se em quão fielmente o teu dinheiro acompanha o índice e em quão "
                "disciplinado estás, sobretudo nas quedas.",
                {"fidelity": 32, "discipline": 23, "patience": 23, "risk": 14, "coherence": 10}),
    "concentrated": ("Concentrated Picker", "Convicção alta em poucas empresas",
                     "Investes a sério em poucas empresas que estudaste bem. Sabes que vai haver volatilidade, com "
                     "anos bons e maus, mas confias que algumas vão multiplicar muito. O sucesso mede-se em quanto o "
                     "teu dinheiro rendeu acima do mercado, em quantas das tuas escolhas multiplicaram de valor, em "
                     "quão bem deixaste correr as vencedoras e no que fazes quando o mercado cai.",
                     {"market": 30, "winners": 15, "asymmetry": 10, "risk": 15, "patience": 15, "discipline": 15}),
    "diversified": ("Diversified Active", "Muitas posições, ganhos distribuídos",
                    "Investes em muitas empresas (20 ou mais), à procura de ganhos acima do mercado espalhados por "
                    "muitas posições em vez de apostar tudo em poucas. O sucesso mede-se em quanto o teu dinheiro "
                    "rendeu acima do mercado, em quantas das tuas posições o bateram e no que fazes quando o "
                    "mercado cai.",
                    {"market": 30, "hit": 20, "risk": 20, "patience": 15, "discipline": 15}),
    "income": ("Income Focus", "Foco em rendimento estável",
               "Procuras dividendos estáveis e crescentes em vez de valorização do capital. O sucesso mede-se em "
               "quanto o teu dinheiro rendeu, com os dividendos, contra um índice mundial (o MSCI World) e em quão "
               "disciplinado estás nas quedas.",
               {"index": 36, "risk": 18, "discipline": 14, "patience": 23, "coherence": 10}),
    "growth": ("Growth/Tech", "Empresas de crescimento rápido",
               "Procuras empresas em rápido crescimento, muitas vezes em tecnologia ou a transformar um setor "
               "inteiro. Aceitas quedas profundas e volatilidade alta como o custo de aceder a retornos enormes a "
               "longo prazo. O sucesso mede-se em quanto o teu dinheiro rendeu acima do Nasdaq 100, em quantas das "
               "tuas escolhas multiplicaram de valor e no que fazes quando o mercado cai.",
               {"nasdaq": 30, "winners": 15, "asymmetry": 10, "risk": 15, "patience": 15, "discipline": 15}),
    "active": ("Active Trader", "Compro e vendo com frequência",
               "Compras e vendes com frequência, em dias ou semanas, à procura dos movimentos do preço. O sucesso "
               "mede-se em quanto o teu dinheiro rendeu acima do mesmo dinheiro no S&P 500 depois de todos os "
               "custos, em quanto ganhas por cada euro que perdes e em cortares as perdas mais depressa do que "
               "deixas correr os ganhos.",
               {"market": 30, "profit_factor": 20, "cut_losses": 20, "asymmetry": 15, "risk": 15}),
}
PORTFOLIO_WEIGHTS = {"concentration": 20, "diversification": 20, "volatility": 20, "costs": 20, "proximity": 20}


def _clamp(x):
    return max(0.0, min(100.0, x))


def _lin(x, lo, hi):
    """0 pontos em `lo`, 100 em `hi` (linear, limitado)."""
    return _clamp((x - lo) / (hi - lo) * 100)


def tier(score):
    if score is None:
        return None, "Sem dados"
    if score >= 80:
        return "A", "Excelente"
    if score >= 65:
        return "B", "Bom"
    if score >= 35:
        return "C", "A melhorar"
    return "D", "Em construção"


def _std(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


class Scorer:
    def __init__(self, p, countries=None, payers=None, risk_free=0.02, today=None):
        """`countries`: ativo -> país (domicílio); `payers`: ativos que pagaram dividendos nos últimos 12 meses."""
        self.p, self.rf = p, risk_free
        self.countries, self.payers = countries or {}, set(payers or ())
        s = p.series
        self.ok = bool(s.dates) and bool(p.open_positions)
        if not self.ok:
            return
        self.end = today or s.dates[-1]
        self.start = max(s.dates[0], self.end - timedelta(days=3 * 365))
        k0 = max(p._index_before(self.start) or 0, 0) if self.start > s.dates[0] else 0
        self.dates = s.dates[k0:]
        self.twr = s.twr[k0:]
        self.holdings = s.holdings[k0:]
        self.flows = s.flows[k0:]
        self.years = max((self.dates[-1] - self.dates[0]).days / 365.25, 1 / 12)
        self.monthly = [r for _, r in period_returns(self.dates, self.twr, "month")]
        total = sum(pos.value_eur for pos in p.open_positions)
        self.weights = {pos.asset.ticker: pos.value_eur / total for pos in p.open_positions} if total > EPS else {}

    # ------------------------------------------------------------ apoio
    def _bench(self, ticker):
        b = next((x for x in self.p.benchmarks if x.ticker == ticker), None)
        if b is None:
            return None
        closes = self.p._bench_closes(b, self.dates)
        if not closes or closes[0] is None or any(c is None for c in closes):
            return None
        return closes

    def _bench_monthly(self, ticker):
        closes = self._bench(ticker)
        if closes is None:
            return None
        return [r for _, r in period_returns(self.dates, [c / closes[0] for c in closes], "month")]

    def _annual(self, index_start, index_end):
        return (index_end / index_start) ** (1 / self.years) - 1 if index_start > EPS else 0.0

    def _excess(self, ticker):
        closes = self._bench(ticker)
        if closes is None or self.years < 0.25:
            return None, ""
        mine = self._annual(self.twr[0], self.twr[-1])
        theirs = self._annual(closes[0], closes[-1])
        diff = mine - theirs
        return _lin(diff, -0.10, 0.10), f"{mine * 100:+.1f}%/ano contra {theirs * 100:+.1f}%/ano ({diff * 100:+.1f} p.p.)"

    def _positions(self):
        """(posição, retorno total, investido) das posições com peso no que investiste."""
        rows = [(pos, pos.bought_eur) for pos in self.p.positions.values() if pos.bought_eur > EPS]
        invested = sum(b for _, b in rows)
        return [(pos, pos.roi_eur / b, b) for pos, b in rows if b >= 0.005 * invested]

    # ------------------------------------------------------------ métricas
    def m_market(self):
        return self._excess(SP500)

    def m_index(self):
        return self._excess(WORLD)

    def m_nasdaq(self):
        return self._excess(NASDAQ)

    def m_fidelity(self):
        bench = self._bench_monthly(WORLD)
        if not bench or len(self.monthly) < 6:
            return None, "precisa de 6 meses de histórico"
        n = min(len(bench), len(self.monthly))
        te = _std([a - b for a, b in zip(self.monthly[:n], bench[:n])]) * 12 ** 0.5
        return _clamp(100 * (1 - te / 0.15)), f"desvio de {te * 100:.1f}% ao ano face ao MSCI World"

    def m_discipline(self):
        txs = [t for t in self.p.transactions if self.dates[0] <= t.date <= self.dates[-1] and not t.opening]
        months = sorted({(d.year, d.month) for d in self.dates})
        if len(months) < 3:
            return None, "precisa de 3 meses de histórico"
        buys = {(t.date.year, t.date.month) for t in txs if t.type in ("BUY", "TRANSFER_IN")}
        regular = len(buys & set(months)) / len(months)
        bench = self._bench(WORLD)
        drops, held = 0, 0
        if bench:
            by_month = {}
            for d, c, h in zip(self.dates, bench, self.holdings):
                by_month.setdefault((d.year, d.month), []).append((c, h))
            keys = sorted(by_month)
            for prev, cur in zip(keys, keys[1:]):
                if by_month[cur][-1][0] / by_month[prev][-1][0] - 1 < -0.03:
                    drops += 1
                    base = by_month[prev][-1][1] or 1.0
                    sold = sum(t.quantity * t.price for t in txs if t.type == "SELL" and (t.date.year, t.date.month) == cur)
                    held += sold / base < 0.02
        calm = held / drops if drops else regular
        score = (regular * 100 + calm * 100) / 2
        text = f"compras em {regular * 100:.0f}% dos meses"
        if drops:
            text += f"; sem vender nas quedas em {held} de {drops} meses"
        return score, text

    def turnover(self):
        """Vendas por ano a dividir pelo valor médio da carteira (nos últimos 3 anos)."""
        sold = sum(s.proceeds_eur for s in self.p.sales if self.dates[0] <= s.date <= self.dates[-1])
        avg = sum(self.holdings) / len(self.holdings) if self.holdings else 0.0
        return sold / self.years / avg if avg > EPS else 0.0

    def m_patience(self):
        t = self.turnover()
        months = min(12 / t, 120) if t > EPS else 120
        score = 0.0 if months <= 1 else _clamp(100 * math.log(months) / math.log(36))
        return score, (f"vendes {t:.1f} vezes a carteira por ano: cada euro fica investido cerca de "
                       f"{months:.0f} meses" if t > EPS else "sem vendas nos últimos 3 anos")

    def m_risk(self):
        if len(self.monthly) < 6:
            return None, "precisa de 6 meses de histórico"
        vol = _std(self.monthly) * 12 ** 0.5
        ann = self._annual(self.twr[0], self.twr[-1])
        sharpe = (ann - self.rf) / vol if vol > EPS else 0.0
        return _lin(sharpe, 0.0, 1.5), f"Sharpe {sharpe:.2f}"

    def m_coherence(self, profile):
        if profile == "passive":
            share = sum(w for pos in self.p.open_positions if pos.asset.kind == "etf"
                        for w in [self.weights.get(pos.asset.ticker, 0)])
            return share * 100, f"{share * 100:.0f}% da carteira em ETF"
        if profile == "income":
            share = sum(self.weights.get(t, 0) for t in self.payers)
            return share * 100, f"{share * 100:.0f}% da carteira em ativos que pagam dividendos"
        return None, ""

    def m_winners(self):
        rows = self._positions()
        if len(rows) < 3:
            return None, "precisa de 3 posições"
        big = sum(1 for _, r, _ in rows if r >= 1.0)
        return _lin(big / len(rows), 0, 0.2), f"{big} de {len(rows)} posições valorizaram 100% ou mais"

    def m_asymmetry(self):
        rows = self._positions()
        wins = [r for _, r, _ in rows if r > 0]
        losses = [-r for _, r, _ in rows if r < 0]
        if not wins or not losses:
            return (None, "precisa de posições a ganhar e a perder") if not wins or len(rows) < 3 else \
                (100.0, "sem posições a perder")
        ratio = (sum(wins) / len(wins)) / (sum(losses) / len(losses))
        return _lin(ratio, 0.5, 3.0), f"ganho médio {ratio:.1f}× a perda média"

    def m_hit(self):
        b = next((x for x in self.p.benchmarks if x.ticker == WORLD), None)
        rows = self._positions()
        if b is None or len(rows) < 3:
            return None, "precisa de 3 posições e do MSCI World"
        beat = total = 0
        for pos, r, _ in rows:
            start = pos.first_date
            end = self.end if pos.is_open else (pos.last_date or self.end)
            c0, c1 = self.p._bench_closes(b, [start, end])
            if not c0 or not c1:
                continue
            total += 1
            beat += r > c1 / c0 - 1
        if not total:
            return None, "sem cotações do MSCI World"
        return _lin(beat / total, 0.2, 0.7), f"{beat} de {total} posições bateram o MSCI World"

    def _trades(self):
        return [s for s in self.p.sales if self.dates[0] <= s.date <= self.dates[-1]]

    def m_profit_factor(self):
        sales = self._trades()
        gains = sum(s.gain_eur for s in sales if s.gain_eur > 0)
        losses = -sum(s.gain_eur for s in sales if s.gain_eur < 0)
        if not sales:
            return None, "sem vendas nos últimos 3 anos"
        if losses <= EPS:
            return 100.0, "sem vendas com perda"
        pf = gains / losses
        return _lin(pf, 0.8, 2.0), f"{pf:.2f} € ganhos por cada 1 € perdido"

    def m_cut_losses(self):
        sales = [s for s in self._trades() if s.acquired]
        win = [(s.date - s.acquired).days for s in sales if s.gain_eur > 0]
        lose = [(s.date - s.acquired).days for s in sales if s.gain_eur < 0]
        if not win or not lose:
            return None, "precisa de vendas com ganho e com perda"
        w, lo = sum(win) / len(win), max(sum(lose) / len(lose), 1)
        return _lin(w / lo, 0.5, 2.0), f"ganhos mantidos {w:.0f} dias, perdas {lo:.0f} dias"

    def m_concentration(self):
        hhi = sum(w * w for w in self.weights.values())
        n = 1 / hhi if hhi > EPS else 0
        top = max(self.weights.items(), key=lambda kv: kv[1]) if self.weights else None
        text = f"{n:.1f} posições efetivas" + (f"; a maior ({top[0]}) pesa {top[1] * 100:.0f}%" if top else "")
        return _lin(n, 1, 10), text

    def m_diversification(self):
        def eff(groups):
            tot = sum(groups.values())
            return 1 / sum((v / tot) ** 2 for v in groups.values()) if tot > EPS else 0
        sectors, countries = {}, {}
        for pos in self.p.open_positions:
            w = self.weights.get(pos.asset.ticker, 0)
            sec = "ETF" if pos.asset.kind == "etf" else (pos.asset.sector or "Outros")
            sectors[sec] = sectors.get(sec, 0) + w
            ctry = self.countries.get(pos.asset.ticker) or "?"
            countries[ctry] = countries.get(ctry, 0) + w
        s, c = eff(sectors), eff(countries)
        return (_lin(s, 1, 5) + _lin(c, 1, 5)) / 2, f"{s:.1f} setores e {c:.1f} países efetivos"

    def m_volatility(self):
        if len(self.monthly) < 6:
            return None, "precisa de 6 meses de histórico"
        vol = _std(self.monthly) * 12 ** 0.5
        return _lin(vol, 0.40, 0.10), f"{vol * 100:.1f}% ao ano"

    def m_costs(self):
        since = self.end - timedelta(days=365)
        fees = sum((t.fees or 0.0) / self.p.book.fx(t.currency, t.date) for t in self.p.transactions
                   if t.date > since and t.type in ("BUY", "SELL"))
        fees += sum(self.p.book.to_eur(t.amount, t.currency, t.date) for t in self.p.transactions
                    if t.date > since and t.type == "FEE")
        recent = [h for d, h in zip(self.dates, self.holdings) if d > since] or self.holdings
        avg = sum(recent) / len(recent) if recent else 0.0
        ratio = fees / avg if avg > EPS else 0.0
        return _clamp(100 * (1 - ratio / 0.01)), f"{fees:.2f} € em comissões ({ratio * 100:.2f}% da carteira)"

    def m_proximity(self):
        bench = self._bench_monthly(WORLD)
        if not bench or len(self.monthly) < 6:
            return None, "precisa de 6 meses de histórico"
        n = min(len(bench), len(self.monthly))
        a, b = self.monthly[:n], bench[:n]
        ma, mb = sum(a) / n, sum(b) / n
        cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
        corr = cov / den if den > EPS else 0.0
        return _lin(corr, 0.3, 0.95), f"correlação {corr:.2f} com o MSCI World"

    # ------------------------------------------------------------ notas
    def metric(self, key, profile=None):
        fn = getattr(self, f"m_{key}")
        value, text = fn(profile) if key == "coherence" else fn()
        name, help_ = METRICS[key]
        return {"key": key, "name": name, "help": help_, "score": None if value is None else round(value),
                "detail": text}

    def _combine(self, weights, profile=None):
        rows = [dict(self.metric(k, profile), weight=w) for k, w in weights.items()]
        known = [r for r in rows if r["score"] is not None]
        total_w = sum(r["weight"] for r in known)
        score = round(sum(r["score"] * r["weight"] for r in known) / total_w) if total_w else None
        letter, label = tier(score)
        return {"score": score, "tier": letter, "label": label, "metrics": rows}

    def investor(self, profile):
        return self._combine(PROFILES[profile][3], profile)

    def portfolio(self):
        return self._combine(PORTFOLIO_WEIGHTS)

    def suggest(self):
        """(perfil sugerido, porquê) a partir do comportamento e da composição da carteira."""
        t = self.turnover()
        if t >= 1.0:
            months = 12 / t
            return "active", (f"nos últimos três anos, vendes em média {t:.1f} vezes a carteira por ano: a este "
                              f"ritmo, cada euro fica investido cerca de {months:.0f} meses.")
        etf = sum(w for pos in self.p.open_positions if pos.asset.kind == "etf"
                  for w in [self.weights.get(pos.asset.ticker, 0)])
        if etf >= 0.7:
            return "passive", f"{etf * 100:.0f}% da tua carteira está em ETF."
        income = sum(self.weights.get(t, 0) for t in self.payers)
        if income >= 0.5:
            return "income", f"{income * 100:.0f}% da tua carteira está em ativos que pagam dividendos."
        growth = sum(self.weights.get(pos.asset.ticker, 0) for pos in self.p.open_positions
                     if (pos.asset.sector or "").lower() in GROWTH_SECTORS)
        if growth >= 0.5:
            return "growth", f"{growth * 100:.0f}% da tua carteira está em tecnologia e crescimento."
        stocks = sum(1 for pos in self.p.open_positions if pos.asset.kind != "etf")
        if stocks >= 20:
            return "diversified", f"tens {stocks} ações diferentes em carteira."
        return "concentrated", f"tens {stocks} ações em carteira, com pesos concentrados."


def profile_list():
    return [{"key": k, "name": v[0], "subtitle": v[1], "description": v[2],
             "weights": [{"name": METRICS[m][0], "weight": w} for m, w in v[3].items()]}
            for k, v in PROFILES.items()]

