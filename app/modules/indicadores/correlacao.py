"""Correlação entre indicadores.

Cada indicador é agregado por um **agrupamento** (dia, semana, unidade,
cidade, regulador…): cada grupo vira um ponto com o valor dos dois
indicadores. A correlação mede se os grupos em que um indicador é alto
também têm o outro alto (ou baixo).

Três leituras:
    dispersao  dois indicadores, um ponto por grupo, r de Pearson,
               ρ de Spearman, reta de tendência e interpretação
    matriz     correlação de Pearson entre vários indicadores de uma vez
    series     vários indicadores ao longo do tempo, alinhados

Correlação não é causa: dois indicadores podem andar juntos porque os dois
dependem de um terceiro (volume, hora do dia, distância). A tela diz isso.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.modules.indicadores import drill
from app.modules.indicadores.constants import SLA_P1

# chave -> (rótulo, unidade, tipo, definição)
#   tipo "tempo": média em minutos dos valores válidos da coluna
#   tipo "taxa":  % de linhas que atendem à condição, dentro da base
#   tipo "media": média simples da coluna
#   tipo "volume": contagem
TEMPOS = {
    "t_p1": "P1 — TARM",
    "t_p2": "P2 — Regulação",
    "t_p3": "P3 — Despacho",
    "t_central": "Tempo de Central",
    "t_p4_1": "Saída de base (P4.1)",
    "t_p4_2": "Deslocamento (P4.2)",
    "t_p4": "Tempo de chegada (P4)",
    "tempo_resposta": "Tempo de Resposta",
    "t_cena": "Tempo de Cena",
    "t_p8": "Transporte (P8)",
    "t_p9": "Transferência de cuidados (P9)",
}

METRICAS: dict[str, dict] = {}
for _col, _rot in TEMPOS.items():
    METRICAS[_col] = {"rotulo": _rot, "unidade": "min", "tipo": "tempo",
                      "col": _col, "grupo": "Tempos (média)"}
METRICAS.update({
    "empenhos": {"rotulo": "Empenhos (linhas)", "unidade": "n", "tipo": "volume",
                 "grupo": "Volume"},
    "ocorrencias": {"rotulo": "Ocorrências", "unidade": "n", "tipo": "volume",
                    "col": "ocorrencia", "grupo": "Volume"},
    "saidas": {"rotulo": "Saídas de viatura", "unidade": "n", "tipo": "volume",
               "base": [("mascara", "saida")], "grupo": "Volume"},
    "sla_p1": {"rotulo": "SLA P1 ≤ 1:30", "unidade": "%", "tipo": "taxa",
               "base": [("valida", "t_p1")], "cond": [("ate", "t_p1", SLA_P1)],
               "grupo": "Taxas"},
    "resposta_10": {"rotulo": "Resposta em até 10 min", "unidade": "%",
                    "tipo": "taxa", "base": [("valida", "tempo_resposta")],
                    "cond": [("ate", "tempo_resposta", 600)], "grupo": "Taxas"},
    "assertividade": {"rotulo": "Assertividade", "unidade": "%", "tipo": "taxa",
                      "base": [("mascara", "assertividade")],
                      "cond": [("mascara", "adequado")], "grupo": "Taxas"},
    "desperdicio": {"rotulo": "Desperdício real", "unidade": "%", "tipo": "taxa",
                    "base": [("mascara", "saida")],
                    "cond": [("mascara", "desperdicio_real")], "grupo": "Taxas"},
    "vermelho": {"rotulo": "Código vermelho", "unidade": "%", "tipo": "taxa",
                 "base": [("notna", "codigo_cor")],
                 "cond": [("igual", "codigo_cor", "vermelho")], "grupo": "Taxas"},
    "fora_municipio": {"rotulo": "Viatura de outro município", "unidade": "%",
                       "tipo": "taxa", "base": [("notna", "fora_do_municipio")],
                       "cond": [("verdadeiro", "fora_do_municipio")],
                       "grupo": "Taxas"},
    "com_atendimento": {"rotulo": "Com atendimento", "unidade": "%",
                        "tipo": "taxa",
                        "base": [("mascara", "atendimento_informado")],
                        "cond": [("mascara", "atendimento_com")], "grupo": "Taxas"},
    "obito": {"rotulo": "Óbito constatado", "unidade": "%", "tipo": "taxa",
              "base": [], "cond": [("mascara", "obito")], "grupo": "Taxas"},
    "news_alto": {"rotulo": "NEWS Alto", "unidade": "%", "tipo": "taxa",
                  "base": [("notna", "news_risco")],
                  "cond": [("igual", "news_risco", "Alto")], "grupo": "Taxas"},
    "news": {"rotulo": "NEWS médio", "unidade": "pts", "tipo": "media",
             "col": "news_total", "grupo": "Paciente"},
    "idade": {"rotulo": "Idade média", "unidade": "anos", "tipo": "media",
              "col": "idade_num", "grupo": "Paciente"},
})

DIAS_SEMANA = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"]

# chave -> (rótulo, temporal?)
DIMENSOES = {
    "dia": ("Dia", True),
    "semana": ("Semana operacional", True),
    "mes": ("Mês", True),
    "hora": ("Hora do dia", True),
    "dia_semana": ("Dia da semana (plantão)", True),
    "plantao": ("Plantão (dia + turno)", False),
    "unidade": ("Unidade", False),
    "cidade": ("Cidade", False),
    "micro_regiao": ("Micro região", False),
    "codigo": ("Código da ocorrência", False),
    "hospital": ("Hospital de destino", False),
    "tarm": ("TARM", False),
    "regulador": ("Regulador", False),
    "controlador": ("Controlador", False),
    "medico": ("Médico", False),
    "enfermeiro": ("Enfermeiro", False),
    "condutor": ("Condutor", False),
}
_COLUNA_DIM = {
    "plantao": "plantao", "unidade": "unidade_curta", "cidade": "cidade",
    "micro_regiao": "micro_regiao", "codigo": "codigo_da_ocorrencia",
    "hospital": "hospital_destino", "tarm": "tarm_nome",
    "regulador": "regulador_nome", "controlador": "controlador_nome",
    "medico": "medico_nome", "enfermeiro": "enfermeiro_nome",
    "condutor": "condutor_nome",
}

PADRAO_MATRIZ = ["t_central", "t_p4_1", "t_p4_2", "tempo_resposta", "t_cena",
                 "empenhos", "sla_p1", "assertividade", "desperdicio"]


# ------------------------------------------------------------------ grupos

def chave_grupo(df: pd.DataFrame, dimensao: str) -> pd.Series:
    """Identificador textual do grupo de cada linha (ordenável)."""
    if dimensao == "dia":
        return df["dia"].map(lambda d: d.isoformat() if pd.notna(d) else None)
    if dimensao == "semana":
        return df["semana_iso"]
    if dimensao == "mes":
        return df["dt_ocorr"].dt.strftime("%Y-%m")
    if dimensao == "hora":
        return df["hora"].map(lambda h: f"{int(h):02d}h" if pd.notna(h) else None)
    if dimensao == "dia_semana":
        return df["plantao_dia_semana"]
    serie = df[_COLUNA_DIM[dimensao]]
    return serie.where(serie.notna() & serie.ne(""))


def _ordenar(indice, dimensao: str) -> list:
    if dimensao == "dia_semana":
        return [d for d in DIAS_SEMANA if d in indice]
    return sorted(indice, key=str)


def tabela(df: pd.DataFrame, metricas: list[str], dimensao: str,
           min_n: int = 10) -> pd.DataFrame:
    """Uma linha por grupo; colunas = valor de cada indicador + n (linhas)."""
    chave = chave_grupo(df, dimensao)
    valido = chave.notna()
    df, chave = df[valido], chave[valido]
    if df.empty:
        return pd.DataFrame(columns=metricas + ["n"])
    grupos = df.groupby(chave)
    resultado = pd.DataFrame({"n": grupos.size()})
    for m in metricas:
        spec = METRICAS[m]
        tipo = spec["tipo"]
        if tipo == "tempo":
            col = spec["col"]
            v = df[col].where(drill.mascara(df, [("valida", col)])) / 60
            resultado[m] = v.groupby(chave).mean()
        elif tipo == "media":
            resultado[m] = pd.to_numeric(df[spec["col"]], errors="coerce") \
                .groupby(chave).mean()
        elif tipo == "volume":
            if spec.get("col"):
                resultado[m] = df.groupby(chave)[spec["col"]].nunique()
            elif spec.get("base"):
                resultado[m] = drill.mascara(df, spec["base"]).groupby(chave).sum()
            else:
                resultado[m] = grupos.size()
        else:   # taxa
            base = drill.mascara(df, spec.get("base"))
            cond = drill.mascara(df, spec["cond"])
            flag = cond.astype(float).where(base)
            resultado[m] = flag.groupby(chave).mean() * 100
    resultado = resultado[resultado["n"] >= min_n]
    return resultado.loc[_ordenar(resultado.index, dimensao)]


# ------------------------------------------------------------------ estatística

def _betacf(a: float, b: float, x: float) -> float:
    """Fração continuada da beta incompleta (Numerical Recipes)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
        c = 1.0 + aa / c if abs(c) > 1e-30 else 1e-30
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
        c = 1.0 + aa / c if abs(c) > 1e-30 else 1e-30
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return h


