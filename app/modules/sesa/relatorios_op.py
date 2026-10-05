"""Relatórios operacionais da SESA calculados dos dados do vSky.

Três itens do "Relatório de dados mensais", todos derivados dos registros
que o sistema já importa — sem baixar planilha do vSky:

    saida-municipio     Saída de Ambulância por Município (USA/USB/total)
    saida-codigo        Saída de Ambulância por Código (cor)
    tempo-deslocamento  Tempo de Deslocamento dos urgentes, pelos 4 municípios

A definição de **saída** e de **tempo de deslocamento** é a mesma do módulo
de Indicadores (empenho que iniciou deslocamento; t_deslocamento = chegada no
local − início do deslocamento). Urgentes = código Vermelho ou Amarelo.

Funções puras: recebem o DataFrame do núcleo recortado no período.
"""

from __future__ import annotations

import io
from datetime import date

from app.modules.sesa.saida_usa import ROTULO_COR, saidas

# Municípios da Região Metropolitana usados no Tempo de Deslocamento
MUNICIPIOS_METRO = ("CARIACICA", "SERRA", "VITORIA", "VILA VELHA")
ORDEM_COR = ("vermelho", "amarelo", "verde", "nao_urgente", "orientacao_medica")
URGENTES = ("vermelho", "amarelo")

TIPOS = {
    "saida-municipio": {"titulo": "Saída de Ambulância por Município",
                        "item": "Saída de Ambulância por Município"},
    "saida-codigo": {"titulo": "Saída de Ambulância por Código",
                     "item": "Saída de Ambulância por Código"},
    "tempo-deslocamento": {"titulo": "Tempo de Deslocamento",
                           "item": "Tempo de deslocamento"},
    "ranking-acionamento": {"titulo": "Ranking de Acionamento",
                            "item": "Ranking de Acionamento"},
}


def acionamentos(df):
    """Empenhos: registros em que uma viatura foi acionada (unidade presente),
    tenha ela saído ou não. É a leitura de "acionamento" do Ranking."""
    return df[df["unidade_curta"].notna() & df["unidade_curta"].ne("")]


def _no_periodo(df, inicio: date, fim: date):
    base = saidas(df)
    if "dia" in base.columns:
        base = base[(base["dia"] >= inicio) & (base["dia"] <= fim)]
    return base


def _por(base, coluna: str, chaves=None, rotulos=None) -> list[dict]:
    """Linhas com USA, USB e total para cada valor de `coluna`."""
    serie = base[coluna]
    if chaves is None:
        chaves = [str(k) for k in serie.value_counts().index]
    linhas = []
    for chave in chaves:
        marca = serie == chave
        usa = int((marca & (base["recurso"] == "USA")).sum())
        usb = int((marca & (base["recurso"] == "USB")).sum())
        total = int(marca.sum())
        if total:
            linhas.append({"rotulo": (rotulos or {}).get(chave, chave),
                           "usa": usa, "usb": usb, "total": total})
    return linhas


def calcular(tipo: str, df, inicio: date, fim: date) -> dict:
    base = _no_periodo(df, inicio, fim)
    total = len(base)
    usa, usb = int((base["recurso"] == "USA").sum()), int((base["recurso"] == "USB").sum())
    resumo = {"total": total, "usa": usa, "usb": usb}

    if tipo == "saida-municipio":
        linhas = _por(base, "cidade")
        linhas.sort(key=lambda l: l["total"], reverse=True)
        return {"tipo": tipo, "resumo": resumo,
                "colunas": ("Município", "USA", "USB", "Total", "%"),
                "linhas": linhas, "inicio": inicio, "fim": fim}

    if tipo == "saida-codigo":
        presentes = [c for c in ORDEM_COR if (base["codigo_cor"] == c).any()]
        extras = [str(c) for c in base["codigo_cor"].dropna().unique()
                  if c not in ORDEM_COR]
        linhas = _por(base, "codigo_cor", presentes + extras,
                      {c: ROTULO_COR.get(c, c) for c in ORDEM_COR})
        return {"tipo": tipo, "resumo": resumo,
                "colunas": ("Código", "USA", "USB", "Total", "%"),
                "linhas": linhas, "inicio": inicio, "fim": fim}

    if tipo == "tempo-deslocamento":
        urg = base[base["codigo_cor"].isin(URGENTES) & base["t_deslocamento"].notna()]
        cidade_norm = urg["cidade"].fillna("").str.upper().str.strip()
        linhas = []
        for m in MUNICIPIOS_METRO:
            sub = urg[cidade_norm == m]["t_deslocamento"]
            linhas.append({"rotulo": m.title(), "n": int(len(sub)),
                           "media": round(sub.mean() / 60, 1) if len(sub) else None,
                           "mediana": round(sub.median() / 60, 1) if len(sub) else None})
        geral = urg[cidade_norm.isin(MUNICIPIOS_METRO)]["t_deslocamento"]
        return {"tipo": tipo, "resumo": resumo,
                "colunas": ("Município", "Saídas urgentes", "Média (min)", "Mediana (min)"),
                "linhas": linhas, "inicio": inicio, "fim": fim,
                "geral": {"n": int(len(geral)),
                          "media": round(geral.mean() / 60, 1) if len(geral) else None,
                          "mediana": round(geral.median() / 60, 1) if len(geral) else None}}

    if tipo == "ranking-acionamento":
        base = acionamentos(df)
        if "dia" in base.columns:
            base = base[(base["dia"] >= inicio) & (base["dia"] <= fim)]
        total = len(base)
        resumo = {"total": total,
                  "usa": int((base["recurso"] == "USA").sum()),
                  "usb": int((base["recurso"] == "USB").sum())}
        linhas = _por(base, "cidade")
        linhas.sort(key=lambda l: l["total"], reverse=True)
        return {"tipo": tipo, "resumo": resumo, "ranking": True,
                "colunas": ("Posição", "Município", "USA", "USB", "Acionamentos", "%"),
                "linhas": linhas, "inicio": inicio, "fim": fim}

    raise ValueError(f"Tipo de relatório desconhecido: {tipo}")


