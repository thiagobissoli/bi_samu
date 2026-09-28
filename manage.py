#!/usr/bin/env python3
"""Comandos administrativos do projeto (§35.25).

    python manage.py criar-usuario --nome "Maria" --email maria@x.com
    python manage.py criar-empresa --razao-social "ACME LTDA" --cnpj 11.222.333/0001-81
    python manage.py criar-modulo pacientes
    python manage.py backup
    python manage.py restore backups/2026-08-13.tar.gz
    python manage.py db-objects
    python manage.py limpar-sessoes

Rode sempre com o venv do projeto ativo, a partir da raiz.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

PASTA_BACKUP = RAIZ / "backups"


# --- Usuários e empresas ---


def criar_usuario(args) -> int:
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.core.security import hash_password
    from app.core.validators import valida_email, valida_senha
    from app.models import Perfil, Usuario

    email = (args.email or "").strip().lower()
    if not valida_email(email):
        print(f"E-mail inválido: {email}", file=sys.stderr)
        return 1

    senha = args.senha or getpass.getpass("Senha: ")
    if not valida_senha(senha):
        print("Senha fraca: use ao menos 8 caracteres, com letra e número.",
              file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        if db.scalar(select(Usuario).where(Usuario.email == email)):
            print(f"Já existe usuário com o e-mail {email}.", file=sys.stderr)
            return 1

        usuario = Usuario(
            empresa_id=args.empresa, nome=args.nome, email=email,
            senha_hash=hash_password(senha), ativo=True, email_confirmado=True,
        )
        if args.perfil:
            perfil = db.scalar(select(Perfil).where(Perfil.nome == args.perfil))
            if perfil is None:
                print(f"Perfil '{args.perfil}' não encontrado.", file=sys.stderr)
                return 1
            usuario.perfis.append(perfil)
        db.add(usuario)
        db.commit()
        print(f"Usuário criado: #{usuario.id} {usuario.nome} <{usuario.email}>")
        if args.perfil:
            print(f"Perfil vinculado: {args.perfil}")
        return 0
    finally:
        db.close()


def criar_empresa(args) -> int:
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.core.validators import valida_cnpj
    from app.models import Empresa

    if not valida_cnpj(args.cnpj):
        print(f"CNPJ inválido: {args.cnpj}", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        if db.scalar(select(Empresa).where(Empresa.cnpj == args.cnpj)):
            print(f"Já existe empresa com o CNPJ {args.cnpj}.", file=sys.stderr)
            return 1
        empresa = Empresa(
            empresa_id=1, razao_social=args.razao_social,
            nome_fantasia=args.nome_fantasia or args.razao_social,
            cnpj=args.cnpj, email=args.email or "", telefone=args.telefone,
            plano=args.plano, status="ativa",
        )
        db.add(empresa)
        db.commit()
        print(f"Empresa criada: #{empresa.id} {empresa.nome_fantasia}")
        return 0
    finally:
        db.close()


def criar_modulo(args) -> int:
    """Atalho para `saas create-module` (§35.26)."""
    try:
        from saas_framework.scaffold import create_module

        caminho = create_module(args.nome, RAIZ)
        print(f"Módulo criado em: {caminho}")
        print("Reinicie a aplicação para registrá-lo.")
        return 0
    except ImportError:
        print("O pacote saas-framework não está instalado neste ambiente.",
              file=sys.stderr)
        return 1
    except (FileExistsError, ValueError) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1


# --- Backup e restore (§36.19) ---


def _dump_banco(destino: Path) -> Path | None:
    """Gera o dump conforme o banco em uso. Devolve o arquivo criado."""
    from app.core.config import settings

    url = settings.database_url

    if url.startswith("sqlite"):
        origem = Path(url.split("sqlite:///")[-1])
        if not origem.is_file():
            return None
        alvo = destino / "banco.sqlite3"
        shutil.copy2(origem, alvo)
        return alvo

    alvo = destino / "banco.sql"
    if url.startswith("postgresql"):
        comando = ["pg_dump", "--no-owner", "--no-privileges", "-f", str(alvo), url]
    elif url.startswith("mysql"):
        from urllib.parse import urlparse

        partes = urlparse(url)
        comando = [
            "mysqldump", f"--host={partes.hostname}", f"--port={partes.port or 3306}",
            f"--user={partes.username}", f"--password={partes.password or ''}",
            (partes.path or "/").lstrip("/"),
        ]
    else:
        print(f"Backup automático não suportado para {url.split('://')[0]}.",
              file=sys.stderr)
        return None

    try:
        if url.startswith("mysql"):
            with alvo.open("w", encoding="utf-8") as saida:
                subprocess.run(comando, stdout=saida, check=True)
        else:
            subprocess.run(comando, check=True)
        return alvo
    except (subprocess.CalledProcessError, FileNotFoundError) as erro:
        print(f"Falha ao gerar o dump ({erro}). "
              "O cliente do banco (pg_dump/mysqldump) está instalado?",
              file=sys.stderr)
        return None


def backup(args) -> int:
    from app.core.config import settings

    PASTA_BACKUP.mkdir(exist_ok=True)
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    trabalho = PASTA_BACKUP / f".tmp-{carimbo}"
    trabalho.mkdir()

    try:
        dump = _dump_banco(trabalho)
        if dump is None:
            return 1

        # Os arquivos ficam no disco, não no banco (§36.12): entram no pacote.
        uploads = Path(settings.upload_dir)
        if not args.sem_uploads and uploads.is_dir():
            shutil.copytree(uploads, trabalho / "uploads", dirs_exist_ok=True)

        pacote = PASTA_BACKUP / f"backup-{carimbo}.tar.gz"
        with tarfile.open(pacote, "w:gz") as tar:
            for item in trabalho.iterdir():
                tar.add(item, arcname=item.name)

        tamanho = pacote.stat().st_size / (1024 * 1024)
        print(f"Backup criado: {pacote} ({tamanho:.1f} MB)")
        if args.sem_uploads:
            print("Atenção: os uploads NÃO foram incluídos (--sem-uploads).")
        return 0
    finally:
        shutil.rmtree(trabalho, ignore_errors=True)


def restore(args) -> int:
    from app.core.config import settings

    pacote = Path(args.arquivo)
    if not pacote.is_file():
        print(f"Arquivo não encontrado: {pacote}", file=sys.stderr)
        return 1

    if not args.sim:
        print("Restaurar SOBRESCREVE o banco e os uploads atuais.")
        if input("Digite 'restaurar' para confirmar: ").strip() != "restaurar":
            print("Cancelado.")
            return 1

    trabalho = PASTA_BACKUP / f".restore-{datetime.now():%Y%m%d-%H%M%S}"
    trabalho.mkdir(parents=True)
    try:
        with tarfile.open(pacote, "r:gz") as tar:
            tar.extractall(trabalho)

        url = settings.database_url
        sqlite = trabalho / "banco.sqlite3"
        sql = trabalho / "banco.sql"

        if sqlite.is_file() and url.startswith("sqlite"):
            shutil.copy2(sqlite, Path(url.split("sqlite:///")[-1]))
            print("Banco SQLite restaurado.")
        elif sql.is_file() and url.startswith("postgresql"):
            subprocess.run(["psql", url, "-f", str(sql)], check=True)
            print("Banco PostgreSQL restaurado.")
        elif sql.is_file() and url.startswith("mysql"):
            from urllib.parse import urlparse

            partes = urlparse(url)
            with sql.open(encoding="utf-8") as entrada:
                subprocess.run([
                    "mysql", f"--host={partes.hostname}",
                    f"--user={partes.username}",
                    f"--password={partes.password or ''}",
                    (partes.path or "/").lstrip("/"),
                ], stdin=entrada, check=True)
            print("Banco MySQL restaurado.")
        else:
            print("O pacote não tem um dump compatível com o banco atual.",
                  file=sys.stderr)
            return 1

        origem_uploads = trabalho / "uploads"
        if origem_uploads.is_dir():
            shutil.copytree(origem_uploads, Path(settings.upload_dir), dirs_exist_ok=True)
            print("Uploads restaurados.")
        return 0
    finally:
        shutil.rmtree(trabalho, ignore_errors=True)


# --- Manutenção ---


def db_objects(args) -> int:
    from app.core.database import engine
    from app.core import db_objects as objetos

    criados = objetos.aplicar(engine)
    for item in criados:
        print(f"  {item}")
    print(f"{len(criados)} objeto(s) aplicados ({engine.dialect.name}).")

    atualizadas = objetos.atualizar_materialized_views(engine)
    if atualizadas:
        print(f"Materialized views atualizadas: {', '.join(atualizadas)}")
    return 0


def limpar_sessoes(args) -> int:
    from app.core.tasks import limpar_sessoes_expiradas

    print(f"{limpar_sessoes_expiradas()} registro(s) expirado(s) removido(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="manage.py", description="Comandos administrativos (§35.25)"
    )
    sub = parser.add_subparsers(dest="comando")

    p = sub.add_parser("criar-usuario", help="Cria um usuário")
    p.add_argument("--nome", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--senha", help="Se omitido, é perguntado sem eco")
    p.add_argument("--empresa", type=int, default=1)
    p.add_argument("--perfil", help="Nome do perfil a vincular (ex.: Administrador)")
    p.set_defaults(func=criar_usuario)

    p = sub.add_parser("criar-empresa", help="Cria uma empresa")
    p.add_argument("--razao-social", required=True, dest="razao_social")
    p.add_argument("--nome-fantasia", dest="nome_fantasia")
    p.add_argument("--cnpj", required=True)
    p.add_argument("--email")
    p.add_argument("--telefone")
    p.add_argument("--plano", default="basico")
    p.set_defaults(func=criar_empresa)

    p = sub.add_parser("criar-modulo", help="Cria um módulo (§35.26)")
    p.add_argument("nome")
    p.set_defaults(func=criar_modulo)

    p = sub.add_parser("backup", help="Backup do banco e dos uploads (§36.19)")
    p.add_argument("--sem-uploads", action="store_true", dest="sem_uploads")
    p.set_defaults(func=backup)

    p = sub.add_parser("restore", help="Restaura um backup")
    p.add_argument("arquivo")
    p.add_argument("--sim", action="store_true", help="Não pede confirmação")
    p.set_defaults(func=restore)

    p = sub.add_parser("db-objects", help="Cria views, funções e triggers (§36.15–36.18)")
    p.set_defaults(func=db_objects)

    p = sub.add_parser("limpar-sessoes", help="Remove sessões e tokens expirados")
    p.set_defaults(func=limpar_sessoes)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    os.chdir(RAIZ)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
