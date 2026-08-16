"""Testes do módulo Backup.

Não geram dump real (o banco tem centenas de MB): o que importa aqui é a
mecânica em volta — retenção, proteção do download e, sobretudo, que a senha
do banco nunca apareça na linha de comando.
"""

import gzip

import pytest
from fastapi.testclient import TestClient

from app.core.seeds import ADMIN_EMAIL, ADMIN_SENHA
from app.main import app
from app.modules.backup import service
from app.modules.backup.constants import PREFIXO

client = TestClient(app)


def _login():
    client.post("/login", data={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})


def _copia_falsa(pasta, nome: str):
    arquivo = pasta / nome
    with gzip.open(arquivo, "wb") as saida:
        saida.write(b"-- dump de teste\n" * 200)
    return arquivo


def test_requer_login():
    resp = client.get("/backup/", headers={"accept": "text/html"},
                      follow_redirects=False)
    assert resp.status_code == 303


def test_pagina_avisa_quando_nao_ha_copia(monkeypatch, tmp_path):
    _login()
    monkeypatch.setattr(service, "diretorio", lambda *a, **k: tmp_path)
    html = client.get("/backup/", headers={"accept": "text/html"}).text
    assert "Não há nenhuma cópia de segurança" in html


def test_listagem_da_mais_recente_para_a_mais_antiga(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "diretorio", lambda *a, **k: tmp_path)
    for nome in (f"{PREFIXO}-20260101-020000.sql.gz",
                 f"{PREFIXO}-20260103-020000.sql.gz",
                 f"{PREFIXO}-20260102-020000.sql.gz"):
        _copia_falsa(tmp_path, nome)
    nomes = [c["nome"] for c in service.listar()]
    assert nomes == [f"{PREFIXO}-20260103-020000.sql.gz",
                     f"{PREFIXO}-20260102-020000.sql.gz",
                     f"{PREFIXO}-20260101-020000.sql.gz"]
    assert service.listar()[0]["tamanho_mb"] >= 0


def test_expurgo_mantem_apenas_as_n_mais_recentes(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "diretorio", lambda *a, **k: tmp_path)
    monkeypatch.setattr(service, "_quantos_manter", lambda *a, **k: 2)
    for dia in range(1, 6):
        _copia_falsa(tmp_path, f"{PREFIXO}-202601{dia:02d}-020000.sql.gz")

    removidos = service.expurgar(db=None)

    assert removidos == 3
    restantes = sorted(p.name for p in tmp_path.glob("*.gz"))
    assert restantes == [f"{PREFIXO}-20260104-020000.sql.gz",
                         f"{PREFIXO}-20260105-020000.sql.gz"]


def test_download_recusa_caminho_para_fora_da_pasta(monkeypatch, tmp_path):
    """'..' no nome não pode servir arquivo de fora da pasta de cópias."""
    monkeypatch.setattr(service, "diretorio", lambda *a, **k: tmp_path)
    (tmp_path.parent / "segredo.env").write_text("SENHA=123")

    with pytest.raises(service.BackupError):
        service.caminho_seguro(None, 1, "../segredo.env")
    with pytest.raises(service.BackupError):
        service.caminho_seguro(None, 1, "/etc/passwd")

    _copia_falsa(tmp_path, f"{PREFIXO}-20260101-020000.sql.gz")
    ok = service.caminho_seguro(None, 1, f"{PREFIXO}-20260101-020000.sql.gz")
    assert ok.parent == tmp_path.resolve()


