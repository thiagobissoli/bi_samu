"""Regras de negócio dos Indicadores (§35.16).

Cada tema tem um construtor que devolve um dicionário serializável:
    {kpis: [...], charts: [...], tables: [...]}
renderizado genericamente por templates/indicadores/dashboard.html (Chart.js).

Filtros globais (todas as páginas): data inicial/final, convênio (Grande
Vitória), ISCMV, transporte, motivo e tipo.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from app.modules.indicadores import nucleo
from app.modules.indicadores.constants import (
    ADEQUACAO,
    AUDITORIA_INDICADORES,
    CAP_TEMPO,
    DIMENSOES_DESEMPENHO,
    METAS_TEMPO,
    METRICAS_DESEMPENHO,
    PREFIXO_CONFIG_META,
    MOTIVOS_EXCLUIDOS_DESPERDICIO,
    NEWS_BANDAS,
    NEWS_CRITERIOS,
    PAPEIS,
    PERIODOS,
    PROFISSIONAIS_SPEC,
    SITUACOES_DESPERDICIO,
    SLA_P1,
    SLA_P2_POR_COR,
    TEMAS,
)

ROTULO_TEMPO = {col: rotulo for col, rotulo, _ in PERIODOS}
ROTULO_TEMPO.update({"tempo_resposta": "Tempo de Resposta",
                     "t_central": "Tempo de Central"})

# Payloads prontos por (empresa, tema, versão dos dados, filtros)
_cache_dashboards: dict[tuple, dict] = {}

def _json_safe(obj):
    """Converte tipos numpy/pandas e NaN para equivalentes serializáveis."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if (np.isnan(f) or np.isinf(f)) else f
    return obj


MESES_PT = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
            "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def _nome_mes(periodo: pd.Period) -> str:
    return f"{MESES_PT[periodo.month]}/{periodo.year}"


ROTULO_COR = {"vermelho": "Vermelho", "amarelo": "Amarelo", "verde": "Verde",
              "nao_urgente": "Não Urgente", "orientacao_medica": "Orientação Médica",
              "azul": "Azul (Não Urgente)"}
HEX_COR = {"vermelho": "#dc3545", "amarelo": "#ffc107", "verde": "#198754",
           "nao_urgente": "#0dcaf0", "orientacao_medica": "#6c757d",
           "azul": "#0d6efd"}


