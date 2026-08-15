"""Modelos do módulo Investigação de Eventos (§35.19).

A análise das ocorrências é somente leitura sobre o núcleo do módulo
indicadores. O que se persiste aqui são os relatórios RAC gerados: cada
pedido de ajuste cria uma **nova versão** (a anterior é preservada, para
o modelo aprender com o que foi corrigido), e a versão aprovada guarda o
PDF assinado institucionalmente.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import BaseModel

STATUS_PENDENTE = "pendente"
STATUS_APROVADO = "aprovado"
STATUS_SUBSTITUIDO = "substituido"   # gerou-se uma versão nova a partir dela


class AnaliseOcorrencia(BaseModel):
    """Uma versão do relatório RAC de uma ocorrência."""

    __tablename__ = "investigacao_analises"

    ocorrencia: Mapped[str] = mapped_column(String(30), index=True)
    versao: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDENTE,
                                        index=True)
    provedor: Mapped[str] = mapped_column(String(30))
    modelo: Mapped[str] = mapped_column(String(120))
    anonimizado: Mapped[bool] = mapped_column(default=True)
    com_prontuario: Mapped[bool] = mapped_column(default=False)
    resultado: Mapped[str] = mapped_column(Text(1_000_000))   # JSON
    bruto: Mapped[str | None] = mapped_column(Text(1_000_000), nullable=True)
    gerado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Ajuste pedido pela equipe que deu origem a ESTA versão
    feedback: Mapped[str | None] = mapped_column(Text(20_000), nullable=True)

    # Risco pós-investigação registrado pela equipe (prevalece sobre a
    # estimativa da IA — é a avaliação institucional)
    risco_pos_probabilidade: Mapped[int | None] = mapped_column(nullable=True)
    risco_pos_consequencia: Mapped[int | None] = mapped_column(nullable=True)
    risco_pos_justificativa: Mapped[str | None] = mapped_column(
        Text(5_000), nullable=True)

    # Campos do formulário que só a equipe conhece (não estão no vSky)
    notificacao_data: Mapped[str | None] = mapped_column(String(20),
                                                         nullable=True)
    time_investigacao: Mapped[str | None] = mapped_column(String(500),
                                                          nullable=True)
    investigacao_inicio: Mapped[str | None] = mapped_column(String(20),
                                                            nullable=True)
    # Relatos dos envolvidos, colhidos em entrevista pela equipe. Entram
    # no RAC e alimentam a análise — sem eles o Protocolo de Londres fica
    # restrito ao que o registro operacional mostra.
    relatos: Mapped[str | None] = mapped_column(Text(50_000), nullable=True)

    # Aprovação
    aprovado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    aprovado_por: Mapped[int | None] = mapped_column(nullable=True)
    aprovado_nome: Mapped[str | None] = mapped_column(String(255),
                                                      nullable=True)
    # PDF do relatório aprovado, guardado no banco para ficar imutável
    pdf: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
