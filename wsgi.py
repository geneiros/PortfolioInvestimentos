"""Ponto de entrada WSGI para servidores na cloud (ex.: PythonAnywhere, gunicorn wsgi:app).

Define PORTFOLIO_PASSWORD (ou uma palavra-passe em Definições) antes de abrir a aplicação na internet,
PORTFOLIO_HTTPS=1 com HTTPS e PORTFOLIO_PROXY=1 atrás de um proxy (ex.: PythonAnywhere).
"""
from portfolio_investimentos import create_app

app = create_app()
