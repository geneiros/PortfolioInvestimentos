"""Arranque local: `python -m portfolio_investimentos` abre a aplicação no browser."""
import argparse
import os
from pathlib import Path
import sys
import threading
import webbrowser

from . import PORTABLE_NAME, create_app, data_dir, is_portable, portable_dir


def main():
    parser = argparse.ArgumentParser(prog="portfolio_investimentos", description="Gestor de carteira (local)")
    parser.add_argument("--port", type=int, default=None,
                        help="porta (por omissão 5000; se estiver ocupada, usa a primeira livre até 5020)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="endereço (por omissão 127.0.0.1; 0.0.0.0 abre-a na rede local e exige palavra-passe)")
    parser.add_argument("--no-browser", action="store_true", help="não abrir o browser (nem a janela) automaticamente")
    parser.add_argument("--browser", action="store_true",
                        help="abrir no browser em vez da janela própria (o executável abre numa janela própria)")
    parser.add_argument("--janela", action="store_true",
                        help="abrir numa janela própria (pywebview), também a correr a partir do código")
    parser.add_argument("--demo", action="store_true", help="carregar dados de demonstração e sair")
    parser.add_argument("--refresh", action="store_true", help="atualizar cotações (yfinance) e sair")
    parser.add_argument("--abertas", action="store_true",
                        help="com --refresh, atualizar só as posições abertas (e os índices de comparação)")
    parser.add_argument("--importar", nargs="+", metavar="FICHEIRO",
                        help="importar extratos (XTB .xlsx, Trading 212, Trade Republic ou CSV genérico) e sair")
    parser.add_argument("--corretora", choices=["generic", "trading212", "traderepublic", "xtb"],
                        help="corretora dos extratos de --importar (por omissão, detetada pelo conteúdo)")
    parser.add_argument("--portatil", action="store_true",
                        help=f"executável: guardar os dados na pasta {PORTABLE_NAME} ao lado do executável "
                             "(automático numa pen USB no Windows)")
    parser.add_argument("--terminal", action="store_true",
                        help="executável do Windows: mostrar o terminal com as mensagens da aplicação")
    parser.add_argument("--testar-janela", action="store_true",
                        help="dizer se a janela própria (pywebview) está disponível e sair")
    parser.add_argument("--testar-yahoo", action="store_true",
                        help="testar a ligação ao Yahoo Finance (cotações, câmbios e pesquisa) e sair")
    args = parser.parse_args()

    if args.portatil:
        if getattr(sys, "frozen", False):
            folder = Path(sys.executable).resolve().parent / PORTABLE_NAME
            try:
                folder.mkdir(exist_ok=True)
            except OSError as exc:
                print(f"Não foi possível criar {folder}: {exc}")
            portable_dir.cache_clear()
        else:
            print("--portatil só se aplica ao executável; a correr a partir do código, usa PORTFOLIO_DATA_DIR.")
    from . import desktop
    if args.terminal:
        desktop.show_console()
    desktop.log_to_file(data_dir() / "registo.log")  # executável do Windows sem terminal: as mensagens ficam aqui
    if args.testar_janela:
        ok = _webview_available()
        print("Janela própria (pywebview): " + ("disponível" if ok else "indisponível (abre no browser)"))
        raise SystemExit(0 if ok else 1)
    if args.testar_yahoo:
        raise SystemExit(_test_yahoo())
    # o executável abre numa janela própria (pywebview), logo com o ecrã de arranque; o resto prepara-se por trás.
    # Sem ela (Linux sem GTK/Qt, --browser, --no-browser, comandos que saem), segue como antes, no browser.
    one_shot = args.demo or args.refresh or args.importar
    if (not args.no_browser and not args.browser and not one_shot
            and (getattr(sys, "frozen", False) or args.janela) and _webview_available()):
        if _window_app(args):
            return
        print("Não foi possível abrir a janela própria; a abrir no browser.")
    desktop.show_console()  # sem a janela própria, o terminal é o que se fecha para terminar a aplicação
    from .migrations import MigrationError
    try:
        app = create_app()
    except MigrationError as exc:
        raise SystemExit(str(exc)) from exc
    if args.importar:
        with app.app_context():
            from .services.backups import auto_backup
            auto_backup("importar")
            raise SystemExit(_import_files(args.importar, args.corretora))
    if args.demo or args.refresh:
        with app.app_context():
            if args.demo:
                from .services.backups import auto_backup
                from .services.demo import create_demo
                auto_backup("demonstracao")
                print(create_demo())
            if args.refresh:
                from .services.market import refresh_all
                result = refresh_all(progress=lambda line: print(line, flush=True), only_open=args.abertas)
                print(result if result.startswith("Já existe") else "Concluído.")
        return

    port, running = _choose_port(args.host, args.port)
    if port is None:
        print(f"A porta {args.port} está ocupada por outro programa. Usa outra porta, por exemplo:")
        if getattr(sys, "frozen", False):  # executável único (PyInstaller)
            print(f"  {os.path.basename(sys.executable)} --port {args.port + 1}")
        else:
            print(f"  python -m portfolio_investimentos --port {args.port + 1}"
                  f"      (no Android: PORT={args.port + 1} bash iniciar-android.sh)")
        raise SystemExit(1)
    url = f"http://127.0.0.1:{port}/"
    _announce(url)
    if running:
        # outra janela (ou uma sessão do Termux em segundo plano) já tem a aplicação aberta: usa essa
        print(f"O Portfolio Investimentos já está a correr em {url}")
        print("Para o parares: fecha a outra janela, ou corre  pkill -f portfolio_investimentos")
        if not args.no_browser:
            webbrowser.open(url)
        return
    if args.port is None and port != DEFAULT_PORT:
        print(f"A porta {DEFAULT_PORT} está ocupada por outro programa; a usar a {port}.")
    args.port = port
    print(f"Portfolio Investimentos a correr em {url}")
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"Aberta na rede em {args.host}:{args.port}. Os outros dispositivos só entram depois de definires "
              "uma palavra-passe (Definições → Segurança ou variável PORTFOLIO_PASSWORD).")
    print(f"Dados guardados em {data_dir()}" + (" (modo portátil)" if is_portable() else ""))
    print("Fecha esta janela (ou Ctrl+C) para terminar.")
    _close_pyi_splash()
    _start_background(app)
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    _serve(app, args.host, args.port)


