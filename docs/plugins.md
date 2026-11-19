# Extensões (plugins)

O Portfolio Investimentos pode ser estendido por pacotes Python instalados à parte, sem mexer no código desta
aplicação. Um plugin pode acrescentar páginas, itens no menu, secções nas Definições, blocos em pontos fixos das
páginas, ações da API, tarefas periódicas e variáveis para os templates.

> **Segurança.** Um plugin corre com os mesmos privilégios da aplicação: lê e escreve a base de dados e pode fazer
> pedidos à internet. Instala só plugins de confiança.

Versão da API de extensões: **`PLUGIN_API = 1`** (`portfolio_investimentos/plugins.py`). Sobe quando um ponto de
extensão muda de forma incompatível; um plugin pode confirmá-la com `registry.api_version`.

## Um plugin mínimo

```
o_meu_plugin/
├── pyproject.toml
└── o_meu_plugin/
    ├── __init__.py
    └── templates/o_meu_plugin/pagina.html
```

`pyproject.toml`:

```toml
[project]
name = "o-meu-plugin"
version = "0.1.0"
dependencies = ["portfolio-investimentos"]

[project.entry-points."portfolio_investimentos.plugins"]
o_meu_plugin = "o_meu_plugin:register"
```

`o_meu_plugin/__init__.py`:

```python
from flask import Blueprint, render_template
from portfolio_investimentos.services import context as ctx

bp = Blueprint("o_meu_plugin", __name__, template_folder="templates")


@bp.route("/o-meu-plugin")
def pagina():
    c = ctx.build("o_meu_plugin", "O meu plugin")   # o mesmo contexto das páginas do núcleo (menu, topo, tema)
    return render_template("o_meu_plugin/pagina.html", **c)


def register(registry):
    registry.blueprint(bp)
    registry.nav_item("o_meu_plugin", "O meu plugin", "/o-meu-plugin", "bi-stars", after="fiscal")
```

`templates/o_meu_plugin/pagina.html`:

```html
{% extends "base.html" %}
{% block content %}<div class="pm-card">Olá!</div>{% endblock %}
```

Instala-o no mesmo ambiente da aplicação (`pip install -e o_meu_plugin`) e reinicia-a.

Para desenvolver sem instalar, usa a variável `PORTFOLIO_PLUGINS` com uma lista de `módulo:função` separada por
vírgulas (o módulo tem de estar no `PYTHONPATH`):

```bash
PORTFOLIO_PLUGINS=o_meu_plugin:register python -m portfolio_investimentos
```

## O que se pode registar

| Método | O que faz |
| --- | --- |
| `registry.blueprint(bp)` | Páginas e rotas próprias (com os templates e os ficheiros estáticos do pacote). As páginas usam `ctx.build(key, título)` para terem o menu e o topo da aplicação. |
| `registry.nav_item(key, label, url, icon, after=None, bottom=False)` | Um item no menu lateral, a seguir ao item `after` (ex.: `"fiscal"`); sem ele, no fim. `bottom=True` põe-no no grupo de baixo (Importar, Transações, Definições). `key` é o que a página passa a `ctx.build` para o item ficar ativo. Ícones: [Bootstrap Icons](https://icons.getbootstrap.com/). |
| `registry.settings_section(template, order=100)` | Um template incluído na página Definições, no fim da coluna da esquerda. |
| `registry.page_slot(page, slot, template)` | Um bloco num ponto fixo de uma página. Pontos disponíveis: `("fiscal", "top")`, `("fiscal", "bottom")`, `("carteira", "bottom")`. |
| `registry.action(fn, name=None)` | Uma ação da API: `POST /api/<nome>`, com o token CSRF, como as do núcleo (nas páginas: `pm.call("nome", {...})`). Não pode ter o nome de uma ação que já exista. |
| `registry.background(fn, every_seconds)` | Uma tarefa `fn(app)` chamada de `every_seconds` em `every_seconds` (mínimo 60), no contexto da aplicação. Só corre no arranque local (`python -m portfolio_investimentos`); em servidores como o PythonAnywhere não há tarefas em segundo plano. |
| `registry.context(fn)` | Variáveis extra para todos os templates: `fn()` devolve um dicionário. |

**Tabelas próprias:** um plugin pode definir modelos com o mesmo `db` (`from portfolio_investimentos.models import
db`). As tabelas novas são criadas no arranque (as migrações correm depois de carregar os plugins). Usa nomes com
um prefixo do plugin para não colidir com as tabelas da aplicação.

## Erros

Um plugin que falhe ao carregar (exceção no `register`, módulo inexistente, ação com um nome repetido) não impede a
aplicação de arrancar: fica no log e em `app.extensions["pm_plugins"].errors`. Um erro numa tarefa periódica fica
no log e a tarefa continua.

## Exemplo completo

`tests/plugin_exemplo.py` usa todos os pontos de extensão e é o que os testes (`tests/test_plugins.py`) carregam.
