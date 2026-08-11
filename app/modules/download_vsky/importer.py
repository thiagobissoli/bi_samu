"""Importação do XLS "Total de Registros Analítico" para o banco.

Regras:
- O cabeçalho é localizado pela linha que contém "Ocorrência" na 1ª coluna;
  as colunas são casadas pelo título (normalizado), não pela posição.
- Cada linha vira um dicionário slug -> valor normalizado (datas do Excel
  convertidas para dd/mm/aaaa hh:mm:ss, números sem ".0" espúrio).
- `linha_hash` = SHA-256 de TODOS os valores da linha, na ordem canônica de
  constants.COLUNAS — duas linhas só são duplicadas se forem idênticas
  campo a campo (por empresa).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime

import xlrd

from app.modules.download_vsky.constants import COLUNAS, DATA_HORA_FMT, SLUGS

HEADER_BUSCA_MAX = 20  # linhas iniciais onde o cabeçalho pode estar


def _slug(titulo: str) -> str:
    s = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()


_SLUGS_CONHECIDOS = {_slug(titulo): slug for slug, titulo in COLUNAS}


def parse_xls(content: bytes) -> list[dict[str, str]]:
    """Converte o XLS em linhas normalizadas (slug -> valor)."""
    book = xlrd.open_workbook(file_contents=content)
    sheet = book.sheet_by_index(0)

    header_row = None
    for r in range(min(HEADER_BUSCA_MAX, sheet.nrows)):
        if str(sheet.cell_value(r, 0)).strip().casefold() == "ocorrência":
            header_row = r
            break
    if header_row is None:
        raise ValueError("Cabeçalho do relatório não encontrado no XLS.")

    colunas: list[tuple[int, str]] = []  # (índice no XLS, slug)
    for c in range(sheet.ncols):
        titulo = str(sheet.cell_value(header_row, c)).strip()
        slug = _SLUGS_CONHECIDOS.get(_slug(titulo))
        if slug:
            colunas.append((c, slug))
    if len(colunas) < 10:
        raise ValueError("XLS não parece ser o relatório Total de Registros Analítico.")

    linhas: list[dict[str, str]] = []
    for r in range(header_row + 1, sheet.nrows):
        valores: dict[str, str] = {}
        preenchidos = 0
        for c, slug in colunas:
            valor = _normalizar(sheet.cell(r, c), book.datemode)
            valores[slug] = valor
            if valor:
                preenchidos += 1
        # Linhas de rodapé/título têm só a 1ª célula ("VSky - Velp ...");
        # linhas de dados sempre têm vários campos preenchidos.
        if preenchidos >= 3:
            linhas.append(valores)
    return linhas


def linha_hash(valores: dict[str, str]) -> str:
    """SHA-256 da linha inteira, na ordem canônica das colunas."""
    canonico = "\x1f".join(valores.get(slug, "") for slug in SLUGS)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def data_ocorrencia_dt(valores: dict[str, str]) -> datetime | None:
    bruto = valores.get("data_ocorrencia") or ""
    try:
        return datetime.strptime(bruto, DATA_HORA_FMT)
    except ValueError:
        return None


def _normalizar(cell, datemode: int) -> str:
    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate_as_datetime(cell.value, datemode).strftime(DATA_HORA_FMT)
        except (ValueError, OverflowError):
            return str(cell.value).strip()
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        valor = cell.value
        if float(valor).is_integer():
            return str(int(valor))
        return repr(valor)
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return "1" if cell.value else "0"
    return str(cell.value).strip()
