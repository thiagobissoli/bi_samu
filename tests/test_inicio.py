"""Página inicial: boas-vindas, alertas e retorno das NCPS."""

import re
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.seeds import ADMIN_EMAIL, ADMIN_SENHA
from app.main import app
from app.modules.inicio import service as inicio


def _id_pelo_codigo(html: str) -> int:
    """Confirmação mostra só o código; o id sai da busca por ele."""
    from app.core.database import SessionLocal as _S
    from app.modules.ncps.service import buscar_acompanhamento
    codigo = re.search(r'font-monospace[^>]*>([A-Z0-9]{8})<', html).group(1)
    assert "Protocolo" not in html            # o número não é informado
    db = _S()
    try:
        return buscar_acompanhamento(db, 1, codigo).id
    finally:
        db.close()

client = TestClient(app)


def _login():
    client.post("/login", data={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})


def test_saudacao_pelo_primeiro_nome():
    u = SimpleNamespace(nome="Maria da Silva")
    assert inicio.boas_vindas(u, "America/Sao_Paulo")["saudacao"].endswith("Maria")


def test_pagina_inicial_mostra_blocos():
    _login()
    html = client.get("/", headers={"accept": "text/html"}).text
    assert "Seus alertas" in html and "Seus dados" in html
    assert re.search(r"(Bom dia|Boa tarde|Boa noite), ", html)
    assert "Indicadores de gestão" in html            # admin vê o bloco


def test_ncps_pendente_vira_alerta_e_resposta_chega_ao_notificante():
    _login()
    html = client.post("/ncps/notificar", data={
        "natureza": "paciente", "descricao": "Teste de alerta da página inicial"}).text
    ncps_id = _id_pelo_codigo(html)

    db = SessionLocal()
    try:
        from app.models import Usuario
        admin = db.query(Usuario).filter(Usuario.email == ADMIN_EMAIL).one()
        titulos = [a["titulo"] for a in inicio.alertas(db, admin)]
        assert any("aguardando avaliação" in t for t in titulos)
    finally:
        db.close()

    # a triagem muda o status: quem notificou recebe o retorno
    client.post(f"/ncps/{ncps_id}", data={"secao": "triagem", "status": "2",
                                          "procedente": "2", "natureza": "paciente"})
    db = SessionLocal()
    try:
        admin = db.query(Usuario).filter(Usuario.email == ADMIN_EMAIL).one()
        respostas = inicio.respostas_ncps(db, admin)
        assert any(r["id"] == ncps_id and r["situacao"] == "Análise concluída"
                   for r in respostas)
        recentes = [n.titulo for n in inicio.notificacoes_recentes(db, admin, 10)]
        assert f"Sua NCPS #{ncps_id}: Análise concluída" in recentes
    finally:
        db.close()