def _start_background(app):
    """Tarefas em segundo plano: cotações rápidas, aviso de versão nova (executável) e as dos plugins."""
    threading.Thread(target=_quick_quotes_loop, args=(app,), daemon=True, name="cotacoes-rapidas").start()
    from .services.updates import is_executable
    if is_executable():  # executável único ou app Android: há uma versão nova no GitHub?
        threading.Timer(10.0, _check_updates, args=(app,)).start()
    for fn, every in getattr(app.extensions.get("pm_plugins"), "tasks", []):  # tarefas periódicas dos plugins
        threading.Thread(target=_plugin_task_loop, args=(app, fn, every), daemon=True,
                         name=f"plugin-{getattr(fn, '__name__', 'tarefa')}").start()


def _close_pyi_splash():
    """Fecha o ecrã de arranque do PyInstaller (só existe no executável do Windows, enquanto se descompacta)."""
    try:
        import pyi_splash
        pyi_splash.close()
    except Exception:
        pass


def _serve(app, host, port):
    try:
        from waitress import serve
        serve(app, host=host, port=port, threads=4)
    except ImportError:
        app.run(host=host, port=port, debug=False, use_reloader=False)


def _webview_available():
    try:
        import webview  # noqa: F401  (pywebview: janela nativa com o motor web do sistema)
        return True
    except Exception:
        return False


def _window_app(args):
    """Executável: abre já a janela própria com o ecrã de arranque e prepara a aplicação por trás (_boot), numa
    thread do pywebview. Devolve False se a janela não abrir (o chamador segue pelo browser)."""
    try:
        import webview
    except Exception:
        return False
    from . import desktop
    settings = getattr(webview, "settings", None)
    if isinstance(settings, dict):
        settings["ALLOW_DOWNLOADS"] = True                 # exportações CSV, cópias de segurança
        settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True  # notícias, GitHub, sites dos emitentes
    color, dark = desktop.saved_color()  # a cor do tema da última vez: não abre branca no tema escuro
    try:  # 85% do ecrã principal, centrada
        screens = webview.screens
    except Exception:
        screens = []
    width, height, x, y = desktop.window_geometry(screens)
    place = {"x": x, "y": y} if x is not None else {}
    try:
        window = webview.create_window(desktop.TITLE, html=desktop.splash_html(color, dark), width=width,
                                       height=height, min_size=(min(900, width), min(600, height)),
                                       text_select=True, background_color=color, js_api=desktop.WindowApi(),
                                       **place)
        events = getattr(window, "events", None)
        if events is not None and hasattr(events, "shown"):  # a barra de título com a cor do tema, logo ao abrir
            events.shown += lambda *a: desktop.title_bar(color, dark)
        # guarda o armazenamento local (tema, preferências) entre arranques
        extra = {"storage_path": str(data_dir() / "janela")} if is_portable() else {}  # o tema também vai na pen
        webview.start(_boot, args=(window, args), private_mode=False, **extra)
        return True
    except Exception as exc:  # sem motor web no sistema (ex.: Linux sem GTK/Qt, Windows sem WebView2)
        print(f"Janela própria indisponível: {exc}")
        return False


