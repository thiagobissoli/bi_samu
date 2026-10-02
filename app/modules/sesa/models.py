"""Modelos dos envios à SESA.

SesaObrigacao  o que se envia, com que frequência, até quando, por onde e a quem
SesaItem       os documentos que compõem o envio (ex.: as 5 certidões)
SesaEntrega    o envio de uma competência (mês): quando saiu e o protocolo
SesaAnexo      o arquivo de um item naquela entrega (+ dados lidos da certidão)
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (Date, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

import app.models  # noqa: F401 — registra Usuario e Arquivo
from app.core.database import BaseModel


class SesaObrigacao(BaseModel):
    __tablename__ = "sesa_obrigacoes"

    chave: Mapped[str] = mapped_column(String(40), index=True)
    nome: Mapped[str] = mapped_column(String(160))
    tipo: Mapped[str] = mapped_column(String(20), default="documentos")
    periodicidade: Mapped[str] = mapped_column(String(20), default="mensal")
    meses: Mapped[str | None] = mapped_column(String(40), nullable=True)
    prazo_tipo: Mapped[str] = mapped_column(String(10), default="util")
    prazo_dia: Mapped[int] = mapped_column(Integer, default=5)
    canal: Mapped[str | None] = mapped_column(String(40), nullable=True)
    destinatario: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordem: Mapped[int] = mapped_column(Integer, default=0)
    ativo: Mapped[bool] = mapped_column(default=True)

    itens = relationship("SesaItem", back_populates="obrigacao",
                         order_by="SesaItem.ordem", lazy="selectin")


class SesaItem(BaseModel):
    __tablename__ = "sesa_itens"

    obrigacao_id: Mapped[int] = mapped_column(ForeignKey("sesa_obrigacoes.id"), index=True)
    chave: Mapped[str] = mapped_column(String(40))
    nome: Mapped[str] = mapped_column(String(160))
    orgao: Mapped[str | None] = mapped_column(String(120), nullable=True)
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    instrucoes: Mapped[str | None] = mapped_column(Text, nullable=True)
    validade_dias: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ordem: Mapped[int] = mapped_column(Integer, default=0)
    ativo: Mapped[bool] = mapped_column(default=True)

    obrigacao = relationship("SesaObrigacao", back_populates="itens")


class SesaEntrega(BaseModel):
    __tablename__ = "sesa_entregas"
    __table_args__ = (UniqueConstraint("empresa_id", "obrigacao_id", "competencia",
                                       name="uq_sesa_entrega_competencia"),)

    obrigacao_id: Mapped[int] = mapped_column(ForeignKey("sesa_obrigacoes.id"), index=True)
    competencia: Mapped[date] = mapped_column(Date, index=True)
    enviada_em: Mapped[date | None] = mapped_column(Date, nullable=True)
    enviada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    protocolo: Mapped[str | None] = mapped_column(String(80), nullable=True)
    observacao: Mapped[str | None] = mapped_column(Text, nullable=True)

    obrigacao = relationship("SesaObrigacao", lazy="joined")
    remetente = relationship("Usuario", foreign_keys=[enviada_por], lazy="joined")
    anexos = relationship("SesaAnexo", back_populates="entrega", lazy="selectin",
                          cascade="all, delete-orphan")


class SesaAnexo(BaseModel):
    __tablename__ = "sesa_anexos"

    entrega_id: Mapped[int] = mapped_column(ForeignKey("sesa_entregas.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("sesa_itens.id"), index=True)
    arquivo_id: Mapped[int] = mapped_column(ForeignKey("arquivos.id"))
    numero: Mapped[str | None] = mapped_column(String(80), nullable=True)
    emitida_em: Mapped[date | None] = mapped_column(Date, nullable=True)
    valida_ate: Mapped[date | None] = mapped_column(Date, nullable=True)
    resultado: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cnpj_confere: Mapped[bool | None] = mapped_column(nullable=True)
    reaproveitado_de: Mapped[int | None] = mapped_column(ForeignKey("sesa_anexos.id"),
                                                          nullable=True)

    entrega = relationship("SesaEntrega", back_populates="anexos")
    item = relationship("SesaItem", lazy="joined")
    arquivo = relationship("Arquivo", lazy="joined")


class SesaAvisoVencimento(BaseModel):
    """Aviso de vencimento já enviado: um por certidão (item + validade),
    para o job diário não repetir o e-mail."""

    __tablename__ = "sesa_avisos_vencimento"
    __table_args__ = (UniqueConstraint("empresa_id", "item_id", "valida_ate",
                                       name="uq_sesa_aviso_item_validade"),)

    item_id: Mapped[int] = mapped_column(ForeignKey("sesa_itens.id"), index=True)
    valida_ate: Mapped[date] = mapped_column(Date)
    destinatarios: Mapped[int] = mapped_column(Integer, default=0)


class SesaHospital(BaseModel):
    """Hospital de destino do relatório 115 do vReport, e como ele aparece no
    documento "Encaminhamentos do SAMU". A seleção fica salva de um mês
    para o outro; hospital novo na planilha entra aqui na primeira leitura."""

    __tablename__ = "sesa_hospitais"
    __table_args__ = (UniqueConstraint("empresa_id", "nome_vsky",
                                       name="uq_sesa_hospital_nome"),)

    nome_vsky: Mapped[str] = mapped_column(String(200))
    nome_documento: Mapped[str] = mapped_column(String(200))
    sigla: Mapped[str | None] = mapped_column(String(20), nullable=True)
    incluir: Mapped[bool] = mapped_column(default=False)
