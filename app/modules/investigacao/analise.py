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

# Meta de tempo de resposta adotada pelo serviço
META_TEMPO_RESPOSTA = 600      # 10 minutos
MINIMO_AMOSTRA_ROTA = 10       # trajetos iguais para a rota servir de base
FAIXAS_HORARIAS = [(-1, 5, "00h–05h"), (5, 9, "06h–09h"), (9, 13, "10h–13h"),
                   (13, 17, "14h–17h"), (17, 21, "18h–21h"), (21, 24, "22h–23h")]


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


# ------------------------------------------- fatores do tempo de resposta

def _faixa_horaria(hora: int) -> str:
    for ini, fim, rotulo in FAIXAS_HORARIAS:
        if ini < hora <= fim:
            return rotulo
    return FAIXAS_HORARIAS[-1][2]


def _mediana(serie: pd.Series) -> float | None:
    return float(serie.median()) if len(serie) else None


def fatores_tempo_resposta(empresa_id: int, registro_id: int,
                           investigacao: dict | None = None) -> dict:
    """Por que o tempo de resposta passou de 10 min, com evidência.

    Separa o que é **distância estrutural** (o trajeto é longo mesmo) do
    que é **anormalidade no percurso** (trânsito, rota, atraso na saída)
    e do que é **atraso de processo** (central, regulação, despacho),
    comparando o caso com o histórico do próprio serviço:

    - o mesmo trajeto (aquela viatura até aquela cidade) costuma levar
      quanto? se o caso está na média do trajeto, a causa é distância;
    - a mesma cidade, na mesma faixa horária, costuma levar mais que nas
      outras faixas? é o que se pode dizer sobre trânsito com estes
      dados (o relatório não traz rota nem condição de tráfego);
    - as viaturas sediadas na própria cidade levam quanto até lá? mede o
      custo de ter mandado viatura de fora.
    """
    df = nucleo.carregar(empresa_id)
    linha = df[df["id"] == registro_id]
    if linha.empty:
        return {"aplicavel": False}
    r = linha.iloc[0]

    tr = r.get("tempo_resposta")
    cap = CAP_TEMPO.get("tempo_resposta", 14400)
    if pd.isna(tr) or not (0 < float(tr) < cap):
        return {"aplicavel": False,
                "motivo": "Tempo de resposta não medido para este empenho."}
    tr = float(tr)
    excesso = tr - META_TEMPO_RESPOSTA
    dentro = excesso <= 0

    fatores: list[dict] = []
    cidade, unidade = r.get("cidade"), r.get("unidade")
    desloc = r.get("t_p4_2")
    desloc_valido = (not pd.isna(desloc)
                     and 0 < float(desloc) < CAP_TEMPO.get("t_p4_2", 14400))
    base_desl = df[(df["t_p4_2"] > 0) & (df["t_p4_2"] < CAP_TEMPO.get("t_p4_2", 14400))]

    # 1. Distância: o mesmo trajeto costuma levar quanto?
    if desloc_valido and cidade and unidade:
        rota = base_desl[(base_desl["unidade"] == unidade)
                         & (base_desl["cidade"] == cidade)]
        med_rota = _mediana(rota["t_p4_2"])
        if med_rota and len(rota) >= MINIMO_AMOSTRA_ROTA:
            razao = float(desloc) / med_rota
            if razao <= 1.25:
                fatores.append({
                    "tipo": "distancia",
                    "titulo": "Distância do trajeto (estrutural)",
                    "evidencia": (
                        f"O deslocamento levou {mmss(desloc)}; este mesmo "
                        f"trajeto ({unidade} → {cidade}) costuma levar "
                        f"{mmss(med_rota)} (n={len(rota)}). O tempo está "
                        "dentro do usual — o trajeto é longo por si só, não "
                        "houve anormalidade no percurso."),
                    "impacto": round(float(desloc)),
                })
            else:
                fatores.append({
                    "tipo": "percurso",
                    "titulo": "Deslocamento acima do usual neste trajeto",
                    "evidencia": (
                        f"O deslocamento levou {mmss(desloc)}, {razao:.1f}× o "
                        f"usual deste trajeto ({mmss(med_rota)}, n={len(rota)}). "
                        "Sugere condição do percurso naquele momento — "
                        "trânsito, rota, bloqueio ou dificuldade de acesso. "
                        "O relatório do vSky não registra rota nem tráfego, "
                        "então a causa exata precisa ser apurada com a equipe."),
                    "impacto": round(float(desloc) - med_rota),
                })
        elif med_rota:
            fatores.append({
                "tipo": "dado",
                "titulo": "Trajeto sem histórico suficiente",
                "evidencia": (
                    f"Só há {len(rota)} registro(s) de {unidade} até {cidade} "
                    "— pouco para dizer se o deslocamento deste caso foi "
                    "atípico."),
                "impacto": 0,
            })

    # 2. Trânsito: a faixa horária é sistematicamente pior naquela cidade?
    if desloc_valido and cidade and not pd.isna(r.get("hora")):
        na_cidade = base_desl[base_desl["cidade"] == cidade]
        if len(na_cidade) >= MINIMO_AMOSTRA:
            faixa = _faixa_horaria(int(r["hora"]))
            marca = na_cidade["hora"].map(lambda h: _faixa_horaria(int(h)))
            desta_faixa = na_cidade[marca == faixa]
            outras = na_cidade[marca != faixa]
            m_faixa, m_outras = _mediana(desta_faixa["t_p4_2"]), _mediana(outras["t_p4_2"])
            if m_faixa and m_outras and len(desta_faixa) >= MINIMO_AMOSTRA_ROTA:
                dif = m_faixa - m_outras
                if dif >= 60:
                    fatores.append({
                        "tipo": "transito",
                        "titulo": f"Faixa horária mais lenta em {cidade} ({faixa})",
                        "evidencia": (
                            f"Nesta faixa o deslocamento até {cidade} tem "
                            f"mediana {mmss(m_faixa)} (n={len(desta_faixa)}), "
                            f"contra {mmss(m_outras)} nas demais faixas — "
                            f"{mmss(dif)} a mais, compatível com trânsito no "
                            "horário."),
                        "impacto": round(dif),
                    })
                else:
                    fatores.append({
                        "tipo": "transito",
                        "titulo": "Horário não explica o atraso",
                        "evidencia": (
                            f"O deslocamento até {cidade} nesta faixa ({faixa}) "
                            f"tem mediana {mmss(m_faixa)}, praticamente igual "
                            f"às demais faixas ({mmss(m_outras)}). O horário "
                            "não é uma explicação plausível aqui."),
                        "impacto": 0,
                    })

    # 3. Custo de ter mandado viatura de outro município
    inv = investigacao or {}
    if desloc_valido and cidade and inv.get("fora_do_municipio"):
        locais = base_desl[
            (base_desl["cidade"] == cidade)
            & (base_desl["unidade"].str.split(" - ", n=1).str[1].str.strip()
               .map(lambda m: bool(m) and nucleo.norm_txt(m)
                    == nucleo.norm_txt(cidade)))]
        med_locais = _mediana(locais["t_p4_2"])
        if med_locais and len(locais) >= MINIMO_AMOSTRA_ROTA:
            fatores.append({
                "tipo": "recurso",
                "titulo": "Viatura de outro município (percurso maior)",
                "evidencia": (
                    f"{unidade} levou {mmss(desloc)} até {cidade}; as viaturas "
                    f"sediadas em {cidade} levam em mediana {mmss(med_locais)} "
                    f"(n={len(locais)}) — diferença de "
                    f"{mmss(float(desloc) - med_locais)}. "
                    + (inv.get("veredito") or "")),
                "impacto": round(float(desloc) - med_locais),
            })

    # 4. Atrasos de processo (etapas antes de sair para o local)
    atraso = decompor_atraso(empresa_id, registro_id)
    for e in atraso.get("contribuintes", []):
        if e["col"] in ("t_p1", "t_p2", "t_p3", "t_p4_1"):
            fatores.append({
                "tipo": "processo",
                "titulo": f"Atraso de processo em {e['rotulo']}",
                "evidencia": (
                    f"{e['valor']} ({e['papel']})"
                    + (f", meta {e['meta']}" if e["meta"] else "")
                    + (f", {e['vezes_referencia']}× a referência "
                       f"{e['referencia']} (n={e['amostra']})"
                       if e["vezes_referencia"] else "")
                    + ". Tempo consumido antes de a viatura estar a caminho."),
                "impacto": max(e["excesso_segundos"], 0),
            })

    fatores.sort(key=lambda f: f["impacto"], reverse=True)
    return {
        "aplicavel": True,
        "meta": mmss(META_TEMPO_RESPOSTA),
        "tempo_resposta": mmss(tr),
        "dentro_da_meta": dentro,
        "excesso": mmss(excesso) if excesso > 0 else None,
        "fatores": fatores,
        "resumo": _resumo_fatores(dentro, tr, excesso, fatores),
    }


def _resumo_fatores(dentro: bool, tr: float, excesso: float,
                    fatores: list[dict]) -> str:
    if dentro:
        return (f"Tempo de resposta {mmss(tr)} — dentro da meta de "
                f"{mmss(META_TEMPO_RESPOSTA)}.")
    if not fatores:
        return (f"Tempo de resposta {mmss(tr)}, {mmss(excesso)} acima da meta "
                f"de {mmss(META_TEMPO_RESPOSTA)}, mas os dados disponíveis não "
                "permitem apontar o que contribuiu.")
    rotulos = {"distancia": "distância do trajeto",
               "percurso": "condição do percurso",
               "transito": "horário/trânsito", "recurso": "origem da viatura",
               "processo": "atraso de processo", "dado": "falta de histórico"}
    principais = [rotulos.get(f["tipo"], f["tipo"]) for f in fatores
                  if f["impacto"] > 0][:3]
    texto = (f"Tempo de resposta {mmss(tr)} — {mmss(excesso)} acima da meta de "
             f"{mmss(META_TEMPO_RESPOSTA)}.")
    if principais:
        texto += " Principais fatores: " + ", ".join(dict.fromkeys(principais)) + "."
    return texto
