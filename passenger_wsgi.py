"""Ponto de entrada para o Passenger (cPanel → Setup Python App; startup file `passenger_wsgi.py`, entry point
`application`).

Se a aplicação não arrancar (ex.: faltam as dependências), em vez do erro genérico do Passenger mostra uma página com
o motivo e o que fazer; o mesmo vai para o registo do Passenger.
"""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    from portfolio_investimentos import create_app
    application = create_app()
except Exception as exc:  # o arranque falhou: diz porquê (sem isto o Passenger só mostra «something went wrong»)
    traceback.print_exc()
    _error = f"{type(exc).__name__}: {exc}"
    _missing = isinstance(exc, ModuleNotFoundError)

    def application(environ, start_response):
        from html import escape
        tip = ("Faltam as dependências. No cPanel, em Setup Python App, escreve <code>requirements.txt</code> em "
               "«Configuration files», carrega em <b>Run Pip Install</b> e depois em <b>Restart</b>." if _missing else
               "Vê o registo do Passenger (o «Passenger log file» da aplicação) e o README, secção «Num alojamento "
               "com cPanel».")
        body = (f"<!doctype html><meta charset='utf-8'><title>Portfolio Investimentos</title>"
                f"<body style='font-family:system-ui,sans-serif;max-width:46rem;margin:3rem auto;padding:0 1rem'>"
                f"<h1>A aplicação não arrancou</h1><p><code>{escape(_error)}</code></p><p>{tip}</p>"
                f"<p style='color:#666'>Python {escape(sys.version.split()[0])} · pasta {escape(HERE)}</p>").encode()
        start_response("500 Internal Server Error", [("Content-Type", "text/html; charset=utf-8"),
                                                     ("Content-Length", str(len(body)))])
        return [body]
