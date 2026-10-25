"""Ponto de entrada WSGI para servidores na cloud (ex.: PythonAnywhere, gunicorn wsgi:app).

Define PORTFOLIO_PASSWORD (ou uma palavra-passe em Definições) antes de abrir a aplicação na internet.
"""
from portfolio_investimentos import create_app

app = create_app()
