"""Das barras e pontos dos gráficos até as ocorrências por trás deles.

Cada gráfico montado pelo serviço leva uma **descrição de detalhamento**:
de que linhas do núcleo ele saiu e como cada rótulo (eixo) e cada série
(dataset) recortam essas linhas. Ao clicar num ponto, a tela manda o índice
do gráfico, do rótulo e da série; aqui a descrição é reaplicada sobre os
mesmos dados filtrados e devolve exatamente as linhas que formaram o valor.

A descrição fica no servidor (registro abaixo), nunca vai para o navegador:
o cliente só manda números, e nenhum nome de coluna vindo de fora é usado.

Descrição:
    eixo      {"tipo": "col", "col": c}            rótulo = valor da coluna
              {"tipo": "tempo", "unidade": u}       dia|semana|mes|ano|hora|dia_semana
              {"tipo": "faixa", "col": c, "bordas": [s0, s1, ...]}  intervalos em s
              {"tipo": "derivada", "nome": n}       chave calculada (DERIVADAS)
              {"tipo": "rotulo"}                    cada rótulo tem sua condição
    chaves    valor da chave de cada rótulo (eixos col/tempo/faixa/derivada)
    rotulos   condição de cada rótulo (eixo "rotulo")
    base      condição comum a todo o gráfico
    series    condição de cada série (None = sem recorte adicional)
    metrica   coluna de tempo a exibir na lista (opcional)

Condição = lista de predicados combinados com E:
    ("valida", col)          tempo > 0 e abaixo do teto de validade
    ("ate", col, s)          tempo válido e ≤ s segundos
    ("acima", col, s)        tempo válido e > s segundos
    ("igual", col, v)        ("em", col, [v...])
    ("notna", col)           ("verdadeiro", col)   ("falso", col)
    ("mascara", nome)        regra de negócio nomeada (MASCARAS)
    ("idx", array)           linhas específicas (recorte que não se expressa
                             com os predicados acima)
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime

import numpy as np
import pandas as pd

from app.modules.indicadores.constants import ADEQUACAO, CAP_TEMPO

POR_PAGINA = 50
_MAX_REGISTROS = 16

# (empresa, tema, versão dos dados, filtros) -> [descrição por gráfico]
_registro: "OrderedDict[tuple, list]" = OrderedDict()


def registrar(chave: tuple, descricoes: list) -> None:
    _registro[chave] = descricoes
    _registro.move_to_end(chave)
    while len(_registro) > _MAX_REGISTROS:
        _registro.popitem(last=False)


def obter(chave: tuple) -> list | None:
    descricoes = _registro.get(chave)
    if descricoes is not None:
        _registro.move_to_end(chave)
    return descricoes


# ------------------------------------------------------------------ montagem

def desc(eixo: dict, chaves=None, *, base=None, series=None, rotulos=None,
         metrica: str | None = None) -> dict:
    return {"eixo": eixo, "chaves": list(chaves) if chaves is not None else None,
            "rotulos": rotulos, "base": base or [], "series": series,
            "metrica": metrica}


def col(coluna: str) -> dict:
    return {"tipo": "col", "col": coluna}


def tempo(unidade: str) -> dict:
    return {"tipo": "tempo", "unidade": unidade}


def faixa(coluna: str, bordas_s: list[float]) -> dict:
    return {"tipo": "faixa", "col": coluna, "bordas": list(bordas_s)}


ROTULO = {"tipo": "rotulo"}


def grade(eixo_linhas: dict, linhas: list, eixo_colunas: dict, colunas: list) -> dict:
    """Eixo de mapa de calor: cada célula é (linha, coluna)."""
    return {"tipo": "grade", "eixo_linhas": eixo_linhas, "linhas": list(linhas),
            "eixo_colunas": eixo_colunas, "colunas": list(colunas)}


def recorte(sub: pd.DataFrame, tema_df: pd.DataFrame | None) -> list:
    """Predicado de linhas quando `sub` é um recorte do DataFrame do tema."""
    if tema_df is None or sub is tema_df or len(sub) == len(tema_df):
        return []
    return [("idx", sub.index.to_numpy(dtype=np.int32))]


# ------------------------------------------------------------------ avaliação

def _validos(df: pd.DataFrame, coluna: str) -> pd.Series:
    v = df[coluna]
    return (v > 0) & (v < CAP_TEMPO.get(coluna, 14400))


def _adequado(df: pd.DataFrame) -> pd.Series:
    ok = pd.Series(False, index=df.index)
    for cor, riscos in ADEQUACAO.items():
        ok |= (df["codigo_cor"] == cor) & df["risco_cor"].isin(riscos)
    return ok


def _base_assertividade(df: pd.DataFrame) -> pd.Series:
    return ((df["transporte"] == "Pré-hospitalar")
            & df["codigo_cor"].isin(ADEQUACAO) & df["risco_cor"].notna())


def _desperdicio(df: pd.DataFrame, qual: str) -> pd.Series:
    from app.modules.indicadores import desperdicio

    saida = df["dt_inicio_deslocamento"].notna()
    resultado = pd.Series(False, index=df.index)
    universo = df[saida]
    if universo.empty:
        return resultado
    real, evitado = desperdicio.mascaras(universo)
    resultado.loc[universo.index] = (real if qual == "real" else evitado).to_numpy()
    return resultado


def _norm(d: pd.DataFrame, coluna: str) -> pd.Series:
    from app.modules.indicadores.nucleo import norm_txt
    return d[coluna].fillna("").map(norm_txt)


MASCARAS = {
    "aph": lambda d: d["transporte"] == "Pré-hospitalar",
    "saida": lambda d: d["dt_inicio_deslocamento"].notna(),
    "com_unidade": lambda d: d["unidade_curta"].notna() & d["unidade_curta"].ne(""),
    "assertividade": _base_assertividade,
    "adequado": lambda d: _base_assertividade(d) & _adequado(d),
    "inadequado": lambda d: _base_assertividade(d) & ~_adequado(d),
    "desperdicio_real": lambda d: _desperdicio(d, "real"),
    "desperdicio_evitado": lambda d: _desperdicio(d, "evitado"),
    "obito": lambda d: d["obito_constatado"].fillna(False).astype(bool),
    "atendimento_com": lambda d: _norm(d, "atendimento").eq("COM ATENDIMENTO"),
    "atendimento_sem": lambda d: _norm(d, "atendimento").eq("SEM ATENDIMENTO"),
    "atendimento_informado": lambda d: _norm(d, "atendimento").isin(
        ["COM ATENDIMENTO", "SEM ATENDIMENTO"]),
    "atendimento_vazio": lambda d: ~_norm(d, "atendimento").isin(
        ["COM ATENDIMENTO", "SEM ATENDIMENTO"]),
    "apoio_policia_militar": lambda d: _norm(d, "apoio_policia_militar").eq("COMPARECEU"),
    "apoio_bombeiros": lambda d: _norm(d, "apoio_bombeiros").eq("COMPARECEU"),
    "apoio_usa": lambda d: _norm(d, "apoio_usa").eq("COMPARECEU"),
    "enviado_ro": lambda d: d["controlador"].notna(),
}


def _cidade_unidade(d: pd.DataFrame) -> pd.Series:
    combinada = d["cidade"].fillna("") + " — " + d["unidade_curta"].fillna("")
    return combinada.where(d["cidade"].notna() & d["unidade_curta"].ne(""))


DERIVADAS = {
    "cidade_unidade": _cidade_unidade,
    "motivo_codigo": lambda d: d["motivo"].str.split(" ").str[0],
    "situacao_norm": lambda d: _norm(d, "situacao_atendimento"),
}


def mascara(df: pd.DataFrame, condicao) -> pd.Series:
    m = pd.Series(True, index=df.index)
    for pred in condicao or []:
        tipo = pred[0]
        if tipo == "valida":
            m &= _validos(df, pred[1])
        elif tipo == "ate":
            m &= _validos(df, pred[1]) & (df[pred[1]] <= pred[2])
        elif tipo == "acima":
            m &= _validos(df, pred[1]) & (df[pred[1]] > pred[2])
        elif tipo == "igual":
            m &= df[pred[1]] == pred[2]
        elif tipo == "em":
            m &= df[pred[1]].isin(pred[2])
        elif tipo == "notna":
            m &= df[pred[1]].notna() & df[pred[1]].ne("")
        elif tipo == "verdadeiro":
            m &= df[pred[1]].fillna(False).astype(bool)
        elif tipo == "falso":
            m &= ~df[pred[1]].fillna(True).astype(bool)
        elif tipo == "mascara":
            m &= MASCARAS[pred[1]](df).fillna(False).astype(bool)
        elif tipo == "idx":
            m &= df.index.isin(pred[1])
        else:
            raise ValueError(f"predicado desconhecido: {tipo}")
    return m.fillna(False).astype(bool)


def chave_eixo(df: pd.DataFrame, eixo: dict) -> pd.Series:
    tipo = eixo["tipo"]
    if tipo == "col":
        return df[eixo["col"]]
    if tipo == "derivada":
        return DERIVADAS[eixo["nome"]](df)
    if tipo == "faixa":
        bordas = eixo["bordas"]
        indice = np.digitize(df[eixo["col"]].to_numpy(dtype=float), bordas) - 1
        # além da última borda = último intervalo (">X")
        indice = np.where(indice >= len(bordas) - 1, len(bordas) - 1, indice)
        return pd.Series(indice, index=df.index)
    unidade = eixo["unidade"]
    if unidade == "dia":
        return df["dia"]
    if unidade == "semana":
        return df["semana_iso"]
    if unidade == "mes":
        return df["dt_ocorr"].dt.to_period("M")
    if unidade == "ano":
        return df["dt_ocorr"].dt.year
    if unidade == "hora":
        return df["hora"]
    if unidade == "dia_semana":
        return df["plantao_dia_semana"]
    raise ValueError(f"eixo desconhecido: {eixo}")


def linhas(df: pd.DataFrame, d: dict, x: int, s: int | None) -> pd.DataFrame:
    """Linhas do núcleo por trás do rótulo x (e da série s) do gráfico."""
    m = mascara(df, d["base"])
    series = d.get("series")
    if series and s is not None and 0 <= s < len(series) and series[s]:
        m &= mascara(df, series[s])
    if d["eixo"]["tipo"] == "grade":
        # mapa de calor: x = linha * nº de colunas + coluna
        eixo = d["eixo"]
        n_col = len(eixo["colunas"])
        lin, col_ = divmod(x, n_col) if n_col else (-1, -1)
        if not (0 <= lin < len(eixo["linhas"]) and 0 <= col_ < n_col):
            return df.iloc[0:0]
        sub = df[m]
        return sub[(chave_eixo(sub, eixo["eixo_linhas"]) == eixo["linhas"][lin])
                   & (chave_eixo(sub, eixo["eixo_colunas"]) == eixo["colunas"][col_])]
    if d["eixo"]["tipo"] == "rotulo":
        rotulos = d.get("rotulos") or []
        if not 0 <= x < len(rotulos):
            return df.iloc[0:0]
        m &= mascara(df, rotulos[x])
    else:
        chaves = d.get("chaves") or []
        if not 0 <= x < len(chaves):
            return df.iloc[0:0]
        sub = df[m]
        return sub[chave_eixo(sub, d["eixo"]) == chaves[x]]
    return df[m]


# ------------------------------------------------------------------ lista

COLUNAS = [
    ("ocorrencia", "Ocorrência"),
    ("dt_ocorr", "Data/hora"),
    ("unidade_curta", "Unidade"),
    ("cidade", "Cidade"),
    ("codigo_da_ocorrencia", "Código"),
    ("risco_inicial", "Risco"),
    ("tipo", "Tipo"),
    ("motivo", "Motivo"),
    ("situacao_atendimento", "Situação"),
    ("transporte", "Transporte"),
]


def _mmss(segundos) -> str:
    if segundos is None or pd.isna(segundos):
        return ""
    s = int(round(float(segundos)))
    return f"{s // 60:02d}:{s % 60:02d}"


def _celula(valor):
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ""
    if isinstance(valor, (pd.Timestamp, datetime)):
        return valor.strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, (np.integer,)):
        return int(valor)
    return str(valor)


def tabela(rows: pd.DataFrame, metrica: str | None = None,
           rotulo_metrica: str | None = None) -> tuple[list[str], list[list]]:
    """Cabeçalho e linhas da lista de ocorrências (mais recentes primeiro)."""
    rows = rows.sort_values("dt_ocorr", ascending=False, na_position="last")
    colunas = [r for _, r in COLUNAS]
    if metrica and metrica in rows:
        colunas.append(rotulo_metrica or "Tempo (mm:ss)")
    corpo = []
    for _, r in rows.iterrows():
        linha = [_celula(r.get(c)) for c, _ in COLUNAS]
        if metrica and metrica in rows:
            linha.append(_mmss(r[metrica]) if _validos(rows.loc[[r.name]], metrica).iat[0] else "")
        corpo.append(linha)
    return colunas, corpo


def pagina(rows: pd.DataFrame, numero: int = 1, metrica: str | None = None,
           rotulo_metrica: str | None = None) -> dict:
    total = int(len(rows))
    paginas = max(1, -(-total // POR_PAGINA))
    numero = min(max(1, numero), paginas)
    ordenadas = rows.sort_values("dt_ocorr", ascending=False, na_position="last")
    fatia = ordenadas.iloc[(numero - 1) * POR_PAGINA: numero * POR_PAGINA]
    colunas, corpo = tabela(fatia, metrica, rotulo_metrica)
    ocorrencias = int(rows["ocorrencia"].nunique()) if total else 0
    return {"total": total, "ocorrencias": ocorrencias, "pagina": numero,
            "paginas": paginas, "colunas": colunas, "linhas": corpo}


def planilha(rows: pd.DataFrame, titulo: str, metrica: str | None = None,
             rotulo_metrica: str | None = None) -> bytes:
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Font

    colunas, corpo = tabela(rows, metrica, rotulo_metrica)
    wb = Workbook()
    aba = wb.active
    aba.title = "Ocorrências"
    aba.append([titulo[:250]])
    aba["A1"].font = Font(bold=True)
    aba.append(colunas)
    for celula in aba[2]:
        celula.font = Font(bold=True)
    for linha in corpo:
        aba.append(linha)
    aba.freeze_panes = "A3"
    saida = BytesIO()
    wb.save(saida)
    return saida.getvalue()
