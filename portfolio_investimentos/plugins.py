"""Extensões (plugins): o que um pacote instalado à parte pode acrescentar à aplicação, sem mexer no núcleo.

Um plugin é um pacote Python que declara, no seu pyproject.toml::

    [project.entry-points."portfolio_investimentos.plugins"]
    meu_plugin = "meu_pacote:register"

e uma função ``register(registry)`` que recebe um :class:`Registry` e regista o que precisa: páginas (blueprints),
itens do menu, secções das Definições, blocos em pontos fixos das páginas, ações da API, tarefas periódicas e
variáveis para os templates. Ver docs/plugins.md.

Para testes e para desenvolver um plugin sem o instalar: ``PORTFOLIO_PLUGINS="modulo:register,outro:register"``.

Um plugin corre com os mesmos privilégios da aplicação (lê e escreve a base de dados): instala só plugins de
confiança. Um plugin que falhe ao carregar fica registado no log e em ``app.extensions["pm_plugins"]["errors"]``,
e a aplicação arranca na mesma.
"""
import importlib
import logging
import os
from importlib.metadata import entry_points

log = logging.getLogger(__name__)

PLUGIN_API = 1          # sobe quando um ponto de extensão muda de forma incompatível
GROUP = "portfolio_investimentos.plugins"

# pontos fixos das páginas onde um plugin pode pôr blocos (lista fechada: cada um é um {% include %} no template)
SLOTS = {
    ("fiscal", "top"), ("fiscal", "bottom"),
    ("carteira", "bottom"),
}


class PluginError(Exception):
    """Registo inválido (ex.: uma ação com o nome de uma que já existe, ou um ponto de página desconhecido)."""


class Registry:
    """O que os plugins registaram. Um por aplicação, em ``app.extensions["pm_plugins"]``."""

    api_version = PLUGIN_API

    def __init__(self, app):
        self.app = app
        self.loaded = []         # nomes dos plugins carregados
        self.errors = {}         # nome → mensagem de erro
        self.nav = []            # (key, label, url, icon, after, bottom)
        self.settings = []       # (order, template)
        self.slots = {}          # (page, slot) → [templates]
        self.tasks = []          # (fn, every_seconds)
        self._current = None

    # ------------------------------------------------------------------ o que um plugin pode registar
    def blueprint(self, bp, **options):
        """Páginas e rotas próprias (com os templates e os ficheiros estáticos do próprio pacote)."""
        self.app.register_blueprint(bp, **options)

    def nav_item(self, key, label, url, icon="bi-puzzle", after=None, bottom=False):
        """Um item no menu lateral, depois do item `after` (ex.: "fiscal"); sem ele, no fim. `bottom=True`: no
        grupo de baixo (Importar, Transações, Definições). `key` é o `active` que a página passa ao `ctx.build`."""
        self.nav.append((key, label, url, icon, after, bottom))

    def settings_section(self, template, order=100):
        """Um template incluído na página Definições (por ordem de `order`)."""
        self.settings.append((order, template))

    def page_slot(self, page, slot, template):
        """Um bloco (template) num ponto fixo de uma página: ver SLOTS."""
        if (page, slot) not in SLOTS:
            raise PluginError(f"ponto de página desconhecido: {page}/{slot} (disponíveis: {sorted(SLOTS)})")
        self.slots.setdefault((page, slot), []).append(template)

    def action(self, fn, name=None):
        """Uma ação da API (POST /api/<nome>, com o token CSRF), como as do núcleo. Não substitui ações existentes."""
        from .api import ACTIONS
        name = name or fn.__name__
        if name in ACTIONS:
            raise PluginError(f"já existe uma ação chamada «{name}»")
        ACTIONS[name] = fn
        return fn

    def background(self, fn, every_seconds):
        """Tarefa periódica `fn(app)`, chamada dentro do contexto da aplicação. Corre só no arranque local
        (python -m portfolio_investimentos); em servidores como o PythonAnywhere não há tarefas em segundo plano."""
        self.tasks.append((fn, max(int(every_seconds), 60)))

    def context(self, fn):
        """Variáveis extra para todos os templates: `fn()` devolve um dicionário."""
        self.app.context_processor(fn)

    # ------------------------------------------------------------------ usado pelo núcleo
    def nav_items(self, base, bottom=False):
        """O menu `base` (lista de (key, label, url, icon)) com os itens dos plugins nos seus lugares."""
        items = list(base)
        for key, label, url, icon, after, low in self.nav:
            if low != bottom:
                continue
            keys = [k for k, *_ in items]
            pos = keys.index(after) + 1 if after in keys else len(items)
            items.insert(pos, (key, label, url, icon))
        return items

    def settings_templates(self):
        return [t for _, t in sorted(self.settings, key=lambda x: x[0])]


def _sources():
    """(nome, função register) de cada plugin: os instalados (entry points) e os de PORTFOLIO_PLUGINS."""
    found = []
    for ep in entry_points(group=GROUP):
        found.append((ep.name, ep.load))
    for spec in filter(None, (s.strip() for s in os.environ.get("PORTFOLIO_PLUGINS", "").split(","))):
        module, _, attr = spec.partition(":")

        def loader(module=module, attr=attr or "register"):
            return getattr(importlib.import_module(module), attr)
        found.append((spec, loader))
    return found


def load(app):
    """Carrega os plugins para esta aplicação; um plugin com erro não impede o arranque."""
    registry = Registry(app)
    app.extensions["pm_plugins"] = registry
    for name, loader in _sources():
        registry._current = name
        try:
            loader()(registry)
            registry.loaded.append(name)
        except Exception as exc:  # um plugin partido não pode deixar a aplicação sem arrancar
            registry.errors[name] = f"{type(exc).__name__}: {exc}"
            log.warning("o plugin %s não carregou: %s", name, exc)
    registry._current = None

    @app.context_processor
    def _plugin_templates():
        return {"plugin_settings": registry.settings_templates(),
                "plugin_slot": lambda page, slot: registry.slots.get((page, slot), [])}
    return registry


def registry(app=None):
    """O registo da aplicação atual (None antes de `load`)."""
    from flask import current_app
    return (app or current_app).extensions.get("pm_plugins")
