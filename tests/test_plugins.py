"""Extensões (plugins.py): um plugin de exemplo (tests/plugin_exemplo.py) carregado por PORTFOLIO_PLUGINS."""
import re

import pytest

from portfolio_investimentos import create_app


def _app(tmp_path, monkeypatch, plugins):
    monkeypatch.setenv("PORTFOLIO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PORTFOLIO_PLUGINS", plugins)
    return create_app({"TESTING": True})


def _csrf(client):
    return re.search(r'csrf_token = "([0-9a-f]+)"', client.get("/").get_data(as_text=True)).group(1)


@pytest.fixture(autouse=True)
def _clean_actions():
    """As ações registadas por um plugin ficam no dicionário global da API: tira-as no fim de cada teste."""
    from portfolio_investimentos.api import ACTIONS
    before = set(ACTIONS)
    yield
    for name in set(ACTIONS) - before:
        ACTIONS.pop(name)


def test_plugin_points(tmp_path, monkeypatch):
    import plugin_exemplo
    app = _app(tmp_path, monkeypatch, "plugin_exemplo:register")
    reg = app.extensions["pm_plugins"]
    assert reg.loaded == ["plugin_exemplo:register"] and reg.errors == {}
    client = app.test_client()
    home = client.get("/").get_data(as_text=True)
    # o item novo no menu, logo a seguir ao Fiscal
    links = re.findall(r'<a href="(/[a-z]*)" class="nav-link', home)
    assert links.index("/exemplo") == links.index("/fiscal") + 1
    page = client.get("/exemplo")
    assert page.status_code == 200 and "Página do plugin de exemplo (versão 1.0)" in page.get_data(as_text=True)
    assert 'id="exemploDefinicoes"' in client.get("/definicoes").get_data(as_text=True)
    token = _csrf(client)
    client.post("/api/load_demo", headers={"X-CSRF-Token": token})
    assert 'id="exemploFiscal"' in client.get("/fiscal").get_data(as_text=True)
    r = client.post("/api/exemplo_ola", data={"nome": "Helder"}, headers={"X-CSRF-Token": token})
    assert r.get_json()["message"] == "Olá, Helder!"
    assert client.post("/api/exemplo_ola", headers={"X-CSRF-Token": "x"}).status_code == 403  # CSRF como no núcleo
    # tarefa periódica: registada e corre no contexto da aplicação
    from portfolio_investimentos import __main__ as main
    assert [fn for fn, _ in reg.tasks] == [plugin_exemplo.tarefa] and reg.tasks[0][1] == 3600
    plugin_exemplo.TICKS.clear()
    main._plugin_task_loop(app, plugin_exemplo.tarefa, 0, rounds=2)
    assert plugin_exemplo.TICKS == [app.name, app.name]


def test_broken_plugins_do_not_stop_the_app(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, "plugin_exemplo:register_partido,plugin_exemplo:register_repetido,nao_existe:register")
    reg = app.extensions["pm_plugins"]
    assert reg.loaded == []
    assert "este plugin falha" in reg.errors["plugin_exemplo:register_partido"]
    assert "set_broker" in reg.errors["plugin_exemplo:register_repetido"]
    assert "ModuleNotFoundError" in reg.errors["nao_existe:register"]
    client = app.test_client()
    assert client.get("/").status_code == 200 and client.get("/definicoes").status_code == 200


def test_unknown_page_slot_and_no_plugins(tmp_path, monkeypatch):
    from portfolio_investimentos import plugins
    app = _app(tmp_path, monkeypatch, "")
    reg = app.extensions["pm_plugins"]
    with pytest.raises(plugins.PluginError):
        reg.page_slot("visao", "topo", "x.html")
    assert reg.loaded == [] and reg.nav_items([("a", "A", "/a", "i")]) == [("a", "A", "/a", "i")]
    html = app.test_client().get("/").get_data(as_text=True)
    assert "/exemplo" not in html
