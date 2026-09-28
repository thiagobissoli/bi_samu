"""ExportService (§39.17) — exportação em CSV, Excel e PDF.

Uso típico numa rota:

    from app.core.export import COLUNAS_PADRAO, export_response

    @router.get("/export")
    def export(formato: str = "csv", ...):
        return export_response(itens, COLUNAS, formato, "Usuários", tz=tz)

As colunas são pares (atributo, rótulo). O atributo aceita navegação por
ponto (`empresa.nome_fantasia`).
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import Response

Coluna = tuple[str, str]

FORMATOS = {
    "csv": ("text/csv; charset=utf-8", "csv"),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
    ),
    "pdf": ("application/pdf", "pdf"),
}


def slug_arquivo(titulo: str) -> str:
    valor = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode()
    return re.sub(r"[^\w]+", "_", valor).strip("_").lower() or "export"


def valor_de(obj, atributo: str, tz: str = "UTC") -> str:
    """Lê o atributo (aceita `a.b.c`) e formata para exibição."""
    valor = obj
    for parte in atributo.split("."):
        valor = getattr(valor, parte, None)
        if valor is None:
            return ""
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    if isinstance(valor, datetime):
        if valor.tzinfo is None:
            valor = valor.replace(tzinfo=dt_timezone.utc)
        try:
            zona = ZoneInfo(tz)
        except Exception:  # noqa: BLE001
            zona = dt_timezone.utc
        return valor.astimezone(zona).strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, Decimal):
        return f"{valor:.2f}".replace(".", ",")
    if isinstance(valor, (list, tuple)):
        return ", ".join(str(v) for v in valor)
    return str(valor)


def _matriz(itens, colunas: list[Coluna], tz: str) -> list[list[str]]:
    return [[valor_de(item, attr, tz) for attr, _ in colunas] for item in itens]


def para_csv(itens, colunas: list[Coluna], tz: str = "UTC") -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")  # ';' abre direto no Excel pt-BR
    writer.writerow([rotulo for _, rotulo in colunas])
    writer.writerows(_matriz(itens, colunas, tz))
    # BOM para o Excel reconhecer o UTF-8 e não quebrar os acentos.
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def para_xlsx(itens, colunas: list[Coluna], titulo: str, tz: str = "UTC") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = titulo[:31] or "Dados"

    cabecalho = Font(bold=True, color="FFFFFF")
    fundo = PatternFill("solid", fgColor="0D6EFD")
    for indice, (_, rotulo) in enumerate(colunas, start=1):
        celula = ws.cell(row=1, column=indice, value=rotulo)
        celula.font = cabecalho
        celula.fill = fundo
        celula.alignment = Alignment(horizontal="center")

    for linha in _matriz(itens, colunas, tz):
        ws.append(linha)

    for indice, (_, rotulo) in enumerate(colunas, start=1):
        largura = max(
            [len(rotulo)] + [len(str(l[indice - 1])) for l in _matriz(itens, colunas, tz)]
        )
        ws.column_dimensions[get_column_letter(indice)].width = min(50, largura + 3)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    saida = io.BytesIO()
    wb.save(saida)
    return saida.getvalue()


def para_pdf(itens, colunas: list[Coluna], titulo: str, tz: str = "UTC") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    saida = io.BytesIO()
    paisagem = len(colunas) > 4
    doc = SimpleDocTemplate(
        saida,
        pagesize=landscape(A4) if paisagem else A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title=titulo,
    )
    estilos = getSampleStyleSheet()
    celula = estilos["BodyText"]
    celula.fontSize = 8
    celula.leading = 10

    dados = [[Paragraph(f"<b>{rotulo}</b>", celula) for _, rotulo in colunas]]
    for linha in _matriz(itens, colunas, tz):
        dados.append([Paragraph(valor, celula) for valor in linha])

    tabela = Table(dados, repeatRows=1)
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d6efd")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))

    emitido = datetime.now(dt_timezone.utc)
    try:
        emitido = emitido.astimezone(ZoneInfo(tz))
    except Exception:  # noqa: BLE001
        pass

    doc.build([
        Paragraph(f"<b>{titulo}</b>", estilos["Title"]),
        Paragraph(
            f"{len(itens)} registro(s) — emitido em "
            f"{emitido.strftime('%d/%m/%Y %H:%M')}",
            estilos["Normal"],
        ),
        Spacer(1, 6 * mm),
        tabela,
    ])
    return saida.getvalue()


def exportar(
    itens, colunas: list[Coluna], formato: str, titulo: str, tz: str = "UTC"
) -> tuple[bytes, str, str]:
    """Devolve (conteúdo, mime, extensão)."""
    formato = (formato or "csv").lower()
    if formato not in FORMATOS:
        formato = "csv"
    mime, extensao = FORMATOS[formato]
    if formato == "csv":
        return para_csv(itens, colunas, tz), mime, extensao
    if formato == "xlsx":
        return para_xlsx(itens, colunas, titulo, tz), mime, extensao
    return para_pdf(itens, colunas, titulo, tz), mime, extensao


def export_response(
    itens, colunas: list[Coluna], formato: str, titulo: str, tz: str = "UTC"
) -> Response:
    conteudo, mime, extensao = exportar(itens, colunas, formato, titulo, tz)
    nome = f"{slug_arquivo(titulo)}.{extensao}"
    return Response(
        content=conteudo,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


def tz_da_empresa(db, empresa_id: int = 1) -> str:
    """Fuso configurado pela empresa (§22), para datar os relatórios."""
    from app.core.config import settings
    from app.core.config_service import get_config

    return get_config(db, "timezone", settings.timezone, empresa_id) or "UTC"
