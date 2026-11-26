"""Prepara os dados das capturas do README numa pasta própria (nunca nos teus dados).

    python docs/screenshots/gerar/preparar.py <pasta> [passo]

Passos (sem passo, correm os quatro primeiros por ordem):
  demo    os dados de demonstração
  triage  as pesquisas da triagem ao Yahoo Finance (uns minutos)
  enrich  os dados de cada ação da triagem (até ENRICH_SECONDS segundos, 900 por omissão; volta a correr para
          continuar de onde ficou)
  lists   as listas de acompanhamento com empresas reais («A minha lista» e «Dividendos»)
  extras  notícias e análise com IA de exemplo (fictícias, como as empresas) e a ficha da Carteira (DEMO-NVTX → NVDA)
  fresh   marca as notícias como pedidas agora (para a página não as pedir à rede); corre antes de cada série
"""
import json
import os
import sys
import time

DATA = sys.argv[1]
os.makedirs(DATA, exist_ok=True)
os.environ["PORTFOLIO_DATA_DIR"] = DATA
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from portfolio_investimentos import create_app, api  # noqa: E402
from portfolio_investimentos.models import Setting, WatchItem, WatchList, db  # noqa: E402
from portfolio_investimentos.services import demo, triage, tracking  # noqa: E402

app = create_app({})
step = sys.argv[2] if len(sys.argv) > 2 else "all"
with app.test_request_context():
    if step in ("all", "demo"):
        demo.create_demo()
        print("demo ok", flush=True)
    if step in ("all", "triage"):
        while True:
            r = triage.refresh_step(budget=30)
            print("refresh", r, flush=True)
            if r["done"]:
                break
        u = triage.universe()
        print("universo", len(u["rows"]), u.get("errors"), flush=True)
    if step in ("all", "enrich"):
        end = time.time() + float(os.environ.get("ENRICH_SECONDS", "900"))
        while time.time() < end:
            r = triage.enrich_step(budget=30)
            print("enrich", r, flush=True)
            if r["done"]:
                break
            if r.get("wait"):
                time.sleep(r["wait"])
    if step in ("all", "lists"):
        lists = tracking.watch_lists()
        main = lists[0]
        div = WatchList.query.filter_by(title="Dividendos").first() or db.session.get(WatchList, api.create_watch_list("Dividendos")["id"])
        plan = [  # (símbolo, nome, moeda, lista, coluna, prioridade, notas)
            ("UCG.MI", "UniCredit S.p.A.", "EUR", main, 0, "alta", None),
            ("BBVA.MC", "Banco Bilbao Vizcaya Argentaria, S.A.", "EUR", main, 0, "media", None),
            ("2330.TW", "Taiwan Semiconductor Manufacturing Company Limited", "TWD", main, 1, "media", None),
            ("SHEL", "Shell plc", "USD", main, 1, "media", None),
            ("005930.KS", "Samsung Electronics Co., Ltd.", "KRW", main, 2, "alta",
             "Tese: a memória para IA sustenta as margens; o risco é o ciclo dos chips."),
            ("NVDA", "NVIDIA Corporation", "USD", main, 3, "baixa", "Caro para o meu método; volto se o P/L descer."),
            ("KO", "The Coca-Cola Company", "USD", div, 0, "media", None),
            ("ALV.DE", "Allianz SE", "EUR", div, 0, "alta", None),
        ]
        for sym, name, cur, wl, col, prio, notes in plan:
            tab = triage.table() or {"rows": []}
            me = next((x for x in tab["rows"] if x["t"] == sym), None)
            lens = next((k for k, s in (me or {}).get("st", {}).items() if s == "entra" and k != "varias"), "buffett")
            try:
                api.add_watch(sym, currency=cur, instrument_name=name, method=lens, list_id=wl.id)
            except Exception as e:
                print("add", sym, e, flush=True)
            w = WatchItem.query.filter_by(instrument=sym, list_id=wl.id).first()
            st = tracking.states(wl.id)[col]
            api.update_watch(w.id, priority=prio, notes=notes, state_id=st.id)
            try:
                api.refresh_tracking(sym)
            except Exception as e:
                print("refresh_tracking", sym, e, flush=True)
            print("lista", sym, "ok", flush=True)
        for w in WatchItem.query.filter(WatchItem.instrument.like("DEMO-%")).all():  # as fictícias ficam no fim
            api.update_watch(w.id, state_id=tracking.states(w.list_id)[-1].id)
print("fim", flush=True)