def _beta_incompleta(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    ln_bt = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
             + a * math.log(x) + b * math.log(1 - x))
    bt = math.exp(ln_bt)
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1 - bt * _betacf(b, a, 1 - x) / b


def p_valor(r: float, n: int) -> float | None:
    """p bicaudal do teste t para r = 0 (n − 2 graus de liberdade)."""
    if n < 3 or r is None or math.isnan(r):
        return None
    if abs(r) >= 1:
        return 0.0
    gl = n - 2
    t = r * math.sqrt(gl / (1 - r * r))
    return _beta_incompleta(gl / 2, 0.5, gl / (gl + t * t))


def forca(r: float | None) -> str:
    if r is None or math.isnan(r):
        return "indefinida"
    a = abs(r)
    if a < 0.1:
        return "desprezível"
    if a < 0.3:
        return "fraca"
    if a < 0.5:
        return "moderada"
    if a < 0.7:
        return "forte"
    return "muito forte"


def _num(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), 4)


# ------------------------------------------------------------------ leituras

def dispersao(df: pd.DataFrame, x: str, y: str, dimensao: str,
              min_n: int = 10) -> dict:
    tab = tabela(df, [x] if x == y else [x, y], dimensao, min_n)
    tab = tab.dropna(subset=[x, y])
    n = len(tab)
    mx, my = METRICAS[x], METRICAS[y]
    resultado = {
        "x": x, "y": y, "dimensao": dimensao,
        "rotulo_x": mx["rotulo"], "rotulo_y": my["rotulo"],
        "unidade_x": mx["unidade"], "unidade_y": my["unidade"],
        "rotulo_dimensao": DIMENSOES[dimensao][0], "min_n": min_n,
        "pontos": [{"grupo": str(g), "x": _num(r[x]), "y": _num(r[y]),
                    "n": int(r["n"])} for g, r in tab.iterrows()],
        "n_grupos": n,
    }
    if n < 3 or tab[x].nunique() < 2 or tab[y].nunique() < 2:
        resultado.update({"pearson": None, "spearman": None, "p": None,
                          "r2": None, "reta": None,
                          "interpretacao": "Poucos grupos com dados (ou valores "
                                           "constantes) para medir correlação. "
                                           "Amplie o período ou reduza o n mínimo."})
        return resultado
    pearson = float(tab[x].corr(tab[y]))
    spearman = float(tab[x].rank().corr(tab[y].rank()))
    inclinacao, intercepto = np.polyfit(tab[x].astype(float), tab[y].astype(float), 1)
    p = p_valor(pearson, n)
    sentido = "positiva" if pearson > 0 else "negativa"

    def br(v, casas=2):
        return f"{v:.{casas}f}".replace(".", ",")

    texto = (f"Correlação {forca(pearson)} e {sentido} (r = {br(pearson)}) entre "
             f"{mx['rotulo']} e {my['rotulo']}, em {n} grupos por "
             f"{DIMENSOES[dimensao][0].lower()}. ")
    if abs(pearson) >= 0.1:
        texto += (f"Grupos com {mx['rotulo']} mais alto tendem a ter "
                  f"{my['rotulo']} mais {'alto' if pearson > 0 else 'baixo'}: "
                  f"cada 1 {mx['unidade']} a mais em X acompanha "
                  f"{br(inclinacao).replace('-', '−') if inclinacao < 0 else '+' + br(inclinacao)} {my['unidade']} em Y, em média. ")
    if p is not None:
        texto += ("A relação é estatisticamente significativa (p < 0,05). "
                  if p < 0.05 else
                  "A relação não é estatisticamente significativa (p ≥ 0,05) — "
                  "pode ser acaso. ")
    if abs(spearman - pearson) >= 0.2:
        texto += (f"Spearman (ρ = {br(spearman)}) difere do Pearson: há "
                  "valores extremos ou relação não linear pesando no resultado. ")
    texto += "Correlação não prova causa: os dois podem depender de um terceiro fator."
    resultado.update({
        "pearson": round(pearson, 3), "spearman": round(spearman, 3),
        "p": None if p is None else round(p, 4), "r2": round(pearson ** 2, 3),
        "reta": {"inclinacao": round(float(inclinacao), 4),
                 "intercepto": round(float(intercepto), 4),
                 "x_min": _num(tab[x].min()), "x_max": _num(tab[x].max())},
        "interpretacao": texto,
    })
    return resultado