class IndicadoresService:
    def __init__(self, empresa_id: int = 1):
        self.empresa_id = empresa_id

    # ------------------------------------------------------------ dados

    def dashboard(self, tema: str, filtros: dict) -> dict:
        if tema not in TEMAS:
            raise KeyError(tema)
        # Cache do payload por (tema, filtros, versão dos dados): revisitar
        # um dashboard com os mesmos filtros devolve o resultado pronto.
        chave = (self.empresa_id, tema, nucleo.marca_cache(self.empresa_id),
                 tuple(sorted((k, tuple(v) if isinstance(v, list) else v)
                              for k, v in filtros.items() if v)))
        pronto = _cache_dashboards.get(chave)
        if pronto is not None:
            return pronto

        df = self._filtrar(nucleo.carregar(self.empresa_id), filtros)
        titulo, icone, descricao = TEMAS[tema]
        if df.empty:
            dados = {"kpis": [], "charts": [], "tables": []}
        elif tema in PROFISSIONAIS_SPEC:
            dados = self._tema_profissional(df, PROFISSIONAIS_SPEC[tema],
                                            filtros)
        else:
            dados = getattr(self, "tema_" + tema.replace("-", "_"))(df)
        dados.update({
            "slug": tema, "titulo": titulo, "icone": icone,
            "descricao": descricao, "total_filtrado": int(len(df)),
        })
        dados = _json_safe(dados)
        if len(_cache_dashboards) > 256:  # dados novos mudam a chave; poda
            _cache_dashboards.clear()
        _cache_dashboards[chave] = dados
        return dados

    def opcoes_filtros(self) -> dict:
        # Pré-calculadas junto com o cache do núcleo (uma vez por carga)
        return nucleo.opcoes_filtros(self.empresa_id)

    def periodo_disponivel(self) -> tuple[str, str]:
        df = nucleo.carregar(self.empresa_id)
        if df.empty or df["dt_ocorr"].isna().all():
            return "", ""
        return (df["dt_ocorr"].min().strftime("%Y-%m-%d"),
                df["dt_ocorr"].max().strftime("%Y-%m-%d"))

    def _filtrar(self, df: pd.DataFrame, f: dict) -> pd.DataFrame:
        if df.empty:
            return df
        mask = pd.Series(True, index=df.index)
        if f.get("data_inicial"):
            try:
                dt = datetime.strptime(f["data_inicial"], "%Y-%m-%d")
                mask &= df["dt_ocorr"] >= dt
            except ValueError:
                pass
        if f.get("data_final"):
            try:
                dt = datetime.strptime(f["data_final"], "%Y-%m-%d") + timedelta(days=1)
                mask &= df["dt_ocorr"] < dt
            except ValueError:
                pass
        if f.get("convenio"):
            mask &= df["convenio"]
        if f.get("iscmv"):
            mask &= df["iscmv"]
        # seleção múltipla: valor único (str) ou lista de valores
        for chave, coluna in (("transporte", "transporte"),
                              ("recurso", "recurso"),
                              ("codigo", "codigo_da_ocorrencia"),
                              ("motivo", "motivo"),
                              ("tipo", "tipo"),
                              ("unidade", "unidade_curta"),
                              ("cidade", "cidade"),
                              ("risco", "risco_inicial")):
            valores = f.get(chave)
            if valores:
                if isinstance(valores, str):
                    valores = [valores]
                mask &= df[coluna].isin(valores)
        return df[mask]

    # ------------------------------------------------- página Desempenho

    def desempenho(self, metrica: str, dimensao: str, filtros: dict,
                   min_n: int = 10) -> dict:
        """Análise de desempenho: uma métrica de tempo aberta por uma
        dimensão — Pareto dos piores (20% em vermelho), curvas normais das
        piores categorias × geral e tabela de estatísticas."""
        import math

        col, rot_m = METRICAS_DESEMPENHO[metrica]
        col_d, rot_d = DIMENSOES_DESEMPENHO[dimensao]
        df = self._filtrar(nucleo.carregar(self.empresa_id), filtros)
        cap = CAP_TEMPO.get(col, 14400)
        base = df[(df[col] > 0) & (df[col] < cap)
                  & df[col_d].notna() & df[col_d].ne("")]
        if base.empty:
            return _json_safe({"metrica": metrica, "dimensao": dimensao,
                               "rotulo_metrica": rot_m, "rotulo_dimensao": rot_d,
                               "kpis": [], "chart_bar": None,
                               "chart_gauss": None, "tabela": None,
                               "total": 0})

        grupo = base.groupby(col_d)[col].agg(
            n="count", media="mean", mediana="median", desvio="std",
            minimo="min", maximo="max",
            p10=lambda v: v.quantile(0.1), p90=lambda v: v.quantile(0.9))
        grupo = grupo[grupo["n"] >= min_n].sort_values("media", ascending=False)
        descartadas = int(base[col_d].nunique() - len(grupo))
        n_piores = min(math.ceil(len(grupo) * 0.2), len(grupo))
        geral = base[col]

        kpis = [
            {"label": f"Média geral — {rot_m}", "valor": self._hms(geral.mean()),
             "sub": f"n = {len(geral)}"},
            {"label": "Mediana geral", "valor": self._hms(geral.median()),
             "sub": f"P90 {self._hms(geral.quantile(0.9))}"},
            {"label": f"Categorias ({rot_d})", "valor": str(len(grupo)),
             "sub": (f"{descartadas} descartadas (n < {min_n})"
                     if descartadas else f"todas com n ≥ {min_n}")},
            {"label": "Piores 20% (Pareto)", "valor": str(n_piores),
             "sub": "destacadas em vermelho"},
        ]

        chart_bar = {
            "tipo": "bar", "horizontal": True, "unidade_y": "min",
            "titulo": f"{rot_m} por {rot_d} — do pior ao melhor "
                      f"(os {n_piores} piores em vermelho)",
            "labels": [f"{cat} (n={int(r['n'])})" for cat, r in grupo.iterrows()],
            "datasets": [{"label": "Média (min)",
                          "data": [round(float(r["media"]) / 60, 2)
                                   for _, r in grupo.iterrows()],
                          "colors": ["#dc3545" if i < n_piores else "#198754"
                                     for i in range(len(grupo))]}],
        }
        if len(grupo) > 12:
            chart_bar["height"] = max(240, 20 * len(grupo) + 60)

        # Curvas normais: as 5 piores categorias × geral
        mu_g, sd_g = float(geral.mean()), float(geral.std()) or 1.0
        piores5 = list(grupo.head(5).iterrows())
        x_max = max([mu_g + 3 * sd_g]
                    + [float(r["media"]) + 3 * (float(r["desvio"]) or 1)
                       for _, r in piores5])
        xs = [x_max * i / 120 for i in range(121)]

        def pdf(mu, sd):
            sd = sd or 1.0
            return [math.exp(-((x - mu) ** 2) / (2 * sd ** 2))
                    / (sd * math.sqrt(2 * math.pi)) for x in xs]

        paleta = ["#dc3545", "#fd7e14", "#ffc107", "#d63384", "#6f42c1"]
        datasets_g = [{"label": f"Geral · μ {self._hms(mu_g)} · n {len(geral)}",
                       "color": "#6c757d", "data": pdf(mu_g, sd_g)}]
        for i, (cat, r) in enumerate(piores5):
            datasets_g.append({
                "label": f"{cat} · μ {self._hms(r['media'])} · n {int(r['n'])}",
                "color": paleta[i % len(paleta)],
                "data": pdf(float(r["media"]), float(r["desvio"]))})
        chart_gauss = {"tipo": "gauss",
                       "titulo": f"Distribuição ({rot_m}) — 5 piores × geral, "
                                 "curva normal ajustada",
                       "labels": [self._hms(x) for x in xs],
                       "datasets": datasets_g}

        tabela = {"titulo": f"Estatísticas por {rot_d} (n ≥ {min_n}, "
                            "do pior ao melhor)",
                  "colunas": [rot_d, "n", "Média", "Mediana", "σ", "P10",
                              "P90", "Máx"],
                  "linhas": [[cat, int(r["n"]), self._hms(r["media"]),
                              self._hms(r["mediana"]), self._hms(r["desvio"]),
                              self._hms(r["p10"]), self._hms(r["p90"]),
                              self._hms(r["maximo"])]
                             for cat, r in grupo.iterrows()]}

        return _json_safe({"metrica": metrica, "dimensao": dimensao,
                           "rotulo_metrica": rot_m, "rotulo_dimensao": rot_d,
                           "kpis": kpis, "chart_bar": chart_bar,
                           "chart_gauss": chart_gauss, "tabela": tabela,
                           "total": int(len(base))})

    # ------------------------------------------------------- helpers

    @staticmethod
    def _hms(segundos: float | None) -> str:
        """Formata tempo como mm:ss (minutos totais, sem hora)."""
        if segundos is None or pd.isna(segundos):
            return "--:--"
        s = int(round(segundos))
        return f"{s // 60:02d}:{s % 60:02d}"

    @staticmethod
    def _validos(df: pd.DataFrame, col: str) -> pd.Series:
        """Valores válidos de uma métrica de tempo: > 0 e abaixo do teto."""
        cap = CAP_TEMPO.get(col, 14400)
        v = df[col]
        return v[(v > 0) & (v < cap)]

    def _kpis_tempo(self, df: pd.DataFrame, col: str) -> list[dict]:
        v = self._validos(df, col)
        if v.empty:
            return [{"label": "Registros válidos", "valor": "0", "sub": ""}]
        return [
            {"label": "Média", "valor": self._hms(v.mean()),
             "sub": f"{len(v)} registros válidos"},
            {"label": "Mediana", "valor": self._hms(v.median()), "sub": ""},
            {"label": "P90", "valor": self._hms(v.quantile(0.9)), "sub": ""},
            {"label": "Mín / Máx",
             "valor": f"{self._hms(v.min())} / {self._hms(v.max())}", "sub": ""},
        ]

    def _serie_diaria_min(self, df: pd.DataFrame, cols: list[tuple[str, str]],
                          titulo: str) -> dict:
        """Linha: média diária (minutos) de uma ou mais métricas de tempo."""
        dias = sorted(df["dia"].dropna().unique())
        datasets = []
        for col, rotulo in cols:
            cap = CAP_TEMPO.get(col, 14400)
            base = df[(df[col] > 0) & (df[col] < cap)]
            medias = base.groupby("dia")[col].mean() / 60
            datasets.append({"label": rotulo,
                             "data": [round(float(medias.get(d, np.nan)), 2)
                                      if d in medias.index else None
                                      for d in dias]})
        return {"tipo": "line", "titulo": titulo,
                "labels": [d.strftime("%d/%m") for d in dias],
                "datasets": datasets, "unidade_y": "min"}

    def _serie_agrupada_min(self, df: pd.DataFrame, cols: list[tuple[str, str]],
                            titulo: str, eixo: str) -> dict:
        """Linha multi-métrica com média em minutos por semana ou por mês."""
        if eixo == "semana":
            chaves = sorted(df["semana_iso"].dropna().unique())
            rotulos = list(chaves)

            def _agrupa(base: pd.DataFrame, col: str) -> pd.Series:
                return base.groupby("semana_iso")[col].mean() / 60
        else:  # mês
            com_data = df[df["dt_ocorr"].notna()]
            chaves = sorted(com_data["dt_ocorr"].dt.to_period("M").unique())
            rotulos = [m.strftime("%m/%Y") for m in chaves]

            def _agrupa(base: pd.DataFrame, col: str) -> pd.Series:
                m = base[base["dt_ocorr"].notna()]
                return m.groupby(m["dt_ocorr"].dt.to_period("M"))[col].mean() / 60

        datasets = []
        for col, rotulo in cols:
            cap = CAP_TEMPO.get(col, 14400)
            serie = _agrupa(df[(df[col] > 0) & (df[col] < cap)], col)
            datasets.append({"label": rotulo,
                             "data": [round(float(serie[k]), 2)
                                      if k in serie.index and pd.notna(serie[k])
                                      else None for k in chaves]})
        return {"tipo": "line", "titulo": titulo, "labels": rotulos,
                "datasets": datasets, "unidade_y": "min"}

    def _hist_tempo(self, df: pd.DataFrame, col: str, titulo: str,
                    passo_min: int = 2, max_min: int = 30) -> dict:
        v = self._validos(df, col) / 60
        bordas = list(range(0, max_min + passo_min, passo_min))
        labels = [f"{a:02d}:00–{b:02d}:00"
                  for a, b in zip(bordas[:-1], bordas[1:])] + [f">{max_min:02d}:00"]
        contagens = [int(((v >= a) & (v < b)).sum())
                     for a, b in zip(bordas[:-1], bordas[1:])]
        contagens.append(int((v >= max_min).sum()))
        return {"tipo": "bar",
                "titulo": titulo.replace("(min)", "(mm:ss)"),
                "labels": labels,
                "datasets": [{"label": "Ocorrências", "data": contagens}]}

    def _por_categoria(self, df: pd.DataFrame, col: str, col_cat: str,
                       titulo: str, top: int | None = 15, min_n: int = 5,
                       horizontal: bool = True) -> dict:
        """Média de uma métrica de tempo por categoria, do pior ao melhor.

        top=None exibe todas as categorias (altura do gráfico acompanha).
        """
        cap = CAP_TEMPO.get(col, 14400)
        base = df[(df[col] > 0) & (df[col] < cap) & df[col_cat].notna()
                  & df[col_cat].ne("")]
        grupo = base.groupby(col_cat)[col].agg(["mean", "count"])
        grupo = grupo[grupo["count"] >= min_n].sort_values("mean", ascending=False)
        if top:
            grupo = grupo.head(top)
            titulo = f"{titulo} — piores primeiro (top {top}, n ≥ {min_n})"
        elif min_n > 1:
            titulo = f"{titulo} — do pior ao melhor (n ≥ {min_n})"
        else:
            titulo = f"{titulo} — do pior ao melhor"
        spec = {"tipo": "bar", "titulo": titulo,
                "labels": [f"{cat} (n={int(r['count'])})"
                           for cat, r in grupo.iterrows()],
                "datasets": [{"label": "Média (min)",
                              "data": [round(x / 60, 2) for x in grupo["mean"]]}],
                "horizontal": horizontal, "unidade_y": "min"}
        if horizontal and len(grupo) > 12:
            spec["height"] = max(240, 20 * len(grupo) + 60)
        return spec

    def _por_unidade(self, df: pd.DataFrame, col: str, titulo: str,
                     top: int = 15, min_n: int = 5) -> dict:
        return self._por_categoria(df, col, "unidade_curta", titulo,
                                   top=top, min_n=min_n)

    def _por_mes(self, df: pd.DataFrame, col: str, titulo: str) -> dict:
        """Média mensal (min) de uma métrica de tempo, em ordem cronológica."""
        cap = CAP_TEMPO.get(col, 14400)
        base = df[(df[col] > 0) & (df[col] < cap) & df["dt_ocorr"].notna()]
        grupo = base.groupby(base["dt_ocorr"].dt.to_period("M"))[col] \
                    .agg(["mean", "count"]).sort_index()
        return {"tipo": "line", "titulo": titulo,
                "labels": [f"{p.strftime('%m/%Y')} (n={int(r['count'])})"
                           for p, r in grupo.iterrows()],
                "datasets": [{"label": "Média (min)",
                              "data": [round(x / 60, 2) for x in grupo["mean"]]}],
                "unidade_y": "min"}

    def _por_ano(self, df: pd.DataFrame, col: str, titulo: str) -> dict:
        """Média anual (min) de uma métrica de tempo."""
        cap = CAP_TEMPO.get(col, 14400)
        base = df[(df[col] > 0) & (df[col] < cap) & df["dt_ocorr"].notna()]
        grupo = base.groupby(base["dt_ocorr"].dt.year)[col] \
                    .agg(["mean", "count"]).sort_index()
        return {"tipo": "line", "titulo": titulo,
                "labels": [f"{int(ano)} (n={int(r['count'])})"
                           for ano, r in grupo.iterrows()],
                "datasets": [{"label": "Média (min)",
                              "data": [round(x / 60, 2) for x in grupo["mean"]]}],
                "unidade_y": "min"}

    def _por_semana(self, df: pd.DataFrame, col: str, titulo: str) -> dict:
        """Média semanal (min) de uma métrica de tempo — semanas ISO."""
        cap = CAP_TEMPO.get(col, 14400)
        base = df[(df[col] > 0) & (df[col] < cap) & df["semana_iso"].notna()]
        grupo = base.groupby("semana_iso")[col].agg(["mean", "count"]).sort_index()
        return {"tipo": "line", "titulo": titulo,
                "labels": [f"{sem} (n={int(r['count'])})"
                           for sem, r in grupo.iterrows()],
                "datasets": [{"label": "Média (min)",
                              "data": [round(x / 60, 2) for x in grupo["mean"]]}],
                "unidade_y": "min"}

    @staticmethod
    def _contagem(df: pd.DataFrame, col: str, top: int | None = None) -> pd.Series:
        vc = df[col].dropna().value_counts()
        return vc.head(top) if top else vc

    def _bar_contagem(self, df: pd.DataFrame, col: str, titulo: str,
                      top: int | None = 15, horizontal: bool = True) -> dict:
        vc = self._contagem(df, col, top)
        spec = {"tipo": "bar", "titulo": titulo, "labels": list(vc.index),
                "datasets": [{"label": "Ocorrências",
                              "data": [int(x) for x in vc]}],
                "horizontal": horizontal}
        if horizontal and len(vc) > 12:
            spec["height"] = max(240, 20 * len(vc) + 60)
        return spec

    def _bar_percentual(self, df: pd.DataFrame, col: str, titulo: str) -> dict:
        """Distribuição percentual de uma coluna (n absoluto no rótulo)."""
        vc = df[col].dropna().value_counts()
        total = int(vc.sum()) or 1
        spec = {"tipo": "bar", "titulo": f"{titulo} — % dos registros",
                "labels": [f"{valor} (n={int(qtd)})" for valor, qtd in vc.items()],
                "datasets": [{"label": "% dos registros",
                              "data": [round(qtd / total * 100, 1) for qtd in vc]}],
                "horizontal": True}
        if len(vc) > 12:
            spec["height"] = max(240, 20 * len(vc) + 60)
        return spec

    def _pizza(self, df: pd.DataFrame, col: str, titulo: str,
               top: int = 8) -> dict:
        vc = self._contagem(df, col, top)
        return {"tipo": "doughnut", "titulo": titulo, "labels": list(vc.index),
                "datasets": [{"label": "Ocorrências",
                              "data": [int(x) for x in vc]}]}

    def _tabela_contagem(self, df: pd.DataFrame, col: str, titulo: str,
                         rotulo: str, top: int = 30) -> dict:
        vc = self._contagem(df, col, top)
        total = int(df[col].notna().sum()) or 1
        linhas = [[nome, int(qtd), f"{qtd / total * 100:.1f}%"]
                  for nome, qtd in vc.items()]
        return {"titulo": titulo, "colunas": [rotulo, "Ocorrências", "%"],
                "linhas": linhas}

    def _volume_por(self, base: pd.DataFrame, eixo: str,
                    nunique_col: str | None = None) -> pd.Series:
        """Contagem por dia/semana/mês (linhas ou valores únicos de uma coluna)."""
        if eixo == "dia":
            chave = base["dia"]
        elif eixo == "semana":
            chave = base["semana_iso"]
        else:  # mês
            chave = base["dt_ocorr"].dt.to_period("M")
        grupo = base.groupby(chave)
        serie = grupo[nunique_col].nunique() if nunique_col else grupo.size()
        return serie.sort_index()

    def _charts_volume(self, bases: list[tuple[str, pd.DataFrame]],
                       rotulo: str, nunique_col: str | None = None) -> list[dict]:
        """Trio de gráficos de volume — por dia, por semana e por mês."""
        charts = []
        for eixo, sufixo, tipo in (("dia", "por dia", "line"),
                                   ("semana", "por semana", "line"),
                                   ("mes", "por mês", "bar")):
            series = [(nome, self._volume_por(b, eixo, nunique_col))
                      for nome, b in bases]
            chaves = sorted(set().union(*[set(s.index) for _, s in series]))
            if eixo == "dia":
                labels = [c.strftime("%d/%m") for c in chaves]
            elif eixo == "mes":
                labels = [c.strftime("%m/%Y") for c in chaves]
            else:
                labels = list(chaves)
            charts.append({
                "tipo": tipo, "titulo": f"{rotulo} — {sufixo}",
                "labels": labels,
                "datasets": [{"label": nome,
                              "data": [int(s.get(c, 0)) for c in chaves]}
                             for nome, s in series]})
        return charts

    def _preenchimento(self, df: pd.DataFrame, col: str) -> str:
        pct = df[col].notna().mean() * 100 if len(df) else 0
        return f"{pct:.1f}% preenchido"

    # ------------------------------------------------------- temas

    def tema_processos(self, df: pd.DataFrame) -> dict:
        kpis, medias, medianas, tabela = [], [], [], []
        for col, rotulo, formula in PERIODOS:
            v = self._validos(df, col)
            kpis.append({"label": rotulo,
                         "valor": self._hms(v.mean()) if len(v) else "--:--:--",
                         "sub": f"n = {len(v)}"})
            medias.append(round(v.mean() / 60, 1) if len(v) else 0)
            medianas.append(round(v.median() / 60, 1) if len(v) else 0)
            tabela.append([rotulo, formula, len(v),
                           self._hms(v.mean()) if len(v) else "--",
                           self._hms(v.median()) if len(v) else "--",
                           self._hms(v.quantile(0.9)) if len(v) else "--"])

        p1 = self._validos(df, "t_p1")
        sla = [("P1 ≤ 1,5 min", float((p1 <= SLA_P1).mean() * 100) if len(p1) else 0)]
        aph = df[df["transporte"] == "Pré-hospitalar"]
        for cor, limite in SLA_P2_POR_COR.items():
            base = aph[aph["codigo_cor"] == cor]
            v = self._validos(base, "t_p2")
            sla.append((f"P2 {ROTULO_COR[cor]} ≤ {limite // 60} min",
                        float((v <= limite).mean() * 100) if len(v) else 0))

        rotulos = [r for _, r, _ in PERIODOS]
        return {
            "kpis": kpis,
            "charts": [
                {"tipo": "bar", "titulo": "Média por processo (min)",
                 "labels": rotulos,
                 "datasets": [{"label": "Média (min)", "data": medias},
                              {"label": "Mediana (min)", "data": medianas}],
                 "unidade_y": "min"},
                {"tipo": "bar", "titulo": "Cumprimento de SLA (%) — P1 geral e P2 APH por cor",
                 "labels": [s[0] for s in sla],
                 "datasets": [{"label": "% dentro do SLA",
                               "data": [round(s[1], 1) for s in sla]}],
                 "max_y": 100},
                self._serie_diaria_min(
                    df, [("t_p1", "P1"), ("t_p2", "P2"), ("t_p3", "P3"),
                         ("t_p4", "P4"), ("t_p4_1", "P4.1"), ("t_p4_2", "P4.2")],
                    "Evolução diária — P1 a P4.2 (média em min)"),
                self._serie_agrupada_min(
                    df, [("t_p1", "P1"), ("t_p2", "P2"), ("t_p3", "P3"),
                         ("t_p4", "P4"), ("t_p4_1", "P4.1"), ("t_p4_2", "P4.2")],
                    "Evolução semanal — P1 a P4.2 (média em min)", "semana"),
                self._serie_agrupada_min(
                    df, [("t_p1", "P1"), ("t_p2", "P2"), ("t_p3", "P3"),
                         ("t_p4", "P4"), ("t_p4_1", "P4.1"), ("t_p4_2", "P4.2")],
                    "Evolução mensal — P1 a P4.2 (média em min)", "mes"),
                self._serie_diaria_min(
                    df, [("t_p5_6_7", "P5-7 Cena"), ("t_p8", "P8"),
                         ("t_p9", "P9")],
                    "Evolução diária — cena, transporte e transferência"),
                self._serie_agrupada_min(
                    df, [("t_p5_6_7", "P5-7 Cena"), ("t_p8", "P8"),
                         ("t_p9", "P9")],
                    "Evolução semanal — cena, transporte e transferência",
                    "semana"),
                self._serie_agrupada_min(
                    df, [("t_p5_6_7", "P5-7 Cena"), ("t_p8", "P8"),
                         ("t_p9", "P9")],
                    "Evolução mensal — cena, transporte e transferência",
                    "mes"),
            ],
            "tables": [{"titulo": "Estatísticas por processo",
                        "colunas": ["Processo", "Fórmula", "n", "Média",
                                    "Mediana", "P90"],
                        "linhas": tabela}],
        }

    def _tema_tempo_generico(self, df: pd.DataFrame, col: str, rotulo: str,
                             extra_cols: list[tuple[str, str]] | None = None) -> dict:
        series = [(col, rotulo)] + (extra_cols or [])
        charts = [
            self._serie_diaria_min(df, series, f"{rotulo} — média diária (min)"),
            self._hist_tempo(df, col, f"{rotulo} — distribuição (min)"),
            self._por_unidade(df, col, f"{rotulo} por unidade"),
        ]
        base = df[(df[col] > 0) & (df[col] < CAP_TEMPO.get(col, 14400))]
        por_hora = base.groupby("hora")[col].mean() / 60
        charts.append({"tipo": "bar", "titulo": f"{rotulo} por hora do dia (média em min)",
                       "labels": [f"{h:02d}h" for h in range(24)],
                       "datasets": [{"label": "Média (min)",
                                     "data": [round(float(por_hora.get(h, 0)), 2)
                                              for h in range(24)]}],
                       "unidade_y": "min"})
        return {"kpis": self._kpis_tempo(df, col), "charts": charts, "tables": []}

    def tema_tempo_central(self, df: pd.DataFrame) -> dict:
        dados = self._tema_tempo_generico(df, "t_central", "Tempo de Central")
        dados["charts"][2] = self._por_categoria(
            df, "t_central", "unidade_curta", "Tempo de Central por unidade",
            top=None, min_n=1)
        # Trio temporal no topo: diária (já é o 1º gráfico), semanal e mensal.
        dados["charts"].insert(1, self._por_semana(
            df, "t_central", "Tempo de Central — média semanal (min)"))
        dados["charts"].insert(2, self._por_mes(
            df, "t_central", "Tempo de Central — média mensal (min)"))
        dados["charts"] += [
            self._por_categoria(df, "t_central", "cidade",
                                "Tempo de Central por cidade",
                                top=None, min_n=1),
            self._por_categoria(df, "t_central", "micro_regiao",
                                "Tempo de Central por micro região",
                                top=None, min_n=1),
            self._por_categoria(df, "t_central", "transporte",
                                "Tempo de Central por transporte",
                                top=None, min_n=1, horizontal=False),
            self._por_categoria(df, "t_central", "recurso",
                                "Tempo de Central por tipo de transporte (USA/USB)",
                                top=None, min_n=1, horizontal=False),
            self._por_categoria(df, "t_central", "codigo_da_ocorrencia",
                                "Tempo de Central por código da ocorrência",
                                top=None, min_n=1),
        ]
        return dados

    def tema_tempo_cena(self, df: pd.DataFrame) -> dict:
        dados = self._tema_tempo_generico(df, "t_cena", "Tempo de Cena")
        # Por unidade com TODAS as categorias (substitui o top 15 genérico)
        dados["charts"][2] = self._por_categoria(
            df, "t_cena", "unidade_curta", "Tempo de Cena por unidade",
            top=None, min_n=1)
        # Trio temporal no topo: diária (1º gráfico), semanal e anual
        dados["charts"].insert(1, self._por_semana(
            df, "t_cena", "Tempo de Cena — média semanal (min)"))
        dados["charts"].insert(2, self._por_mes(
            df, "t_cena", "Tempo de Cena — média mensal (min)"))
        # Dimensão combinada cidade — unidade
        combinada = df["cidade"].fillna("") + " — " + df["unidade_curta"].fillna("")
        dfx = df.assign(cidade_unidade=combinada.where(
            df["cidade"].notna() & df["unidade_curta"].ne("")))
        dados["charts"] += [
            self._por_categoria(df, "t_cena", "micro_regiao",
                                "Tempo de Cena por micro região",
                                top=None, min_n=1),
            self._por_categoria(dfx, "t_cena", "cidade_unidade",
                                "Tempo de Cena por cidade — unidade",
                                top=None, min_n=1),
        ]
        return dados

    def tema_tempo_saida_base(self, df: pd.DataFrame) -> dict:
        dados = self._tema_tempo_generico(
            df, "t_saida_gps", "Saída de Base (GPS)",
            extra_cols=[("t_saida_j9", "Saída J9")])
        dados["kpis"] += [{"label": "Saída J9 — média",
                           "valor": self._hms(self._validos(df, "t_saida_j9").mean()),
                           "sub": f"n = {len(self._validos(df, 't_saida_j9'))}"}]
        # Por unidade completo (substitui o top 15 genérico)
        dados["charts"][2] = self._por_categoria(
            df, "t_saida_gps", "unidade_curta", "Saída de Base por unidade",
            top=None, min_n=1)
        dados["charts"] += [
            self._por_categoria(df, "t_saida_gps", "recurso",
                                "Saída de Base por tipo de transporte (USA/USB)",
                                top=None, min_n=1, horizontal=False),
            self._por_categoria(df, "t_saida_gps", "micro_regiao",
                                "Saída de Base por micro região",
                                top=None, min_n=1),
            self._por_categoria(df, "t_saida_gps", "cidade",
                                "Saída de Base por cidade",
                                top=None, min_n=1),
        ]
        tabela = self._tabela_ranking_saida_base(df)
        if tabela:
            dados["tables"].append(tabela)
        return dados

    def _tabela_ranking_saida_base(self, df: pd.DataFrame) -> dict | None:
        """Ranking mensal de P4.1 por unidade, no molde do relatório impresso.

        A média e a posição referem-se ao mês anterior (último mês fechado
        dos dados filtrados); a variação compara com a posição no mês que
        antecede o anterior (positiva = subiu no ranking). Verde: média
        ≤ 2 min; vermelho: > 2 min.
        """
        cap = CAP_TEMPO.get("t_saida_gps", 14400)
        base = df[(df["t_saida_gps"] > 0) & (df["t_saida_gps"] < cap)
                  & df["dt_ocorr"].notna()
                  & df["unidade_curta"].notna() & df["unidade_curta"].ne("")]
        if base.empty:
            return None
        per = base["dt_ocorr"].dt.to_period("M")
        mes_ref = base["dt_ocorr"].max().to_period("M") - 1
        if not (per == mes_ref).any():   # filtro sem o mês anterior completo
            mes_ref = per.max()
        mes_ant = mes_ref - 1

        def _ranking(mes: pd.Period) -> pd.DataFrame:
            g = base[per == mes].groupby("unidade_curta")["t_saida_gps"] \
                .agg(["mean", "count"]).sort_values("mean")
            g["pos"] = range(1, len(g) + 1)
            return g

        atual, anterior = _ranking(mes_ref), _ranking(mes_ant)
        if atual.empty:
            return None
        # Cidade predominante da unidade (para o rótulo "USB 44 — SERRA")
        cidades = base.groupby("unidade_curta")["cidade"].agg(
            lambda s: s.mode().iat[0] if not s.mode().empty else "")

        linhas = []
        for unidade, r in atual.iterrows():
            cidade = cidades.get(unidade, "")
            rotulo = f"{unidade} — {cidade}" if cidade else unidade
            tempo = {"v": self._hms(r["mean"]),
                     "cls": "table-success" if r["mean"] <= 120
                            else "table-danger"}
            if unidade in anterior.index:
                delta = int(anterior.loc[unidade, "pos"] - r["pos"])
                if delta > 0:
                    var = {"v": f"▲ +{delta}", "cls": "text-success fw-bold"}
                elif delta < 0:
                    var = {"v": f"▼ {delta}", "cls": "text-danger fw-bold"}
                else:
                    var = {"v": "▶ 0", "cls": "text-warning fw-bold"}
            else:
                var = {"v": "novo", "cls": "text-muted"}
            linhas.append([rotulo, tempo, int(r["pos"]), var])

        return {"titulo": (f"Ranking de Saída de Base (P4.1) por unidade — "
                           f"{_nome_mes(mes_ref)} · variação vs "
                           f"{_nome_mes(mes_ant)} · verde ≤ 02:00, "
                           "vermelho > 02:00"),
                "colunas": ["Unidade", "P4.1 (média)",
                            f"Posição — {_nome_mes(mes_ref)}",
                            f"Variação vs {_nome_mes(mes_ant)}"],
                "linhas": linhas}

    def tema_saidas_ambulancia(self, df: pd.DataFrame) -> dict:
        """Volume de saídas de ambulâncias (empenhos que iniciaram deslocamento)."""
        base = df[df["dt_ocorr"].notna()
                  & df["unidade_curta"].notna() & df["unidade_curta"].ne("")
                  & df["dt_inicio_deslocamento"].notna()]
        dias = int(base["dia"].nunique())
        usa = base[base["recurso"] == "USA"]
        usb = base[base["recurso"] == "USB"]
        kpis = [
            {"label": "Saídas no período", "valor": f"{len(base):,}".replace(",", "."),
             "sub": "empenhos com início de deslocamento"},
            {"label": "Média por dia",
             "valor": f"{len(base) / dias:.1f}" if dias else "0",
             "sub": f"{dias} dias com registro"},
            {"label": "USA", "valor": f"{len(usa):,}".replace(",", "."),
             "sub": f"{len(usa) / len(base) * 100:.1f}% do total" if len(base) else ""},
            {"label": "USB", "valor": f"{len(usb):,}".replace(",", "."),
             "sub": f"{len(usb) / len(base) * 100:.1f}% do total" if len(base) else ""},
        ]
        charts = self._charts_volume(
            [("Total", base), ("USA", usa), ("USB", usb)],
            "Saídas de ambulâncias")
        return {"kpis": kpis, "charts": charts, "tables": []}

    def tema_regulacoes(self, df: pd.DataFrame) -> dict:
        """Volume de regulações — ocorrências únicas com regulador."""
        base = df[df["dt_ocorr"].notna() & df["regulador"].notna()
                  & df["ocorrencia"].notna()]
        total = int(base["ocorrencia"].nunique())
        dias = int(base["dia"].nunique())
        kpis = [
            {"label": "Regulações no período",
             "valor": f"{total:,}".replace(",", "."),
             "sub": "ocorrências únicas com regulador"},
            {"label": "Média por dia",
             "valor": f"{total / dias:.1f}" if dias else "0",
             "sub": f"{dias} dias com registro"},
            {"label": "Reguladores distintos",
             "valor": str(int(base["regulador"].nunique())), "sub": ""},
        ]
        charts = self._charts_volume([("Regulações", base)],
                                     "Regulações", nunique_col="ocorrencia")
        # Distribuição por hora do dia: média de regulações por hora
        # (regulações da hora ÷ dias com registro no período)
        por_hora = base.groupby("hora")["ocorrencia"].nunique()
        charts.append({
            "tipo": "bar",
            "titulo": "Média de regulações por hora do dia",
            "labels": [f"{h:02d}h" for h in range(24)],
            "datasets": [{"label": "Média por dia",
                          "data": [round(float(por_hora.get(h, 0)) / dias, 1)
                                   if dias else 0 for h in range(24)]}]})
        return {"kpis": kpis, "charts": charts, "tables": []}

    def tema_tempo_resposta(self, df: pd.DataFrame) -> dict:
        dados = self._tema_tempo_generico(df, "tempo_resposta",
                                          "Tempo de Resposta")
        # Por unidade completo (todas as categorias, com scroll automático)
        dados["charts"][2] = self._por_categoria(
            df, "tempo_resposta", "unidade_curta",
            "Tempo de Resposta por unidade", top=None, min_n=1)
        dados["charts"].insert(1, self._por_semana(
            df, "tempo_resposta", "Tempo de Resposta — média semanal (min)"))
        dados["charts"].insert(2, self._por_mes(
            df, "tempo_resposta", "Tempo de Resposta — média mensal (min)"))
        # Recorte fixo de gestão: Pré-hospitalar · USA · Código Vermelho ·
        # Convênio · despacho único (ocorrência com uma só ambulância
        # empenhada; a contagem de empenhos considera todas as linhas da
        # ocorrência, antes do recorte). tempo_resposta já considera só a
        # 1ª ambulância a chegar.
        empenhos = df[df["ocorrencia"].notna()].groupby("ocorrencia").size()
        unico = df["ocorrencia"].map(empenhos).eq(1)
        vermelho_usa = df[(df["transporte"] == "Pré-hospitalar")
                          & (df["recurso"] == "USA")
                          & (df["codigo_cor"] == "vermelho")
                          & df["convenio"] & unico]
        dados["charts"].insert(3, self._por_semana(
            vermelho_usa, "tempo_resposta",
            "Tempo de Resposta — Pré-hospitalar · USA · Código Vermelho · "
            "Convênio · despacho único (média semanal)"))
        dados["charts"].insert(4, self._por_mes(
            vermelho_usa, "tempo_resposta",
            "Tempo de Resposta — Pré-hospitalar · USA · Código Vermelho · "
            "Convênio · despacho único (média mensal)"))
        v = self._validos(df, "tempo_resposta")
        if len(v):
            dados["kpis"] += [
                {"label": "≤ 10 min", "valor": f"{(v <= 600).mean() * 100:.1f}%",
                 "sub": f"{int((v <= 600).sum())} ocorrências"},
                {"label": "≤ 15 min", "valor": f"{(v <= 900).mean() * 100:.1f}%",
                 "sub": f"{int((v <= 900).sum())} ocorrências"},
            ]
        cores = ["vermelho", "amarelo", "verde"]
        medias, ns = [], []
        for cor in cores:
            vc = self._validos(df[df["codigo_cor"] == cor], "tempo_resposta")
            medias.append(round(vc.mean() / 60, 1) if len(vc) else None)
            ns.append(len(vc))
        dados["charts"].append({
            "tipo": "bar",
            "titulo": "Tempo de resposta médio por código (min) — "
                      + " · ".join(f"{ROTULO_COR[c]}: n={n}"
                                   for c, n in zip(cores, ns)),
            "labels": [ROTULO_COR[c] for c in cores],
            "datasets": [{"label": "Média (min)", "data": medias,
                          "colors": [HEX_COR[c] for c in cores]}],
            "unidade_y": "min"})
        dados["charts"] += [
            self._por_categoria(df, "tempo_resposta", "micro_regiao",
                                "Tempo de Resposta por micro região",
                                top=None, min_n=1),
            self._por_categoria(df, "tempo_resposta", "cidade",
                                "Tempo de Resposta por cidade",
                                top=None, min_n=1),
            self._por_categoria(df, "tempo_resposta", "recurso",
                                "Tempo de Resposta por tipo de transporte (USA/USB)",
                                top=None, min_n=1, horizontal=False),
        ]
        return dados

    def tema_transferencia_cuidados(self, df: pd.DataFrame) -> dict:
        rotulo = "Transferência de Cuidados (P9)"
        dados = self._tema_tempo_generico(df, "t_p9", rotulo)
        # Por unidade completo (substitui o top 15 genérico)
        dados["charts"][2] = self._por_categoria(
            df, "t_p9", "unidade_curta", f"{rotulo} por unidade",
            top=None, min_n=1)
        # Trio temporal no topo: diária (1º gráfico), semanal e mensal
        dados["charts"].insert(1, self._por_semana(
            df, "t_p9", f"{rotulo} — média semanal (min)"))
        dados["charts"].insert(2, self._por_mes(
            df, "t_p9", f"{rotulo} — média mensal (min)"))
        dados["charts"] += [
            self._por_categoria(df, "t_p9", "hospital_destino",
                                f"{rotulo} por destino", top=None, min_n=1),
            self._por_categoria(df, "t_p9", "micro_regiao",
                                f"{rotulo} por micro região",
                                top=None, min_n=1),
            self._por_categoria(df, "t_p9", "cidade",
                                f"{rotulo} por cidade", top=None, min_n=1),
            self._por_categoria(df, "t_p9", "recurso",
                                f"{rotulo} por tipo de transporte (USA/USB)",
                                top=None, min_n=1, horizontal=False),
            self._por_categoria(df, "t_p9", "transporte",
                                f"{rotulo} por transporte",
                                top=None, min_n=1, horizontal=False),
        ]
        return dados

    def tema_assertividade(self, df: pd.DataFrame) -> dict:
        base = df[(df["transporte"] == "Pré-hospitalar")
                  & df["codigo_cor"].isin(ADEQUACAO)
                  & df["risco_cor"].notna()]
        kpis, barras = [], []
        corretos_total = 0
        for cor, riscos_ok in ADEQUACAO.items():
            grupo = base[base["codigo_cor"] == cor]
            corretos = int(grupo["risco_cor"].isin(riscos_ok).sum())
            corretos_total += corretos
            pct = corretos / len(grupo) * 100 if len(grupo) else 0
            kpis.append({"label": f"{ROTULO_COR[cor]}",
                         "valor": f"{pct:.1f}%",
                         "sub": f"{corretos}/{len(grupo)} adequados"})
            barras.append(round(pct, 1))
        geral = corretos_total / len(base) * 100 if len(base) else 0
        kpis.insert(0, {"label": "Assertividade geral", "valor": f"{geral:.1f}%",
                        "sub": f"base APH com risco: {len(base)} registros"})

        matriz = pd.crosstab(base["codigo_cor"], base["risco_cor"])
        cores_risco = ["vermelho", "amarelo", "verde", "azul"]
        linhas = []
        for cor in ADEQUACAO:
            linha = [ROTULO_COR[cor]]
            for rc in cores_risco:
                linha.append(int(matriz.loc[cor, rc])
                             if cor in matriz.index and rc in matriz.columns else 0)
            linhas.append(linha)

        # Marca linha a linha se a classificação foi adequada
        ok = pd.Series(False, index=base.index)
        for cor, riscos in ADEQUACAO.items():
            ok |= (base["codigo_cor"] == cor) & base["risco_cor"].isin(riscos)
        base = base.assign(adequado=ok)

        def _serie_pct(grupos) -> tuple[list, list]:
            labels, valores = [], []
            for rotulo, g in grupos:
                labels.append(f"{rotulo} (n={len(g)})")
                valores.append(round(g["adequado"].mean() * 100, 1))
            return labels, valores

        semanas = sorted(base["semana_iso"].dropna().unique())
        serie = [round(base[base["semana_iso"] == s]["adequado"].mean() * 100, 1)
                 for s in semanas]

        meses = base[base["dt_ocorr"].notna()]
        lab_mes, val_mes = _serie_pct(
            (p.strftime("%m/%Y"), g) for p, g in
            meses.groupby(meses["dt_ocorr"].dt.to_period("M")))

        def _assert_por(col: str, titulo: str, horizontal: bool = True) -> dict:
            grupo = base[base[col].notna() & base[col].ne("")] \
                .groupby(col)["adequado"].agg(["mean", "count"]) \
                .sort_values("mean")
            spec = {"tipo": "bar",
                    "titulo": f"{titulo} — do pior ao melhor",
                    "labels": [f"{cat} (n={int(r['count'])})"
                               for cat, r in grupo.iterrows()],
                    "datasets": [{"label": "% adequado",
                                  "data": [round(x * 100, 1) for x in grupo["mean"]]}],
                    "horizontal": horizontal, "max_y": 100}
            if horizontal and len(grupo) > 12:
                spec["height"] = max(240, 20 * len(grupo) + 60)
            return spec

        return {
            "kpis": kpis,
            "charts": [
                {"tipo": "bar", "titulo": "Assertividade por cor (%)",
                 "labels": [ROTULO_COR[c] for c in ADEQUACAO],
                 "datasets": [{"label": "% adequado", "data": barras,
                               "colors": [HEX_COR[c] for c in ADEQUACAO]}],
                 "max_y": 100},
                {"tipo": "line", "titulo": "Assertividade geral por semana (%)",
                 "labels": semanas,
                 "datasets": [{"label": "% adequado", "data": serie}],
                 "max_y": 100},
                {"tipo": "line", "titulo": "Assertividade geral por mês (%)",
                 "labels": lab_mes,
                 "datasets": [{"label": "% adequado", "data": val_mes}],
                 "max_y": 100},
                _assert_por("micro_regiao", "Assertividade por micro região"),
                _assert_por("cidade", "Assertividade por cidade"),
                _assert_por("recurso",
                            "Assertividade por tipo de transporte (USA/USB)",
                            horizontal=False),
                _assert_por("unidade_curta", "Assertividade por unidade"),
            ],
            "tables": [{"titulo": "Matriz código (equipe) × risco (triagem)",
                        "colunas": ["Código \\ Risco", "Vermelho (Emerg./M.Urg.)",
                                    "Amarelo (Urgente)", "Verde (Pouco Urg.)",
                                    "Azul (Não Urg.)"],
                        "linhas": linhas}],
        }

    def tema_codigos(self, df: pd.DataFrame) -> dict:
        cores4 = ["vermelho", "amarelo", "verde", "orientacao_medica"]
        base4 = df[df["codigo_cor"].isin(cores4)]
        kpis = [{"label": "Com código", "valor": str(int(df["codigo_da_ocorrencia"].notna().sum())),
                 "sub": self._preenchimento(df, "codigo_da_ocorrencia")}]
        for cor in cores4:
            n = int((base4["codigo_cor"] == cor).sum())
            pct = n / len(base4) * 100 if len(base4) else 0
            kpis.append({"label": ROTULO_COR[cor], "valor": f"{pct:.1f}%",
                         "sub": f"{n} ocorrências"})

        dias = sorted(base4["dia"].dropna().unique())
        semanas = sorted(base4["semana_iso"].dropna().unique())
        mes_de = base4["dt_ocorr"].dt.to_period("M")
        meses = sorted(mes_de.dropna().unique())

        def _serie_cores(chaves, agrupa) -> list[dict]:
            datasets = []
            for cor in cores4:
                serie = agrupa(base4[base4["codigo_cor"] == cor])
                datasets.append({"label": ROTULO_COR[cor],
                                 "data": [int(serie.get(k, 0)) for k in chaves],
                                 "color": HEX_COR[cor]})
            return datasets

        return {
            "kpis": kpis,
            "charts": [
                self._bar_contagem(df, "codigo_da_ocorrencia",
                                   "Ocorrências por código", top=12),
                {"tipo": "doughnut", "titulo": "Distribuição das 4 cores (denominador só cores)",
                 "labels": [ROTULO_COR[c] for c in cores4],
                 "datasets": [{"label": "Ocorrências",
                               "data": [int((base4["codigo_cor"] == c).sum()) for c in cores4],
                               "colors": [HEX_COR[c] for c in cores4]}]},
                {"tipo": "line", "titulo": "Evolução diária por cor",
                 "labels": [d.strftime("%d/%m") for d in dias],
                 "datasets": _serie_cores(
                     dias, lambda b: b.groupby("dia").size())},
                {"tipo": "line", "titulo": "Evolução semanal por cor",
                 "labels": list(semanas),
                 "datasets": _serie_cores(
                     semanas, lambda b: b.groupby("semana_iso").size())},
                {"tipo": "line", "titulo": "Evolução mensal por cor",
                 "labels": [m.strftime("%m/%Y") for m in meses],
                 "datasets": _serie_cores(
                     meses, lambda b: b.groupby(
                         b["dt_ocorr"].dt.to_period("M")).size())},
            ],
            "tables": [self._tabela_contagem(df, "codigo_da_ocorrencia",
                                             "Todos os códigos", "Código")],
        }

    def tema_situacao(self, df: pd.DataFrame) -> dict:
        return {
            "kpis": [{"label": "Com situação",
                      "valor": str(int(df["situacao_atendimento"].notna().sum())),
                      "sub": self._preenchimento(df, "situacao_atendimento")}],
            "charts": [
                self._bar_contagem(df, "situacao_atendimento",
                                   "Situações mais frequentes", top=20),
                self._pizza(df, "situacao_atendimento", "Top 8 situações"),
            ],
            "tables": [self._tabela_contagem(df, "situacao_atendimento",
                                             "Todas as situações", "Situação",
                                             top=100)],
        }

    # ------------------------------------- Auditoria de Ocorrências

    def tema_auditoria_ocorrencias(self, df: pd.DataFrame) -> dict:
        """Duas perguntas de auditoria sobre o mesmo recorte filtrado.

        1. A ocorrência foi atendida por viatura do próprio município?
        2. Com que frequência cada indicador estourou a meta — e como isso
           se compara à referência que o próprio serviço pratica?
        """
        kpis, charts, tables = [], [], []
        cobertura = self._auditoria_cobertura(df)
        if cobertura:
            kpis += cobertura["kpis"]
            charts += cobertura["charts"]
            tables += cobertura["tables"]
        indicadores = self._auditoria_indicadores(df)
        if indicadores:
            kpis += indicadores["kpis"]
            charts += indicadores["charts"]
            tables += indicadores["tables"]
        return {"kpis": kpis, "charts": charts, "tables": tables}

    def _auditoria_principal(self, df: pd.DataFrame) -> pd.DataFrame:
        """Uma linha por ocorrência: a viatura que de fato a atendeu.

        Ocorrência com vários empenhos é comum. A que conta para cobertura
        é a que chegou primeiro; se nenhuma chegou, a primeira despachada.
        """
        emp = df[df["unidade"].notna()].copy()
        if emp.empty:
            return emp
        emp["_sem_chegada"] = emp["dt_chegada_no_local"].isna()
        emp = emp.sort_values(["_sem_chegada", "dt_chegada_no_local",
                               "dt_data_controlador"])
        # Empenho sem número de ocorrência não pode ser agrupado com os
        # outros: cada um vale por si, senão todos virariam uma ocorrência só.
        com_numero = emp[emp["ocorrencia"].notna()].drop_duplicates(
            subset="ocorrencia", keep="first")
        return pd.concat([com_numero, emp[emp["ocorrencia"].isna()]])

    def _auditoria_cobertura(self, df: pd.DataFrame) -> dict | None:
        """Atendimento por viatura do próprio município × de outro."""
        principal = self._auditoria_principal(df)
        if principal.empty:
            return None
        aval = principal[principal["fora_do_municipio"].notna()]
        if aval.empty:
            return None

        fora = int(aval["fora_do_municipio"].sum())
        proprio = len(aval) - fora
        pct_fora = fora / len(aval) * 100
        sem_base = len(principal) - len(aval)

        kpis = [
            {"label": "Ocorrências",
             "valor": f"{len(aval):,}".replace(",", "."),
             "sub": (f"com viatura e município identificados" if not sem_base
                     else f"{sem_base:,}".replace(",", ".") +
                     " sem município identificado")},
            {"label": "Viatura da casa",
             "valor": f"{proprio / len(aval) * 100:.1f}%",
             "sub": f"{proprio:,}".replace(",", ".") +
                    " do próprio município"},
            {"label": "Viatura de fora",
             "valor": f"{pct_fora:.1f}%",
             "sub": f"{fora:,}".replace(",", ".") + " de outro município"},
        ]
        charts = [{"tipo": "doughnut",
                   "titulo": "Origem da viatura que atendeu",
                   "labels": ["Do próprio município", "De outro município"],
                   "datasets": [{"label": "Ocorrências",
                                 "data": [proprio, fora]}]}]

        # Por município da ocorrência. A cor compara com a média do serviço
        # (a "referência"): quem depende de fora bem mais que a casa toda.
        grupo = aval.groupby("cidade")["fora_do_municipio"].agg(["size", "sum"])
        grupo = grupo[grupo["size"] > 0].sort_values("size", ascending=False)
        linhas = []
        for cidade, r in grupo.iterrows():
            total, qtd = int(r["size"]), int(r["sum"])
            pct = qtd / total * 100
            if pct > pct_fora * 2:
                cls = "table-danger"
            elif pct > pct_fora:
                cls = "table-warning"
            else:
                cls = "table-success"
            de_fora = aval[(aval["cidade"] == cidade)
                           & aval["fora_do_municipio"].fillna(False)]
            origem = de_fora["municipio_base"].mode()
            linhas.append([cidade, total, qtd,
                           {"v": f"{pct:.1f}%", "cls": cls},
                           origem.iat[0] if not origem.empty else "—"])
        tables = [{
            "titulo": (f"Cobertura por município da ocorrência — verde abaixo "
                       f"da média do serviço ({pct_fora:.1f}% de fora), "
                       f"vermelho acima do dobro dela"),
            "colunas": ["Município da ocorrência", "Ocorrências",
                        "Atendidas por viatura de fora", "% de fora",
                        "Principal município de origem"],
            "linhas": linhas,
        }]

        pares = aval[aval["fora_do_municipio"].fillna(False)].groupby(
            ["municipio_base", "cidade"]).size().sort_values(ascending=False)
        if not pares.empty:
            tables.append({
                "titulo": "Quem atende fora da própria base — base → município "
                          "atendido (30 maiores)",
                "colunas": ["Base da viatura", "Município atendido",
                            "Ocorrências"],
                "linhas": [[base, cidade, int(qtd)]
                           for (base, cidade), qtd in pares.head(30).items()],
            })
        return {"kpis": kpis, "charts": charts, "tables": tables}

    def _auditoria_indicadores(self, df: pd.DataFrame) -> dict | None:
        """% de descumprimento da meta por indicador, com a referência real.

        A referência é o que o serviço pratica no recorte (mediana e p90),
        e é ela que define a cor: se a mediana já passou da meta, a maioria
        descumpre; se só o p90 passou, o problema está na cauda.
        """
        metas = self._metas_tempo()
        linhas, labels, valores = [], [], []
        for col, rotulo, sub in AUDITORIA_INDICADORES:
            if col not in df.columns:
                continue
            valida = self._validos(df, col)
            if valida.empty:
                continue
            mediana, p90 = float(valida.median()), float(valida.quantile(0.9))

            if col == "t_p2":
                # Meta por cor do código: cada linha tem o seu limite.
                limite = df.loc[valida.index, "codigo_cor"].map(SLA_P2_POR_COR)
                com_meta = limite.notna()
                avaliados = int(com_meta.sum())
                acima = int((valida[com_meta] > limite[com_meta]).sum())
                meta_txt = "01:30 / 03:00 / 04:00 por cor"
                referencia = SLA_P2_POR_COR["amarelo"]
            else:
                meta = metas.get(col)
                if meta is None:
                    # Sem meta (P8 depende da distância ao hospital): entra
                    # só com a referência do serviço, sem juízo de valor.
                    linhas.append([f"{rotulo} · {sub}",
                                   {"v": "sem meta", "cls": "text-muted"},
                                   len(valida), {"v": "—", "cls": "text-muted"},
                                   self._hms(mediana), self._hms(p90)])
                    continue
                avaliados = len(valida)
                acima = int((valida > meta).sum())
                meta_txt, referencia = self._hms(meta), meta

            if not avaliados:
                continue
            pct = acima / avaliados * 100
            if mediana > referencia:
                cls = "table-danger"      # a maioria dos atendimentos falha
            elif p90 > referencia:
                cls = "table-warning"     # falha na cauda
            else:
                cls = "table-success"
            linhas.append([f"{rotulo} · {sub}", meta_txt, avaliados,
                           {"v": f"{pct:.1f}%", "cls": cls},
                           self._hms(mediana), self._hms(p90)])
            labels.append(rotulo)
            valores.append(round(pct, 1))

        if not linhas:
            return None

        piores = sorted(zip(labels, valores), key=lambda x: -x[1])[:3]
        kpis = [{"label": "Pior indicador",
                 "valor": f"{piores[0][1]:.1f}%",
                 "sub": f"{piores[0][0]} acima da meta"}] if piores else []
        charts = [{"tipo": "bar", "horizontal": True,
                   "titulo": "% de atendimentos acima da meta, por indicador",
                   "labels": labels,
                   "datasets": [{"label": "% acima da meta", "data": valores}],
                   "height": max(240, 26 * len(labels) + 60)}]
        tables = [{
            "titulo": ("Descumprimento de meta por indicador — verde: até o "
                       "p90 dentro da meta · amarelo: a cauda estoura · "
                       "vermelho: a mediana já estoura"),
            "colunas": ["Indicador", "Meta", "Atendimentos avaliados",
                        "% acima da meta", "Mediana do serviço",
                        "p90 do serviço"],
            "linhas": linhas,
        }]
        return {"kpis": kpis, "charts": charts, "tables": tables}

    def _metas_tempo(self) -> dict[str, int]:
        """Metas em segundos, com o ajuste feito em /configuracoes."""
        from app.core.config_service import get_config
        from app.core.database import SessionLocal

        metas = dict(METAS_TEMPO)
        db = SessionLocal()
        try:
            for col in list(metas):
                valor = get_config(db, f"{PREFIXO_CONFIG_META}{col}_segundos",
                                   empresa_id=self.empresa_id)
                if valor in (None, ""):
                    continue
                try:
                    metas[col] = max(int(str(valor).strip()), 1)
                except ValueError:
                    pass
        finally:
            db.close()
        return metas

    def tema_localidade(self, df: pd.DataFrame) -> dict:
        return {
            "kpis": [
                {"label": "Cidades distintas",
                 "valor": str(df["cidade"].nunique()),
                 "sub": self._preenchimento(df, "cidade")},
                {"label": "Grande Vitória",
                 "valor": f"{df['convenio'].mean() * 100:.1f}%",
                 "sub": "Vitória + Vila Velha + Serra + Cariacica"},
            ],
            "charts": [
                self._bar_contagem(df, "cidade", "Top 15 cidades"),
                self._bar_contagem(df, "micro_regiao", "Micro regiões", top=12),
            ],
            "tables": [self._tabela_contagem(df, "cidade", "Ocorrências por cidade",
                                             "Cidade", top=50)],
        }

    def tema_perfil_paciente(self, df: pd.DataFrame) -> dict:
        idade = df["idade_num"].dropna()
        bordas = [(0, 1), (1, 12), (12, 18), (18, 30), (30, 45), (45, 60),
                  (60, 75), (75, 200)]
        labels = ["<1", "1–11", "12–17", "18–29", "30–44", "45–59", "60–74", "75+"]
        hist = [int(((idade >= a) & (idade < b)).sum()) for a, b in bordas]
        return {
            "kpis": [
                {"label": "Idade média", "valor": f"{idade.mean():.0f} anos"
                 if len(idade) else "--", "sub": f"{len(idade)} com idade numérica"},
                {"label": "Sexo preenchido",
                 "valor": self._preenchimento(df, "sexo"), "sub": ""},
                {"label": "Faixa preenchida",
                 "valor": self._preenchimento(df, "faixa"), "sub": ""},
            ],
            "charts": [
                self._pizza(df, "sexo", "Sexo"),
                {"tipo": "bar", "titulo": "Idade (faixas etárias)", "labels": labels,
                 "datasets": [{"label": "Pacientes", "data": hist}]},
                self._bar_contagem(df, "faixa", "Faixa (campo do vSky)", top=10,
                                   horizontal=False),
            ],
            "tables": [],
        }

    def tema_tipo_motivo(self, df: pd.DataFrame) -> dict:
        motivo_cod = df["motivo"].dropna().str.split(" ").str[0]
        vc = motivo_cod.value_counts().head(15)
        return {
            "kpis": [
                {"label": "Tipo preenchido", "valor": self._preenchimento(df, "tipo"),
                 "sub": ""},
                {"label": "Motivo preenchido",
                 "valor": self._preenchimento(df, "motivo"), "sub": ""},
                {"label": "Motivos distintos", "valor": str(df["motivo"].nunique()),
                 "sub": ""},
            ],
            "charts": [
                self._pizza(df, "tipo", "Tipo"),
                self._bar_contagem(df, "motivo", "Top 20 motivos", top=20),
                {"tipo": "bar", "titulo": "Top 15 códigos clínicos (prefixo do motivo)",
                 "labels": list(vc.index),
                 "datasets": [{"label": "Ocorrências",
                               "data": [int(x) for x in vc]}], "horizontal": True},
            ],
            "tables": [self._tabela_contagem(df, "motivo", "Motivos", "Motivo",
                                             top=50)],
        }

    def tema_atendimento(self, df: pd.DataFrame) -> dict:
        """O campo só é preenchido quando houve despacho: a grande maioria
        das chamadas (orientação, trote, queda, sem resposta) fica sem valor.
        Os gráficos mostram as três fatias para não distorcer a leitura."""
        norm = df["atendimento"].fillna("").map(nucleo.norm_txt)
        com = norm.eq("COM ATENDIMENTO")
        sem = norm.eq("SEM ATENDIMENTO")
        vazio = ~com & ~sem
        informados = int(com.sum() + sem.sum())

        dias = sorted(df["dia"].dropna().unique())
        serie_com = df[com].groupby("dia").size()
        serie_sem = df[sem].groupby("dia").size()

        pct_dia = []
        for d in dias:
            c, s = int(serie_com.get(d, 0)), int(serie_sem.get(d, 0))
            pct_dia.append(round(c / (c + s) * 100, 1) if c + s else None)

        def _com_sem_serie(chaves, chave_com, chave_sem, titulo) -> dict:
            return {"tipo": "line", "titulo": titulo, "labels": list(chaves),
                    "datasets": [
                        {"label": "Com atendimento",
                         "data": [int(chave_com.get(k, 0)) for k in chaves],
                         "color": "#198754"},
                        {"label": "Sem atendimento",
                         "data": [int(chave_sem.get(k, 0)) for k in chaves],
                         "color": "#dc3545"},
                    ]}

        semanas = sorted(df["semana_iso"].dropna().unique())
        sem_com = df[com].groupby("semana_iso").size()
        sem_sem = df[sem].groupby("semana_iso").size()

        mes_ord = df[df["dt_ocorr"].notna()]["dt_ocorr"].dt.to_period("M")
        meses = sorted(mes_ord.dropna().unique())
        mes_com = df[com & df["dt_ocorr"].notna()].groupby(mes_ord[com & df["dt_ocorr"].notna()]).size()
        mes_sem = df[sem & df["dt_ocorr"].notna()].groupby(mes_ord[sem & df["dt_ocorr"].notna()]).size()

        def _com_sem_por(col: str, titulo: str, horizontal: bool = True) -> dict:
            base = df[(com | sem) & df[col].notna() & df[col].ne("")]
            tab = pd.crosstab(base[col],
                              norm[base.index].eq("COM ATENDIMENTO"))
            tab = tab.rename(columns={True: "com", False: "sem"})
            for faltante in ("com", "sem"):
                if faltante not in tab.columns:
                    tab[faltante] = 0
            tab = tab.assign(total=tab["com"] + tab["sem"]) \
                     .sort_values("total", ascending=False)
            spec = {"tipo": "bar", "titulo": titulo,
                    "labels": [f"{cat} (n={int(r['total'])})"
                               for cat, r in tab.iterrows()],
                    "datasets": [
                        {"label": "Com atendimento",
                         "data": [int(x) for x in tab["com"]], "color": "#198754"},
                        {"label": "Sem atendimento",
                         "data": [int(x) for x in tab["sem"]], "color": "#dc3545"},
                    ], "horizontal": horizontal}
            if horizontal and len(tab) > 12:
                spec["height"] = max(240, 22 * len(tab) + 60)
            return spec

        return {
            "kpis": [
                {"label": "Com atendimento", "valor": str(int(com.sum())),
                 "sub": (f"{com.mean() * 100:.1f}% do total · "
                         f"{com.sum() / informados * 100:.1f}% dos informados"
                         if informados else "")},
                {"label": "Sem atendimento", "valor": str(int(sem.sum())),
                 "sub": f"{sem.mean() * 100:.1f}% do total"},
                {"label": "Não informado", "valor": str(int(vazio.sum())),
                 "sub": (f"{vazio.mean() * 100:.1f}% do total — chamadas sem "
                         "despacho (orientação, trote, queda, sem resposta)")},
            ],
            "charts": [
                {"tipo": "doughnut", "titulo": "Atendimento — composição do total",
                 "labels": ["Com atendimento", "Sem atendimento",
                            "Não informado (sem despacho)"],
                 "datasets": [{"label": "Ocorrências",
                               "data": [int(com.sum()), int(sem.sum()),
                                        int(vazio.sum())],
                               "colors": ["#198754", "#dc3545", "#adb5bd"]}]},
                {"tipo": "line", "titulo": "Com × sem atendimento por dia (contagem)",
                 "labels": [d.strftime("%d/%m") for d in dias],
                 "datasets": [
                     {"label": "Com atendimento",
                      "data": [int(serie_com.get(d, 0)) for d in dias],
                      "color": "#198754"},
                     {"label": "Sem atendimento",
                      "data": [int(serie_sem.get(d, 0)) for d in dias],
                      "color": "#dc3545"},
                 ]},
                {"tipo": "line",
                 "titulo": "% com atendimento por dia (entre os informados)",
                 "labels": [d.strftime("%d/%m") for d in dias],
                 "datasets": [{"label": "% com atendimento", "data": pct_dia}],
                 "max_y": 100},
                _com_sem_serie(semanas, sem_com, sem_sem,
                               "Com × sem atendimento por semana (contagem)"),
                _com_sem_serie([m.strftime("%m/%Y") for m in meses],
                               {m.strftime("%m/%Y"): v for m, v in mes_com.items()},
                               {m.strftime("%m/%Y"): v for m, v in mes_sem.items()},
                               "Com × sem atendimento por mês (contagem)"),
                _com_sem_por("recurso",
                             "Com × sem atendimento por tipo de transporte (USA/USB)",
                             horizontal=False),
                _com_sem_por("codigo_da_ocorrencia",
                             "Com × sem atendimento por código da ocorrência"),
                _com_sem_por("micro_regiao",
                             "Com × sem atendimento por micro região"),
            ],
            "tables": [self._tabela_contagem(df, "atendimento",
                                             "Valores preenchidos",
                                             "Atendimento")],
        }

    def tema_transporte(self, df: pd.DataFrame) -> dict:
        valores = list(df["transporte"].dropna().unique())
        dias = sorted(df["dia"].dropna().unique())
        semanas = sorted(df["semana_iso"].dropna().unique())
        meses = sorted(df["dt_ocorr"].dt.to_period("M").dropna().unique())

        def _serie_transportes(chaves, agrupa) -> list[dict]:
            resultado = []
            for valor in valores:
                serie = agrupa(df[df["transporte"] == valor])
                resultado.append({"label": valor,
                                  "data": [int(serie.get(k, 0))
                                           for k in chaves]})
            return resultado

        datasets = _serie_transportes(dias, lambda b: b.groupby("dia").size())

        def _transporte_por(col: str, titulo: str,
                            horizontal: bool = True) -> dict:
            base = df[df["transporte"].notna() & df[col].notna()
                      & df[col].ne("")]
            tab = pd.crosstab(base[col], base["transporte"])
            tab = tab.assign(total=tab.sum(axis=1)) \
                     .sort_values("total", ascending=False)
            spec = {"tipo": "bar", "titulo": titulo,
                    "labels": [f"{cat} (n={int(r['total'])})"
                               for cat, r in tab.iterrows()],
                    "datasets": [
                        {"label": valor,
                         "data": [int(x) for x in tab[valor]]}
                        for valor in valores if valor in tab.columns
                    ], "horizontal": horizontal}
            if horizontal and len(tab) > 12:
                spec["height"] = max(240, 22 * len(tab) + 60)
            return spec

        return {
            "kpis": [{"label": valor, "valor": str(int((df["transporte"] == valor).sum())),
                      "sub": f"{(df['transporte'] == valor).mean() * 100:.1f}%"}
                     for valor in valores],
            "charts": [
                self._pizza(df, "transporte", "Transporte"),
                {"tipo": "line", "titulo": "Evolução diária por transporte",
                 "labels": [d.strftime("%d/%m") for d in dias],
                 "datasets": datasets},
                {"tipo": "line", "titulo": "Evolução semanal por transporte",
                 "labels": list(semanas),
                 "datasets": _serie_transportes(
                     semanas, lambda b: b.groupby("semana_iso").size())},
                {"tipo": "line", "titulo": "Evolução mensal por transporte",
                 "labels": [m.strftime("%m/%Y") for m in meses],
                 "datasets": _serie_transportes(
                     meses, lambda b: b.groupby(
                         b["dt_ocorr"].dt.to_period("M")).size())},
                _transporte_por("recurso",
                                "Transporte por tipo de transporte (USA/USB)",
                                horizontal=False),
                _transporte_por("micro_regiao", "Transporte por micro região"),
                _transporte_por("cidade", "Transporte por cidade"),
                _transporte_por("codigo_da_ocorrencia",
                                "Transporte por código da ocorrência"),
            ],
            "tables": [self._tabela_contagem(df, "transporte", "Valores",
                                             "Transporte")],
        }

    def tema_unidade(self, df: pd.DataFrame) -> dict:
        com_unidade = df[df["unidade_curta"].ne("")]
        grupo = com_unidade.groupby("unidade_curta").agg(
            n=("id", "count"), tr=("tempo_resposta",
                                   lambda v: v[(v > 0) & (v < 10800)].mean()))
        grupo = grupo.sort_values("n", ascending=False).head(30)
        linhas = [[u, int(r["n"]),
                   self._hms(r["tr"]) if pd.notna(r["tr"]) else "--"]
                  for u, r in grupo.iterrows()]
        return {
            "kpis": [
                {"label": "Registros com unidade", "valor": str(len(com_unidade)),
                 "sub": self._preenchimento(df, "unidade")},
                {"label": "Unidades distintas",
                 "valor": str(com_unidade["unidade_curta"].nunique()), "sub": ""},
                {"label": "Viaturas ISCMV",
                 "valor": str(int(com_unidade["iscmv"].sum())),
                 "sub": "registros em viaturas do núcleo"},
            ],
            "charts": [
                self._bar_contagem(com_unidade, "unidade_curta",
                                   "Unidades por volume", top=None),
                self._pizza(com_unidade, "recurso", "Tipo de recurso (USA/USB/VIR)"),
                self._por_categoria(df, "tempo_resposta", "unidade_curta",
                                    "Tempo resposta por unidade",
                                    top=None, min_n=1),
            ],
            "tables": [{"titulo": "Unidades — volume e tempo resposta médio",
                        "colunas": ["Unidade", "Registros", "T. resposta médio"],
                        "linhas": linhas}],
        }

    def tema_sinais_vitais(self, df: pd.DataFrame) -> dict:
        vitais = [("fr", "Frq. Respiratória", [(0, 8), (8, 12), (12, 20), (20, 25), (25, 60)]),
                  ("fc", "Frq. Cardíaca", [(0, 40), (40, 60), (60, 90), (90, 110), (110, 130), (130, 250)]),
                  ("pas", "PA Sistólica", [(0, 90), (90, 110), (110, 140), (140, 180), (180, 300)]),
                  ("glasgow", "Glasgow", [(3, 8), (8, 12), (12, 14), (14, 16)]),
                  ("glicemia", "Glicemia", [(0, 60), (60, 100), (100, 180), (180, 300), (300, 1000)])]
        kpis = [{"label": rotulo, "valor": f"{df[col].notna().mean() * 100:.1f}%",
                 "sub": f"aferido em {int(df[col].notna().sum())}"}
                for col, rotulo, _ in vitais]
        charts = []
        for col, rotulo, faixas in vitais:
            v = df[col].dropna()
            labels = [f"{a}–{b}" for a, b in faixas]
            data = [int(((v >= a) & (v < b)).sum()) for a, b in faixas]
            charts.append({"tipo": "bar", "titulo": f"{rotulo} (aferidos)",
                           "labels": labels,
                           "datasets": [{"label": "Pacientes", "data": data}]})

        news = df["news_total"].dropna()
        bandas = df["news_risco"].dropna().value_counts()
        ordem = ["Baixo", "Baixo-Médio", "Médio", "Alto"]
        cores_bandas = {"Baixo": "#198754", "Baixo-Médio": "#0dcaf0",
                        "Médio": "#ffc107", "Alto": "#dc3545"}
        kpis.append({"label": "NEWS calculado", "valor": str(len(news)),
                     "sub": "núcleo completo: FR+FC+PA+Glasgow"})
        kpis.append({"label": "NEWS Alto (≥7)",
                     "valor": f"{(news >= 7).mean() * 100:.1f}%" if len(news) else "--",
                     "sub": f"{int((news >= 7).sum())} pacientes"})
        charts.append({"tipo": "doughnut", "titulo": "NEWS modificada — bandas de risco",
                       "labels": [b for b in ordem if b in bandas.index],
                       "datasets": [{"label": "Pacientes",
                                     "data": [int(bandas[b]) for b in ordem if b in bandas.index],
                                     "colors": [cores_bandas[b] for b in ordem if b in bandas.index]}]})
        scores = list(range(0, 16))
        charts.append({"tipo": "bar", "titulo": "NEWS modificada — distribuição do escore",
                       "labels": [str(s) for s in scores[:-1]] + ["15+"],
                       "datasets": [{"label": "Pacientes",
                                     "data": [int((news == s).sum()) for s in scores[:-1]]
                                     + [int((news >= 15).sum())]}]})
        rel_kpis, rel_charts, rel_tabelas = self._relacao_news(df, cores_bandas)
        return {
            "kpis": kpis + rel_kpis, "charts": charts + rel_charts,
            "tables": rel_tabelas + [
                {"titulo": "Escala NEWS modificada — critérios de pontuação",
                 "colunas": ["Parâmetro", "Pontuação"],
                 "linhas": [list(c) for c in NEWS_CRITERIOS]},
                {"titulo": "Bandas de risco",
                 "colunas": ["Banda", "Critério"],
                 "linhas": [list(b) for b in NEWS_BANDAS]},
            ],
        }

    ORDEM_RISCO = ["Emergência", "Muito Urgente", "Urgente",
                   "Pouco Urgente", "Não Urgente"]
    CORES_RISCO = {"Emergência": "#dc3545", "Muito Urgente": "#fd7e14",
                   "Urgente": "#ffc107", "Pouco Urgente": "#198754",
                   "Não Urgente": "#0d6efd"}

    def _relacao_news(self, df: pd.DataFrame, cores_bandas: dict) -> tuple:
        """Relação NEWS × código da ocorrência × risco inicial.

        A NEWS mede a gravidade fisiológica aferida na cena. O código da
        ocorrência é a classificação da EQUIPE na cena (contemporânea aos
        vitais); o risco inicial é a triagem da REGULAÇÃO, anterior ao
        contato. Cruzar com o código mede a coerência da equipe com a
        fisiologia; cruzar com o risco mede o quanto a triagem antecipou
        a gravidade. Toda a seção condiciona em ter NEWS calculada
        (sinais vitais completos) — a cobertura é declarada no KPI e nos
        títulos, pois a aferição completa não é aleatória.
        """
        base = df[df["news_total"].notna()]
        if base.empty:
            return [], [], []
        ordem_bandas = ["Baixo", "Baixo-Médio", "Médio", "Alto"]
        min_n = 30   # esconde categorias raras (ex.: 3 casos não urgentes)

        def _grupos(col: str, ordem: list[str]) -> list[str]:
            vc = base[col].value_counts()
            return [g for g in ordem if vc.get(g, 0) >= min_n]

        def _bar_news_medio(col: str, ordem: list[str], cores: dict,
                            rotulos: dict | None, titulo: str) -> dict:
            g = base.groupby(col)["news_total"].agg(["mean", "count"])
            cats = _grupos(col, ordem)
            return {"tipo": "bar", "titulo": titulo,
                    "labels": [f"{(rotulos or {}).get(c, c)} "
                               f"(n={int(g.loc[c, 'count'])})" for c in cats],
                    "datasets": [{"label": "NEWS médio",
                                  "data": [round(float(g.loc[c, "mean"]), 2)
                                           for c in cats],
                                  "colors": [cores[c] for c in cats]}]}

        def _stack_bandas(col: str, ordem: list[str],
                          rotulos: dict | None, titulo: str) -> dict:
            cats = _grupos(col, ordem)
            tab = pd.crosstab(base[col], base["news_risco"], normalize="index") * 100
            return {"tipo": "bar", "titulo": titulo, "stacked": True, "max_y": 100,
                    "labels": [f"{(rotulos or {}).get(c, c)} "
                               f"(n={int((base[col] == c).sum())})" for c in cats],
                    "datasets": [{"label": banda,
                                  "data": [round(float(tab.loc[c].get(banda, 0)), 1)
                                           for c in cats],
                                  "color": cores_bandas[banda]}
                                 for banda in ordem_bandas]}

        nota = " · pacientes com NEWS aferida"
        ordem_cod = ["vermelho", "amarelo", "verde", "orientacao_medica",
                     "nao_urgente"]
        charts = [
            _bar_news_medio("codigo_cor", ordem_cod, HEX_COR, ROTULO_COR,
                            "NEWS médio por código da ocorrência "
                            "(equipe na cena)" + nota),
            _bar_news_medio("risco_inicial", self.ORDEM_RISCO, self.CORES_RISCO,
                            None, "NEWS médio por risco inicial "
                            "(triagem da regulação)" + nota),
            _stack_bandas("codigo_cor", ordem_cod, ROTULO_COR,
                          "Bandas NEWS dentro de cada código (%)" + nota),
            _stack_bandas("risco_inicial", self.ORDEM_RISCO, None,
                          "Bandas NEWS dentro de cada risco inicial (%)" + nota),
        ]

        # KPIs: cobertura da NEWS + antecipação/subtriagem DA REGULAÇÃO
        # (risco inicial). O código da equipe fica nos gráficos — não entra
        # nos KPIs para não atribuir a subtriagem ao ator errado.
        kpis = [{"label": "Cobertura da NEWS",
                 "valor": f"{len(base) / len(df) * 100:.1f}%",
                 "sub": f"{len(base)} de {len(df)} registros com sinais "
                        "vitais completos — demais ficam fora desta seção"}]
        com_risco = base[base["risco_cor"].notna()]
        alto_r = com_risco[com_risco["news_risco"] == "Alto"]
        if len(alto_r):
            pct_ant = (alto_r["risco_cor"] == "vermelho").mean() * 100
            kpis.append({"label": "NEWS Alto → triagem grave",
                         "valor": f"{pct_ant:.1f}%",
                         "sub": f"dos {len(alto_r)} NEWS Alto, triados como "
                                "Emergência/Muito Urgente"})
        leve = com_risco[com_risco["risco_cor"].isin(["verde", "azul"])]
        if len(leve):
            pct_sub = (leve["news_risco"] == "Alto").mean() * 100
            kpis.append({"label": "NEWS Alto no risco leve",
                         "valor": f"{pct_sub:.1f}%",
                         "sub": f"dos {len(leve)} triados Pouco/Não Urgente "
                                "com NEWS — subtriagem da regulação"})

        # Tabela cruzada risco inicial × código: NEWS médio, % Alto e n
        cods = _grupos("codigo_cor", ordem_cod)
        riscos = _grupos("risco_inicial", self.ORDEM_RISCO)

        def _celula(sub: pd.DataFrame) -> dict | str:
            if len(sub) < min_n:
                return "--"
            pct_alto = (sub["news_risco"] == "Alto").mean() * 100
            cls = ("table-danger" if pct_alto >= 20 else
                   "table-warning" if pct_alto >= 10 else
                   "table-info" if pct_alto >= 5 else "table-success")
            return {"v": f"{sub['news_total'].mean():.2f} · "
                         f"{pct_alto:.1f}% Alto (n={len(sub)})", "cls": cls}

        linhas = []
        for r in riscos:
            sub_r = base[base["risco_inicial"] == r]
            linhas.append([r] + [_celula(sub_r[sub_r["codigo_cor"] == c])
                                 for c in cods] + [_celula(sub_r)])
        linhas.append(["Todos"] + [_celula(base[base["codigo_cor"] == c])
                                   for c in cods] + [_celula(base)])
        tabela = {"titulo": ("Risco inicial (triagem) × Código (equipe) — "
                             "NEWS médio · % NEWS Alto · n — pacientes com "
                             "NEWS aferida (verde < 5% Alto, azul < 10%, "
                             "amarelo < 20%, vermelho >= 20%)"),
                  "colunas": ["Risco inicial"] + [ROTULO_COR[c] for c in cods]
                             + ["Todos os códigos"],
                  "linhas": linhas}
        return kpis, charts, [tabela]

    def tema_obito(self, df: pd.DataFrame) -> dict:
        obitos = df[df["obito_constatado"]]
        dias = sorted(df["dia"].dropna().unique())
        serie = obitos.groupby("dia").size()

        semanas = sorted(df["semana_iso"].dropna().unique())
        serie_sem = obitos.groupby("semana_iso").size()
        mes_ord = obitos[obitos["dt_ocorr"].notna()]["dt_ocorr"].dt.to_period("M")
        todos_meses = sorted(df[df["dt_ocorr"].notna()]["dt_ocorr"]
                             .dt.to_period("M").unique())
        serie_mes = obitos.groupby(mes_ord).size()
        return {
            "kpis": [
                {"label": "Óbitos constatados", "valor": str(len(obitos)),
                 "sub": f"{len(obitos) / len(df) * 100:.2f}% do total filtrado"},
                {"label": "Campo preenchido",
                 "valor": self._preenchimento(df, "obito"), "sub": ""},
            ],
            "charts": [
                self._bar_contagem(df, "obito", "Valores do campo Óbito", top=8,
                                   horizontal=False),
                {"tipo": "line", "titulo": "Óbitos por dia",
                 "labels": [d.strftime("%d/%m") for d in dias],
                 "datasets": [{"label": "Óbitos",
                               "data": [int(serie.get(d, 0)) for d in dias],
                               "color": "#dc3545"}]},
                {"tipo": "line", "titulo": "Óbitos por semana",
                 "labels": semanas,
                 "datasets": [{"label": "Óbitos",
                               "data": [int(serie_sem.get(s, 0)) for s in semanas],
                               "color": "#dc3545"}]},
                {"tipo": "line", "titulo": "Óbitos por mês",
                 "labels": [m.strftime("%m/%Y") for m in todos_meses],
                 "datasets": [{"label": "Óbitos",
                               "data": [int(serie_mes.get(m, 0)) for m in todos_meses],
                               "color": "#dc3545"}]},
                self._bar_contagem(obitos, "micro_regiao",
                                   "Óbitos por micro região", top=None),
                self._bar_contagem(obitos, "cidade", "Óbitos por cidade",
                                   top=None),
                self._bar_contagem(obitos, "recurso",
                                   "Óbitos por tipo de transporte (USA/USB)",
                                   top=None, horizontal=False),
                self._bar_contagem(obitos, "transporte", "Óbitos por transporte",
                                   top=None, horizontal=False),
                self._bar_contagem(obitos, "codigo_da_ocorrencia",
                                   "Óbitos por código da ocorrência", top=None),
            ],
            "tables": [self._tabela_contagem(obitos, "motivo",
                                             "Motivos com óbito", "Motivo",
                                             top=20)],
        }

    def tema_plantao(self, df: pd.DataFrame) -> dict:
        """Plantões: diurno 07:00–18:59, noturno 19:00–06:59 — o noturno
        pertence ao dia em que começou. Compara volume e tempos por turno,
        dia da semana e pelos 14 plantões da semana."""
        COR_TURNO = {"Diurno": "#fd7e14", "Noturno": "#0d6efd"}
        dias_ordem = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta",
                      "Sábado", "Domingo"]
        plantoes = [f"{d} {t}" for d in dias_ordem
                    for t in ("Diurno", "Noturno")]
        metricas = [("t_central", "T. Central"),
                    ("tempo_resposta", "T. Resposta"),
                    ("t_cena", "T. Cena")]

        kpis = []
        for turno in ("Diurno", "Noturno"):
            m = df["turno"] == turno
            kpis.append({"label": f"Ocorrências — {turno}",
                         "valor": str(int(m.sum())),
                         "sub": f"{m.mean() * 100:.1f}% do total"})
        for col, rotulo in metricas:
            for turno in ("Diurno", "Noturno"):
                v = self._validos(df[df["turno"] == turno], col)
                kpis.append({"label": f"{rotulo} — {turno}",
                             "valor": self._hms(v.mean()) if len(v) else "--:--",
                             "sub": f"n = {len(v)}"})

        charts = [
            {"tipo": "doughnut", "titulo": "Volume por plantão",
             "labels": ["Diurno (07:00–18:59)", "Noturno (19:00–06:59)"],
             "datasets": [{"label": "Ocorrências",
                           "data": [int((df["turno"] == "Diurno").sum()),
                                    int((df["turno"] == "Noturno").sum())],
                           "colors": [COR_TURNO["Diurno"],
                                      COR_TURNO["Noturno"]]}]},
        ]

        # Evolução do tempo de resposta por semana e por mês (linha por turno)
        cap_tr = CAP_TEMPO.get("tempo_resposta", 10800)
        tr_valido = df[(df["tempo_resposta"] > 0)
                       & (df["tempo_resposta"] < cap_tr)]
        semanas = sorted(df["semana_iso"].dropna().unique())
        meses = sorted(df[df["dt_ocorr"].notna()]["dt_ocorr"]
                       .dt.to_period("M").unique())
        for eixo, chaves, rotulos_x in (
                ("semanal", semanas, list(semanas)),
                ("mensal", meses, [m.strftime("%m/%Y") for m in meses])):
            datasets_tr = []
            for turno in ("Diurno", "Noturno"):
                base_t = tr_valido[tr_valido["turno"] == turno]
                if eixo == "semanal":
                    serie = base_t.groupby("semana_iso")["tempo_resposta"].mean() / 60
                else:
                    com_data = base_t[base_t["dt_ocorr"].notna()]
                    serie = com_data.groupby(
                        com_data["dt_ocorr"].dt.to_period("M"))["tempo_resposta"].mean() / 60
                datasets_tr.append({
                    "label": turno,
                    "data": [round(float(serie[k]), 2)
                             if k in serie.index and pd.notna(serie[k])
                             else None for k in chaves],
                    "color": COR_TURNO[turno]})
            charts.append({"tipo": "line",
                           "titulo": f"Tempo de Resposta — média {eixo} por plantão (min)",
                           "labels": rotulos_x, "datasets": datasets_tr,
                           "unidade_y": "min"})

            # Mesma evolução, aberta pelos 14 plantões (dia × turno):
            # cor por dia da semana; diurno sólido, noturno tracejado.
            cores_dia = {"Segunda": "#0d6efd", "Terça": "#dc3545",
                         "Quarta": "#198754", "Quinta": "#fd7e14",
                         "Sexta": "#6f42c1", "Sábado": "#20c997",
                         "Domingo": "#d63384"}
            datasets_dow = []
            for plantao in plantoes:
                dia, turno = plantao.rsplit(" ", 1)
                base_d = tr_valido[tr_valido["plantao"] == plantao]
                if eixo == "semanal":
                    serie = base_d.groupby("semana_iso")["tempo_resposta"].mean() / 60
                else:
                    com_data = base_d[base_d["dt_ocorr"].notna()]
                    serie = com_data.groupby(
                        com_data["dt_ocorr"].dt.to_period("M"))["tempo_resposta"].mean() / 60
                ds = {"label": plantao,
                      "data": [round(float(serie[k]), 2)
                               if k in serie.index and pd.notna(serie[k])
                               else None for k in chaves],
                      "color": cores_dia[dia]}
                if turno == "Noturno":
                    ds["dash"] = [6, 4]
                datasets_dow.append(ds)
            charts.append({"tipo": "line",
                           "titulo": f"Tempo de Resposta — média {eixo} por dia da "
                                     "semana e plantão (min) — noturno tracejado",
                           "labels": rotulos_x, "datasets": datasets_dow,
                           "unidade_y": "min"})

        # Volume por dia da semana do plantão (dois turnos lado a lado)
        datasets_dia = []
        for turno in ("Diurno", "Noturno"):
            serie = df[df["turno"] == turno].groupby("plantao_dia_semana").size()
            datasets_dia.append({"label": turno,
                                 "data": [int(serie.get(d, 0))
                                          for d in dias_ordem],
                                 "color": COR_TURNO[turno]})
        charts.append({"tipo": "bar",
                       "titulo": "Volume por dia da semana do plantão",
                       "labels": dias_ordem, "datasets": datasets_dia})

        # Volume por hora do dia (fronteiras dos plantões às 07h e 19h)
        por_hora = df.groupby("hora").size()
        charts.append({"tipo": "bar", "titulo": "Volume por hora do dia",
                       "labels": [f"{h:02d}h" for h in range(24)],
                       "datasets": [{"label": "Ocorrências",
                                     "data": [int(por_hora.get(h, 0))
                                              for h in range(24)],
                                     "colors": [COR_TURNO["Diurno"]
                                                if 7 <= h <= 18 else
                                                COR_TURNO["Noturno"]
                                                for h in range(24)]}]})

        # Tempos médios pelos 14 plantões da semana
        for col, rotulo in metricas:
            cap = CAP_TEMPO.get(col, 14400)
            base = df[(df[col] > 0) & (df[col] < cap)]
            grupo = base.groupby("plantao")[col].agg(["mean", "count"])
            charts.append({
                "tipo": "bar",
                "titulo": f"{rotulo} por plantão (média em min)",
                "labels": [f"{p} (n={int(grupo.loc[p, 'count'])})"
                           if p in grupo.index else p for p in plantoes],
                "datasets": [{"label": "Média (min)",
                              "data": [round(float(grupo.loc[p, "mean"]) / 60, 2)
                                       if p in grupo.index else None
                                       for p in plantoes],
                              "colors": [COR_TURNO[p.split()[-1]]
                                         for p in plantoes]}],
                "horizontal": True, "unidade_y": "min",
                "height": max(240, 20 * len(plantoes) + 60)})

        # Tabela: os 14 plantões com volume e tempos médios
        extras = [("t_p1", "P1"), ("t_p4_1", "P4.1"), ("t_p9", "P9")]
        medias = {}
        for col, _ in metricas + extras:
            cap = CAP_TEMPO.get(col, 14400)
            base = df[(df[col] > 0) & (df[col] < cap)]
            medias[col] = base.groupby("plantao")[col].mean()
        volume = df.groupby("plantao").size()
        linhas = []
        for p in plantoes:
            linha = [p, int(volume.get(p, 0))]
            for col, _ in metricas + extras:
                v = medias[col].get(p)
                linha.append(self._hms(v) if v is not None and pd.notna(v)
                             else "--:--")
            linhas.append(linha)
        return {
            "kpis": kpis, "charts": charts,
            "tables": [{"titulo": "Indicadores por plantão",
                        "colunas": ["Plantão", "Ocorrências",
                                    "T. Central", "T. Resposta", "T. Cena",
                                    "P1", "P4.1 Saída", "P9 Transf."],
                        "linhas": linhas}],
        }

    def tema_desperdicio(self, df: pd.DataFrame) -> dict:
        """Desperdício operacional (definição curada do projeto Desperdicio):
        universo = saídas efetivas (início de deslocamento), excluindo
        motivos PCG3/PCC3; candidato = situação em SITUACOES_DESPERDICIO;
        REAL = chegou ao local · EVITADO = cancelada no trajeto."""
        motivo_cod = df["motivo"].fillna("").str.split(" ").str[0].str.upper()
        universo = df[df["dt_inicio_deslocamento"].notna()
                      & ~motivo_cod.isin(MOTIVOS_EXCLUIDOS_DESPERDICIO)]
        sit = universo["situacao_atendimento"].fillna("").map(nucleo.norm_txt)
        cand = sit.isin(SITUACOES_DESPERDICIO)
        chegou = universo["dt_chegada_no_local"].notna()
        real = cand & chegou
        evitado = cand & ~chegou
        n_u = len(universo) or 1

        kpis = [
            {"label": "Saídas no universo", "valor": str(len(universo)),
             "sub": "com deslocamento, sem PCG3/PCC3"},
            {"label": "Desperdício real", "valor": str(int(real.sum())),
             "sub": f"{real.sum() / n_u * 100:.1f}% das saídas — chegou ao local"},
            {"label": "Desperdício evitado", "valor": str(int(evitado.sum())),
             "sub": f"{evitado.sum() / n_u * 100:.1f}% — cancelada no trajeto"},
            {"label": "Total candidatos", "valor": str(int(cand.sum())),
             "sub": f"{cand.sum() / n_u * 100:.1f}% (real + evitado)"},
        ]

        # --- séries temporais: % real e % evitado -------------------------
        def _serie_pct(eixo_col, chaves, rotulos_x, titulo):
            datasets = []
            for rot, mask, cor in (("Real (chegou ao local)", real, "#dc3545"),
                                   ("Evitado (cancelada no trajeto)", evitado,
                                    "#198754")):
                dados_s = []
                for k in chaves:
                    grupo_mask = eixo_col == k
                    total = int(grupo_mask.sum())
                    dados_s.append(round(int((mask & grupo_mask).sum())
                                         / total * 100, 1) if total else None)
                datasets.append({"label": rot, "data": dados_s, "color": cor})
            return {"tipo": "line", "titulo": titulo, "labels": rotulos_x,
                    "datasets": datasets}

        semanas = sorted(universo["semana_iso"].dropna().unique())
        meses_col = universo["dt_ocorr"].dt.to_period("M")
        meses = sorted(meses_col.dropna().unique())
        charts = [
            _serie_pct(universo["semana_iso"], semanas, list(semanas),
                       "% de desperdício por semana (sobre as saídas)"),
            _serie_pct(meses_col, meses,
                       [m.strftime("%m/%Y") for m in meses],
                       "% de desperdício por mês (sobre as saídas)"),
        ]

        # --- composição por situação (real × evitado) ----------------------
        sits = sorted(sit[cand].unique())
        charts.append({
            "tipo": "bar", "titulo": "Composição por situação",
            "labels": [s.title() for s in sits],
            "datasets": [
                {"label": "Real",
                 "data": [int((sit.eq(s) & real).sum()) for s in sits],
                 "color": "#dc3545"},
                {"label": "Evitado",
                 "data": [int((sit.eq(s) & evitado).sum()) for s in sits],
                 "color": "#198754"},
            ], "horizontal": True})

        # --- % de desperdício real por dimensão ----------------------------
        def _pct_por(col, titulo, horizontal=True):
            base = universo[universo[col].notna() & universo[col].ne("")]
            grupo = pd.DataFrame({
                "saidas": base.groupby(col).size(),
                "reais": base[real[base.index]].groupby(col).size(),
            }).fillna(0)
            grupo["pct"] = grupo["reais"] / grupo["saidas"] * 100
            grupo = grupo.sort_values("pct", ascending=False)
            spec = {"tipo": "bar",
                    "titulo": f"{titulo} — % de desperdício real, do pior ao melhor",
                    "labels": [f"{cat} (n={int(r['saidas'])})"
                               for cat, r in grupo.iterrows()],
                    "datasets": [{"label": "% desperdício real",
                                  "data": [round(x, 1) for x in grupo["pct"]]}],
                    "horizontal": horizontal}
            if horizontal and len(grupo) > 12:
                spec["height"] = max(240, 20 * len(grupo) + 60)
            return spec

        charts += [
            _pct_por("unidade_curta", "Por unidade"),
            _pct_por("cidade", "Por cidade"),
            _pct_por("micro_regiao", "Por micro região"),
            _pct_por("recurso", "Por tipo de transporte (USA/USB)",
                     horizontal=False),
            _pct_por("regulador_nome", "Por regulador"),
            _pct_por("tipo", "Por tipo", horizontal=False),
        ]

        # --- Pareto de motivos dos desperdícios reais (80/20) --------------
        motivos = universo[real]["motivo"].dropna().value_counts()
        total_m = int(motivos.sum()) or 1
        acumulado, pareto = 0, []
        for motivo, qtd in motivos.items():
            acumulado += int(qtd)
            pareto.append((motivo, int(qtd)))
            if acumulado / total_m >= 0.8:
                break
        spec_pareto = {
            "tipo": "bar",
            "titulo": "Pareto de motivos do desperdício real (até 80% acumulado)",
            "labels": [f"{m} " for m, _ in pareto],
            "datasets": [{"label": "Ocorrências",
                          "data": [q for _, q in pareto]}],
            "horizontal": True}
        if len(pareto) > 12:
            spec_pareto["height"] = max(240, 20 * len(pareto) + 60)
        charts.append(spec_pareto)

        # --- tabelas --------------------------------------------------------
        linhas_sit = []
        for s in sits:
            n_real = int((sit.eq(s) & real).sum())
            n_evit = int((sit.eq(s) & evitado).sum())
            linhas_sit.append([s.title(), n_real, n_evit, n_real + n_evit,
                               f"{(n_real + n_evit) / n_u * 100:.2f}%"])
        criterio = [[s.title()] for s in sorted(SITUACOES_DESPERDICIO)]
        return {"kpis": kpis, "charts": charts, "tables": [
            {"titulo": "Real × evitado por situação",
             "colunas": ["Situação", "Real", "Evitado", "Total", "% das saídas"],
             "linhas": linhas_sit},
            {"titulo": "Critério — situações consideradas desperdício "
                       "(exclui 'Atendimento no local'; motivos PCG3/PCC3 fora do universo)",
             "colunas": ["Situação"], "linhas": criterio},
        ]}

    def tema_apoio(self, df: pd.DataFrame) -> dict:
        """Comparecimentos de cada apoio (PM, Bombeiros, USA) por período e
        por dimensão — três datasets por gráfico, cores fixas por apoio."""
        apoios = [("apoio_policia_militar", "Polícia Militar", "#0d6efd"),
                  ("apoio_bombeiros", "Bombeiros", "#dc3545"),
                  ("apoio_usa", "USA (escalonamento)", "#198754")]
        masks = {rotulo: df[col].fillna("").map(nucleo.norm_txt).eq("COMPARECEU")
                 for col, rotulo, _ in apoios}
        cores_ds = {rotulo: cor for _, rotulo, cor in apoios}

        kpis = [{"label": rotulo, "valor": str(int(masks[rotulo].sum())),
                 "sub": f"{masks[rotulo].mean() * 100:.2f}% compareceu"}
                for _, rotulo, _ in apoios]

        def _apoio_serie(chaves: list, grupo_de) -> list[dict]:
            datasets = []
            for _, rotulo, cor in apoios:
                serie = grupo_de(df[masks[rotulo]])
                datasets.append({"label": rotulo,
                                 "data": [int(serie.get(k, 0)) for k in chaves],
                                 "color": cor})
            return datasets

        dias = sorted(df["dia"].dropna().unique())
        semanas = sorted(df["semana_iso"].dropna().unique())
        meses = sorted(df[df["dt_ocorr"].notna()]["dt_ocorr"]
                       .dt.to_period("M").unique())

        def _apoio_por(col_cat: str, titulo: str,
                       horizontal: bool = True) -> dict:
            series = {}
            for _, rotulo, _ in apoios:
                base = df[masks[rotulo] & df[col_cat].notna() & df[col_cat].ne("")]
                series[rotulo] = base.groupby(col_cat).size()
            tab = pd.DataFrame(series).fillna(0)
            tab = tab.assign(total=tab.sum(axis=1))
            tab = tab[tab["total"] > 0].sort_values("total", ascending=False)
            spec = {"tipo": "bar", "titulo": titulo,
                    "labels": [f"{cat} (n={int(r['total'])})"
                               for cat, r in tab.iterrows()],
                    "datasets": [{"label": rotulo,
                                  "data": [int(x) for x in tab[rotulo]],
                                  "color": cores_ds[rotulo]}
                                 for _, rotulo, _ in apoios],
                    "horizontal": horizontal}
            if horizontal and len(tab) > 12:
                spec["height"] = max(240, 22 * len(tab) + 60)
            return spec

        charts = [
            {"tipo": "line", "titulo": "Comparecimentos por dia",
             "labels": [d.strftime("%d/%m") for d in dias],
             "datasets": _apoio_serie(dias, lambda b: b.groupby("dia").size())},
            {"tipo": "line", "titulo": "Comparecimentos por semana",
             "labels": semanas,
             "datasets": _apoio_serie(
                 semanas, lambda b: b.groupby("semana_iso").size())},
            {"tipo": "line", "titulo": "Comparecimentos por mês",
             "labels": [m.strftime("%m/%Y") for m in meses],
             "datasets": _apoio_serie(
                 meses, lambda b: b[b["dt_ocorr"].notna()].groupby(
                     b[b["dt_ocorr"].notna()]["dt_ocorr"].dt.to_period("M")).size())},
            _apoio_por("tipo", "Comparecimentos por tipo", horizontal=False),
            _apoio_por("motivo", "Comparecimentos por motivo"),
            _apoio_por("codigo_da_ocorrencia",
                       "Comparecimentos por código da ocorrência"),
            _apoio_por("micro_regiao", "Comparecimentos por micro região"),
            _apoio_por("cidade", "Comparecimentos por cidade"),
        ]
        for col, rotulo, _ in apoios:
            charts.append(self._pizza(df, col, f"Apoio {rotulo}"))

        return {"kpis": kpis, "charts": charts,
                "tables": [self._tabela_contagem(
                    df[masks["USA (escalonamento)"]],
                    "motivo", "Motivos com escalonamento USA", "Motivo",
                    top=15)]}

    def _tema_profissional(self, df: pd.DataFrame, spec: dict,
                           filtros: dict | None = None) -> dict:
        """Dashboard de um papel profissional: indicadores gerais (KPIs sobre
        o papel inteiro) e individuais — restritos aos profissionais
        selecionados no filtro, quando houver seleção."""
        nome_col = f"{spec['col']}_nome"
        rotulo = spec["rotulo"]
        base = df[df[nome_col].notna()]
        kpis, charts = [], []

        opcoes_prof = sorted(base[nome_col].dropna().unique())
        selecao = filtros.get("profissional") if filtros else []
        if isinstance(selecao, str):
            selecao = [selecao]
        selecionados = [p for p in (selecao or []) if p in opcoes_prof]
        # Indicadores individuais usam só a seleção (ou todos, se vazia)
        base_ind = base[base[nome_col].isin(selecionados)] if selecionados else base

        kpis.append({"label": f"Profissionais distintos ({rotulo})",
                     "valor": str(base[nome_col].nunique()),
                     "sub": f"{len(base)} registros (volume)"})

        # --- tempos específicos do papel (gerais) --------------------------
        for tempo in spec["tempos"]:
            v = self._validos(base, tempo)
            kpis.append({"label": f"{ROTULO_TEMPO[tempo]} — média",
                         "valor": self._hms(v.mean()) if len(v) else "--:--",
                         "sub": f"n = {len(v)}"})
        if spec["tempo_resposta"]:
            v = self._validos(base, "tempo_resposta")
            kpis.append({"label": "Tempo de Resposta — média",
                         "valor": self._hms(v.mean()) if len(v) else "--:--",
                         "sub": f"n = {len(v)}"})

        # --- % envio para RO (regulador) -----------------------------------
        if spec["envio_ro"]:
            enviados = base["controlador"].notna()
            kpis.append({"label": "% envio para Controlador",
                         "valor": f"{enviados.mean() * 100:.1f}%",
                         "sub": f"{int(enviados.sum())}/{len(base)} regulações"})

        # --- SLA de P1 (TARM): % ≤ 1,5 min ---------------------------------
        if spec.get("sla_p1"):
            p1 = self._validos(base, "t_p1")
            kpis.append({"label": "SLA P1 ≤ 1:30",
                         "valor": f"{(p1 <= SLA_P1).mean() * 100:.1f}%"
                         if len(p1) else "--",
                         "sub": f"{int((p1 <= SLA_P1).sum())}/{len(p1)} dentro do SLA"})

        # --- desperdício (definição curada) no recorte do papel ------------
        tem_desperdicio = spec.get("desperdicio", False)
        desp_real = desp_evitado = None
        if tem_desperdicio:
            motivo_cod_b = base["motivo"].fillna("").str.split(" ").str[0].str.upper()
            univ_mask = (base["dt_inicio_deslocamento"].notna()
                         & ~motivo_cod_b.isin(MOTIVOS_EXCLUIDOS_DESPERDICIO))
            sit_b = base["situacao_atendimento"].fillna("").map(nucleo.norm_txt)
            cand_b = univ_mask & sit_b.isin(SITUACOES_DESPERDICIO)
            desp_real = cand_b & base["dt_chegada_no_local"].notna()
            desp_evitado = cand_b & base["dt_chegada_no_local"].isna()
            n_univ = int(univ_mask.sum()) or 1
            kpis.append({"label": "Desperdício real",
                         "valor": f"{desp_real.sum() / n_univ * 100:.1f}%",
                         "sub": f"{int(desp_real.sum())}/{n_univ} saídas"})
            kpis.append({"label": "Desperdício evitado",
                         "valor": f"{desp_evitado.sum() / n_univ * 100:.1f}%",
                         "sub": f"{int(desp_evitado.sum())} canceladas no trajeto"})

        # --- assertividade geral do papel ----------------------------------
        tem_assert = spec.get("assertividade", True)
        aph = base[(base["transporte"] == "Pré-hospitalar")
                   & base["codigo_cor"].isin(ADEQUACAO)
                   & base["risco_cor"].notna()]
        adequado = pd.Series(False, index=aph.index)
        for cor, riscos in ADEQUACAO.items():
            adequado |= (aph["codigo_cor"] == cor) & aph["risco_cor"].isin(riscos)
        if tem_assert and len(aph):
            kpis.append({"label": "Assertividade",
                         "valor": f"{adequado.mean() * 100:.1f}%",
                         "sub": f"base APH com risco: {len(aph)}"})

        # --- gráficos: séries temporais (semana e mês) por indicador -------
        # Um dataset por profissional selecionado; sem seleção, a linha
        # "Geral" do papel inteiro.
        sufixo = " (seleção)" if selecionados else " (geral)"
        grupos = ([(n, base[base[nome_col] == n]) for n in selecionados]
                  if selecionados else [("Geral", base)])

        semanas = sorted(base["semana_iso"].dropna().unique())
        meses = sorted(base[base["dt_ocorr"].notna()]["dt_ocorr"]
                       .dt.to_period("M").unique())

        def _grupo_mes(dfx):
            m = dfx[dfx["dt_ocorr"].notna()]
            return m.groupby(m["dt_ocorr"].dt.to_period("M"))

        def _par_temporal(titulo, valor_fn, unidade=None, max_y=None,
                          zero=False) -> list[dict]:
            """Par de gráficos de linha (por semana e por mês)."""
            pares = [("semana", semanas, list(semanas)),
                     ("mês", meses, [m.strftime("%m/%Y") for m in meses])]
            specs = []
            for eixo, chaves, rotulos_x in pares:
                datasets = []
                for rot, dfg in grupos:
                    serie = valor_fn(dfg, eixo)
                    dados_ds = []
                    for k in chaves:
                        if zero:
                            dados_ds.append(int(serie.get(k, 0)))
                        elif k in serie.index and pd.notna(serie[k]):
                            dados_ds.append(round(float(serie[k]), 2))
                        else:
                            dados_ds.append(None)
                    datasets.append({"label": rot, "data": dados_ds})
                spec_c = {"tipo": "line",
                          "titulo": f"{titulo} por {eixo}{sufixo}",
                          "labels": rotulos_x, "datasets": datasets}
                if unidade:
                    spec_c["unidade_y"] = unidade
                if max_y:
                    spec_c["max_y"] = max_y
                specs.append(spec_c)
            return specs

        def _fn_volume(dfg, eixo):
            return (dfg.groupby("semana_iso").size() if eixo == "semana"
                    else _grupo_mes(dfg).size())

        def _fn_tempo(col):
            cap = CAP_TEMPO.get(col, 14400)

            def fn(dfg, eixo):
                v = dfg[(dfg[col] > 0) & (dfg[col] < cap)]
                g = (v.groupby("semana_iso")[col] if eixo == "semana"
                     else _grupo_mes(v)[col])
                return g.mean() / 60
            return fn

        charts += _par_temporal("Volume", _fn_volume, zero=True)
        for tempo in spec["tempos"]:
            charts += _par_temporal(ROTULO_TEMPO[tempo], _fn_tempo(tempo),
                                    unidade="min")
        if spec["tempo_resposta"]:
            charts += _par_temporal("Tempo de Resposta",
                                    _fn_tempo("tempo_resposta"), unidade="min")

        if spec.get("sla_p1"):
            cap_p1 = CAP_TEMPO.get("t_p1", 3600)

            def _fn_sla(dfg, eixo):
                v = dfg[(dfg["t_p1"] > 0) & (dfg["t_p1"] < cap_p1)]
                v = v.assign(dentro=v["t_p1"] <= SLA_P1)
                g = (v.groupby("semana_iso")["dentro"] if eixo == "semana"
                     else _grupo_mes(v)["dentro"])
                return g.mean() * 100
            charts += _par_temporal("SLA P1 ≤ 1:30 (%)", _fn_sla, max_y=100)

        if spec["envio_ro"]:
            def _fn_envio(dfg, eixo):
                e = dfg.assign(env=dfg["controlador"].notna())
                g = (e.groupby("semana_iso")["env"] if eixo == "semana"
                     else _grupo_mes(e)["env"])
                return g.mean() * 100
            charts += _par_temporal("% envio para Controlador", _fn_envio,
                                    max_y=100)

        if tem_desperdicio:
            def _fn_desp(flags):
                def fn(dfg, eixo):
                    # % sobre as saídas do universo (com deslocamento,
                    # sem PCG3/PCC3) daquele período
                    univ = dfg[univ_mask[dfg.index]]
                    univ = univ.assign(flag=flags[univ.index])
                    g = (univ.groupby("semana_iso")["flag"] if eixo == "semana"
                         else _grupo_mes(univ)["flag"])
                    return g.mean() * 100
                return fn
            charts += _par_temporal("% desperdício real",
                                    _fn_desp(desp_real), max_y=100)
            charts += _par_temporal("% desperdício evitado",
                                    _fn_desp(desp_evitado), max_y=100)
            # Composição do desperdício por situação (real × evitado)
            idx_sel = base_ind.index
            real_sel = desp_real[idx_sel]
            evit_sel = desp_evitado[idx_sel]
            sit_sel = sit_b[idx_sel]
            sits = sorted(sit_sel[real_sel | evit_sel].unique())
            if sits:
                charts.append({
                    "tipo": "bar",
                    "titulo": "Desperdício por situação"
                              f" nos registros de {rotulo.lower()}{sufixo}",
                    "labels": [s.title() for s in sits],
                    "datasets": [
                        {"label": "Real (chegou ao local)",
                         "data": [int((sit_sel.eq(s) & real_sel).sum())
                                  for s in sits],
                         "color": "#dc3545"},
                        {"label": "Evitado (cancelada no trajeto)",
                         "data": [int((sit_sel.eq(s) & evit_sel).sum())
                                  for s in sits],
                         "color": "#198754"},
                    ], "horizontal": True})

        aph_ind = aph[aph[nome_col].isin(selecionados)] if selecionados else aph
        adequado_ind = adequado[aph_ind.index]
        if tem_assert and len(aph):
            aph_ok = aph.assign(ok=adequado)

            def _fn_assert(dfg, eixo):
                sub = aph_ok[aph_ok.index.isin(dfg.index)]
                g = (sub.groupby("semana_iso")["ok"] if eixo == "semana"
                     else _grupo_mes(sub)["ok"])
                return g.mean() * 100
            charts += _par_temporal("Assertividade", _fn_assert, max_y=100)

        if spec.get("codigo", True):
            charts.append(self._bar_percentual(
                base_ind, "codigo_da_ocorrencia",
                f"Código da ocorrência nos registros de {rotulo.lower()}{sufixo}"))
        if spec.get("situacao"):
            charts.append(self._bar_percentual(
                base_ind, "situacao_atendimento",
                f"Situação atendimento nos registros de {rotulo.lower()}{sufixo}"))

        # --- tabela: indicadores individuais por profissional ---------------
        vol = base_ind.groupby(nome_col).size().sort_values(ascending=False)
        medias_tempo = {}
        tempos_tab = list(spec["tempos"])
        if spec["tempo_resposta"]:
            tempos_tab.append("tempo_resposta")
        for tempo in tempos_tab:
            cap = CAP_TEMPO.get(tempo, 14400)
            vt = base_ind[(base_ind[tempo] > 0) & (base_ind[tempo] < cap)]
            medias_tempo[tempo] = vt.groupby(nome_col)[tempo].mean()
        envio_prof = base_ind.assign(env=base_ind["controlador"].notna()) \
            .groupby(nome_col)["env"].mean() if spec["envio_ro"] else None
        assert_prof = aph_ind.assign(ok=adequado_ind) \
            .groupby(nome_col)["ok"].agg(["mean", "count"]) if len(aph_ind) else None

        colunas = ["Profissional", "Registros"] + \
                  [ROTULO_TEMPO[t] for t in tempos_tab]
        desp_prof = None
        if tem_desperdicio:
            univ_ind = base_ind[univ_mask[base_ind.index]]
            desp_prof = univ_ind.assign(
                real=desp_real[univ_ind.index],
                evitado=desp_evitado[univ_ind.index],
            ).groupby(nome_col)[["real", "evitado"]].agg(["mean", "count"])

        if spec["envio_ro"]:
            colunas.append("% envio RO")
        if tem_assert:
            colunas.append("Assertividade")
        if tem_desperdicio:
            colunas += ["Desp. real", "Desp. evitado"]
        linhas = []
        for nome, qtd in vol.head(50).items():
            linha = [nome, int(qtd)]
            for tempo in tempos_tab:
                media = medias_tempo[tempo].get(nome)
                linha.append(self._hms(media) if media is not None
                             and pd.notna(media) else "--:--")
            if spec["envio_ro"]:
                env = envio_prof.get(nome) if envio_prof is not None else None
                linha.append(f"{env * 100:.1f}%" if env is not None
                             and pd.notna(env) else "--")
            if tem_assert:
                if assert_prof is not None and nome in assert_prof.index:
                    r = assert_prof.loc[nome]
                    linha.append(f"{r['mean'] * 100:.1f}% (n={int(r['count'])})")
                else:
                    linha.append("--")
            if tem_desperdicio:
                if desp_prof is not None and nome in desp_prof.index:
                    r = desp_prof.loc[nome]
                    n_saidas = int(r[("real", "count")])
                    linha.append(f"{r[('real', 'mean')] * 100:.1f}% "
                                 f"(n={n_saidas})")
                    linha.append(f"{r[('evitado', 'mean')] * 100:.1f}%")
                else:
                    linha += ["--", "--"]
            linhas.append(linha)

        titulo_tab = (f"Indicadores individuais — {rotulo.lower()}"
                      + (" selecionados" if selecionados
                         else " (top 50 por volume)"))
        return {"kpis": kpis, "charts": charts,
                "profissionais_opcoes": opcoes_prof,
                "profissionais_selecionados": selecionados,
                "tables": [{"titulo": titulo_tab,
                            "colunas": colunas, "linhas": linhas}]}

    def tema_equipe(self, df: pd.DataFrame) -> dict:
        kpis, charts = [], []
        for col, rotulo in PAPEIS:
            serie = df[f"{col}_nome"].dropna()
            kpis.append({"label": rotulo, "valor": str(serie.nunique()),
                         "sub": f"{len(serie)} registros"})
            # Todos os profissionais do papel — scroll automático (>12 barras)
            charts.append(self._bar_contagem(
                df, f"{col}_nome", f"{rotulo} — volume por profissional",
                top=None))
        return {"kpis": kpis, "charts": charts, "tables": []}