# ---- extras das capturas: notícias de exemplo, análise com IA de exemplo, símbolo para a ficha na Carteira
if step == "extras":
    from datetime import datetime, timedelta
    from portfolio_investimentos.models import Instrument, NewsItem
    from portfolio_investimentos.services import ai, data as data_svc
    with app.test_request_context():
        now = datetime.now().replace(second=0, microsecond=0)
        NewsItem.query.filter(NewsItem.url.like("https://exemplo.pt/%")).delete(synchronize_session=False)
        sample = [
            ("DEMO-NVTX", "Nova Tech supera estimativas e revê em alta as vendas do ano", "Receitas do trimestre 12% acima do esperado, puxadas pelos centros de dados.", "Jornal de Negócios", 3, "google"),
            ("DEMO-NVTX", "Analistas sobem preço-alvo da Nova Tech depois dos resultados", "Três casas de investimento reviram em alta as estimativas para 2027.", "Reuters", 20, "yahoo"),
            ("DEMO-SOLP", "Sol Pharma recebe aprovação europeia para novo tratamento", "A Agência Europeia do Medicamento aprovou o tratamento para a diabetes tipo 2.", "Expresso", 28, "google"),
            ("DEMO-ATLE", "Atlântico Energia sente a descida do petróleo nas margens", "A empresa avisou que a margem de refinação do trimestre vai ficar abaixo da do ano passado.", "Eco", 6, "google"),
            ("DEMO-ATLE", "Petróleo cai para mínimos de seis meses", "O Brent desceu abaixo dos 70 dólares com a subida dos stocks nos EUA.", "Bloomberg", 30, "yahoo"),
            ("DEMO-LUSB", "Lusa Bank mantém margem financeira, mas o crédito malparado sobe", "O rácio de crédito em incumprimento passou de 2,1% para 2,4%.", "Público", 10, "google"),
            ("DEMO-AUTO", "Motores do Norte adia nova fábrica de baterias", "A decisão de investimento passa para 2027, à espera de mais procura de carros elétricos.", "Observador", 50, "google"),
            ("", "BCE mantém juros e admite descida no início do ano", "A presidente do BCE disse que a inflação está perto dos 2%.", "Reuters", 4, "yahoo"),
        ]
        for i, (t, h, s, src, hours, prov) in enumerate(sample):
            db.session.add(NewsItem(ticker=t, headline=h, summary=s, source=src, url=f"https://exemplo.pt/noticia-{i}",
                                    published=now - timedelta(hours=hours), provider=prov))
        db.session.commit()
        Setting.set("ai_provider", "gemini")
        Setting.set("ai_fallback", "groq")
        Setting.set("ai_key_gemini", "AIzaEXEMPLO000000000")
        rows = ai.news_for([i.ticker for i in Instrument.query.filter(Instrument.ticker.like("DEMO-%"))])
        link = {n.headline: {"titulo": n.headline, "url": n.url} for n in rows}
        Setting.set("ai_analysis:carteira", json.dumps({"key": ai._key(rows), "at": now.isoformat(timespec="minutes"),
            "scope": "carteira", "provider": "gemini", "provider_name": "Google Gemini", "model": "gemini-flash-latest",
            "count": len(rows), "result": {
            "resumo": "Semana positiva para a tecnologia e a saúde: a Nova Tech bateu as estimativas e a Sol Pharma teve uma aprovação importante. Do outro lado, a descida do petróleo pesa na Atlântico Energia e o Lusa Bank mostra os primeiros sinais de crédito malparado a subir.",
            "ativos": [
                {"ticker": "DEMO-NVTX", "tom": "positivo", "conclusao": "Resultados acima do esperado e estimativas revistas em alta. O crescimento continua a vir dos centros de dados.", "riscos": ["Avaliação exigente depois da subida"], "a_verificar": ["Margem bruta no próximo trimestre"], "noticias": [link[h] for h in ("Nova Tech supera estimativas e revê em alta as vendas do ano", "Analistas sobem preço-alvo da Nova Tech depois dos resultados")]},
                {"ticker": "DEMO-SOLP", "tom": "positivo", "conclusao": "A aprovação europeia abre um mercado novo; o efeito nas vendas só deve aparecer em 2027.", "riscos": ["Concorrência de genéricos"], "a_verificar": ["Preço acordado com os sistemas de saúde"], "noticias": [link["Sol Pharma recebe aprovação europeia para novo tratamento"]]},
                {"ticker": "DEMO-ATLE", "tom": "negativo", "conclusao": "A descida do petróleo reduz a margem de refinação; a empresa já avisou que o trimestre vai ser mais fraco.", "riscos": ["Brent abaixo dos 70 dólares durante mais tempo"], "a_verificar": ["Se o dividendo se mantém"], "noticias": [link[h] for h in ("Atlântico Energia sente a descida do petróleo nas margens", "Petróleo cai para mínimos de seis meses")]},
                {"ticker": "DEMO-LUSB", "tom": "misto", "conclusao": "A margem financeira aguenta-se, mas o crédito malparado subiu pela primeira vez em dois anos.", "riscos": ["Descida dos juros pelo BCE"], "a_verificar": ["Evolução do crédito em incumprimento"], "noticias": [link["Lusa Bank mantém margem financeira, mas o crédito malparado sobe"]]},
                {"ticker": "DEMO-AUTO", "tom": "neutro", "conclusao": "O adiamento da fábrica poupa dinheiro agora, mas atrasa a aposta nos elétricos.", "riscos": [], "a_verificar": ["Procura de carros elétricos na Europa"], "noticias": [link["Motores do Norte adia nova fábrica de baterias"]]}]}}))
        nvtx = db.session.get(Instrument, "DEMO-NVTX")
        nvtx.data_symbol = "NVDA"
        db.session.commit()
        data_svc.invalidate()
    print("extras ok", flush=True)

if step == "fresh":  # antes de cada série de capturas: as notícias contam como pedidas agora (sem pedidos à rede)
    from datetime import datetime
    from portfolio_investimentos.models import Instrument, WatchItem
    with app.test_request_context():
        now = datetime.now().isoformat(timespec="seconds")
        tickers = [""] + [i.ticker for i in Instrument.query] + [w.instrument for w in WatchItem.query]
        Setting.set("news_fetched", json.dumps({f"{p}:{t}": now for p in ("finnhub", "google", "yahoo", "marketaux") for t in tickers}))
    print("fresh ok", flush=True)
