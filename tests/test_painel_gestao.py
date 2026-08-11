"""Testes do módulo Painel de Gestão."""

from fastapi.testclient import TestClient

from app.core.seeds import ADMIN_EMAIL, ADMIN_SENHA
from app.main import app

client = TestClient(app)


def _login():
    client.post("/login", data={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})


def test_requer_login():
    resp = client.get("/painel_gestao/", headers={"accept": "text/html"},
                      follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_pagina_renderiza():
    _login()
    resp = client.get("/painel_gestao/", headers={"accept": "text/html"})
    assert resp.status_code == 200
    assert "Painel de Gestão" in resp.text
    # formato próprio: seções coloridas, sem a barra de filtros dos dashboards
    assert 'name="transporte"' not in resp.text
    for secao in ["Tempo Resposta", "Assertividade ISCMV",
                  "Transferência Inter-hospitalar", "Plantão", "Desperdício"]:
        assert secao in resp.text, secao


def test_api_payload():
    _login()
    corpo = client.get("/painel_gestao/api").json()
    assert corpo["success"] is True
    dados = corpo["data"]
    ids = [s["id"] for s in dados["secoes"]]
    assert ids == ["tr", "assertividade", "transferencia", "plantao",
                   "desperdicio"]
    assert dados["semana"]
    # período (segunda a domingo) da última semana completa
    import re
    assert re.fullmatch(r"\d{2}/\d{2}/\d{4} a \d{2}/\d{2}/\d{4}",
                        dados["semana_periodo"])
    # a semana escolhida tem dados em todos os 7 dias (ou ao menos 6)
    from app.modules.indicadores import nucleo
    df = nucleo.carregar(1)
    dias = df[df["semana_iso"] == dados["semana"]]["dia"].nunique()
    assert dias >= 6
    # TR: 3 blocos (Convênio, USA, USB), cada um com UM KPI da última
    # semana + gráfico com as linhas Geral/Diurno/Noturno
    tr = dados["secoes"][0]
    assert len(tr["blocos"]) == 3
    for bloco in tr["blocos"]:
        assert [k["label"] for k in bloco["kpis"]] == ["Última semana"]
        assert bloco["chart"]["tipo"] == "line"
        assert [ds["label"] for ds in bloco["chart"]["datasets"]] == \
            ["Geral", "Diurno", "Noturno"]
    assert len(dados["charts_flat"]) == sum(len(s["blocos"])
                                            for s in dados["secoes"])


def test_menu_e_permissao():
    _login()
    home = client.get("/", headers={"accept": "text/html"})
    assert "Painel de Gestão" in home.text
