"""Camada de banco de dados (§36).

Base declarativa com os campos base obrigatórios (§36.4), soft delete (§36.7)
e versionamento otimista (§36.8).

Em desenvolvimento o padrão é SQLite (zero configuração); em produção use
PostgreSQL 16+ via DATABASE_URL no .env (§36.2). Alterações estruturais em
produção devem ser feitas exclusivamente via Alembic (§36.20) — o create_all
do init_db() é uma conveniência de desenvolvimento.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, create_engine
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


def init_db() -> None:
    """Cria as tabelas registradas (desenvolvimento). Produção: Alembic."""
    Base.metadata.create_all(engine)
