"""Testes do módulo Download vSky."""

import re

import pytest
from fastapi.testclient import TestClient

from app.core.seeds import ADMIN_EMAIL, ADMIN_SENHA
from app.main import app

client = TestClient(app)

LINHA_A = {
    "ocorrencia": "2710199", "codigo_da_ocorrencia": "Queda de Ligação",
    "status_da_ocorrencia": "Encerrada", "sexo": "M",
    "telefone": "27996920323", "data_ocorrencia": "06/08/2026 00:03:31",
}
LINHA_B = {
    "ocorrencia": "2710213", "codigo_da_ocorrencia": "Trauma",
    "status_da_ocorrencia": "Encerrada", "sexo": "F",
    "telefone": "27996450771", "data_ocorrencia": "06/08/2026 00:27:39",
}


def _login():
    client.post("/login", data={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})


def _configurar_credenciais():
    from app.core.config_service import set_config
    from app.core.database import SessionLocal
    from app.modules.download_vsky.constants import CONFIG_SENHA, CONFIG_USUARIO

    db = SessionLocal()
    try:
        set_config(db, CONFIG_USUARIO, "usuario.teste", empresa_id=1)
        set_config(db, CONFIG_SENHA, "senha-teste", empresa_id=1)
    finally:
        db.close()


def _limpar_credenciais():
    from app.core.config_service import set_config
    from app.core.database import SessionLocal
    from app.modules.download_vsky.constants import CONFIG_SENHA, CONFIG_USUARIO

    db = SessionLocal()
    try:
        set_config(db, CONFIG_USUARIO, None, empresa_id=1)
        set_config(db, CONFIG_SENHA, None, empresa_id=1)
    finally:
        db.close()