def test_senha_do_banco_nunca_vai_na_linha_de_comando(monkeypatch, tmp_path):
    """Argumento de processo é público na máquina — a senha vai por MYSQL_PWD."""
    from sqlalchemy.engine import make_url

    capturado = {}

    class _Processo:
        returncode = 0
        stdout = b"-- dump\n" * 500
        stderr = b""

    def _run(comando, **kwargs):
        capturado["comando"] = comando
        capturado["env"] = kwargs.get("env") or {}
        return _Processo()

    monkeypatch.setattr(service.shutil, "which", lambda _: "/usr/bin/mysqldump")
    monkeypatch.setattr(service.subprocess, "run", _run)
    url = make_url("mysql+pymysql://root:senha-secreta@localhost:3306/samu")

    service._dump_mysql(url, tmp_path / "saida.sql.gz")

    assert "senha-secreta" not in " ".join(capturado["comando"])
    assert capturado["env"]["MYSQL_PWD"] == "senha-secreta"
    # sem isto a restauração falha na própria instância de origem
    assert "--set-gtid-purged=OFF" in capturado["comando"]
    assert "--single-transaction" in capturado["comando"]


def test_dump_repete_sem_gtid_quando_a_opcao_nao_existe(monkeypatch, tmp_path):
    """MariaDB não conhece --set-gtid-purged; a cópia não pode falhar por isso."""
    from sqlalchemy.engine import make_url

    tentativas = []

    class _Falha:
        returncode = 2
        stdout = b""
        stderr = b"mysqldump: unknown option '--set-gtid-purged=OFF'"

    class _Sucesso:
        returncode = 0
        stdout = b"-- dump\n" * 500
        stderr = b""

    def _run(comando, **kwargs):
        tentativas.append(comando)
        return _Falha() if "--set-gtid-purged=OFF" in comando else _Sucesso()

    monkeypatch.setattr(service.shutil, "which", lambda _: "/usr/bin/mysqldump")
    monkeypatch.setattr(service.subprocess, "run", _run)
    url = make_url("mysql+pymysql://root:x@localhost/samu")

    destino = tmp_path / "saida.sql.gz"
    service._dump_mysql(url, destino)

    assert len(tentativas) == 2
    assert destino.is_file() and destino.stat().st_size > 0


def test_erro_do_mysqldump_vira_mensagem_legivel(monkeypatch, tmp_path):
    from sqlalchemy.engine import make_url

    class _Falha:
        returncode = 1
        stdout = b""
        stderr = b"Access denied for user 'root'@'localhost'"

    monkeypatch.setattr(service.shutil, "which", lambda _: "/usr/bin/mysqldump")
    monkeypatch.setattr(service.subprocess, "run", lambda *a, **k: _Falha())
    url = make_url("mysql+pymysql://root:x@localhost/samu")

    with pytest.raises(service.BackupError, match="Access denied"):
        service._dump_mysql(url, tmp_path / "saida.sql.gz")


def test_falta_do_mysqldump_orienta_a_instalacao(monkeypatch, tmp_path):
    from sqlalchemy.engine import make_url

    monkeypatch.setattr(service.shutil, "which", lambda _: None)
    with pytest.raises(service.BackupError, match="mysqldump não encontrado"):
        service._dump_mysql(make_url("mysql+pymysql://root:x@localhost/samu"),
                            tmp_path / "s.sql.gz")


def test_job_agendado_nunca_derruba_o_scheduler(monkeypatch):
    """Falha no backup vira status na tela, não exceção que mata o job."""
    from app.modules.backup import scheduler

    monkeypatch.setattr("app.modules.backup.service.executar",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("disco cheio")))
    status = scheduler.executar_backup(empresa_id=1)
    assert "erro" in status.lower() and "disco cheio" in status


def test_api_resume_a_situacao(monkeypatch, tmp_path):
    _login()
    monkeypatch.setattr(service, "diretorio", lambda *a, **k: tmp_path)
    _copia_falsa(tmp_path, f"{PREFIXO}-20260101-020000.sql.gz")
    corpo = client.get("/backup/api").json()
    assert corpo["success"] is True
    dados = corpo["data"]
    assert dados["total"] == 1
    for campo in ("ativo", "ultima", "status", "proxima", "copias"):
        assert campo in dados, campo
