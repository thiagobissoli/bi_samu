"""Decomposição do atraso de uma ocorrência, etapa a etapa (§35.16).

Responde "quais Ps contribuíram para o atraso" com cálculo — não com
opinião: cada etapa é comparada à sua meta (quando existe) e à mediana
de casos comparáveis (mesmo código de gravidade e mesmo tipo de
viatura), e o excesso é quantificado em segundos e em % do tempo de
resposta.

A referência sai da própria base: é o desempenho usual do serviço para
casos parecidos, não uma meta externa. Assim "atrasou" significa "levou
mais que o próprio serviço costuma levar", que é o que sustenta uma
análise de causa.
"""

from __future__ import annotations

import pandas as pd

from app.modules.indicadores import nucleo
from app.modules.indicadores.constants import CAP_TEMPO, SLA_P1, SLA_P2_POR_COR
from app.modules.indicadores.ocorrencia import META_P4_1, mmss

# Etapas que somam o tempo de resposta (abertura → chegada no local).
# P4.1 e P4.2 detalham o P4; por isso o P4 fica fora da soma.
ETAPAS_RESPOSTA = [
    ("t_p1", "P1 · Atendimento TARM", "TARM recebe e qualifica o chamado"),
    ("t_p2", "P2 · Regulação médica", "médico regulador decide a resposta"),
    ("t_p3", "P3 · Despacho", "controlador aciona a viatura"),
    ("t_p4_1", "P4.1 · Saída de base", "equipe sai da base após o acionamento"),
    ("t_p4_2", "P4.2 · Deslocamento", "trajeto da base até o local"),
]
# Etapas posteriores à chegada — não entram no tempo de resposta, mas
# contam para a duração total do atendimento.
ETAPAS_POSTERIORES = [
    ("t_p5_6_7", "P5-7 · Tempo de cena", "atendimento no local"),
    ("t_p8", "P8 · Transporte", "deslocamento até o hospital"),
    ("t_p9", "P9 · Transf. de cuidados", "passagem do paciente ao hospital"),
]

# Excesso a partir do qual a etapa é considerada contribuinte do atraso
FATOR_ALERTA = 1.5      # 50% acima da referência
MINIMO_RELEVANTE = 60   # segundos — ignora diferenças irrelevantes
MINIMO_AMOSTRA = 30     # casos comparáveis para a referência ser confiável


def _meta(col: str, cor: str | None) -> int | None:
    if col == "t_p1":
        return SLA_P1
    if col == "t_p2":
        return SLA_P2_POR_COR.get(cor)
    if col == "t_p4_1":
        return META_P4_1
    return None


def _referencia(df: pd.DataFrame, col: str, r) -> tuple[float | None, int]:
    """Mediana da etapa em casos comparáveis (código + tipo de viatura)."""
    cap = CAP_TEMPO.get(col, 14400)
    base = df[(df[col] > 0) & (df[col] < cap)]
    for filtro in (
        # do mais específico para o mais geral, até ter amostra suficiente
        lambda b: b[(b["codigo_cor"] == r.get("codigo_cor"))
                    & (b["recurso"] == r.get("recurso"))],
        lambda b: b[b["codigo_cor"] == r.get("codigo_cor")],
        lambda b: b,
    ):
        sub = filtro(base)
        if len(sub) >= MINIMO_AMOSTRA:
            return float(sub[col].median()), len(sub)
    return (float(base[col].median()), len(base)) if len(base) else (None, 0)