def _boot(window, args, wait=30.0):
    """Prepara a aplicação com o ecrã de arranque à vista: base de dados, porta, servidor; depois abre-a na janela.
    Os erros (base de dados mais recente, porta ocupada) aparecem no próprio ecrã de arranque."""
    import json
    import time
    import urllib.request
    from .migrations import MigrationError
    _close_pyi_splash()

    def status(text, error=False):
        print(text)
        try:
            window.evaluate_js(f"window.pmSplash && pmSplash({json.dumps(text)}, {json.dumps(error)})")
        except Exception:
            pass
    status("A abrir a base de dados…")
    try:
        app = create_app()
    except MigrationError as exc:
        status(str(exc), error=True)
        return
    port, running = _choose_port(args.host, args.port)
    if port is None:
        status(f"A porta {args.port} está ocupada por outro programa. Fecha esse programa ou arranca com "
               f"--port {args.port + 1}.", error=True)
        return
    url = f"http://127.0.0.1:{port}/"
    if running:  # a aplicação já está aberta (outra janela): mostra-a aqui
        window.load_url(url)
        return
    args.port = port
    print(f"Portfolio Investimentos a correr em {url} · dados em {data_dir()}"
          + (" (modo portátil)" if is_portable() else ""))
    print("Fecha a janela da aplicação para terminar.")
    status("A arrancar o servidor…")
    _start_background(app)
    threading.Thread(target=_serve, args=(app, args.host, port), daemon=True, name="servidor").start()
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:  # espera que o servidor responda, para não abrir uma página em branco
        try:
            urllib.request.urlopen(url + "ping", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    window.load_url(url)


DEFAULT_PORT = 5000
QUICK_EVERY = 300  # segundos


def _check_updates(app):
    """Pergunta ao GitHub pela última release (no máximo uma vez por dia); sem internet não faz nada."""
    try:
        with app.app_context():
            from .services import updates
            updates.check()
    except Exception:  # nunca impede a aplicação de correr
        pass


def _plugin_task_loop(app, fn, every, rounds=None):
    """Tarefa periódica de um plugin, no contexto da aplicação; um erro fica no log e a tarefa continua."""
    import logging
    import time
    n = 0
    while rounds is None or n < rounds:
        n += 1
        time.sleep(every)
        try:
            with app.app_context():
                fn(app)
        except Exception as exc:  # nunca deixa a thread morrer
            logging.getLogger(__name__).info("tarefa do plugin %s falhou: %s", getattr(fn, "__name__", fn), exc)


def _quick_quotes_loop(app, every=QUICK_EVERY, rounds=None):
    """No computador: com a opção «de 5 em 5 minutos» ligada, atualiza os preços das posições abertas mesmo com o
    browser fechado (o servidor só pede ao Yahoo com o mercado aberto). No PythonAnywhere quem o faz é a página."""
    import logging
    import time
    n = 0
    while rounds is None or n < rounds:
        n += 1
        time.sleep(every)
        try:
            with app.app_context():
                from . import api
                from .services import market
                if market.quick_quotes_enabled():
                    api.quick_quotes_now()
        except Exception as exc:  # nunca deixa a thread morrer
            logging.getLogger(__name__).info("cotações rápidas falharam: %s", exc)


def _choose_port(host, wanted):
    """Devolve (porta, já_a_correr). Sem porta indicada, procura uma livre (ou esta aplicação) até 5020."""
    candidates = [wanted] if wanted else range(DEFAULT_PORT, DEFAULT_PORT + 21)
    for port in candidates:
        if not _port_in_use(host, port):
            return port, False
        if _is_this_app(f"http://127.0.0.1:{port}/"):
            return port, True
    return None, False


def _announce(url):
    """Escreve o endereço escolhido onde o script do Android o vai buscar para abrir o browser."""
    import os
    target = os.environ.get("PORTFOLIO_URL_FILE")
    if target:
        try:
            with open(target, "w") as fh:
                fh.write(url)
        except OSError:
            pass


def _port_in_use(host, port):
    import os
    import socket
    with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM) as sock:
        if os.name != "nt":
            # como o waitress: ligações a fechar (TIME_WAIT) depois de parar a aplicação não ocupam a porta
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return True
    return False


