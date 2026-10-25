"""Testes da aplicação Flask (base de dados SQLite temporária)."""
import io
import re
from datetime import date

import pytest

from portfolio_investimentos import create_app
from portfolio_investimentos.models import ImportBatch, Transaction, db

PAGES = ["/", "/carteira", "/desempenho", "/desempenho?periodo=1A&bench=%5EGSPC", "/dividendos", "/fiscal",
         "/radar", "/noticias", "/importar", "/transacoes", "/transacoes?tipo=BUY", "/definicoes"]

T212 = """Action,Time,ISIN,Ticker,Name,No. of shares,Price / share,Currency (Price / share),Exchange rate,Total,Currency (Total),Withholding tax,Currency (Withholding tax),ID
Deposit,2024-01-02 10:00:00,,,,,,,,1000.00,EUR,,,DEP1
Market buy,2024-01-03 15:30:00,US0378331005,AAPL,Apple,2,185.00,USD,1.0950,338.43,EUR,,,EOF1
Dividend (Ordinary),2024-02-15 12:00:00,US0378331005,AAPL,Apple,2,0.24,USD,1.08,0.38,EUR,0.07,USD,
Interest on cash,2024-03-01 00:00:00,,,,,,,,1.25,EUR,,,INT1
"""


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    app = create_app({"TESTING": True})
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def csrf(client):
    html = client.get("/").get_data(as_text=True)
    return re.search(r'csrf_token = "([0-9a-f]+)"', html).group(1)


def post(client, action, token, **data):
    return client.post(f"/api/{action}", data=data, headers={"X-CSRF-Token": token})


def test_empty_pages_render(client):
    for url in PAGES:
        assert client.get(url).status_code == 200, url


def test_demo_pages_render(client):
    token = csrf(client)
    assert post(client, "load_demo", token).status_code == 200
    for url in PAGES:
        resp = client.get(url)
        assert resp.status_code == 200, url
        assert "Traceback" not in resp.get_data(as_text=True)


def test_csrf_required(client):
    assert client.post("/api/hide_banner").status_code == 403
    assert post(client, "hide_banner", "errado").status_code == 403


def test_import_deduplicates(app, client):
    token = csrf(client)
    for expected in ((4, 0), (0, 4)):
        resp = client.post("/api/upload_statement", headers={"X-CSRF-Token": token},
                           data={"broker_key": "trading212", "file": (io.BytesIO(T212.encode()), "t212.csv")},
                           content_type="multipart/form-data")
        assert resp.status_code == 200, resp.get_data(as_text=True)
        r = resp.get_json()["message"][0]
        assert (r["imported"], r["skipped"]) == expected
    with app.app_context():
        assert Transaction.query.count() == 4
        assert ImportBatch.query.count() == 2
        div = Transaction.query.filter_by(type="DIVIDEND").one()
        assert (div.currency, div.tax) == ("USD", pytest.approx(0.07))


def test_manual_transaction_and_validation(app, client):
    token = csrf(client)
    ok = post(client, "add_transaction", token, date="2024-05-02", type="BUY", instrument="vwce.de",
              quantity="3", price="110,5", fees="1", currency="eur")
    assert ok.status_code == 200
    bad = post(client, "add_transaction", token, date="2024-05-02", type="BUY", instrument="X", quantity="0")
    assert bad.status_code == 400 and "quantidade" in bad.get_json()["error"]
    with app.app_context():
        t = db.session.get(Transaction, ok.get_json()["message"])
        assert (t.instrument, t.price, t.currency) == ("VWCE.DE", 110.5, "EUR")


def test_backup_and_reset(app, client):
    token = csrf(client)
    post(client, "load_demo", token)
    backup = client.get("/api/backup")
    assert backup.status_code == 200 and backup.data[:15] == b"SQLite format 3"
    assert post(client, "reset_data", token, confirm="não").status_code == 400
    assert post(client, "reset_data", token, confirm="APAGAR").status_code == 200
    with app.app_context():
        assert Transaction.query.count() == 0


