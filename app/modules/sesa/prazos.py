"""Competências e prazos dos envios à SESA — funções puras.

Uma **competência** é o mês em que o envio é feito (as colunas da planilha
"Processos da qualidade - SESA"): as certidões de outubro são as emitidas
para o 1º dia útil de outubro. É guardada como o dia 1 do mês.

Dia útil: segunda a sexta, fora os feriados nacionais, os pontos
facultativos do governo estadual (Carnaval, Corpus Christi), o feriado
estadual do ES (Nossa Senhora da Penha, 8 dias depois da segunda de Páscoa)
e os feriados extras configurados em `sesa_feriados_extras`.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro")

_FIXOS = ((1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15),
          (11, 20), (12, 25))


def pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(ano, mes, dia)


def ler_extras(texto: str | None) -> list[str]:
    """'08/09, 26/12/2026' → ['08/09', '26/12/2026'] (dd/mm repete todo ano)."""
    return re.findall(r"\d{1,2}/\d{1,2}(?:/\d{4})?", texto or "")


def feriados(ano: int, extras: list[str] | tuple = ()) -> set[date]:
    p = pascoa(ano)
    dias = {date(ano, m, d) for m, d in _FIXOS}
    dias |= {p - timedelta(days=48), p - timedelta(days=47),   # Carnaval
             p - timedelta(days=2),                            # Paixão
             p + timedelta(days=8),                            # N. Sra. da Penha (ES)
             p + timedelta(days=60)}                           # Corpus Christi
    for item in extras:
        partes = [int(x) for x in item.split("/")]
        try:
            if len(partes) == 2:
                dias.add(date(ano, partes[1], partes[0]))
            elif partes[2] == ano:
                dias.add(date(ano, partes[1], partes[0]))
        except ValueError:
            continue
    return dias


def dia_util(dia: date, extras=()) -> bool:
    return dia.weekday() < 5 and dia not in feriados(dia.year, extras)


def enesimo_dia_util(ano: int, mes: int, n: int, extras=()) -> date:
    """n-ésimo dia útil do mês (n ≥ 1). Se o mês não tiver tantos, o último."""
    dia, achados, ultimo = date(ano, mes, 1), 0, None
    while dia.month == mes:
        if dia_util(dia, extras):
            achados += 1
            ultimo = dia
            if achados == n:
                return dia
        dia += timedelta(days=1)
    return ultimo or date(ano, mes, 1)


def prazo(competencia: date, tipo: str, dia: int, extras=()) -> date:
    """Data-limite do envio: 'util' = n-ésimo dia útil; 'corrido' = dia n
    (se cair em dia não útil, vale o próximo dia útil)."""
    if tipo == "util":
        return enesimo_dia_util(competencia.year, competencia.month, dia, extras)
    alvo = date(competencia.year, competencia.month, 1) + timedelta(days=dia - 1)
    while not dia_util(alvo, extras):
        alvo += timedelta(days=1)
    return alvo


def descrever_prazo(tipo: str, dia: int) -> str:
    return f"{dia}º dia útil" if tipo == "util" else f"dia {dia}"


# ------------------------------------------------------------------ competência

def competencia_de(texto: str | None, hoje: date | None = None) -> date:
    """'2026-10' → date(2026, 10, 1). Inválido ou vazio → mês de `hoje`."""
    hoje = hoje or date.today()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", (texto or "").strip())
    if m and 1 <= int(m.group(2)) <= 12 and 2000 <= int(m.group(1)) <= 2100:
        return date(int(m.group(1)), int(m.group(2)), 1)
    return date(hoje.year, hoje.month, 1)


def chave(competencia: date) -> str:
    return f"{competencia.year}-{competencia.month:02d}"


def rotulo(competencia: date) -> str:
    return f"{MESES[competencia.month - 1]}/{competencia.year}"


def somar_meses(competencia: date, n: int) -> date:
    total = competencia.year * 12 + competencia.month - 1 + n
    return date(total // 12, total % 12 + 1, 1)


def aplica(meses: str | None, competencia: date) -> bool:
    """A obrigação tem envio nesta competência? `meses` vazio = todo mês."""
    if not meses:
        return True
    return competencia.month in {int(x) for x in re.findall(r"\d+", meses)}


def periodo_competencia_anterior(competencia: date) -> tuple[date, date]:
    """Dados de um envio são do mês anterior: envio de out → 01/09 a 30/09."""
    inicio = somar_meses(competencia, -1)
    fim = date.fromordinal(competencia.toordinal() - 1)
    return inicio, fim
