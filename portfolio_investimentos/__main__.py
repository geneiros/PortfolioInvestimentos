"""Arranque local: `python -m portfolio_investimentos` abre a aplicação no browser."""
import argparse
import threading
import webbrowser

from . import create_app, data_dir


def main():
    parser = argparse.ArgumentParser(prog="portfolio_investimentos", description="Gestor de carteira (local)")
    parser.add_argument("--port", type=int, default=None,
                        help="porta (por omissão 5000; se estiver ocupada, usa a primeira livre até 5020)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="endereço (por omissão 127.0.0.1; 0.0.0.0 abre-a na rede local e exige palavra-passe)")
    parser.add_argument("--no-browser", action="store_true", help="não abrir o browser automaticamente")
    parser.add_argument("--demo", action="store_true", help="carregar dados de demonstração e sair")
    parser.add_argument("--refresh", action="store_true", help="atualizar cotações (yfinance) e sair")
    parser.add_argument("--importar", nargs="+", metavar="FICHEIRO",
                        help="importar extratos (XTB .xlsx, Trading 212, Trade Republic ou CSV genérico) e sair")
    parser.add_argument("--corretora", choices=["generic", "trading212", "traderepublic", "xtb"],
                        help="corretora dos extratos de --importar (por omissão, detetada pelo conteúdo)")
    args = parser.parse_args()

    app = create_app()
    if args.importar:
        with app.app_context():
            raise SystemExit(_import_files(args.importar, args.corretora))
    if args.demo or args.refresh:
        with app.app_context():
            if args.demo:
                from .services.demo import create_demo
                print(create_demo())
            if args.refresh:
                from .services.market import refresh_all
                print(refresh_all())
        return

    port, running = _choose_port(args.host, args.port)
    if port is None:
        print(f"A porta {args.port} está ocupada por outro programa. Usa outra porta, por exemplo:")
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
    print(f"Dados guardados em {data_dir()}")
    print("Fecha esta janela (ou Ctrl+C) para terminar.")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        from waitress import serve
        serve(app, host=args.host, port=args.port, threads=4)
    except ImportError:
        app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


DEFAULT_PORT = 5000


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
    import socket
    with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM) as sock:
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
