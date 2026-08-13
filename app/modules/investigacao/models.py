"""Modelos do módulo Investigação de Eventos (§35.19).

A análise das ocorrências é somente leitura sobre o núcleo do módulo
indicadores. O que se persiste aqui é o resultado da análise por IA —
para não repetir a chamada (e o custo) a cada abertura da página e para
manter o histórico do que foi apresentado numa investigação.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import BaseModel


class AnaliseOcorrencia(BaseModel):
    """Resultado de uma análise por IA (Londres, Ishikawa, matriz de risco)."""

    __tablename__ = "investigacao_analises"

    ocorrencia: Mapped[str] = mapped_column(String(30), index=True)
    provedor: Mapped[str] = mapped_column(String(30))
    modelo: Mapped[str] = mapped_column(String(120))
    anonimizado: Mapped[bool] = mapped_column(default=True)
    com_prontuario: Mapped[bool] = mapped_column(default=False)
    resultado: Mapped[str] = mapped_column(Text(1_000_000))   # JSON
    bruto: Mapped[str | None] = mapped_column(Text(1_000_000), nullable=True)
    gerado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
