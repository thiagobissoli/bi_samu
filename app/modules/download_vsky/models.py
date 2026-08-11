"""Modelos SQLAlchemy do módulo Download vSky (§35.19 — somente persistência).

Herdam de BaseModel os campos base obrigatórios (§36.4): id, empresa_id,
created_at/by, updated_at/by, deleted_at/by e version.

- VskyImportacao: uma execução do relatório "Total de Registros Analítico"
  (período, status, contadores e o XLS baixado).
- VskyRegistroAnalitico: uma linha do relatório, com todas as colunas do XLS
  e `linha_hash` (SHA-256 da linha inteira) único por empresa para impedir
  duplicados.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import BaseModel
from app.modules.download_vsky.constants import STATUS_PENDENTE


class VskyImportacao(BaseModel):
    __tablename__ = "vsky_importacoes"

    data_inicial: Mapped[str] = mapped_column(String(10))  # dd/mm/aaaa
    data_final: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDENTE, index=True)
    total_linhas: Mapped[int] = mapped_column(default=0)
    linhas_novas: Mapped[int] = mapped_column(default=0)
    linhas_duplicadas: Mapped[int] = mapped_column(default=0)
    tamanho: Mapped[int] = mapped_column(default=0)  # bytes do XLS
    caminho: Mapped[str | None] = mapped_column(String(500), nullable=True)  # XLS no disco
    erro: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class VskyRegistroAnalitico(BaseModel):
    __tablename__ = "vsky_registros_analiticos"
    __table_args__ = (
        UniqueConstraint("empresa_id", "linha_hash", name="uq_vsky_registro_linha"),
    )

    importacao_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    linha_hash: Mapped[str] = mapped_column(String(64), index=True)
    data_ocorrencia_dt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    # Colunas do relatório (ordem do XLS — ver constants.COLUNAS)
    ocorrencia: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    codigo_da_ocorrencia: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status_da_ocorrencia: Mapped[str | None] = mapped_column(String(100), nullable=True)
    situacao_atendimento: Mapped[str | None] = mapped_column(String(255), nullable=True)
    atendimento: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transporte: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unidade: Mapped[str | None] = mapped_column(String(255), nullable=True)
    veiculo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cidade: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bairro: Mapped[str | None] = mapped_column(String(255), nullable=True)
    endereco: Mapped[str | None] = mapped_column(String(500), nullable=True)
    numero: Mapped[str | None] = mapped_column(String(50), nullable=True)
    referencia: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lat_local_atendimento: Mapped[str | None] = mapped_column(String(50), nullable=True)
    long_local_atendimento: Mapped[str | None] = mapped_column(String(50), nullable=True)
    paciente: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sexo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    idade: Mapped[str | None] = mapped_column(String(50), nullable=True)
    faixa: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tipo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    motivo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    risco_inicial: Mapped[str | None] = mapped_column(String(100), nullable=True)
    frq_respiratoria: Mapped[str | None] = mapped_column(String(50), nullable=True)
    frq_cardiaca: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pressao_arterial: Mapped[str | None] = mapped_column(String(50), nullable=True)
    escala_glasgow: Mapped[str | None] = mapped_column(String(50), nullable=True)
    glicemia: Mapped[str | None] = mapped_column(String(50), nullable=True)
    obito: Mapped[str | None] = mapped_column(String(50), nullable=True)
    data_ocorrencia: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tarm: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data_tarm: Mapped[str | None] = mapped_column(String(30), nullable=True)
    regulador: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data_regulador: Mapped[str | None] = mapped_column(String(30), nullable=True)
    controlador: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data_controlador: Mapped[str | None] = mapped_column(String(30), nullable=True)
    inicio_deslocamento: Mapped[str | None] = mapped_column(String(30), nullable=True)
    saida_para_atendimento: Mapped[str | None] = mapped_column(String(30), nullable=True)
    chegada_no_local: Mapped[str | None] = mapped_column(String(30), nullable=True)
    saida_para_hospital: Mapped[str | None] = mapped_column(String(30), nullable=True)
    chegada_no_hospital: Mapped[str | None] = mapped_column(String(30), nullable=True)
    atendimento_encerrado: Mapped[str | None] = mapped_column(String(30), nullable=True)
    chegada_na_base: Mapped[str | None] = mapped_column(String(30), nullable=True)
    hospital_origem: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hospital_destino: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lat_hospital_destino: Mapped[str | None] = mapped_column(String(50), nullable=True)
    long_hospital_destino: Mapped[str | None] = mapped_column(String(50), nullable=True)
    solicitante: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telefone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    protocolo_telefone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    micro_regiao: Mapped[str | None] = mapped_column(String(255), nullable=True)
    apoio_policia_militar: Mapped[str | None] = mapped_column(String(100), nullable=True)
    apoio_bombeiros: Mapped[str | None] = mapped_column(String(100), nullable=True)
    apoio_usa: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tec_enfermagem: Mapped[str | None] = mapped_column(String(255), nullable=True)
    condutor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enfermeiro: Mapped[str | None] = mapped_column(String(255), nullable=True)
    medico: Mapped[str | None] = mapped_column(String(255), nullable=True)
    primeiro_j14: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ultimo_j14: Mapped[str | None] = mapped_column(String(30), nullable=True)
    primeiro_j15: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ultimo_j15: Mapped[str | None] = mapped_column(String(30), nullable=True)