class _ClientFake:
    """Substitui VskyClient nos testes — devolve um 'XLS' sintético."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def login(self):
        pass

    def gerar_total_registros_analitico(self, data_inicial, data_final,
                                        cliente_id=None):
        return b"xls-fake"


def _stub_client(monkeypatch, linhas):
    from app.modules.download_vsky import service as svc

    monkeypatch.setattr(svc, "VskyClient", _ClientFake)
    monkeypatch.setattr(svc, "parse_xls", lambda content: [dict(l) for l in linhas])


def test_requer_login():
    response = client.get("/download_vsky/", headers={"accept": "text/html"},
                          follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_index():
    _login()
    response = client.get("/download_vsky/", headers={"accept": "text/html"})
    assert response.status_code == 200
    assert "Download vSky" in response.text


def test_config_page():
    _login()
    response = client.get("/download_vsky/config", headers={"accept": "text/html"})
    assert response.status_code == 200
    assert "vSky" in response.text


def test_validar_periodo():
    from app.modules.download_vsky.validators import data_iso_para_br, validar_periodo

    assert validar_periodo("01/08/2026", "06/08/2026") == ("01/08/2026", "06/08/2026")
    assert data_iso_para_br("2026-08-01") == "01/08/2026"
    with pytest.raises(ValueError):
        validar_periodo("06/08/2026", "01/08/2026")
    with pytest.raises(ValueError):
        validar_periodo("2026-13-45", "01/08/2026")


def test_normalizar_base_url():
    from app.modules.download_vsky.validators import normalizar_base_url

    assert normalizar_base_url(
        "https://es.vskysamu.com.br/vskymanagement/login.xhtml"
    ) == "https://es.vskysamu.com.br"
    assert normalizar_base_url("gestao-es.vskysamu.com.br") == \
        "https://gestao-es.vskysamu.com.br"
    assert normalizar_base_url("https://gestao-es.vskysamu.com.br/") == \
        "https://gestao-es.vskysamu.com.br"
    assert normalizar_base_url("") == ""


def test_linha_hash_considera_linha_inteira():
    from app.modules.download_vsky.importer import linha_hash

    assert linha_hash(LINHA_A) == linha_hash(dict(LINHA_A))
    alterada = dict(LINHA_A, telefone="27000000000")
    assert linha_hash(LINHA_A) != linha_hash(alterada)


def test_importar_sem_credenciais():
    _limpar_credenciais()
    _login()
    response = client.post("/download_vsky/importar",
                           data={"data_inicial": "2026-08-01",
                                 "data_final": "2026-08-06"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert "erro=" in response.headers["location"]


def _limpar_registros_de_teste():
    """dev.db persiste entre execuções — remove as linhas destes testes."""
    from sqlalchemy import delete
    from app.core.database import SessionLocal
    from app.modules.download_vsky.models import VskyRegistroAnalitico

    db = SessionLocal()
    try:
        db.execute(delete(VskyRegistroAnalitico).where(
            VskyRegistroAnalitico.ocorrencia.in_(
                [LINHA_A["ocorrencia"], LINHA_B["ocorrencia"]])))
        db.commit()
    finally:
        db.close()


def test_importacao_e_dedupe(monkeypatch):
    _stub_client(monkeypatch, [LINHA_A, LINHA_B, LINHA_A])  # A duplicada no arquivo
    _limpar_registros_de_teste()
    _configurar_credenciais()
    _login()

    response = client.post("/download_vsky/importar",
                           data={"data_inicial": "2026-08-01",
                                 "data_final": "2026-08-06"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert "msg=" in response.headers["location"]

    payload = client.get("/download_vsky/api").json()
    ultima = payload["data"][0]
    assert ultima["status"] == "concluido"
    assert ultima["total_linhas"] == 3
    assert ultima["linhas_novas"] == 2
    assert ultima["linhas_duplicadas"] == 1

    # Reimportar o mesmo período: nada novo, tudo duplicado.
    response = client.post("/download_vsky/api",
                           json={"data_inicial": "2026-08-01",
                                 "data_final": "2026-08-06"})
    assert response.status_code == 201
    dados = response.json()["data"]
    assert dados["linhas_novas"] == 0
    assert dados["linhas_duplicadas"] == 3

    # Busca pela ocorrência: independe da posição na paginação (o dev.db
    # compartilhado pode ter registros com datas mais recentes).
    registros = client.get("/download_vsky/registros?q=2710199",
                           headers={"accept": "text/html"})
    assert registros.status_code == 200
    assert "2710199" in registros.text


def test_download_automatico_agendamento():
    """Salvar a configuração cria/remove o job agendado conforme o toggle."""
    from app.core.config_service import get_config, invalidate_config, set_config
    from app.core.database import SessionLocal
    from app.modules.download_vsky import scheduler

    _login()
    db = SessionLocal()
    chaves = ["vsky_base_url", "vsky_usuario", "vsky_senha", "vsky_cliente_id",
              "vsky_auto_ativo", "vsky_auto_modo", "vsky_auto_hora",
              "vsky_auto_intervalo", "vsky_auto_dias"]
    orig = {k: get_config(db, k, empresa_id=1) for k in chaves}
    try:
        # liga: diariamente às 05:45, últimos 3 dias
        resp = client.post("/download_vsky/config", data={
            "base_url": orig["vsky_base_url"] or "https://gestao-es.vskysamu.com.br",
            "usuario_vsky": orig["vsky_usuario"] or "u", "senha_vsky": "",
            "cliente_id": orig["vsky_cliente_id"] or "",
            "auto_ativo": "1", "auto_modo": "diario", "auto_hora": "05:45",
            "auto_dias": "3"}, follow_redirects=False)
        invalidate_config()
        assert resp.status_code == 303
        assert "05%3A45" in resp.headers["location"] or "05:45" in resp.headers["location"]
        assert get_config(db, "vsky_auto_ativo", empresa_id=1) == "1"
        proxima = scheduler.proxima_execucao()
        assert proxima is not None and "05:45" in proxima

        # intervalo abaixo do mínimo é elevado ao mínimo
        client.post("/download_vsky/config", data={
            "base_url": orig["vsky_base_url"] or "https://gestao-es.vskysamu.com.br",
            "usuario_vsky": orig["vsky_usuario"] or "u", "senha_vsky": "",
            "auto_ativo": "1", "auto_modo": "intervalo", "auto_intervalo": "1",
            "auto_dias": "2"}, follow_redirects=False)
        invalidate_config()
        assert int(get_config(db, "vsky_auto_intervalo", empresa_id=1)) >= 15

        # desliga: job removido
        client.post("/download_vsky/config", data={
            "base_url": orig["vsky_base_url"] or "https://gestao-es.vskysamu.com.br",
            "usuario_vsky": orig["vsky_usuario"] or "u", "senha_vsky": "",
            "auto_modo": "diario"}, follow_redirects=False)
        invalidate_config()
        assert scheduler.proxima_execucao() is None
    finally:
        for k, v in orig.items():
            set_config(db, k, v, empresa_id=1)
        invalidate_config()
        scheduler.sincronizar()
        db.close()


def test_calendario_de_cobertura():
    """A página inicial exibe o calendário com dias com/sem registros."""
    _login()
    resp = client.get("/download_vsky/", headers={"accept": "text/html"})
    assert resp.status_code == 200
    assert "Cobertura de dados por dia" in resp.text
    # havendo registros importados, há células de dia com registros
    from app.core.database import SessionLocal
    from app.modules.download_vsky.service import DownloadVskyService

    db = SessionLocal()
    try:
        cal = DownloadVskyService(db, 1).calendario_cobertura()
    finally:
        db.close()
    if cal["meses"]:
        assert "cal-com" in resp.text
        # todo dia entre o início e hoje é classificado (com/sem)
        total_dias = sum(1 for m in cal["meses"] for s in m["semanas"]
                         for d in s if d and d["status"] in ("com", "sem"))
        assert total_dias > 0
        # dias sem registro aparecem como célula clicável
        if cal["dias_sem"]:
            assert "cal-sem" in resp.text


def test_importacao_com_falha_no_portal(monkeypatch):
    from app.modules.download_vsky import service as svc
    from app.modules.download_vsky.vsky_client import VskyError

    class _ClientFalho(_ClientFake):
        def login(self):
            raise VskyError("Autenticação no vSky recusada — confira usuário e senha.")

    monkeypatch.setattr(svc, "VskyClient", _ClientFalho)
    _configurar_credenciais()
    _login()

    response = client.post("/download_vsky/api",
                           json={"data_inicial": "2026-08-01",
                                 "data_final": "2026-08-06"})
    assert response.status_code == 502
    payload = response.json()
    assert payload["success"] is False
    assert "recusada" in payload["data"]["erro"]


def test_periodo_invalido_na_api(monkeypatch):
    _stub_client(monkeypatch, [])
    _configurar_credenciais()
    _login()
    response = client.post("/download_vsky/api",
                           json={"data_inicial": "2026-08-10",
                                 "data_final": "2026-08-01"})
    assert response.status_code == 422
    assert response.json()["success"] is False


def test_download_automatico_usa_formato_de_data_aceito(monkeypatch):
    """O job agendado deve chamar a importação no formato dd/mm/aaaa.

    Passar ISO (aaaa-mm-dd) fazia toda execução automática falhar com
    'Datas devem estar no formato dd/mm/aaaa' — e o erro só aparecia no
    status da configuração, nunca na importação manual.
    """
    from app.core.config_service import get_config, set_config
    from app.core.database import SessionLocal
    from app.modules.download_vsky import scheduler
    from app.modules.download_vsky.constants import (CONFIG_AUTO_STATUS,
                                                     STATUS_CONCLUIDO)
    from app.modules.download_vsky.validators import validar_periodo

    recebido = {}

    class ServicoFalso:
        def __init__(self, db, empresa_id):
            pass

        def importar_periodo(self, data_inicial, data_final, *a, **k):
            # o validador real é quem reprovava as datas do agendador
            recebido["periodo"] = validar_periodo(data_inicial, data_final)

            class Item:
                status = STATUS_CONCLUIDO
                linhas_novas = 3
                linhas_duplicadas = 1
                erro = None
            return Item()

    import app.modules.download_vsky.service as servico_mod
    monkeypatch.setattr(servico_mod, "DownloadVskyService", ServicoFalso)

    db = SessionLocal()
    try:
        set_config(db, "vsky_usuario", "u", empresa_id=1)
        set_config(db, "vsky_senha", "s", empresa_id=1)
    finally:
        db.close()

    scheduler.executar_download_automatico(1)

    assert "periodo" in recebido, "a importação não chegou a ser chamada"
    inicial, final = recebido["periodo"]
    assert re.fullmatch(r"\d{2}/\d{2}/\d{4}", inicial), inicial
    assert re.fullmatch(r"\d{2}/\d{2}/\d{4}", final), final

    db = SessionLocal()
    try:
        status = get_config(db, CONFIG_AUTO_STATUS, empresa_id=1) or ""
    finally:
        db.close()
    assert status.startswith("sucesso"), status
