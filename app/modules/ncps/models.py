"""Modelos do módulo NCPS — Notificação de Não Conformidade / Evento (§35.19).

Uma notificação (`Ncps`) é sobre a **segurança do paciente** ou sobre a
**saúde e segurança do trabalhador** (NR-1). A tratativa acontece em
tabelas filhas: dados ocupacionais, análise sistêmica (Protocolo de
Londres / NR-1 1.5.5.5), causas (Londres ou Ishikawa), matriz de risco
(inicial e residual) e plano de ação.

Os códigos dos campos de classificação são os mesmos do sistema anterior
(ver constants.py). A importação preserva o id de lá (o id é o
**protocolo** que quem notificou anotou) e guarda-o também em
`legado_id`, o que a torna idempotente.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Date, DateTime, ForeignKey, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

import app.models  # noqa: F401 — registra Usuario, alvo dos relacionamentos
from app.core.database import BaseModel


# ------------------------------------------------------------------ cadastros

class NcpsGestor(BaseModel):
    """Gestor da área a quem a notificação diz respeito."""

    __tablename__ = "ncps_gestores"

    nome: Mapped[str] = mapped_column(String(120), index=True)
    ativo: Mapped[bool] = mapped_column(default=True)


class NcpsLocal(BaseModel):
    """Local padronizado (base, setor, viatura) para agrupar notificações."""

    __tablename__ = "ncps_locais"

    nome: Mapped[str] = mapped_column(String(120), index=True)
    ativo: Mapped[bool] = mapped_column(default=True)


class NcpsGhe(BaseModel):
    """Grupo Homogêneo de Exposição do PGR."""

    __tablename__ = "ncps_ghe"

    codigo: Mapped[str] = mapped_column(String(10), index=True)
    nome: Mapped[str] = mapped_column(String(100))
    cargos: Mapped[str | None] = mapped_column(Text, nullable=True)
    ativo: Mapped[bool] = mapped_column(default=True)

    @property
    def rotulo(self) -> str:
        return f"GHE {self.codigo} · {self.nome}"


class NcpsPerigo(BaseModel):
    """Perigo / fator de risco do inventário do PGR."""

    __tablename__ = "ncps_perigos"

    grupo: Mapped[str] = mapped_column(String(20), index=True)
    nome: Mapped[str] = mapped_column(String(150))
    fonte: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dano: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ativo: Mapped[bool] = mapped_column(default=True)


# ------------------------------------------------------------------ notificação

class Ncps(BaseModel):
    __tablename__ = "ncps"

    # Notificação
    natureza: Mapped[str] = mapped_column(String(20), default="paciente",
                                          index=True)
    descricao: Mapped[str] = mapped_column(Text)
    local: Mapped[str | None] = mapped_column(String(100), nullable=True)
    id_ocorrencia: Mapped[str | None] = mapped_column(String(100),
                                                      nullable=True, index=True)
    # Hora local informada por quem notificou (sem fuso, como no vSky)
    data_hora_ocorrencia: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True)
    sugestao: Mapped[str | None] = mapped_column(Text, nullable=True)
    registrado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                    index=True)

    # Quem notificou (vazio quando anônima ou pelo formulário público)
    notificante_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id"), nullable=True, index=True)
    anonima: Mapped[bool] = mapped_column(default=False)
    # Violência/assédio: só a Comissão de Integridade vê
    confidencial: Mapped[bool] = mapped_column(default=False, index=True)
    # Hash SHA-256 do código de acompanhamento (o código só é mostrado uma vez)
    codigo_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Triagem
    status: Mapped[str] = mapped_column(String(2), default="0", index=True)
    procedente: Mapped[str] = mapped_column(String(2), default="0")
    local_id: Mapped[int | None] = mapped_column(
        ForeignKey("ncps_locais.id"), nullable=True, index=True)
    gestor_id: Mapped[int | None] = mapped_column(
        ForeignKey("ncps_gestores.id"), nullable=True, index=True)
    coordenador_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id"), nullable=True, index=True)

    # Classificação — segurança do paciente
    classificacao_incidente: Mapped[str] = mapped_column(String(2), default="0")
    dano: Mapped[str] = mapped_column(String(2), default="0")
    macroprocesso: Mapped[str] = mapped_column(String(2), default="0")
    seguranca: Mapped[str] = mapped_column(String(2), default="0")
    sentinela: Mapped[str] = mapped_column(String(2), default="0")

    # Classificação — trabalhador
    tipo_evento_trab: Mapped[str | None] = mapped_column(String(30),
                                                         nullable=True)
    ghe_id: Mapped[int | None] = mapped_column(ForeignKey("ncps_ghe.id"),
                                               nullable=True)
    houve_lesao: Mapped[bool | None] = mapped_column(nullable=True)

    # Importação do sistema anterior
    legado_id: Mapped[int | None] = mapped_column(Integer, nullable=True,
                                                  index=True)
    # Campos do formulário antigo sem equivalente (impacto, controle, plano…)
    legado: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON

    local_padronizado: Mapped[NcpsLocal | None] = relationship(lazy="selectin")
    gestor: Mapped[NcpsGestor | None] = relationship(lazy="selectin")
    ghe: Mapped[NcpsGhe | None] = relationship(lazy="selectin")
    coordenador = relationship("Usuario", foreign_keys=[coordenador_id],
                               lazy="selectin")
    notificante = relationship("Usuario", foreign_keys=[notificante_id],
                               lazy="selectin")

    ocupacional: Mapped["NcpsOcupacional | None"] = relationship(
        back_populates="ncps", cascade="all, delete-orphan", uselist=False,
        lazy="selectin")
    analise: Mapped["NcpsAnalise | None"] = relationship(
        back_populates="ncps", cascade="all, delete-orphan", uselist=False,
        lazy="selectin")
    causas: Mapped[list["NcpsCausa"]] = relationship(
        back_populates="ncps", cascade="all, delete-orphan",
        order_by="NcpsCausa.id", lazy="selectin")
    riscos: Mapped[list["NcpsRisco"]] = relationship(
        back_populates="ncps", cascade="all, delete-orphan", lazy="selectin")
    acoes: Mapped[list["NcpsAcao"]] = relationship(
        back_populates="ncps", cascade="all, delete-orphan",
        order_by="NcpsAcao.id", lazy="selectin")

    def risco(self, momento: str) -> "NcpsRisco | None":
        return next((r for r in self.riscos if r.momento == momento), None)


class NcpsOcupacional(BaseModel):
    """Dados do evento com o trabalhador (NR-1)."""

    __tablename__ = "ncps_ocupacional"

    ncps_id: Mapped[int] = mapped_column(ForeignKey("ncps.id"), unique=True)
    grupo_risco: Mapped[str | None] = mapped_column(String(20), nullable=True)
    perigo_id: Mapped[int | None] = mapped_column(
        ForeignKey("ncps_perigos.id"), nullable=True)
    natureza_lesao: Mapped[str | None] = mapped_column(String(150),
                                                       nullable=True)
    parte_corpo: Mapped[str | None] = mapped_column(String(60), nullable=True)
    afastamento: Mapped[bool | None] = mapped_column(nullable=True)
    dias_afastamento: Mapped[int | None] = mapped_column(nullable=True)
    cat_emitida: Mapped[bool | None] = mapped_column(nullable=True)
    cat_numero: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cat_data: Mapped[date | None] = mapped_column(Date, nullable=True)
    revisar_pgr: Mapped[bool] = mapped_column(default=False)
    pgr_revisado_em: Mapped[date | None] = mapped_column(Date, nullable=True)

    ncps: Mapped[Ncps] = relationship(back_populates="ocupacional")
    perigo: Mapped[NcpsPerigo | None] = relationship(lazy="selectin")


class NcpsAnalise(BaseModel):
    """Análise sistêmica: Protocolo de Londres (paciente) / NR-1 1.5.5.5."""

    __tablename__ = "ncps_analise"

    ncps_id: Mapped[int] = mapped_column(ForeignKey("ncps.id"), unique=True)
    cronologia: Mapped[str | None] = mapped_column(Text, nullable=True)
    problemas: Mapped[str | None] = mapped_column(Text, nullable=True)
    fontes: Mapped[str | None] = mapped_column(Text, nullable=True)
    barreiras: Mapped[str | None] = mapped_column(Text, nullable=True)
    recomendacoes: Mapped[str | None] = mapped_column(Text, nullable=True)

    ncps: Mapped[Ncps] = relationship(back_populates="analise")


class NcpsCausa(BaseModel):
    """Causa / fator contribuinte — Protocolo de Londres ou Ishikawa (6M)."""

    __tablename__ = "ncps_causas"

    ncps_id: Mapped[int] = mapped_column(ForeignKey("ncps.id"), index=True)
    metodo: Mapped[str] = mapped_column(String(10))   # londres | ishikawa
    categoria: Mapped[str] = mapped_column(String(20))
    descricao: Mapped[str] = mapped_column(Text)
    causa_raiz: Mapped[bool] = mapped_column(default=False)

    ncps: Mapped[Ncps] = relationship(back_populates="causas")


class NcpsRisco(BaseModel):
    """Avaliação na matriz de risco do PGR (inicial e residual)."""

    __tablename__ = "ncps_riscos"
    __table_args__ = (UniqueConstraint("ncps_id", "momento",
                                       name="uq_ncps_risco_momento"),)

    ncps_id: Mapped[int] = mapped_column(ForeignKey("ncps.id"), index=True)
    momento: Mapped[str] = mapped_column(String(10))   # inicial | residual
    probabilidade: Mapped[int] = mapped_column(Integer)
    severidade: Mapped[int] = mapped_column(Integer)
    justificativa: Mapped[str | None] = mapped_column(Text, nullable=True)

    ncps: Mapped[Ncps] = relationship(back_populates="riscos")

    @property
    def nivel(self) -> dict | None:
        from app.modules.ncps.constants import nivel_risco
        return nivel_risco(self.probabilidade, self.severidade)


class NcpsAcao(BaseModel):
    """Ação do plano (o quê, tipo, responsável, prazo, status, eficácia)."""

    __tablename__ = "ncps_acoes"

    ncps_id: Mapped[int] = mapped_column(ForeignKey("ncps.id"), index=True)
    descricao: Mapped[str] = mapped_column(Text)
    tipo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    responsavel: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prazo: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(12), default="pendente",
                                        index=True)
    concluida_em: Mapped[date | None] = mapped_column(Date, nullable=True)
    eficacia: Mapped[str] = mapped_column(String(15), default="nao_verificada")
    observacao: Mapped[str | None] = mapped_column(Text, nullable=True)

    ncps: Mapped[Ncps] = relationship(back_populates="acoes")

