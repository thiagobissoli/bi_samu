"""Menu lateral agrupado por afinidade."""

import app.main  # noqa: F401 — carrega os módulos e seus itens de menu
from app.core.modules import MENU_GRUPOS, agrupar_menu, get_menu


def _itens():
    return [
        {"label": "Lista de NCPS", "url": "/ncps", "group": "qualidade"},
        {"label": "Indicadores NCPS", "url": "/ncps/painel", "group": "qualidade"},
        {"label": "Usuários", "url": "/usuarios", "group": "acesso"},
        {"label": "Solto", "url": "/solto"},
    ]


def test_ativo_e_o_mais_especifico():
    arvore = agrupar_menu(_itens(), "/ncps/painel")
    qualidade = next(n for n in arvore if n.get("chave") == "qualidade")
    assert qualidade["aberto"]
    assert [i["ativo"] for i in qualidade["itens"]] == [False, True]
    acesso = next(n for n in arvore if n.get("chave") == "acesso")
    assert not acesso["aberto"]


def test_subpagina_acende_o_item_pai():
    arvore = agrupar_menu(_itens(), "/ncps/123")
    qualidade = next(n for n in arvore if n.get("chave") == "qualidade")
    assert qualidade["itens"][0]["ativo"]


def test_itens_soltos_primeiro_e_grupos_na_ordem():
    arvore = agrupar_menu(_itens(), "/")
    assert arvore[0]["tipo"] == "item" and arvore[0]["label"] == "Solto"
    ordens = [MENU_GRUPOS[n["chave"]]["order"] for n in arvore if n["tipo"] == "grupo"]
    assert ordens == sorted(ordens)


def test_todo_item_dos_modulos_tem_grupo():
    assert len(get_menu()) > 10
    assert all(i.get("group") in MENU_GRUPOS for i in get_menu())
