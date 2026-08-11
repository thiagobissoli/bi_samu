"""Schemas Pydantic do módulo Download vSky (§35.18)."""

from pydantic import BaseModel, Field


class ImportacaoCreate(BaseModel):
    data_inicial: str = Field(min_length=8, max_length=10,
                              description="dd/mm/aaaa ou aaaa-mm-dd")
    data_final: str = Field(min_length=8, max_length=10)


class ImportacaoRead(BaseModel):
    id: int
    data_inicial: str
    data_final: str
    status: str
    total_linhas: int = 0
    linhas_novas: int = 0
    linhas_duplicadas: int = 0
    tamanho: int = 0
    erro: str | None = None

    model_config = {"from_attributes": True}
