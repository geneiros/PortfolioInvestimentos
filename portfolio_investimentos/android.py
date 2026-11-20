"""Arranque dentro da app Android (Chaquopy): o servidor corre no próprio telemóvel e a app mostra-o numa WebView.

A app (android/, MainActivity.java) chama ``start(pasta_dos_dados)`` numa thread e abre o URL devolvido. Os dados
ficam na área privada da app. Sem o yfinance (não há curl_cffi para Android): as cotações usam o acesso direto ao
Yahoo Finance.
"""
import os
import socket
import threading
import time
import urllib.request

_lock = threading.Lock()
_state = {}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(url, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(url + "ping", timeout=2):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def start(data_dir):
    """Arranca o servidor (uma vez por processo) e devolve o URL da aplicação."""
    with _lock:
        if "url" in _state:
            return _state["url"]
        os.environ["PORTFOLIO_DATA_DIR"] = str(data_dir)
        os.environ["PORTFOLIO_ANDROID"] = "1"
        try:  # certificados para os pedidos HTTPS do Python (Yahoo Finance, notícias, GitHub)
            import certifi
            os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        except ImportError:
            pass
        from . import __main__ as cli
        from . import create_app
        app = create_app()
        port = _free_port()
        threading.Thread(target=cli._serve, args=(app, "127.0.0.1", port), daemon=True, name="servidor").start()
        url = f"http://127.0.0.1:{port}/"
        if not _wait(url):
            raise RuntimeError("O servidor da aplicação não respondeu.")
        cli._start_background(app)
        _state["url"] = url
        print(f"Portfolio Investimentos pronto em {url}", flush=True)
        return url
