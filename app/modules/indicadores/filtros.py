"""Catálogo único dos filtros dos Indicadores.

Cada filtro é declarado uma vez aqui e dele saem: a leitura da query string,
a aplicação sobre o DataFrame do núcleo, as opções dos selects e o painel
de filtros das telas (templates/indicadores/_filtros.html).

Tipos:
    data     — data inicial/final (sobre a data da ocorrência)
    multi    — seleção múltipla; a linha passa se a coluna está entre os valores
    marca    — caixa de seleção; a linha passa se a coluna booleana é verdadeira
    simnao   — Sim/Não sobre uma coluna booleana
    faixa    — mínimo/máximo numérico (chaves <chave>_min e <chave>_max)
    hora     — faixa de horas do dia; aceita virar a meia-noite (19h a 6h)
    tempo    — um indicador de tempo entre X e Y minutos (chaves tempo_*)

Grupos organizam o painel: os marcados como principais ficam sempre
visíveis; os demais, em "Mais filtros".
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from urllib.parse import urlencode

import pandas as pd

from app.modules.indicadores.constants import CAP_TEMPO

DIAS_PERIODO_PADRAO = 30

GRUPOS = {
    "periodo": "Período",
    "ocorrencia": "Ocorrência",
    "recurso": "Viatura",
    "local": "Local",
    "paciente": "Paciente",
    "equipe": "Equipe",
    "indicador": "Indicador de tempo",
}

ROTULO_COR = {"vermelho": "Vermelho", "amarelo": "Amarelo", "verde": "Verde",
              "nao_urgente": "Não Urgente", "orientacao_medica": "Orientação Médica"}
ORDEM_DIAS = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"]

# (chave, rótulo, tipo, coluna, grupo, principal, dica)
FILTROS = [
    ("data_inicial", "Data inicial", "data", "dt_ocorr", "periodo", True, ""),
    ("data_final", "Data final", "data", "dt_ocorr", "periodo", True, ""),
    ("hora", "Hora do dia", "hora", "hora", "periodo", False,
     "De/até (0–23). De 19 até 6 cobre a madrugada."),
    ("dia_semana", "Dia da semana (plantão)", "multi", "plantao_dia_semana",
     "periodo", False, "Madrugada conta no dia em que o plantão começou"),
    ("turno", "Turno", "multi", "turno", "periodo", False,
     "Diurno 07:00–18:59 · Noturno 19:00–06:59"),

    ("codigo", "Código da ocorrência", "multi", "codigo_da_ocorrencia",
     "ocorrencia", True, ""),
    ("cor", "Cor do código", "multi", "codigo_cor", "ocorrencia", False, ""),
    ("risco", "Risco inicial", "multi", "risco_inicial", "ocorrencia", False, ""),
    ("tipo", "Tipo", "multi", "tipo", "ocorrencia", False, ""),
    ("motivo", "Motivo", "multi", "motivo", "ocorrencia", False, ""),
    ("situacao", "Situação do atendimento", "multi", "situacao_atendimento",
     "ocorrencia", False, ""),
    ("atendimento", "Atendimento", "multi", "atendimento", "ocorrencia", False, ""),
    ("transporte", "Transporte", "multi", "transporte", "ocorrencia", True, ""),
    ("obito", "Óbito constatado", "simnao", "obito_constatado", "ocorrencia",
     False, ""),

    ("recurso", "Tipo de transporte", "multi", "recurso", "recurso", True,
     "Identificado pela coluna Unidade (USA/USB)"),
    ("unidade", "Unidade", "multi", "unidade_curta", "recurso", True, ""),
    ("iscm", "ISCM", "marca", "iscm", "recurso", True,
     "42 viaturas do núcleo (USA 10–100, USB pares)"),
    ("fora_municipio", "Viatura de outro município", "simnao",
     "fora_do_municipio", "recurso", False,
     "Base da viatura diferente da cidade da ocorrência"),

    ("cidade", "Cidade", "multi", "cidade", "local", True, ""),
    ("convenio", "Convênio (GV)", "marca", "convenio", "local", True,
     "Vitória + Vila Velha + Serra + Cariacica"),
    ("micro_regiao", "Micro região", "multi", "micro_regiao", "local", False, ""),
    ("hospital", "Hospital de destino", "multi", "hospital_destino", "local",
     False, ""),

    ("sexo", "Sexo", "multi", "sexo", "paciente", False, ""),
    ("faixa", "Faixa etária", "multi", "faixa", "paciente", False, ""),
    ("idade", "Idade (anos)", "faixa", "idade_num", "paciente", False, ""),
    ("news", "Risco NEWS", "multi", "news_risco", "paciente", False,
     "Escala NEWS modificada"),

    ("tarm", "TARM", "multi", "tarm_nome", "equipe", False, ""),
    ("regulador", "Regulador", "multi", "regulador_nome", "equipe", False, ""),
    ("controlador", "Controlador", "multi", "controlador_nome", "equipe", False, ""),
    ("medico", "Médico", "multi", "medico_nome", "equipe", False, ""),
    ("enfermeiro", "Enfermeiro", "multi", "enfermeiro_nome", "equipe", False, ""),
    ("tec_enfermagem", "Téc. Enfermagem", "multi", "tec_enfermagem_nome",
     "equipe", False, ""),
    ("condutor", "Condutor", "multi", "condutor_nome", "equipe", False, ""),

    ("tempo", "Tempo entre", "tempo", None, "indicador", False,
     "Só os atendimentos em que o indicador escolhido ficou nesta faixa"),
]

POR_CHAVE = {f[0]: f for f in FILTROS}

# Indicadores de tempo filtráveis por faixa (coluna → rótulo)
TEMPOS_FILTRAVEIS = {
    "t_p1": "P1 — TARM",
    "t_p2": "P2 — Regulação",
    "t_p3": "P3 — Despacho",
    "t_central": "Tempo de Central",
    "t_p4_1": "P4.1 — Saída de base",
    "t_p4_2": "P4.2 — Deslocamento",
    "t_p4": "P4 — Chegada",
    "tempo_resposta": "Tempo de Resposta",
    "t_cena": "Tempo de Cena (P5-7)",
    "t_p8": "P8 — Transporte",
    "t_p9": "P9 — Transferência de cuidados",
}

# Filtros que não são do catálogo mas as telas carregam
EXTRAS = ("profissional",)


def ler(params) -> dict:
    """Filtros a partir da query string (ou de qualquer mapeamento).

    `params` precisa de get() e, para seleção múltipla, getlist(). Um dict
    simples também serve (listas como valor).
    """
    def lista(chave):
        if hasattr(params, "getlist"):
            return [v for v in params.getlist(chave) if v != ""]
        valor = params.get(chave)
        if valor in (None, ""):
            return []
        return list(valor) if isinstance(valor, (list, tuple)) else [valor]

    f: dict = {}
    for chave, _r, tipo, _c, _g, _p, _d in FILTROS:
        if tipo == "multi":
            f[chave] = lista(chave)
        elif tipo == "faixa" or tipo == "hora":
            f[f"{chave}_min"] = (params.get(f"{chave}_min") or "").strip()
            f[f"{chave}_max"] = (params.get(f"{chave}_max") or "").strip()
        elif tipo == "tempo":
            metrica = params.get("tempo_metrica") or ""
            f["tempo_metrica"] = metrica if metrica in TEMPOS_FILTRAVEIS else ""
            f["tempo_min"] = (params.get("tempo_min") or "").strip()
            f["tempo_max"] = (params.get("tempo_max") or "").strip()
        elif tipo == "simnao":
            valor = params.get(chave) or ""
            f[chave] = valor if valor in ("sim", "nao") else ""
        else:
            f[chave] = (params.get(chave) or "").strip()
    # "iscmv" era o nome antigo do filtro: links e favoritos salvos continuam
    # valendo (sem isto o filtro sumiria em silêncio e a tela mostraria a
    # frota inteira).
    if not f["iscm"]:
        f["iscm"] = (params.get("iscmv") or "").strip()
    f["profissional"] = lista("profissional")
    return f


def _numero(valor) -> float | None:
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None


def aplicar(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    """Linhas do núcleo que passam em todos os filtros ativos."""
    if df.empty or not f:
        return df
    mask = pd.Series(True, index=df.index)

    if f.get("data_inicial"):
        try:
            mask &= df["dt_ocorr"] >= datetime.strptime(f["data_inicial"], "%Y-%m-%d")
        except ValueError:
            pass
    if f.get("data_final"):
        try:
            fim = datetime.strptime(f["data_final"], "%Y-%m-%d") + timedelta(days=1)
            mask &= df["dt_ocorr"] < fim
        except ValueError:
            pass

    for chave, _r, tipo, coluna, _g, _p, _d in FILTROS:
        if tipo == "multi":
            valores = f.get(chave)
            if valores:
                if isinstance(valores, str):
                    valores = [valores]
                mask &= df[coluna].isin(valores)
        elif tipo == "marca" and f.get(chave):
            mask &= df[coluna].fillna(False).astype(bool)
        elif tipo == "simnao" and f.get(chave) in ("sim", "nao"):
            coluna_bool = df[coluna]
            mask &= coluna_bool.eq(f[chave] == "sim").fillna(False).astype(bool)
        elif tipo == "faixa":
            minimo, maximo = _numero(f.get(f"{chave}_min")), _numero(f.get(f"{chave}_max"))
            if minimo is not None:
                mask &= df[coluna] >= minimo
            if maximo is not None:
                mask &= df[coluna] <= maximo
        elif tipo == "hora":
            de, ate = _numero(f.get("hora_min")), _numero(f.get("hora_max"))
            if de is not None or ate is not None:
                de = 0 if de is None else de
                ate = 23 if ate is None else ate
                hora = df["hora"]
                mask &= (hora.between(de, ate) if de <= ate
                         else (hora >= de) | (hora <= ate))   # vira a meia-noite
        elif tipo == "tempo":
            col = f.get("tempo_metrica")
            minimo, maximo = _numero(f.get("tempo_min")), _numero(f.get("tempo_max"))
            if col in TEMPOS_FILTRAVEIS and (minimo is not None or maximo is not None):
                v = df[col]
                valido = (v > 0) & (v < CAP_TEMPO.get(col, 14400))
                if minimo is not None:
                    valido &= v >= minimo * 60
                if maximo is not None:
                    valido &= v <= maximo * 60
                mask &= valido.fillna(False)
    return df[mask]


def opcoes(df: pd.DataFrame) -> dict:
    """Valores disponíveis para cada filtro de seleção múltipla.

    Mantém também as chaves antigas (transportes, codigos…) que as telas de
    Calendários e Desempenho ainda usam.
    """
    resultado: dict = {}
    for chave, _r, tipo, coluna, _g, _p, _d in FILTROS:
        if tipo != "multi":
            continue
        if df.empty or coluna not in df:
            resultado[chave] = []
            continue
        valores = [v for v in df[coluna].dropna().unique() if v != ""]
        if chave == "dia_semana":
            valores = [d for d in ORDEM_DIAS if d in valores]
        elif chave == "faixa":
            ordem = ["0-1", "2-9", "10-19", "20-40", "41-60", ">60"]
            valores = [x for x in ordem if x in valores] + sorted(
                x for x in valores if x not in ordem)
        else:
            valores = sorted(valores, key=lambda v: str(v))
        resultado[chave] = valores
    legado = {"transportes": "transporte", "recursos": "recurso",
              "codigos": "codigo", "tipos": "tipo", "motivos": "motivo",
              "unidades": "unidade", "cidades": "cidade", "riscos": "risco"}
    for antigo, novo in legado.items():
        resultado[antigo] = resultado.get(novo, [])
    return resultado


def rotulo_opcao(chave: str, valor) -> str:
    if chave == "cor":
        return ROTULO_COR.get(valor, valor)
    return str(valor)


def padrao(periodo_fim: str | None) -> dict:
    """Filtros iniciais: os últimos 30 dias com dados (nada é calculado
    até o usuário aplicar)."""
    f = ler({})
    try:
        fim = date.fromisoformat(periodo_fim) if periodo_fim else date.today()
    except ValueError:
        fim = date.today()
    f["data_inicial"] = (fim - timedelta(days=DIAS_PERIODO_PADRAO - 1)).isoformat()
    f["data_final"] = fim.isoformat()
    return f


def ativos(f: dict) -> int:
    """Quantos filtros além do período estão em uso (para o selo do painel)."""
    ignorar = {"data_inicial", "data_final", "tempo_metrica"}
    return sum(1 for k, v in f.items() if v and k not in ignorar)


def ativos_ocultos(f: dict) -> int:
    """Filtros em uso que ficam dentro de "Mais filtros"."""
    total = 0
    for chave, _r, tipo, _c, _g, principal, _d in FILTROS:
        if principal:
            continue
        if tipo in ("faixa", "hora"):
            total += bool(f.get(f"{chave}_min") or f.get(f"{chave}_max"))
        elif tipo == "tempo":
            total += bool(f.get("tempo_metrica")
                          and (f.get("tempo_min") or f.get("tempo_max")))
        else:
            total += bool(f.get(chave))
    return total


def query_string(f: dict, **extra) -> str:
    itens = {k: v for k, v in f.items() if v not in ("", [], None, False)}
    itens.update({k: v for k, v in extra.items() if v not in ("", None)})
    return urlencode(itens, doseq=True)


def chave_cache(f: dict) -> tuple:
    return tuple(sorted((k, tuple(v) if isinstance(v, list) else v)
                        for k, v in f.items() if v))