def _is_this_app(url):
    """A porta ocupada é desta aplicação? (o manifesto é público, mesmo com palavra-passe)"""
    import urllib.request
    try:
        with urllib.request.urlopen(url + "static/manifest.webmanifest", timeout=3) as resp:
            return b"Portfolio Investimentos" in resp.read(4096)
    except (OSError, ValueError):
        return False


def _test_yahoo():
    """Diagnóstico da ligação ao Yahoo: mostra o que corre bem e o erro exato do que falha."""
    from datetime import date, timedelta

    from .services.market import _yahoo_client
    yf = _yahoo_client()
    print("A usar:", "yfinance" if yf.__name__ == "yfinance" else "acesso direto (sem yfinance)")
    start = date.today() - timedelta(days=10)
    ok = True
    for symbol in ("AAPL", "ADB.DE", "EURUSD=X"):
        try:
            t = yf.Ticker(symbol)
            hist = t.history(start=start, auto_adjust=False)
            rows = list(hist.iterrows())
            last = rows[-1][1]["Close"] if rows else None
            cur = (getattr(t, "history_metadata", None) or {}).get("currency")
            print(f"  {symbol:9} {len(rows)} dias, último fecho {last} {cur or ''}")
        except Exception as exc:
            ok = False
            print(f"  {symbol:9} ERRO: {exc}")
    try:
        quotes = yf.Search("US00724F1012", max_results=5).quotes or []
        print("  pesquisa ISIN US00724F1012:", ", ".join(q.get("symbol", "?") for q in quotes) or "(vazio)")
    except Exception as exc:
        ok = False
        print("  pesquisa ISIN: ERRO:", exc)
    # dados fundamentais (valor de cada ação): o info (quoteSummary) e a segunda fonte (séries das demonstrações)
    from .services import yahoo
    for symbol in ("ADBE", "ADB.DE"):
        try:
            info = yf.Ticker(symbol).info or {}
            keys = [k for k in ("trailingEps", "forwardEps", "bookValue", "freeCashflow") if info.get(k) is not None]
            print(f"  {symbol:9} info: " + (", ".join(f"{k}={info[k]}" for k in keys) or f"sem dados ({len(info)} campos)"))
        except Exception as exc:
            print(f"  {symbol:9} info: ERRO: {exc}")
        try:
            series = yahoo.fundamentals(symbol)
            eps = (series.get("trailingDilutedEPS") or [None])[-1]
            print(f"  {symbol:9} demonstrações: {len(series)} séries" + (f", lucro por ação {eps[1]} {eps[2]}" if eps else ""))
        except Exception as exc:
            print(f"  {symbol:9} demonstrações: ERRO: {exc}")
    return 0 if ok else 1


def _import_files(paths, broker=None):
    """Importa extratos a partir da linha de comandos (útil no Android, sem o seletor de ficheiros)."""
    from pathlib import Path

    from .models import Setting
    from .services import importer
    status = 0
    for name in paths:
        path = Path(name).expanduser()
        try:
            content = path.read_bytes()
        except OSError as exc:
            print(f"{path}: não foi possível ler o ficheiro ({exc.strerror or exc}).")
            status = 1
            continue
        key = broker or importer.detect_broker(path.name, content)
        if Setting.get("demo") == "1":  # os dados reais substituem a demonstração, como na página Importar
            from .api import reset_data
            reset_data("APAGAR")
        try:
            batch = importer.import_file(key, path.name, content)
        except importer.ImportError_ as exc:
            print(f"{path.name} ({key}): {exc}")
            status = 1
            continue
        ignored = ", ".join(f"{n}× {k}" for k, n in (getattr(batch, "ignored", {}) or {}).items())
        print(f"{path.name} ({key}): {batch.imported} novas transações, {batch.skipped} duplicadas ignoradas"
              + (f" · sem efeito na carteira: {ignored}" if ignored else ""))
    return status


if __name__ == "__main__":
    main()
