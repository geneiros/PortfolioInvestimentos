"""Plugin de exemplo para os testes (e modelo para escrever um plugin): uma página, um item no menu, uma secção
nas Definições, um bloco no Fiscal, uma ação da API e uma tarefa periódica. Ver docs/plugins.md."""
from pathlib import Path

from flask import Blueprint, render_template

from portfolio_investimentos.services import context as ctx

bp = Blueprint("exemplo", __name__, template_folder=str(Path(__file__).parent / "plugin_exemplo_templates"))
TICKS = []


@bp.route("/exemplo")
def pagina():
    c = ctx.build("exemplo", "Exemplo")
    return render_template("exemplo/pagina.html", **c)


def ola(nome="mundo"):
    return f"Olá, {nome}!"


def tarefa(app):
    TICKS.append(app.name)


def register(registry):
    registry.blueprint(bp)
    registry.nav_item("exemplo", "Exemplo", "/exemplo", "bi-stars", after="fiscal")
    registry.settings_section("exemplo/definicoes.html")
    registry.page_slot("fiscal", "bottom", "exemplo/fiscal.html")
    registry.action(ola, name="exemplo_ola")
    registry.background(tarefa, every_seconds=3600)
    registry.context(lambda: {"exemplo_versao": "1.0"})


def register_partido(registry):
    raise RuntimeError("este plugin falha de propósito")


def register_repetido(registry):
    registry.action(ola, name="set_broker")  # já existe no núcleo: recusado
