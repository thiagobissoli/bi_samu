"""Testes do módulo Investigação de Eventos."""

import re

from fastapi.testclient import TestClient

from app.core.seeds import ADMIN_EMAIL, ADMIN_SENHA
from app.main import app
from app.modules.investigacao.service import InvestigacaoService

client = TestClient(app)


def _login():
    client.post("/login", data={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})


def test_requer_login():
    resp = client.get("/investigacao/", headers={"accept": "text/html"},
                      follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_timeline_do_dia():
    """Ocupação por viatura, posicionada na régua de 24h."""
    _login()
    service = InvestigacaoService(1)
    dia = service.opcoes()["dia_max"]
    dados = client.get(f"/investigacao/api/timeline?dia={dia}").json()["data"]

    assert dados["dia"] == dia
    assert dados["unidades"], "nenhuma viatura na timeline"
    for unidade in dados["unidades"]:
        assert unidade["periodos"]
        for p in unidade["periodos"]:
            # posição dentro do dia (0–100%) e largura visível
            assert 0 <= p["esquerda"] <= 100
            assert 0 < p["largura"] <= 100
            assert p["esquerda"] + p["largura"] <= 100.5
            assert re.fullmatch(r"\d{2}/\d{2} \d{2}:\d{2}", p["inicio"])
            assert isinstance(p["fora"], bool)


def test_timeline_filtra_por_municipio():
    _login()
    service = InvestigacaoService(1)
    dia = service.opcoes()["dia_max"]
    todos = service.timeline_dia(dia)
    municipio = todos["unidades"][0]["municipio"]
    filtrado = service.timeline_dia(dia, municipios=[municipio])
    assert filtrado["unidades"]
    assert all(u["municipio"] == municipio for u in filtrado["unidades"])
    assert filtrado["total_unidades"] <= todos["total_unidades"]


def test_investigar_empenho_de_outro_municipio():
    """O caso de uso central: viatura de fora atendeu — as locais estavam ocupadas?"""
    _login()
    service = InvestigacaoService(1)
    dia = service.opcoes()["dia_max"]
    casos = service.cruzamentos(dia)["casos"]
    if not casos:
        return
    alvo = casos[0]

    dados = client.get(
        f"/investigacao/api/investigar?ocorrencia={alvo['ocorrencia']}"
    ).json()["data"]

    assert dados["ocorrencia"] == alvo["ocorrencia"]
    assert dados["fora_do_municipio"] is True
    # a sede da viatura difere do município da ocorrência
    assert dados["municipio_unidade"] != dados["cidade"]
    assert dados["veredito"]
    # cada viatura do município tem um estado conclusivo no instante
    for s in dados["situacoes"]:
        assert s["status"] in ("ocupada", "atendeu", "sem_empenho")
        if s["status"] == "ocupada":
            assert s["ocorrencia"] and s["desde"] and s["ate"]
    assert dados["n_ocupadas"] + dados["n_livres"] <= len(dados["situacoes"])


def test_investigar_ocorrencia_inexistente():
    _login()
    corpo = client.get("/investigacao/api/investigar?ocorrencia=000000").json()
    assert corpo["success"] is False
    assert "não encontrada" in corpo["message"]


def test_ocupada_no_instante_bate_com_a_timeline():
    """Uma viatura marcada 'ocupada' tem período cobrindo o acionamento."""
    from datetime import datetime

    service = InvestigacaoService(1)
    dia = service.opcoes()["dia_max"]
    for caso in service.cruzamentos(dia)["casos"]:
        dados = service.investigar(caso["ocorrencia"])
        ocupadas = [s for s in dados["situacoes"] if s["status"] == "ocupada"]
        if not ocupadas:
            continue
        momento = datetime.strptime(dados["momento"], "%d/%m/%Y %H:%M")
        for s in ocupadas:
            desde = datetime.strptime(f"{s['desde']}/{momento.year}",
                                      "%d/%m %H:%M/%Y")
            ate = datetime.strptime(f"{s['ate']}/{momento.year}",
                                    "%d/%m %H:%M/%Y")
            assert desde <= momento <= ate, (s["unidade"], s["desde"], s["ate"])
        return   # um caso com ocupadas basta


def test_pagina_e_menu():
    _login()
    pagina = client.get("/investigacao/", headers={"accept": "text/html"})
    assert pagina.status_code == 200
    assert "Investigar ocorrência" in pagina.text
    assert "tl-periodo" in pagina.text          # barras da timeline
    assert "Empenhos de outro município" in pagina.text
    # a ressalva sobre o significado de "sem empenho" é obrigatória
    assert "fora de escala" in pagina.text

    home = client.get("/", headers={"accept": "text/html"})
    assert "Investigação de Eventos" in home.text
