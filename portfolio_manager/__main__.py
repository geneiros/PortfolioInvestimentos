"""Arranque local: `python -m portfolio_manager` abre a aplicação no browser."""
import argparse
import threading
import webbrowser

from . import create_app, data_dir


def main():
    parser = argparse.ArgumentParser(prog="portfolio_manager", description="Gestor de carteira (local)")
    parser.add_argument("--port", type=int, default=5000, help="porta (por omissão 5000)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="endereço (por omissão 127.0.0.1; 0.0.0.0 abre-a na rede local e exige palavra-passe)")
    parser.add_argument("--no-browser", action="store_true", help="não abrir o browser automaticamente")
    parser.add_argument("--demo", action="store_true", help="carregar dados de demonstração e sair")
    parser.add_argument("--refresh", action="store_true", help="atualizar cotações (yfinance) e sair")
    args = parser.parse_args()

    app = create_app()
    if args.demo or args.refresh:
        with app.app_context():
            if args.demo:
                from .services.demo import create_demo
                print(create_demo())
            if args.refresh:
                from .services.market import refresh_all
                print(refresh_all())
        return

    url = f"http://127.0.0.1:{args.port}/"
    print(f"Portfolio Manager a correr em {url}")
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


if __name__ == "__main__":
    main()
