"""Cópia de segurança do banco (§35.16).

Executa `mysqldump` comprimido em gzip, guarda os arquivos numa pasta
configurável e mantém apenas as N cópias mais recentes. Também funciona
com SQLite (cópia consistente via API de backup do próprio SQLite).

A senha do banco NUNCA vai na linha de comando — iria parar na lista de
processos, visível a qualquer usuário da máquina. Segue por variável de
ambiente (MYSQL_PWD), que é o mecanismo previsto pelo cliente MySQL.
"""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.config import settings
from app.modules.backup.constants import (CONFIG_DIRETORIO, CONFIG_MANTER,
                                          MANTER_PADRAO, PREFIXO,
                                          TIMEOUT_DUMP)


class BackupError(RuntimeError):
    """Falha ao gerar a cópia (mensagem pronta para a tela)."""


def diretorio(db=None, empresa_id: int = 1) -> Path:
    """Pasta onde as cópias são guardadas (configurável)."""
    destino = ""
    if db is not None:
        from app.core.config_service import get_config
        destino = (get_config(db, CONFIG_DIRETORIO,
                              empresa_id=empresa_id) or "").strip()
    caminho = Path(destino) if destino else Path(settings.upload_dir) / "backups"
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho


def _quantos_manter(db, empresa_id: int = 1) -> int:
    from app.core.config_service import get_config
    try:
        return max(int(get_config(db, CONFIG_MANTER, str(MANTER_PADRAO),
                                  empresa_id) or MANTER_PADRAO), 1)
    except ValueError:
        return MANTER_PADRAO


def executar(db=None, empresa_id: int = 1) -> Path:
    """Gera uma cópia e devolve o caminho do arquivo. Levanta BackupError."""
    url = make_url(settings.database_url)
    pasta = diretorio(db, empresa_id)
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    if url.drivername.startswith("sqlite"):
        destino = pasta / f"{PREFIXO}-{carimbo}.sqlite.gz"
        _dump_sqlite(url.database, destino)
    else:
        destino = pasta / f"{PREFIXO}-{carimbo}.sql.gz"
        _dump_mysql(url, destino)

    if not destino.exists() or destino.stat().st_size < 1024:
        destino.unlink(missing_ok=True)
        raise BackupError("A cópia saiu vazia — verifique as credenciais do "
                          "banco e o espaço em disco.")
    if db is not None:
        expurgar(db, empresa_id)
    return destino


def _dump_mysql(url, destino: Path) -> None:
    if shutil.which("mysqldump") is None:
        raise BackupError(
            "mysqldump não encontrado no servidor. Instale o cliente MySQL "
            "(no macOS, 'brew install mysql-client'; no Windows ele vem com "
            "o MySQL Server).")
    base = [
        "mysqldump",
        f"--host={url.host or 'localhost'}",
        f"--port={url.port or 3306}",
        f"--user={url.username or 'root'}",
        "--single-transaction",     # não trava as tabelas durante a cópia
        "--routines", "--triggers", "--events",
        "--default-character-set=utf8mb4",
    ]
    # Sem isto o dump carrega o GTID do servidor e a restauração falha
    # justamente no caso mais provável — recuperar na mesma instância:
    # "@@GLOBAL.GTID_PURGED cannot be changed". MariaDB não tem a opção,
    # daí a nova tentativa sem ela.
    tentativas = [base + ["--set-gtid-purged=OFF", url.database],
                  base + [url.database]]
    ambiente = {**os.environ}
    if url.password:
        ambiente["MYSQL_PWD"] = url.password    # fora da linha de comando
    try:
        for indice, comando in enumerate(tentativas):
            processo = subprocess.run(comando, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, env=ambiente,
                                      timeout=TIMEOUT_DUMP, check=False)
            if processo.returncode == 0:
                break
            erro = (processo.stderr or b"").decode("utf-8", "ignore")
            ultima = indice == len(tentativas) - 1
            if ultima or "unknown option" not in erro.lower():
                raise BackupError(f"mysqldump falhou: {erro.strip()[:300]}")
        with gzip.open(destino, "wb") as saida:
            saida.write(processo.stdout)
    except subprocess.TimeoutExpired as exc:
        destino.unlink(missing_ok=True)
        raise BackupError(f"A cópia passou de {TIMEOUT_DUMP}s e foi "
                          "interrompida.") from exc
    except OSError as exc:
        destino.unlink(missing_ok=True)
        raise BackupError(f"Não foi possível gravar a cópia: {exc}") from exc


def _dump_sqlite(caminho_banco: str, destino: Path) -> None:
    """Cópia consistente mesmo com o sistema em uso."""
    import sqlite3
    import tempfile

    origem = Path(caminho_banco)
    if not origem.is_file():
        raise BackupError(f"Arquivo do banco não encontrado: {origem}")
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        temporario = Path(tmp.name)
    try:
        with sqlite3.connect(origem) as fonte, \
                sqlite3.connect(temporario) as copia:
            fonte.backup(copia)
        with open(temporario, "rb") as entrada, \
                gzip.open(destino, "wb") as saida:
            shutil.copyfileobj(entrada, saida)
    finally:
        temporario.unlink(missing_ok=True)


def listar(db=None, empresa_id: int = 1) -> list[dict]:
    """Cópias existentes, da mais recente para a mais antiga."""
    pasta = diretorio(db, empresa_id)
    arquivos = sorted(pasta.glob(f"{PREFIXO}-*.gz"), reverse=True)
    itens = []
    for arquivo in arquivos:
        info = arquivo.stat()
        itens.append({
            "nome": arquivo.name,
            "tamanho_mb": round(info.st_size / 1024 / 1024, 1),
            "criado_em": datetime.fromtimestamp(info.st_mtime).strftime(
                "%d/%m/%Y %H:%M"),
            "idade_dias": (datetime.now()
                           - datetime.fromtimestamp(info.st_mtime)).days,
        })
    return itens


def expurgar(db, empresa_id: int = 1) -> int:
    """Apaga as cópias que excedem o número a manter. Devolve quantas foram."""
    manter = _quantos_manter(db, empresa_id)
    pasta = diretorio(db, empresa_id)
    arquivos = sorted(pasta.glob(f"{PREFIXO}-*.gz"), reverse=True)
    removidos = 0
    for arquivo in arquivos[manter:]:
        try:
            arquivo.unlink()
            removidos += 1
        except OSError:      # arquivo em uso ou sem permissão: ignora
            pass
    return removidos


def caminho_seguro(db, empresa_id: int, nome: str) -> Path:
    """Resolve o nome pedido dentro da pasta de cópias.

    Impede que um nome com '..' leve o download para fora da pasta.
    """
    pasta = diretorio(db, empresa_id).resolve()
    alvo = (pasta / Path(nome).name).resolve()
    if alvo.parent != pasta or not alvo.is_file():
        raise BackupError("Cópia não encontrada.")
    return alvo
