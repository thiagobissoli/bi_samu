"""Núcleo de dados dos Indicadores — carga e derivações (sem efeitos colaterais).

Lê `vsky_registros_analiticos` (módulo download_vsky) para um DataFrame e
deriva tudo o que os dashboards consomem: datas, períodos P1–P9, cores de
código/risco, viatura/ISCMV, convênio, sinais vitais e NEWS modificada.

Convenções herdadas dos legados:
- "---" e vazio = ausente;
- 0 em FR/FC/Glasgow/Glicemia e PA "0/0" = NÃO MEDIDO (vira nulo);
- tempos em segundos; validade por métrica em constants.CAP_TEMPO.
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
import warnings

import numpy as np
import pandas as pd
from pandas.errors import PerformanceWarning
from sqlalchemy import text

from app.core.database import engine
from app.modules.indicadores.constants import (
    CIDADES_CONVENIO,
    DATA_HORA_FMT,
    ISCMV_VIATURAS,
    MAPA_CODIGO_COR,
    MAPA_RISCO_COR,
)

COLS_DATA = [
    "data_tarm", "data_regulador", "data_controlador",
    "inicio_deslocamento", "saida_para_atendimento", "chegada_no_local",
    "saida_para_hospital", "chegada_no_hospital", "atendimento_encerrado",
    "primeiro_j14",
]

# Somente as colunas que os dashboards usam — reduz tempo de carga e memória
# (endereço, telefones, coordenadas, paciente etc. ficam fora).
COLS_USADAS = [
    "id", "ocorrencia", "codigo_da_ocorrencia", "situacao_atendimento", "atendimento",
    "transporte", "unidade", "cidade", "micro_regiao", "sexo", "idade",
    "faixa", "tipo", "motivo", "risco_inicial", "frq_respiratoria",
    "frq_cardiaca", "pressao_arterial", "escala_glasgow", "glicemia",
    "obito", "hospital_destino", "apoio_policia_militar", "apoio_bombeiros",
    "apoio_usa", "tarm", "regulador", "controlador", "medico", "enfermeiro",
    "tec_enfermagem", "condutor", "data_ocorrencia_dt", *COLS_DATA,
]

_AUSENTES = {"", "---", "nan", "none", "null"}

DIAS_SEMANA = {0: "Segunda", 1: "Terça", 2: "Quarta", 3: "Quinta",
               4: "Sexta", 5: "Sábado", 6: "Domingo"}

_RE_SUFIXO_PROF = [
    re.compile(r"\s*-\s*CRM[:\s]*\S.*$", re.IGNORECASE),
    re.compile(r"\s*-\s*\d{3}\.\d{3}\.\d{3}-\d{2}\s*$"),        # CPF
    re.compile(r"\s*-\s*[\d.]+\s*[-/]?\s*[A-Z]{2}\s*$"),        # 17.186-ES, 013876 /ES
    re.compile(r"\s*-\s*[\d.]+\s*$"),                           # - 761
]

_cache: dict[int, dict] = {}
_LOCK = threading.Lock()   # uma recarga do núcleo por vez (rotas em threadpool)
_CACHE_TTL = 600        # revalidação completa (segundos)
_CACHE_VERIFICA = 30    # intervalo mínimo entre checagens de novidade no banco


def _marca_banco(empresa_id: int) -> int:
    with engine.connect() as conn:
        total = conn.execute(text(
            "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM vsky_registros_analiticos "
            "WHERE empresa_id = :emp AND deleted_at IS NULL"), {"emp": empresa_id},
        ).fetchone()
    return int(total[0]) * 1_000_000 + int(total[1])


CONFIG_DESCONTO_P41 = "indicadores_p41_desconto_segundos"
DESCONTO_P41_PADRAO = 45   # atraso típico de transmissão rede móvel/GPS


def desconto_p41(empresa_id: int = 1) -> int:
    """Desconto (s) aplicado ao P4.1 — configurável em /configuracoes."""
    from app.core.config_service import get_config
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        valor = get_config(db, CONFIG_DESCONTO_P41, empresa_id=empresa_id)
    finally:
        db.close()
    if valor in (None, ""):
        return DESCONTO_P41_PADRAO
    try:
        return max(int(str(valor).strip()), 0)
    except ValueError:
        return DESCONTO_P41_PADRAO


def _com_desconto(bruto: pd.Series, desconto: float) -> pd.Series:
    """Subtrai o desconto dos tempos válidos, com piso de 1 s.

    O piso mantém válidos (> 0) os registros cuja saída real foi mais
    rápida que o próprio atraso de transmissão — descartá-los inflaria
    a média das unidades mais ágeis.
    """
    if desconto <= 0:
        return bruto
    return (bruto - desconto).clip(lower=1.0).where(bruto > 0, bruto)


def carregar(empresa_id: int = 1) -> pd.DataFrame:
    """DataFrame derivado, cacheado por empresa.

    A checagem de novidade no banco (COUNT/MAX) é limitada a uma vez a cada
    _CACHE_VERIFICA segundos — requests dentro da janela devolvem o cache
    imediatamente, sem tocar o banco. Mudar o desconto do P4.1 na
    configuração invalida o cache na próxima leitura (rederiva tudo).

    Com as rotas rodando em threadpool, o lock garante uma única carga por
    vez: threads concorrentes esperam e reaproveitam o resultado, em vez de
    dispararem recargas simultâneas do mesmo DataFrame.
    """
    resultado = _tentar_cache(empresa_id)
    if resultado is not None:
        return resultado
    with _LOCK:
        resultado = _tentar_cache(empresa_id)   # outra thread pode ter carregado
        if resultado is not None:
            return resultado
        return _recarregar(empresa_id)


def _tentar_cache(empresa_id: int) -> pd.DataFrame | None:
    """Devolve o DataFrame do cache se ainda estiver válido; senão None."""
    agora = time.time()
    em_cache = _cache.get(empresa_id)
    if not em_cache or em_cache["desconto"] != desconto_p41(empresa_id):
        return None
    if agora - em_cache["verificado_em"] < _CACHE_VERIFICA:
        return em_cache["df"]
    if agora - em_cache["carregado_em"] < _CACHE_TTL \
            and _marca_banco(empresa_id) == em_cache["marca"]:
        em_cache["verificado_em"] = agora
        return em_cache["df"]
    return None


def _recarregar(empresa_id: int) -> pd.DataFrame:
    agora = time.time()
    desconto = desconto_p41(empresa_id)
    marca = _marca_banco(empresa_id)
    df = pd.read_sql_query(
        text(f"SELECT {', '.join(COLS_USADAS)} FROM vsky_registros_analiticos "
             "WHERE empresa_id = :emp AND deleted_at IS NULL"),
        engine, params={"emp": empresa_id},
        parse_dates=["data_ocorrencia_dt"],
    )
    with warnings.catch_warnings():
        # As dezenas de colunas derivadas fragmentam o frame; o .copy()
        # final resolve — o aviso intermediário é só ruído.
        warnings.simplefilter("ignore", PerformanceWarning)
        df = _derivar(df, desconto)
    _cache[empresa_id] = {"df": df, "marca": marca, "carregado_em": agora,
                          "verificado_em": agora, "desconto": desconto,
                          "opcoes": _montar_opcoes(df)}
    return df


def opcoes_filtros(empresa_id: int = 1) -> dict:
    """Opções dos filtros globais — calculadas uma vez por carga do cache."""
    carregar(empresa_id)
    return _cache[empresa_id]["opcoes"]


def marca_cache(empresa_id: int = 1) -> int:
    """Identificador da versão dos dados em cache (muda a cada carga nova).

    Inclui o desconto do P4.1: alterar a configuração também renova os
    caches derivados (dashboards, painel, apresentação).
    """
    carregar(empresa_id)
    em_cache = _cache[empresa_id]
    return em_cache["marca"] * 10_000 + em_cache["desconto"]


def _montar_opcoes(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"transportes": [], "recursos": [], "codigos": [], "tipos": [],
                "motivos": [], "unidades": [], "cidades": [], "riscos": []}
    return {
        "transportes": sorted(df["transporte"].dropna().unique()),
        "recursos": sorted(df["recurso"].dropna().unique()),
        "codigos": sorted(df["codigo_da_ocorrencia"].dropna().unique()),
        "tipos": sorted(df["tipo"].dropna().unique()),
        "motivos": sorted(df["motivo"].dropna().unique()),
        "unidades": sorted(u for u in df["unidade_curta"].unique() if u),
        "cidades": sorted(df["cidade"].dropna().unique()),
        "riscos": sorted(df["risco_inicial"].dropna().unique()),
    }


def invalidar_cache(empresa_id: int | None = None) -> None:
    if empresa_id is None:
        _cache.clear()
    else:
        _cache.pop(empresa_id, None)


def norm_txt(valor: str) -> str:
    """Maiúsculas sem acento, espaços colapsados."""
    s = unicodedata.normalize("NFKD", str(valor)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def _derivar(df: pd.DataFrame,
             desconto_p41_s: float = DESCONTO_P41_PADRAO) -> pd.DataFrame:
    if df.empty:
        return df

    # --- limpeza: vazios disfarçados viram NA -----------------------------
    # A checagem cobre `object` (pandas 2) e o dtype `str` nativo (pandas 3):
    # testar só por object fazia esta limpeza ser pulada inteira no pandas 3,
    # e "" / "---" passavam a contar como valor real (ex.: 350 mil registros
    # sem óbito eram contados como óbito constatado).
    for col in df.columns:
        if df[col].dtype == object or pd.api.types.is_string_dtype(df[col]):
            s = df[col].astype(str).str.strip()
            df[col] = s.mask(s.str.casefold().isin(_AUSENTES))

    # --- datas ------------------------------------------------------------
    for col in COLS_DATA:
        df[f"dt_{col}"] = pd.to_datetime(df[col], format=DATA_HORA_FMT,
                                         errors="coerce")
    # data_ocorrencia_dt já vem tipada do banco — evita reparse de 180k strings
    df["dt_ocorr"] = df["data_ocorrencia_dt"]
    df["dt_data_ocorrencia"] = df["data_ocorrencia_dt"]
    df["dia"] = df["dt_ocorr"].dt.date
    df["hora"] = df["dt_ocorr"].dt.hour
    df["semana_iso"] = df["dt_ocorr"].dt.strftime("%G-S%V")
    # Plantão diurno: 07:00–18:59 · noturno: 19:00–06:59 (do dia seguinte).
    df["turno"] = np.where(df["hora"].between(7, 18), "Diurno", "Noturno")
    # O plantão noturno pertence ao dia em que COMEÇOU: deslocando 7h,
    # a madrugada (00:00–06:59) cai na data do plantão da véspera.
    plantao_ref = df["dt_ocorr"] - pd.Timedelta(hours=7)
    df["plantao_data"] = plantao_ref.dt.date
    df["plantao_dia_semana"] = plantao_ref.dt.weekday.map(DIAS_SEMANA)
    df["plantao"] = df["plantao_dia_semana"] + " " + df["turno"]

    # --- períodos P1–P9 e tempos consolidados (segundos) ------------------
    def _seg(fim: str, inicio: str) -> pd.Series:
        return (df[fim] - df[inicio]).dt.total_seconds()

    df["t_p1"] = _seg("dt_data_tarm", "dt_ocorr")
    df["t_p2"] = _seg("dt_data_regulador", "dt_data_tarm")
    df["t_p3"] = _seg("dt_data_controlador", "dt_data_regulador")
    # P4 = tempo de chegada; P4.1 = saída de base; P4.2 = deslocamento.
    # P4.1 recebe desconto do atraso de transmissão rede móvel/GPS
    # (padrão 45 s, chave indicadores_p41_desconto_segundos).
    df["t_p4"] = _seg("dt_chegada_no_local", "dt_data_controlador")
    df["t_p4_1"] = _com_desconto(
        _seg("dt_inicio_deslocamento", "dt_data_controlador"), desconto_p41_s)
    df["t_p4_2"] = _seg("dt_chegada_no_local", "dt_inicio_deslocamento")
    df["t_p5_6"] = _seg("dt_primeiro_j14", "dt_chegada_no_local")
    df["t_p5_6_7"] = _seg("dt_saida_para_hospital", "dt_chegada_no_local")
    df["t_p7_mais"] = _seg("dt_saida_para_hospital", "dt_primeiro_j14")
    df["t_p8"] = _seg("dt_chegada_no_hospital", "dt_saida_para_hospital")
    df["t_p9"] = _seg("dt_atendimento_encerrado", "dt_chegada_no_hospital")
    df["t_central"] = _seg("dt_data_controlador", "dt_ocorr")

    # Tempo de resposta = abertura do chamado até a chegada da PRIMEIRA
    # unidade. Ocorrências com múltiplos empenhos têm várias linhas; só a
    # linha da primeira chegada carrega o tempo_resposta — as demais ficam
    # nulas e não entram em nenhuma média/contagem do indicador.
    tr_bruto = _seg("dt_chegada_no_local", "dt_ocorr")
    com_chegada = df["dt_chegada_no_local"].notna()
    chegadas = df[com_chegada & df["ocorrencia"].notna()]
    idx_primeira = chegadas.groupby("ocorrencia")["dt_chegada_no_local"].idxmin()
    primeira = pd.Series(False, index=df.index)
    primeira.loc[idx_primeira] = True
    # sem número de ocorrência não há como agrupar: linha vale por si
    primeira |= com_chegada & df["ocorrencia"].isna()
    df["primeira_chegada"] = primeira
    df["tempo_resposta"] = tr_bruto.where(primeira)
    df["t_saida_gps"] = df["t_p4_1"]   # mesma métrica, já com o desconto
    df["t_saida_j9"] = _seg("dt_saida_para_atendimento", "dt_data_controlador")
    df["t_deslocamento"] = _seg("dt_chegada_no_local", "dt_inicio_deslocamento")
    df["t_cena"] = df["t_p5_6_7"]

    # --- classificações ---------------------------------------------------
    df["codigo_cor"] = df["codigo_da_ocorrencia"].map(
        lambda v: MAPA_CODIGO_COR.get(norm_txt(v).lower()) if pd.notna(v) else None)
    df["risco_cor"] = df["risco_inicial"].map(
        lambda v: MAPA_RISCO_COR.get(norm_txt(v).lower()) if pd.notna(v) else None)

    # --- viatura / ISCMV / convênio ---------------------------------------
    # Tipo de transporte (USA/USB) identificado pela coluna Unidade:
    # casa a sigla em qualquer posição (ex.: "USA - AEROMEDICO",
    # "USB 42 - SERRA"), com o número da viatura quando houver.
    unid = df["unidade"].fillna("").map(norm_txt)
    ext = unid.str.extract(r"\b(USA|USB|VIR)\b\s*-?\s*(\d+)?")
    df["recurso"] = ext[0].where(ext[0].notna(),
                                 np.where(unid.eq(""), None, "OUTRO"))
    df["viatura"] = np.where(
        ext[0].notna() & ext[1].notna(), ext[0] + " " + ext[1], None)
    df["iscmv"] = df["viatura"].isin(ISCMV_VIATURAS)
    # Rótulo curto: "USB 42 - SERRA" -> "USB 42". Quando o prefixo não tem
    # número ("USA - AEROMEDICO", "USA - NEP 33"), mantém o complemento para
    # não colapsar unidades distintas num só rótulo "USA".
    partes = df["unidade"].fillna("").str.split(" - ")
    seg1 = partes.str[0].str.strip()
    seg2 = partes.str[1].fillna("").str.strip()
    df["unidade_curta"] = np.where(
        seg1.str.contains(r"\d") | seg2.eq(""), seg1, seg1 + " " + seg2)

    df["cidade_norm"] = df["cidade"].map(lambda v: norm_txt(v) if pd.notna(v) else None)
    df["convenio"] = df["cidade_norm"].isin(CIDADES_CONVENIO)

    # --- paciente ---------------------------------------------------------
    df["idade_num"] = pd.to_numeric(df["idade"], errors="coerce")

    # --- sinais vitais (0 = não medido) -----------------------------------
    def _vital(col: str) -> pd.Series:
        v = pd.to_numeric(df[col], errors="coerce")
        return v.mask(v <= 0)

    df["fr"] = _vital("frq_respiratoria")
    df["fc"] = _vital("frq_cardiaca")
    df["glasgow"] = _vital("escala_glasgow")
    df["glicemia"] = _vital("glicemia")
    pas = pd.to_numeric(
        df["pressao_arterial"].fillna("").str.extract(r"^(\d+)")[0],
        errors="coerce")
    df["pas"] = pas.mask(pas <= 0)

    _derivar_news(df)

    # --- óbito ------------------------------------------------------------
    df["obito_constatado"] = df["obito"].notna() & (
        df["obito"].fillna("").map(norm_txt) != "NAO HOUVE OBITO")

    # --- profissionais (remove CRM/CPF/registro do nome) ------------------
    for col in ("tarm", "regulador", "controlador", "medico",
                "enfermeiro", "tec_enfermagem", "condutor"):
        df[f"{col}_nome"] = df[col].map(_limpar_nome_prof)

    # Desfragmenta: as dezenas de inserções acima deixam o frame em blocos.
    return df.copy()


def _limpar_nome_prof(valor) -> str | None:
    if pd.isna(valor):
        return None
    nome = str(valor)
    for regex in _RE_SUFIXO_PROF:
        nome = regex.sub("", nome)
    return nome.strip() or None


def _pontos(serie: pd.Series, faixas: list[tuple[float, float, int]]) -> pd.Series:
    """Pontua uma série numérica por faixas [(min, max, pontos)] (inclusivas)."""
    resultado = pd.Series(np.nan, index=serie.index)
    for minimo, maximo, pontos in faixas:
        resultado = resultado.mask(serie.between(minimo, maximo), pontos)
    return resultado


def _derivar_news(df: pd.DataFrame) -> None:
    """Escala NEWS modificada — ver constants.NEWS_CRITERIOS."""
    inf = float("inf")
    df["news_fr"] = _pontos(df["fr"], [
        (-inf, 8, 3), (9, 11, 1), (12, 20, 0), (21, 24, 2), (25, inf, 3)])
    df["news_fc"] = _pontos(df["fc"], [
        (-inf, 40, 3), (41, 50, 1), (51, 90, 0), (91, 110, 1),
        (111, 130, 2), (131, inf, 3)])
    df["news_pas"] = _pontos(df["pas"], [
        (-inf, 90, 3), (91, 100, 2), (101, 110, 1), (111, 219, 0),
        (220, inf, 3)])
    df["news_gcs"] = _pontos(df["glasgow"], [
        (15, 15, 0), (13, 14, 1), (9, 12, 2), (-inf, 8, 3)])
    df["news_gli"] = _pontos(df["glicemia"], [
        (-inf, 40, 3), (41, 60, 2), (61, 70, 1), (71, 180, 0),
        (181, 300, 1), (301, inf, 2)])

    nucleo = ["news_fr", "news_fc", "news_pas", "news_gcs"]
    completo = df[nucleo].notna().all(axis=1)
    df["news_total"] = (
        df[nucleo].sum(axis=1) + df["news_gli"].fillna(0)).where(completo)

    tem3 = (df[nucleo] == 3).any(axis=1)
    df["news_risco"] = np.select(
        [df["news_total"] >= 7, df["news_total"] >= 5,
         completo & tem3, completo],
        ["Alto", "Médio", "Baixo-Médio", "Baixo"], default=None)