T212_UTC = """Action,Time (UTC),ISIN,Ticker,Name,Notes,ID,No. of shares,Price / share,Currency (Price / share),Exchange rate,Result,Currency (Result),Total,Currency (Total),Withholding tax,Currency (Withholding tax),Stamp duty reserve tax,Currency (Stamp duty reserve tax),Currency conversion from amount,Currency (Currency conversion from amount),Currency conversion to amount,Currency (Currency conversion to amount),Currency conversion fee,Currency (Currency conversion fee),Merchant name
Deposit,2026-01-02 08:00:00+00:00,,,,Bank Transfer,D1,,,,,,,2000.00,EUR,,,,,,,,,,,
Market buy,2026-01-05 15:00:00+00:00,GB00B63QSB39,GRG,Greggs,,B1,10.0000000000,1500.0000000000,GBX,87.00000000,,,174.91,EUR,,,1.92,EUR,,,,,0.58,EUR,
Market sell,2026-01-06 15:00:00+00:00,US00724F1012,ADBE,Adobe,,S1,3.0000000000,250.0000000000,USD,1.16000000,-40.00,EUR,645.77,EUR,,,,,,,,,0.78,EUR,
Market sell,2026-01-06 15:00:01+00:00,US00724F1012,ADBE,Adobe,,S2,0.0001000000,250.0000000000,USD,1.00000000,0.00,EUR,0.00,EUR,,,,,,,,,,,
Dividend (Dividend),2026-01-07 15:00:00+00:00,US71654V1017,PBR/A,Petrobras,,,40.0000000000,0.2000000,USD,0.85000000,,,6.80,EUR,1.20,USD,,,,,,,,,
Transfer out,2026-01-08 01:00:00+00:00,IE00BK5BQT80,VWCE,Vanguard FTSE All-World (Acc),,T1,3.0000000000,140.0000000000,EUR,1.00000000,0.00,EUR,420.00,EUR,,,,,,,,,,,
Card debit,2026-01-09 19:00:00+00:00,,,,,C1,,,,,,,-100.00,EUR,,,,,,,,,,,Supermercado
Spin off,2026-01-10 09:00:00+00:00,US9256991067,VSNT,Versant Media Group,,SP1,0.5000000000,0E-10,USD,,,,0.00,EUR,,,,,,,,,,,
Currency conversion,2026-01-11 23:00:00+00:00,,,,500.00 EUR -> 580.00 USD,CC1,,,,,,,-0.90,USD,,,,,500.00,EUR,580.00,USD,-0.90,USD,
ADR Fee,2026-01-12 13:00:00+00:00,US31810T1016,FINV,FinVolution,,,300.00000000,-0.02000000,USD,0.86000000,,,-6.00,USD,,,,,,,,,,,
Interest on cash,2026-01-13 02:00:00+00:00,,,,Interest on cash,I1,,,,,,,0.18,EUR,,,,,,,,,,,
"""