def matriz(df: pd.DataFrame, metricas: list[str], dimensao: str,
           min_n: int = 10) -> dict:
    metricas = [m for m in dict.fromkeys(metricas) if m in METRICAS]
    tab = tabela(df, metricas, dimensao, min_n)
    celulas = []
    for a in metricas:
        linha = []
        for b in metricas:
            par = tab[[a, b]].dropna() if a != b else tab[[a]].dropna()
            n = len(par)
            if a == b:
                r = 1.0 if n >= 3 else None
            elif n >= 3 and par[a].nunique() > 1 and par[b].nunique() > 1:
                r = float(par[a].corr(par[b]))
            else:
                r = None
            linha.append({"r": None if r is None else round(r, 3), "n": n,
                          "p": None if r is None or a == b else
                          _num(p_valor(r, n))})
        celulas.append(linha)
    return {"metricas": metricas,
            "rotulos": [METRICAS[m]["rotulo"] for m in metricas],
            "dimensao": dimensao, "rotulo_dimensao": DIMENSOES[dimensao][0],
            "n_grupos": int(len(tab)), "celulas": celulas, "min_n": min_n}


def series(df: pd.DataFrame, metricas: list[str], dimensao: str,
           min_n: int = 1) -> dict:
    metricas = [m for m in dict.fromkeys(metricas) if m in METRICAS]
    tab = tabela(df, metricas, dimensao, min_n)
    grupos = [str(g) for g in tab.index]
    resultado = {"dimensao": dimensao, "rotulo_dimensao": DIMENSOES[dimensao][0],
                 "grupos": grupos, "series": [], "indexadas": []}
    for m in metricas:
        valores = [_num(v) for v in tab[m]] if m in tab else []
        resultado["series"].append({"metrica": m, "rotulo": METRICAS[m]["rotulo"],
                                    "unidade": METRICAS[m]["unidade"],
                                    "valores": valores})
        # base 100 = média do período: permite comparar indicadores de
        # unidades diferentes num eixo só, sem eixo duplo
        validos = [v for v in valores if v is not None]
        media = sum(validos) / len(validos) if validos else None
        resultado["indexadas"].append({
            "metrica": m, "rotulo": METRICAS[m]["rotulo"],
            "valores": [round(v / media * 100, 1) if v is not None and media
                        else None for v in valores]})
    return resultado


def linhas_do_grupo(df: pd.DataFrame, dimensao: str, grupo: str,
                    metrica: str | None = None) -> pd.DataFrame:
    """Linhas de um grupo (ponto da dispersão / ponto da série)."""
    rows = df[chave_grupo(df, dimensao) == grupo]
    spec = METRICAS.get(metrica or "")
    if spec and spec["tipo"] == "tempo":
        rows = rows[drill.mascara(rows, [("valida", spec["col"])])]
    elif spec and spec.get("base"):
        rows = rows[drill.mascara(rows, spec["base"])]
    return rows


def coluna_tempo(metrica: str | None) -> str | None:
    spec = METRICAS.get(metrica or "")
    return spec["col"] if spec and spec["tipo"] == "tempo" else None

