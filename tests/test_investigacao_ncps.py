"""Investigação de eventos a partir de uma NCPS (e NCPS dentro do dossiê)."""

import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.seeds import ADMIN_EMAIL, ADMIN_SENHA
from app.main import app

client = TestClient(app)
HTML = {"accept": "text/html"}


def _login():
    client.post("/login", data={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})


def _uma_ocorrencia() -> str:
    from app.modules.download_vsky.models import VskyRegistroAnalitico as R
    db = SessionLocal()
    try:
        return db.scalar(select(R.ocorrencia).where(
            R.ocorrencia.isnot(None), R.chegada_no_local.isnot(None),
            R.deleted_at.is_(None)).order_by(R.id.desc()).limit(1))
    finally:
        db.close()


def _notificar(**dados) -> int:
    html = client.post("/ncps/notificar", data={"natureza": "paciente", **dados}).text
    return int(re.search(r'Protocolo</small>\s*<span[^>]*>(\d+)<', html).group(1))


def test_ncps_com_ocorrencia_abre_o_dossie_com_o_relato():
    _login()
    numero = _uma_ocorrencia()
    ncps_id = _notificar(descricao="Relato de teste: demora na passagem do caso.",
                         id_ocorrencia=f" {numero} ")
    html = client.get(f"/investigacao/?ncps={ncps_id}", headers=HTML).text
    assert f"NCPS #{ncps_id}" in html
    assert "Cadeia do chamado" in html                  # seguiu pela ocorrência
    assert "Notificações NCPS sobre esta ocorrência" in html

    # pela ocorrência, a NCPS aparece e vai para o material da IA
    html = client.get(f"/investigacao/?ocorrencia={numero}", headers=HTML).text
    assert f"/ncps/{ncps_id}" in html
    from app.models import Usuario
    from app.modules.investigacao.ia_analise import montar_prompt
    from app.modules.investigacao.service import InvestigacaoService
    db = SessionLocal()
    try:
        admin = db.scalar(select(Usuario).where(Usuario.email == ADMIN_EMAIL))
        prompt = montar_prompt(InvestigacaoService(1).dossie(db, numero, admin))
        assert "demora na passagem do caso" in prompt
        # sem usuário (sem permissão de NCPS) o relato não entra
        assert "demora na passagem" not in montar_prompt(
            InvestigacaoService(1).dossie(db, numero))
    finally:
        db.close()


def test_ncps_sem_ocorrencia_permite_vincular():
    _login()
    ncps_id = _notificar(descricao="Relato sem número de ocorrência.")
    html = client.get(f"/investigacao/?ncps={ncps_id}", headers=HTML).text
    assert "não informa a ocorrência" in html and "Vincular e investigar" in html

    numero = _uma_ocorrencia()
    resp = client.post("/investigacao/vincular-ncps",
                       data={"ncps": ncps_id, "ocorrencia": numero},
                       follow_redirects=False)
    assert resp.status_code == 303 and "erro_ia" not in resp.headers["location"]
    html = client.get(resp.headers["location"], headers=HTML).text
    assert "Cadeia do chamado" in html

    invalida = client.post("/investigacao/vincular-ncps",
                           data={"ncps": ncps_id, "ocorrencia": "999999999999"},
                           follow_redirects=False)
    assert "erro_ia" in invalida.headers["location"]


def test_ncps_sigilosa_nao_entra_na_investigacao():
    _login()
    ncps_id = _notificar(natureza="trabalhador", tipo_evento_trab="violencia_assedio",
                         descricao="Relato sigiloso de teste.",
                         id_ocorrencia=_uma_ocorrencia())
    html = client.get(f"/investigacao/?ncps={ncps_id}", headers=HTML).text
    assert "sigilosa" in html and "Relato sigiloso de teste" not in html


def test_ncps_inexistente():
    _login()
    html = client.get("/investigacao/?ncps=99999999", headers=HTML).text
    assert "NCPS #99999999 não encontrada" in html


def test_rac_de_ncps_sem_ocorrencia(monkeypatch):
    """NCPS sem ocorrência no vSky gera, aprova e imprime o FOR.SAMU.038."""
    from tests.test_investigacao import _mock_ia

    _login()
    capturado = _mock_ia(monkeypatch)
    ncps_id = _notificar(descricao="Paciente caiu da maca durante a transferência.",
                         sugestao="Revisar travas das macas.")
    # análise já registrada na NCPS também alimenta o RAC
    client.post(f"/ncps/{ncps_id}", data={"secao": "causa_add", "metodo": "londres",
                                          "categoria": "2", "descricao": "Trava da maca gasta",
                                          "causa_raiz": "1"})
    html = client.get(f"/investigacao/?ncps={ncps_id}", headers=HTML).text
    assert "FOR.SAMU.038" in html and "Cadeia do chamado" not in html
    assert "Incluir o texto do prontuário" not in html

    chave = f"NCPS-{ncps_id}"
    resp = client.post("/investigacao/analisar", data={"ocorrencia": chave},
                       follow_redirects=False)
    assert resp.status_code == 303 and "erro_ia" not in resp.headers["location"]
    prompt = capturado["prompt"]
    assert "caiu da maca" in prompt and "Trava da maca gasta" in prompt
    assert "não há ocorrência" in prompt and "FOR.SAMU.038" in prompt

    resp = client.post("/investigacao/aprovar", data={
        "ocorrencia": chave, "risco_pos_probabilidade": "2",
        "risco_pos_consequencia": "4", "risco_pos_justificativa": "ok"})
    assert resp.status_code == 200
    pdf = client.get(f"/investigacao/rac.pdf?ocorrencia={chave}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    pagina = client.get(f"/investigacao/?ocorrencia={chave}", headers=HTML).text
    assert f"NCPS #{ncps_id}" in pagina and "Abrir PDF aprovado" in pagina

    relatorios = client.get("/investigacao/relatorios", headers=HTML).text
    assert chave in relatorios