def test_import_trading212_full_export(app, client):
    from portfolio_investimentos.models import FxRate, Instrument, Price
    from portfolio_investimentos.services import data

    token = csrf(client)
    resp = client.post("/api/upload_statement", headers={"X-CSRF-Token": token},
                       data={"broker_key": "trading212", "file": (io.BytesIO(T212_UTC.encode()), "t212.csv")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["message"][0]["imported"] == 11
    with app.test_request_context():
        types = sorted(t.type for t in Transaction.query)
        assert types.count("TRANSFER_OUT") == 1 and types.count("FEE") == 2 and types.count("WITHDRAWAL") == 1
        grg = db.session.get(Instrument, "GRG")
        assert grg.currency == "GBP" and grg.data_symbol == "GRG.L"
        buy = Transaction.query.filter_by(instrument="GRG").one()
        assert buy.price == pytest.approx(15.00)
        assert buy.fees == pytest.approx((1.92 + 0.58) * 0.87)
        div = Transaction.query.filter_by(type="DIVIDEND").one()
        assert div.currency == "USD" and div.tax == pytest.approx(1.20)
        assert div.amount == pytest.approx(8.0 + 1.20)
        # a venda residual (total 0, taxa 1.0) não pode estragar o câmbio do dia
        fx = FxRate.query.filter_by(currency="USD").all()
        assert all(abs(f.rate - 1.0) > 0.01 for f in fx)
        p = data.load_portfolio(None)
        # o preço da compra serve de cotação enquanto não há fechos reais
        assert p.book.price("GRG", date(2026, 1, 5)) == pytest.approx(15.00)
        assert {o.asset.ticker for o in p.opening} == {"ADBE", "VWCE"}
        assert p.realized == pytest.approx(-40.0, abs=0.01)


def _xtb_workbook():
    """XLSX sintético com a estrutura do extrato da XTB."""
    from datetime import datetime as dt

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Closed Positions"
    for row in (["Account number", "123"], ["Closed Positions", ""],
                ["Instrument", "Ticker", "Category", "Type", "Volume", "Open Price", "Open Time (UTC)", "Close Price",
                 "Close Time (UTC)", "Product", "Profit/Loss", "Position ID"],
                ["Prime Global", "F50A.DE", "ETF", "BUY", 10.0, 30.0, dt(2026, 4, 22, 11, 0), 30.0,
                 dt(2026, 4, 23, 13, 0), "My Trades", 0.0, 900.0],                       # fecho técnico
                ["Prime Global", "F50A.DE", "ETF", "BUY", 10.0, 30.0, dt(2026, 4, 23, 13, 1), 36.0,
                 dt(2026, 5, 4, 8, 3, 24), "My Trades", 60.0, 901.0],                   # vendido com dinheiro
                ["Profit/loss", 60.0]):
        ws.append(row)
    ops = wb.create_sheet("Cash Operations")
    for row in (["Account number", "123"], ["Cash Operations", ""],
                ["Type", "Instrument", "Ticker", "Category", "Time", "Amount", "ID", "Comment", "Product", "Position ID"],
                ["Deposit", "", "", "", dt(2026, 1, 2, 7), 1000.0, "1", "Deposit", "My Trades", ""],
                ["Stock purchase", "Core S&P 500", "SXR8.DE", "ETF", dt(2026, 1, 3, 9), -480.0, "2",
                 "OPEN BUY 1 @ 480.00", "My Trades", "100"],
                ["Stock purchase", "Ultrashort Bond", "ERNX.DE", "ETF", dt(2026, 1, 5, 5), -55.0, "3",
                 "OPEN BUY ERNX.DE 10/10.0000 @ 5.5000", "Investment Plans", "101"],
                ["Subaccount transfer", "", "", "", dt(2026, 1, 6, 5), -50.0, "4", "Transfer", "My Trades", ""],
                ["Subaccount transfer", "", "", "", dt(2026, 1, 6, 5), 50.0, "5", "Transfer", "Investment Plans", ""],
                ["Stock sell", "Prime Global", "F50A.DE", "ETF", dt(2026, 5, 4, 8, 3, 25), 360.0, "6",
                 "CLOSE BUY 10/10 @ 36.000", "My Trades", "901"],
                ["Free funds interest", "", "", "", dt(2026, 6, 1, 7), 0.20, "7", "Free-funds Interest", "My Trades", ""],
                ["Free funds interest tax", "", "", "", dt(2026, 6, 1, 7), -0.06, "8", "Interest Tax", "My Trades", ""],
                ["Close trade", "", "ETHEREUM", "CRT", dt(2026, 6, 2, 7), -0.38, "9", "Profit of position", "My Trades", "7"],
                ["Total", 775.30]):
        ops.append(row)
    op = wb.create_sheet("Open Positions")
    for row in (["Account number", "123"], ["Open Positions", ""], ["Data as of report generated", dt(2026, 10, 24, 15)],
                ["Product", "Metric", "Amount", "Currency"], ["My Trades", "Open position value", 590.0, "EUR"],
                ["Product", "Instrument/Position", "Ticker", "Category", "Type", "Volume", "Value", "Current price",
                 "Open price", "Open time (UTC)"],
                ["My Trades", "100", "SXR8.DE", "", "BUY", 1.0, 520.0, 520.0, 480.0, dt(2026, 1, 3, 9)],
                ["Investment Plan", "101", "ERNX.DE", "", "BUY", 10.0, 56.0, 5.60, 5.50, dt(2026, 1, 5, 5)]):
        op.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_import_xtb_xlsx(app, client):
    from portfolio_investimentos.models import Instrument, Price
    from portfolio_investimentos.services import data

    token = csrf(client)
    resp = client.post("/api/upload_statement", headers={"X-CSRF-Token": token},
                       data={"broker_key": "xtb", "file": (io.BytesIO(_xtb_workbook()), "xtb.xlsx")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    r = resp.get_json()["message"][0]
    assert r["ignored"] == {"Transferência entre subcontas": 2}
    with app.test_request_context():
        assert db.session.get(Instrument, "SXR8.DE").data_symbol == "SXR8.DE"
        assert db.session.get(Instrument, "F50A.DE").kind == "etf"
        transfer = Transaction.query.filter_by(type="TRANSFER_IN").one()  # só a parte vendida com dinheiro
        assert (transfer.quantity, transfer.price) == (10.0, 30.0)
        # preço atual das posições abertas usado como cotação na data do relatório
        assert Price.query.filter_by(instrument="SXR8.DE").order_by(Price.date.desc()).first().close == 520.0
        p = data.load_portfolio(None)
        assert p.warnings == []
        assert p.realized == pytest.approx(60.0)
        assert p.holdings_value == pytest.approx(520.0 + 56.0)
        # caixa: 1000 - 480 - 55 + 360 + 0.20 - 0.06 - 0.38
        assert p.cash == pytest.approx(824.76)


TR_CSV = '''"datetime","date","account_type","category","type","asset_class","name","symbol","shares","price","amount","fee","tax","currency","original_amount","original_currency","fx_rate","description","transaction_id","counterparty_name","counterparty_iban","payment_reference","mcc_code"
"2026-09-20T10:00:00Z","2026-09-20","DEFAULT","CASH","TRANSFER_INSTANT_INBOUND","","Eu","","","","1500.000000","","","EUR","","","","Incoming transfer","t1","","","",""
"2026-09-23T07:28:00Z","2026-09-23","DEFAULT","TRADING","BUY","STOCK","FinVolution (ADR)","US31810T1016","80.0000000000","3.1000000000","-248.00","-1.00","-0.04","EUR","","","","Buy trade","t2","","","",""
"2026-09-24T15:09:00Z","2026-09-24","DEFAULT","TRADING","BUY","STOCK","LVMH","FR0000121014","1.0000000000","398.8000000000","-398.80","-1.00","-1.64","EUR","","","","Buy trade","t3","","","",""
"2026-09-25T15:09:00Z","2026-09-25","DEFAULT","TRADING","SELL","STOCK","LVMH","FR0000121014","-1.0000000000","400.0000000000","400.00","-1.00","-0.04","EUR","","","","Sell trade","t4","","","",""
"2026-10-01T08:00:00Z","2026-10-01","DEFAULT","CASH","INTEREST_PAYMENT","","","","","","1.120000","","","EUR","","","","Interest payment","t5","","","",""
"2026-10-02T08:00:00Z","2026-10-02","DEFAULT","TRADING","BUY","FUND","FTSE All-World","IE000716YHJ7","5.0000000000","9.0000000000","-45.00","","","EUR","","","","Savings plan execution","t6","","","",""
'''


def _upload(client, token, key, name, content):
    return client.post("/api/upload_statement", headers={"X-CSRF-Token": token},
                       data={"broker_key": key, "file": (io.BytesIO(content), name)},
                       content_type="multipart/form-data")


@pytest.mark.parametrize("trade_republic_first", [True, False])
def test_trade_republic_and_isin_unification(app, client, trade_republic_first):
    from portfolio_investimentos.models import Instrument
    from portfolio_investimentos.services import data

    t212 = ("Action,Time (UTC),ISIN,Ticker,Name,ID,No. of shares,Price / share,Currency (Price / share),"
            "Exchange rate,Total,Currency (Total)\n"
            "Deposit,2026-09-01 08:00:00+00:00,,,,D1,,,,,500.00,EUR\n"
            "Market buy,2026-09-18 15:00:00+00:00,US31810T1016,FINV,FinVolution,B1,50,3.50,USD,1.17,149.57,EUR\n")
    token = csrf(client)
    jobs = [("traderepublic", "tr.csv", TR_CSV.encode()), ("trading212", "t212.csv", t212.encode())]
    for key, name, content in (jobs if trade_republic_first else jobs[::-1]):
        assert _upload(client, token, key, name, content).status_code == 200
    with app.test_request_context():
        # o mesmo título nas duas corretoras é um só ativo, com o ticker real da Trading 212
        assert Transaction.query.filter_by(instrument="FINV").count() == 2
        assert db.session.get(Instrument, "US31810T1016") is None
        p = data.load_portfolio(None)
        finv = p.positions["FINV"]
        assert finv.qty == pytest.approx(130)
        # cotação mais recente = compra na Trade Republic (3,10 EUR), convertida para USD
        assert finv.value_eur == pytest.approx(130 * 3.10, rel=0.01)
        assert p.realized == pytest.approx((400 - 1.04) - (398.8 + 2.64))
        assert p.interest_eur == pytest.approx(1.12)


class _Hist:
    """Imitação mínima de um DataFrame do yfinance (só o que a atualização usa)."""

    def __init__(self, rows):
        from datetime import datetime
        self.rows = [(datetime.combine(d, datetime.min.time()), {"Close": c}) for d, c in rows]
        self.empty = not rows

    def iterrows(self):
        return iter(self.rows)


class _FakeYf:
    QUOTES = {  # símbolo -> (moeda, fecho)
        "ADBE": ("USD", 263.82), "ADB.DE": ("EUR", 227.10),  # a cotação dos EUA aparece primeiro na pesquisa
        "NVO": ("USD", 39.05), "NOVO-B.CO": ("DKK", 260.15), "NOV.DE": ("EUR", 34.80),
        "GRG.L": ("GBp", 1650.0),
    }
    SEARCH = {"US00724F1012": ["ADBE", "ADB.DE"], "DK0062498333": ["NVO", "NOVO-B.CO"]}

    class Search:
        def __init__(self, isin, max_results=10):
            self.quotes = [{"symbol": s} for s in _FakeYf.SEARCH.get(isin, [])]

    class Ticker:
        def __init__(self, symbol):
            self.symbol, self.news, self.calendar, self.info = symbol, [], {}, {}
            self.history_metadata = {}

        def history(self, start=None, **kw):
            cur, close = _FakeYf.QUOTES.get(self.symbol, (None, None))
            self.history_metadata = {"currency": cur}
            # o Yahoo devolve às vezes dias sem fecho (NaN)
            return _Hist([(date(2026, 10, 21), float("nan")), (date(2026, 10, 22), close),
                          (date(2026, 10, 23), close)] if cur else [])


def test_refresh_picks_symbol_in_instrument_currency(app, client, monkeypatch):
    import sys
    from portfolio_investimentos.models import Instrument, Price
    from portfolio_investimentos.services import market
    monkeypatch.setitem(sys.modules, "yfinance", _FakeYf)
    with app.app_context():
        db.session.add_all([
            # símbolo errado guardado por uma versão anterior (cotação em USD num ativo em EUR)
            Instrument(ticker="ADB", currency="EUR", isin="US00724F1012", data_symbol="ADBE"),
            Instrument(ticker="NOV", currency="EUR", isin="DK0062498333"),
            Instrument(ticker="GRG", currency="GBP", isin="GB00B63QSB39", data_symbol="GRG.L"),
            Price(instrument="ADB", date=date(2026, 10, 1), close=270.0),
            Transaction(date=date(2026, 8, 27), type="BUY", instrument="ADB", quantity=1, price=240.4, currency="EUR"),
            Transaction(date=date(2026, 9, 14), type="BUY", instrument="NOV", quantity=1, price=37.5, currency="EUR"),
            Instrument(ticker="XYZ", currency="EUR"),  # não existe no Yahoo Finance
            Transaction(date=date(2026, 9, 14), type="BUY", instrument="XYZ", quantity=1, price=10.0, currency="EUR"),
        ])
        db.session.commit()
    assert "Ainda não atualizaste" in client.get("/").get_data(as_text=True)
    with app.app_context():
        market.refresh_all(start=date(2026, 10, 1))
        assert db.session.get(Instrument, "ADB").data_symbol == "ADB.DE"
        assert db.session.get(Instrument, "NOV").data_symbol == "NOV.DE"
        assert [p.close for p in Price.query.filter_by(instrument="ADB")] == [227.10, 227.10]
        assert [p.close for p in Price.query.filter_by(instrument="GRG")] == pytest.approx([16.5, 16.5])
    html = client.get("/").get_data(as_text=True)
    assert "Ainda não atualizaste" not in html
    assert "Sem cotações do Yahoo Finance para XYZ" in html and "ADB," not in html
    assert "ADB.DE: 2 cotações" in client.get("/definicoes").get_data(as_text=True)
    st = client.post("/api/refresh_status", headers={"X-CSRF-Token": csrf(client)}).get_json()["message"]
    assert (st["running"], st["error"], st["missing"], st["updated"]) == (False, None, ["XYZ"], 3)


def test_refresh_state(app):
    from datetime import datetime, timedelta
    from portfolio_investimentos.models import Setting
    from portfolio_investimentos.services.market import refresh_state
    with app.app_context():
        Setting.set("refresh_status", "running:" + datetime.now().isoformat())
        assert refresh_state()[0] is True
        Setting.set("refresh_status", "running:" + (datetime.now() - timedelta(hours=2)).isoformat())
        assert refresh_state()[0] is False  # a aplicação foi fechada a meio
        Setting.set("refresh_status", "error:sem rede")
        assert refresh_state()[1] == "sem rede"


REMOTE = {"REMOTE_ADDR": "203.0.113.7"}


def test_remote_access_blocked_without_password(client):
    assert client.get("/").status_code == 200  # no próprio computador abre sem palavra-passe
    resp = client.get("/", environ_base=REMOTE)
    assert resp.status_code == 403 and "Define uma palavra-passe" in resp.get_data(as_text=True)
    # atrás de um proxy no mesmo servidor o endereço é local, mas o pedido vem de fora
    assert client.get("/", headers={"X-Forwarded-For": "203.0.113.7"}).status_code == 403
    assert client.get("/api/backup", environ_base=REMOTE).status_code == 403


def test_password_login_flow(app, client):
    token = csrf(client)
    assert post(client, "set_password", token, new_password="curta", confirm="curta").status_code == 400
    resp = post(client, "set_password", token, new_password="segredo123", confirm="segredo123")
    assert resp.status_code == 200
    assert client.get("/").status_code == 200  # quem definiu continua com a sessão aberta

    other = app.test_client()  # outro dispositivo
    resp = other.get("/carteira", environ_base=REMOTE)
    assert resp.status_code == 302 and "/login?next=/carteira" in resp.headers["Location"]
    assert other.post("/api/hide_banner", environ_base=REMOTE).status_code == 401
    assert other.get("/api/backup", environ_base=REMOTE).status_code == 401
    login_page = other.get("/login", environ_base=REMOTE).get_data(as_text=True)
    t = re.search(r'name="csrf_token" value="([0-9a-f]+)"', login_page).group(1)
    assert other.post("/login", data={"password": "segredo123"}, environ_base=REMOTE).status_code == 403  # sem CSRF
    bad = other.post("/login", data={"csrf_token": t, "password": "errada"}, environ_base=REMOTE)
    assert bad.status_code == 401 and "Palavra-passe errada" in bad.get_data(as_text=True)
    ok = other.post("/login?next=/%5Cevil.example/x", data={"csrf_token": t, "password": "segredo123"},
                    environ_base=REMOTE)
    assert ok.status_code == 302 and ok.headers["Location"] == "/"  # não redireciona para outro site
    assert other.get("/carteira", environ_base=REMOTE).status_code == 200

    # mudar a palavra-passe termina as sessões dos outros dispositivos
    assert post(client, "set_password", csrf(client), current_password="segredo123",
                new_password="outra-segredo", confirm="outra-segredo").status_code == 200
    assert other.get("/carteira", environ_base=REMOTE).status_code == 302

    # remover a palavra-passe só no próprio computador
    token = csrf(client)
    assert post(client, "remove_password", token, current_password="errada").status_code == 400
    assert post(client, "remove_password", token, current_password="outra-segredo").status_code == 200
    assert client.get("/login").status_code == 302


def test_login_rate_limited(app):
    from portfolio_investimentos import auth
    from portfolio_investimentos.models import Setting
    with app.app_context():
        Setting.set("password_hash", __import__("werkzeug.security").security.generate_password_hash("segredo123"))
    c = app.test_client()
    page = c.get("/login", environ_base=REMOTE).get_data(as_text=True)
    t = re.search(r'name="csrf_token" value="([0-9a-f]+)"', page).group(1)
    for _ in range(auth.MAX_FAILS):
        c.post("/login", data={"csrf_token": t, "password": "x"}, environ_base=REMOTE)
    resp = c.post("/login", data={"csrf_token": t, "password": "segredo123"}, environ_base=REMOTE)
    assert "Demasiadas tentativas" in resp.get_data(as_text=True)
    auth._fails.clear()


def test_env_password(app, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_PASSWORD", "da-variavel")
    c = app.test_client()
    page = c.get("/login", environ_base=REMOTE).get_data(as_text=True)
    t = re.search(r'name="csrf_token" value="([0-9a-f]+)"', page).group(1)
    ok = c.post("/login", data={"csrf_token": t, "password": "da-variavel"}, environ_base=REMOTE)
    assert ok.status_code == 302
    assert "PORTFOLIO_PASSWORD" in c.get("/definicoes", environ_base=REMOTE).get_data(as_text=True)


def test_closes_undo_split_adjustment():
    from portfolio_investimentos.services.market import _closes
    # reagrupamento 1:15 a 07/07/2025: o Yahoo mostra os preços antigos multiplicados por 15
    hist = _Hist([(date(2025, 7, 3), 9.33), (date(2025, 7, 4), float("nan")), (date(2025, 7, 7), 9.40)])
    hist.rows[2][1]["Stock Splits"] = 1 / 15
    assert _closes(hist) == [(date(2025, 7, 3), pytest.approx(0.622)), (date(2025, 7, 7), 9.40)]
    # desdobramento 10:1: os preços antigos aparecem divididos por 10
    hist = _Hist([(date(2024, 6, 7), 120.0), (date(2024, 6, 10), 121.0)])
    hist.rows[1][1]["Stock Splits"] = 10.0
    assert _closes(hist) == [(date(2024, 6, 7), 1200.0), (date(2024, 6, 10), 121.0)]


def test_pwa_files(app, client):
    html = client.get("/").get_data(as_text=True)
    assert 'rel="manifest"' in html
    m = client.get("/static/manifest.webmanifest")
    assert m.status_code == 200 and m.mimetype == "application/manifest+json"
    assert m.get_json()["display"] == "standalone"
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.mimetype and sw.headers["Cache-Control"] == "no-cache"
    for icon in m.get_json()["icons"]:
        assert client.get(icon["src"]).status_code == 200
    # com palavra-passe, o browser continua a conseguir instalar (manifesto e service worker abertos)
    from portfolio_investimentos import auth
    with app.app_context():
        auth.clear_password()
        from portfolio_investimentos.models import Setting
        Setting.set("password_hash", "x")
    other = app.test_client()
    assert other.get("/sw.js", environ_base=REMOTE).status_code == 200
    assert other.get("/static/manifest.webmanifest", environ_base=REMOTE).status_code == 200
    assert other.get("/", environ_base=REMOTE).status_code == 302


def test_portfolio_cache_invalidated_on_changes(app, client):
    from portfolio_investimentos.models import Price
    from portfolio_investimentos.services import data
    token = csrf(client)
    post(client, "add_transaction", token, date="2024-01-02", type="DEPOSIT", amount="1000", currency="EUR")
    post(client, "add_transaction", token, date="2024-01-03", type="BUY", instrument="ACME", quantity="10", price="50",
         currency="EUR")
    with app.test_request_context():
        assert data.load_portfolio(None).holdings_value == pytest.approx(500)
    # nova cotação (como numa atualização): o pedido seguinte já a vê
    with app.app_context():
        db.session.add(Price(instrument="ACME", date=date(2024, 1, 4), close=60.0))
        db.session.commit()
    with app.test_request_context():
        assert data.load_portfolio(None).holdings_value == pytest.approx(600)
    # apagar em bloco (query.delete) também invalida
    with app.app_context():
        Price.query.filter_by(instrument="ACME").delete()
        db.session.commit()
    with app.test_request_context():
        assert data.load_portfolio(None).holdings_value == pytest.approx(500)


def test_legacy_data_dir_is_renamed(tmp_path):
    from portfolio_investimentos import _adopt_legacy
    old, new = tmp_path / "PortfolioManager", tmp_path / "PortfolioInvestimentos"
    old.mkdir()
    (old / "portfolio.db").write_text("dados")
    assert _adopt_legacy(old, new) == new
    assert (new / "portfolio.db").read_text() == "dados" and not old.exists()
    # já com a pasta nova: não mexe em nada
    old.mkdir()
    assert _adopt_legacy(old, new) == new and old.exists()


def test_starts_without_timezone_database(monkeypatch, tmp_path):
    """No Android/Termux sem tzdata, ZoneInfo falha: a aplicação tem de arrancar na mesma."""
    import importlib
    import zoneinfo
    from portfolio_investimentos.services import market

    def no_tz(key):
        raise zoneinfo.ZoneInfoNotFoundError(key)
    monkeypatch.setattr(zoneinfo, "ZoneInfo", no_tz)
    try:
        importlib.reload(market)
        assert isinstance(market.LISBON, market._LisbonFallback)
        assert market.market_status()["label"] in ("Aberto", "Fechado")
        monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
        app = create_app({"TESTING": True})
        assert app.test_client().get("/").status_code == 200
    finally:
        monkeypatch.undo()
        importlib.reload(market)


def test_detect_broker_and_cli_import(app, tmp_path, monkeypatch, capsys):
    import sys
    from portfolio_investimentos import __main__ as cli
    from portfolio_investimentos.services.importer import detect_broker
    assert detect_broker("x.xlsx", _xtb_workbook()) == "xtb"
    assert detect_broker("t.csv", T212_UTC.encode()) == "trading212"
    assert detect_broker("tr.csv", TR_CSV.encode()) == "traderepublic"
    assert detect_broker("g.csv", b"date,type,ticker,quantity,price\n") == "generic"
    (tmp_path / "xtb.xlsx").write_bytes(_xtb_workbook())
    monkeypatch.setattr(cli, "create_app", lambda: app)
    monkeypatch.setattr(sys, "argv", ["portfolio_investimentos", "--importar", str(tmp_path / "xtb.xlsx"),
                                      str(tmp_path / "nao-existe.csv")])
    with pytest.raises(SystemExit) as exit_:
        cli.main()
    out = capsys.readouterr().out
    assert "xtb.xlsx (xtb): 8 novas transações" in out and "nao-existe.csv: não foi possível ler" in out
    assert exit_.value.code == 1


def test_choose_port(monkeypatch):
    from portfolio_investimentos import __main__ as cli
    busy, ours = {5000, 5001}, {5001}
    monkeypatch.setattr(cli, "_port_in_use", lambda host, port: port in busy)
    monkeypatch.setattr(cli, "_is_this_app", lambda url: any(f":{p}/" in url for p in ours))
    assert cli._choose_port("127.0.0.1", None) == (5001, True)       # a aplicação já está na 5001
    ours.clear()
    assert cli._choose_port("127.0.0.1", None) == (5002, False)      # 5000 e 5001 ocupadas por outros
    assert cli._choose_port("127.0.0.1", 5000) == (None, False)      # porta indicada e ocupada: erro
    assert cli._choose_port("127.0.0.1", 6000) == (6000, False)


# resposta do endpoint "chart" do Yahoo (formato real, valores fictícios)
YAHOO_CHART = {"chart": {"result": [{
    "meta": {"currency": "EUR", "symbol": "ACME.DE", "gmtoffset": 7200},
    "timestamp": [1760943600, 1761030000, 1761116400],          # 20, 21 e 22/10/2025 às 07:00 UTC
    "events": {"splits": {"1761116400": {"date": 1761116400, "numerator": 2, "denominator": 1}}},
    "indicators": {"quote": [{"close": [50.0, None, 26.0]}]},
}], "error": None}}


def test_yahoo_direct_parse():
    from portfolio_investimentos.services import yahoo
    from portfolio_investimentos.services.market import _closes
    hist, meta = yahoo._parse_chart(YAHOO_CHART)
    assert meta == {"currency": "EUR"} and not hist.empty
    # dia sem fecho ignorado; antes do desdobramento 2:1 o preço negociado era o dobro do ajustado
    assert _closes(hist) == [(date(2025, 10, 20), 100.0), (date(2025, 10, 22), 26.0)]
    assert yahoo._parse_chart({"chart": {"result": None, "error": {"code": "Not Found"}}})[0].empty


def test_refresh_without_yfinance(app, monkeypatch):
    """Sem o yfinance (ex.: Android), a atualização usa o acesso direto ao Yahoo."""
    import sys
    from portfolio_investimentos.models import Instrument, Price
    from portfolio_investimentos.services import market, yahoo
    monkeypatch.setitem(sys.modules, "yfinance", None)  # import yfinance → ImportError
    calls = []

    def fake_get(url, params):
        calls.append(url)
        if "search" in url:
            return {"quotes": [{"symbol": "ACME.DE"}], "news": []}
        return YAHOO_CHART if "ACME.DE" in url else {"chart": {"result": None}}
    monkeypatch.setattr(yahoo, "_get_json", fake_get)
    with app.app_context():
        db.session.add_all([Instrument(ticker="ACME", currency="EUR", isin="DE0000000001"),
                            Transaction(date=date(2025, 10, 1), type="BUY", instrument="ACME", quantity=1,
                                        price=95.0, currency="EUR")])
        db.session.commit()
        assert market.yfinance_available()
        market.refresh_all(start=date(2025, 10, 1))
        assert db.session.get(Instrument, "ACME").data_symbol == "ACME.DE"
        assert [p.close for p in Price.query.filter_by(instrument="ACME").order_by(Price.date)] == [100.0, 26.0]
    assert any("chart/ACME.DE" in u for u in calls)


def test_yahoo_direct_retries_and_crumb(monkeypatch):
    import io as _io
    import json as _json
    import urllib.error
    from portfolio_investimentos.services import yahoo
    monkeypatch.setattr(yahoo, "_state", {"opener": None, "crumb": None})
    monkeypatch.setattr(yahoo._time, "sleep", lambda s: None)
    seen = []

    def http_error(url, code):
        return urllib.error.HTTPError(url, code, "x", {}, _io.BytesIO(b""))

    def fake_fetch(url):
        seen.append(url)
        if "fc.yahoo.com" in url:
            raise http_error(url, 404)
        if "getcrumb" in url:
            return b"abc123"
        if "crumb=abc123" in url:
            return _json.dumps({"ok": True}).encode()
        raise http_error(url, 401 if "query2" in url else 429)
    monkeypatch.setattr(yahoo, "_fetch", fake_fetch)
    assert yahoo._get_json(yahoo.CHART_URL.format(symbol="AAPL"), {"interval": "1d"}) == {"ok": True}
    assert "query1" in seen[0] and "query2" in seen[1] and any("getcrumb" in u for u in seen)

    # sem ligação nenhuma: erro legível, para o resumo da atualização
    monkeypatch.setattr(yahoo, "_state", {"opener": None, "crumb": None})
    monkeypatch.setattr(yahoo, "_fetch", lambda url: (_ for _ in ()).throw(urllib.error.URLError("rede em baixo")))
    with pytest.raises(yahoo.YahooError, match="sem ligação ao Yahoo"):
        yahoo._get_json(yahoo.CHART_URL.format(symbol="AAPL"), {})


def test_refresh_report_shows_yahoo_error(app, monkeypatch):
    import sys
    from portfolio_investimentos.models import Instrument, Setting
    from portfolio_investimentos.services import market, yahoo
    monkeypatch.setitem(sys.modules, "yfinance", None)

    def fail(url, params):
        raise yahoo.YahooError("HTTP 429: o Yahoo limitou os pedidos; tenta mais tarde")
    monkeypatch.setattr(yahoo, "_get_json", fail)
    with app.app_context():
        db.session.add(Instrument(ticker="ACME", currency="EUR", data_symbol="ACME.DE"))
        db.session.commit()
        market.refresh_all(start=date(2025, 10, 1))
        report = Setting.get("refresh_report")
    assert "ACME: sem cotações em EUR (ACME.DE: HTTP 429" in report


def test_offline_mode_marks_pages(app, client, monkeypatch):
    token = csrf(client)
    assert client.get("/ping").status_code == 204
    assert "X-PM-Offline" not in client.get("/").headers          # desligado por omissão
    assert post(client, "set_offline", token, enabled="1").status_code == 200
    page = client.get("/carteira")
    assert page.headers.get("X-PM-Offline") == "1" and 'data-offline="1"' in page.get_data(as_text=True)
    assert "X-PM-Offline" not in client.get("/sw.js").headers
    assert "X-PM-Offline" not in client.get("/static/offline.html").headers
    assert "X-PM-Offline" not in client.get("/definicoes").headers         # só páginas de consulta
    # com palavra-passe: o login e os redirecionamentos nunca ficam guardados
    monkeypatch.setenv("PORTFOLIO_PASSWORD", "segredo123")
    other = app.test_client()
    assert "X-PM-Offline" not in other.get("/login", environ_base=REMOTE).headers
    assert "X-PM-Offline" not in other.get("/", environ_base=REMOTE).headers
    assert other.get("/ping", environ_base=REMOTE).status_code == 204   # aberto, para a página saber se a app corre
    monkeypatch.delenv("PORTFOLIO_PASSWORD")
    assert post(client, "set_offline", token, enabled="0").status_code == 200
    assert "X-PM-Offline" not in client.get("/").headers
