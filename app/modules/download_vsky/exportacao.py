"""Exportação dos registros do vSky para planilha (§35.16).

Escreve em modo streaming: a consulta vem em lotes e cada linha é gravada e
descartada. Exportar a base inteira são 480 mil linhas por 61 colunas — o
caminho ingênuo (carregar tudo e montar a planilha em memória) derruba o
processo.
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.modules.download_vsky.constants import COLUNAS

# Limite do formato xlsx (1.048.576 linhas, uma é o cabeçalho). Acima disso o
# Excel recusa o arquivo inteiro, então é melhor cortar e avisar.
LIMITE_LINHAS = 1_048_575
LOTE = 2_000


def gerar_planilha(db: Session, query, nome_aba: str = "Registros") -> tuple[Path, int, bool]:
    """Grava a planilha num arquivo temporário.

    Devolve (caminho, linhas escritas, truncado).
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook(write_only=True)
    aba = wb.create_sheet(nome_aba)
    cabecalho = [titulo for _, titulo in COLUNAS]
    negrito = Font(bold=True)
    aba.append([_celula(aba, t, negrito) for t in cabecalho])

    campos = [slug for slug, _ in COLUNAS]
    escritas, truncado = 0, False
    for registro in db.scalars(query).yield_per(LOTE):
        if escritas >= LIMITE_LINHAS:
            truncado = True
            break
        aba.append([_valor(getattr(registro, campo, None)) for campo in campos])
        escritas += 1

    destino = Path(tempfile.gettempdir()) / (
        f"registros_vsky_{datetime.now():%Y%m%d_%H%M%S}.xlsx")
    wb.save(destino)
    return destino, escritas, truncado


def _celula(aba, texto, fonte):
    from openpyxl.cell import WriteOnlyCell

    celula = WriteOnlyCell(aba, value=texto)
    celula.font = fonte
    return celula


def _valor(valor):
    """O relatório do vSky vem todo como texto; datas ficam como estão.

    Converter "01/08/2026 07:15:33" para data do Excel mudaria o dado em
    relação ao que o portal entregou e ao que o sistema guarda.
    """
    return "" if valor is None else valor
