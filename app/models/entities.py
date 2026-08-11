"""Tabelas compartilhadas da plataforma (§8, §36.5, §36.6).

Presentes em qualquer sistema construído sobre o framework.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, BaseModel, utcnow

# --- Relacionamentos N:N (§8) ---

usuarios_perfis = Table(
    "usuarios_perfis",
    Base.metadata,
    Column("usuario_id", ForeignKey("usuarios.id"), primary_key=True),
    Column("perfil_id", ForeignKey("perfis.id"), primary_key=True),
)

perfis_permissoes = Table(
    "perfis_permissoes",
    Base.metadata,
    Column("perfil_id", ForeignKey("perfis.id"), primary_key=True),
    Column("permissao_id", ForeignKey("permissoes.id"), primary_key=True),
)


class Empresa(BaseModel):
    __tablename__ = "empresas"

    razao_social: Mapped[str] = mapped_column(String(255))
    nome_fantasia: Mapped[str] = mapped_column(String(255), index=True)
    cnpj: Mapped[str] = mapped_column(String(18), unique=True)
    email: Mapped[str] = mapped_column(String(255))
    telefone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    plano: Mapped[str] = mapped_column(String(50), default="basico")
    status: Mapped[str] = mapped_column(String(20), default="ativa", index=True)
    timezone: Mapped[str] = mapped_column(String(50), default="America/Sao_Paulo")
    idioma: Mapped[str] = mapped_column(String(10), default="pt-BR")


class Usuario(BaseModel):
    __tablename__ = "usuarios"

    nome: Mapped[str] = mapped_column(String(255), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    senha_hash: Mapped[str] = mapped_column(String(255))
    telefone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ativo: Mapped[bool] = mapped_column(default=True, index=True)
    email_confirmado: Mapped[bool] = mapped_column(default=False)
    mfa_habilitado: Mapped[bool] = mapped_column(default=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ultimo_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)

    perfis: Mapped[list["Perfil"]] = relationship(
        secondary=usuarios_perfis, lazy="selectin"
    )

    @property
    def permissoes(self) -> set[str]:
        """Códigos de permissão via RBAC: Usuário -> Perfil -> Permissões (§7)."""
        return {
            p.codigo
            for perfil in self.perfis
            if perfil.ativo and perfil.deleted_at is None
            for p in perfil.permissoes
        }


class Perfil(BaseModel):
    __tablename__ = "perfis"

    nome: Mapped[str] = mapped_column(String(100), index=True)
    descricao: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ativo: Mapped[bool] = mapped_column(default=True)

    permissoes: Mapped[list["Permissao"]] = relationship(
        secondary=perfis_permissoes, lazy="selectin"
    )


class Permissao(BaseModel):
    __tablename__ = "permissoes"

    codigo: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    descricao: Mapped[str | None] = mapped_column(String(255), nullable=True)
    modulo: Mapped[str] = mapped_column(String(50), index=True)


class Configuracao(BaseModel):
    __tablename__ = "configuracoes"

    chave: Mapped[str] = mapped_column(String(100), index=True)
    valor: Mapped[str | None] = mapped_column(Text, nullable=True)


class Auditoria(Base):
    """Trilha de auditoria (§11) — nunca apagar registros desta tabela."""

    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(BigInteger, index=True, default=1)
    usuario_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    usuario_nome: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tabela: Mapped[str] = mapped_column(String(100), index=True)
    registro_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    acao: Mapped[str] = mapped_column(String(30), index=True)
    valor_anterior: Mapped[str | None] = mapped_column(Text, nullable=True)
    valor_novo: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class Log(Base):
    """Logs da aplicação (§12), separados por módulo."""

    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(BigInteger, index=True, default=1)
    nivel: Mapped[str] = mapped_column(String(10), index=True)
    modulo: Mapped[str] = mapped_column(String(50), index=True)
    mensagem: Mapped[str] = mapped_column(Text)
    stacktrace: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class Sessao(Base):
    """Sessões de usuário — cookie HTTPOnly (§6)."""

    __tablename__ = "sessoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(BigInteger, index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TokenSeguranca(Base):
    """Tokens de uso único (§36.5): recuperação de senha, confirmação de e-mail."""

    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(BigInteger, index=True)
    tipo: Mapped[str] = mapped_column(String(30), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    utilizado: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notificacao(BaseModel):
    """Notificações do sistema (§21, §36.5)."""

    __tablename__ = "notificacoes"

    usuario_id: Mapped[int] = mapped_column(BigInteger, index=True)
    titulo: Mapped[str] = mapped_column(String(255))
    mensagem: Mapped[str] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(String(20), default="info")
    lida: Mapped[bool] = mapped_column(default=False, index=True)
    lida_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Arquivo(BaseModel):
    """Metadados de arquivos (§36.5) — o conteúdo fica no disco (§36.12)."""

    __tablename__ = "arquivos"

    nome_original: Mapped[str] = mapped_column(String(255))
    nome_servidor: Mapped[str] = mapped_column(String(255), unique=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    tamanho: Mapped[int] = mapped_column(BigInteger)
    hash: Mapped[str] = mapped_column(String(64))
    caminho: Mapped[str] = mapped_column(String(500))
    modulo: Mapped[str] = mapped_column(String(50), default="geral", index=True)
