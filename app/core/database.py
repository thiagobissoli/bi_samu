"""Camada de banco de dados (§36).

Base declarativa com os campos base obrigatórios (§36.4), soft delete (§36.7)
e versionamento otimista (§36.8).

Em desenvolvimento o padrão é SQLite (zero configuração); em produção use
PostgreSQL 16+ via DATABASE_URL no .env (§36.2). Alterações estruturais em
produção devem ser feitas exclusivamente via Alembic (§36.20) — o create_all
do init_db() é uma conveniência de desenvolvimento.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import BigInteger, DateTime, Integer, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.core.config import settings

_connect_args = {}
if settings.database_url.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class BaseModel(Base):
    """Campos base obrigatórios de toda tabela (§36.4)."""

    __abstract__ = True

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    empresa_id: Mapped[int] = mapped_column(BigInteger, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    deleted_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    __mapper_args__ = {"version_id_col": version}


def get_session():
    """Dependency do FastAPI — sessão por requisição."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _garantir_banco() -> None:
    """Cria o próprio banco (MySQL/MariaDB) na primeira execução.

    Conecta ao servidor sem selecionar schema e emite CREATE DATABASE IF
    NOT EXISTS — assim uma instalação nova só precisa do servidor de pé e
    das credenciais no .env. SQLite cria o arquivo sozinho; PostgreSQL
    exige o banco criado previamente (createdb).
    """
    from sqlalchemy.engine import make_url

    url = make_url(settings.database_url)
    if not url.drivername.startswith("mysql") or not url.database:
        return

    # set(database=None) seria ignorado pelo SQLAlchemy; "" conecta ao
    # servidor sem selecionar schema.
    servidor = create_engine(url.set(database=""))
    try:
        with servidor.connect() as conn:
            conn.execute(text(
                f"CREATE DATABASE IF NOT EXISTS `{url.database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
            conn.commit()
    finally:
        servidor.dispose()


def _config_alembic():
    """Configuração do Alembic apontando para este projeto."""
    from alembic.config import Config

    raiz = Path(__file__).resolve().parent.parent.parent
    config = Config(str(raiz / "alembic.ini"))
    config.set_main_option("script_location", str(raiz / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def _versionado() -> bool:
    """True se o banco já tem revisão do Alembic carimbada."""
    from sqlalchemy import inspect

    inspetor = inspect(engine)
    if not inspetor.has_table("alembic_version"):
        return False
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar() > 0


def aplicar_migracoes() -> None:
    """Põe o schema no head do Alembic ao subir a aplicação.

    create_all() cria tabela que falta, mas nunca COLUNA que falta. Foi assim
    que uma atualização de código derrubou a instalação em produção com
    "Unknown column 'linhas_superadas'": o código novo subiu, o banco ficou
    no schema velho e a página só quebrou quando alguém abriu.

    Aplicando as migrações no boot, atualizar o sistema volta a ser `git pull`
    mais reiniciar. Banco recém-criado nasce no head e é só carimbado; banco
    anterior ao versionamento é carimbado na baseline antes de subir.
    """
    from alembic import command
    from sqlalchemy import inspect

    log = logging.getLogger("uvicorn.error")
    config = _config_alembic()
    novo = not inspect(engine).has_table("usuarios")
    try:
        if novo:
            Base.metadata.create_all(engine)
            command.stamp(config, "head")
            log.info("Banco criado no schema atual.")
            return
        if not _versionado():
            # Instalação anterior ao Alembic: o schema existe e corresponde à
            # baseline. Sem o carimbo, o upgrade tentaria recriar tudo.
            command.stamp(config, "0001_baseline")
            log.info("Banco existente carimbado na baseline do Alembic.")
        command.upgrade(config, "head")
        # Tabela de módulo novo ainda sem migração própria
        Base.metadata.create_all(engine)
    except Exception:  # noqa: BLE001 — sem migração o app sobe com schema velho
        log.exception(
            "Falha ao aplicar as migrações. O sistema vai subir, mas telas "
            "que dependem do schema novo podem falhar. Rode à mão: "
            "alembic upgrade head")


def init_db() -> None:
    """Cria o banco se preciso e deixa o schema no head das migrações."""
    _garantir_banco()
    aplicar_migracoes()