def decompor_atraso(empresa_id: int, registro_id: int) -> dict:
    """Etapas do atendimento, com excesso sobre meta e sobre a referência."""
    df = nucleo.carregar(empresa_id)
    linha = df[df["id"] == registro_id]
    if linha.empty:
        return {"etapas": [], "resumo": "Empenho não encontrado."}
    r = linha.iloc[0]
    cor = r.get("codigo_cor")

    tr = r.get("tempo_resposta")
    tr_valido = (not pd.isna(tr)
                 and 0 < float(tr) < CAP_TEMPO.get("tempo_resposta", 14400))
    total = float(tr) if tr_valido else None

    etapas, contribuintes = [], []
    for col, rotulo, papel in ETAPAS_RESPOSTA + ETAPAS_POSTERIORES:
        v = r.get(col)
        cap = CAP_TEMPO.get(col, 14400)
        if pd.isna(v) or not (0 < float(v) < cap):
            etapas.append({"col": col, "rotulo": rotulo, "papel": papel,
                           "valor": None, "situacao": "sem_dado",
                           "resposta": col in dict(
                               (c, 1) for c, _, _ in ETAPAS_RESPOSTA)})
            continue
        v = float(v)
        meta = _meta(col, cor)
        ref, amostra = _referencia(df, col, r)
        excesso_ref = (v - ref) if ref else None
        estourou_meta = bool(meta and v > meta)
        acima_ref = bool(ref and v > ref * FATOR_ALERTA
                         and excesso_ref >= MINIMO_RELEVANTE)

        situacao = "ruim" if (estourou_meta or acima_ref) else "ok"
        item = {
            "col": col, "rotulo": rotulo, "papel": papel,
            "valor": mmss(v), "segundos": round(v),
            "meta": mmss(meta) if meta else None,
            "estourou_meta": estourou_meta,
            "referencia": mmss(ref) if ref else None,
            "amostra": amostra,
            "excesso": mmss(excesso_ref) if excesso_ref and excesso_ref > 0
                       else None,
            "excesso_segundos": round(excesso_ref) if excesso_ref else 0,
            "vezes_referencia": round(v / ref, 1) if ref else None,
            "pct_do_total": (round(v / total * 100, 1)
                             if total and col != "t_p4" else None),
            "situacao": situacao,
            "resposta": any(col == c for c, _, _ in ETAPAS_RESPOSTA),
        }
        etapas.append(item)
        if situacao == "ruim" and item["resposta"]:
            contribuintes.append(item)

    contribuintes.sort(key=lambda e: e["excesso_segundos"], reverse=True)
    # Quanto do tempo de resposta as etapas medidas realmente explicam:
    # marcações ausentes deixam um vão que não se pode atribuir a ninguém.
    medido = sum(e["segundos"] for e in etapas
                 if e["resposta"] and e.get("segundos"))
    cobertura = None
    if total and medido:
        cobertura = {
            "medido": mmss(medido), "total": mmss(total),
            "pct": round(medido / total * 100),
            "nao_explicado": mmss(total - medido) if total - medido > 60 else None,
            "faltando": [e["rotulo"].split(" · ")[0] for e in etapas
                         if e["resposta"] and e["valor"] is None],
        }
    return {"etapas": etapas, "contribuintes": contribuintes,
            "tempo_resposta": mmss(total) if total else None,
            "cobertura": cobertura,
            "resumo": _resumo(contribuintes, total, etapas, cobertura)}


def _resumo(contribuintes: list[dict], total: float | None,
            etapas: list[dict], cobertura: dict | None = None) -> str:
    if not any(e["valor"] for e in etapas):
        return "Sem marcações de tempo suficientes para decompor o atendimento."
    if not contribuintes:
        return ("Nenhuma etapa do tempo de resposta ficou acima da meta ou "
                "do desempenho usual do serviço em casos comparáveis.")
    partes = []
    for e in contribuintes:
        motivo = []
        if e["estourou_meta"]:
            motivo.append(f"meta {e['meta']}")
        if e["vezes_referencia"] and e["vezes_referencia"] > 1:
            motivo.append(f"{e['vezes_referencia']}× a referência "
                          f"{e['referencia']}")
        partes.append(f"{e['rotulo'].split(' · ')[0]} {e['valor']} "
                      f"({', '.join(motivo)})")
    excesso = sum(e["excesso_segundos"] for e in contribuintes if
                  e["excesso_segundos"] > 0)
    texto = "Contribuíram para o atraso: " + "; ".join(partes) + "."
    if excesso > 0:
        texto += (f" Excesso somado sobre a referência: {mmss(excesso)}"
                  + (f" de um tempo de resposta de {mmss(total)}." if total
                     else "."))
    if cobertura and cobertura["nao_explicado"]:
        texto += (f" Atenção: as etapas medidas somam {cobertura['medido']} "
                  f"({cobertura['pct']}% do tempo de resposta) — restam "
                  f"{cobertura['nao_explicado']} sem marcação"
                  + (f" (faltam {', '.join(cobertura['faltando'])})."
                     if cobertura["faltando"] else "."))
    return texto