def _pct(parte: int, total: int) -> float:
    return round(parte / total * 100, 1) if total else 0.0


def gerar_xlsx(dados: dict, periodo_rotulo: str, orgao: str = "SAMU 192 ES") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    tipo = dados["tipo"]
    titulo = TIPOS[tipo]["titulo"]
    titulo_fill = PatternFill("solid", fgColor="1F4E79")
    titulo_font = Font(bold=True, color="FFFFFF", size=12)
    cab_fill = PatternFill("solid", fgColor="D9E1F2")
    negrito = Font(bold=True)
    centro = Alignment(horizontal="center")

    wb = Workbook()
    ws = wb.active
    ws.title = titulo[:31]
    colunas = dados["colunas"]
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(colunas))
    c = ws.cell(1, 1, f"{titulo} — {orgao}")
    c.fill, c.font = titulo_fill, titulo_font
    ws.cell(2, 1, f"Período: {periodo_rotulo}").font = Font(italic=True)
    if tipo == "tempo-deslocamento":
        ws.cell(3, 1, "Urgentes (Vermelho/Amarelo) · tempo = chegada no local − início do "
                      "deslocamento").font = Font(italic=True, size=9)

    cab_linha = 4
    for j, nome in enumerate(colunas, start=1):
        cel = ws.cell(cab_linha, j, nome)
        cel.fill, cel.font = cab_fill, negrito
        if j > 1:
            cel.alignment = centro

    linha = cab_linha + 1
    if tipo == "tempo-deslocamento":
        for l in dados["linhas"]:
            ws.cell(linha, 1, l["rotulo"])
            ws.cell(linha, 2, l["n"]).alignment = centro
            ws.cell(linha, 3, l["media"] if l["media"] is not None else "—").alignment = centro
            ws.cell(linha, 4, l["mediana"] if l["mediana"] is not None else "—").alignment = centro
            linha += 1
        g = dados["geral"]
        ws.cell(linha, 1, "Geral (4 municípios)").font = negrito
        for j, v in enumerate((g["n"], g["media"], g["mediana"]), start=2):
            cel = ws.cell(linha, j, v if v is not None else "—")
            cel.font, cel.alignment = negrito, centro
    elif dados.get("ranking"):
        total = dados["resumo"]["total"]
        for pos, l in enumerate(dados["linhas"], start=1):
            ws.cell(linha, 1, pos).alignment = centro
            ws.cell(linha, 2, l["rotulo"])
            ws.cell(linha, 3, l["usa"]).alignment = centro
            ws.cell(linha, 4, l["usb"]).alignment = centro
            ws.cell(linha, 5, l["total"]).alignment = centro
            ws.cell(linha, 6, f'{_pct(l["total"], total)}%').alignment = centro
            linha += 1
        ws.cell(linha, 2, "Total").font = negrito
        r = dados["resumo"]
        for j, v in enumerate((r["usa"], r["usb"], r["total"], "100%"), start=3):
            cel = ws.cell(linha, j, v)
            cel.font, cel.alignment = negrito, centro
    else:
        total = dados["resumo"]["total"]
        for l in dados["linhas"]:
            ws.cell(linha, 1, l["rotulo"])
            ws.cell(linha, 2, l["usa"]).alignment = centro
            ws.cell(linha, 3, l["usb"]).alignment = centro
            ws.cell(linha, 4, l["total"]).alignment = centro
            ws.cell(linha, 5, f'{_pct(l["total"], total)}%').alignment = centro
            linha += 1
        ws.cell(linha, 1, "Total").font = negrito
        r = dados["resumo"]
        for j, v in enumerate((r["usa"], r["usb"], r["total"], "100%"), start=2):
            cel = ws.cell(linha, j, v)
            cel.font, cel.alignment = negrito, centro

    if dados.get("ranking"):
        larguras = [9, 34, 12, 12, 16, 10]
    else:
        larguras = [34] + [14] * (len(colunas) - 1)
    for j, w in enumerate(larguras, start=1):
        ws.column_dimensions[get_column_letter(j)].width = w

    saida = io.BytesIO()
    wb.save(saida)
    return saida.getvalue()
