"""Painel de Gestão (§35.16) — indicadores operacionais executivos.

Formato: seções temáticas com filtros PRÉ-ESTABELECIDOS por indicador.
KPIs = última semana ISO completa (≥6 dias com dados); gráficos de linha =
últimos 12 meses. Consome o núcleo de dados do módulo indicadores.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.modules.indicadores import nucleo
from app.modules.indicadores.constants import (
    ADEQUACAO,
    CAP_TEMPO,
    MOTIVOS_EXCLUIDOS_DESPERDICIO,
    SITUACOES_DESPERDICIO,
)
from app.modules.indicadores.service import _json_safe

CORES_PLANTAO = {"Geral": "#6c757d", "Diurno": "#fd7e14", "Noturno": "#0d6efd"}

# Payload pronto por (empresa, versão dos dados)
_cache_painel: dict[tuple, dict] = {}


def _mmss(segundos) -> str:
    if segundos is None or pd.isna(segundos):
        return "--:--"
    s = int(round(segundos))
    return f"{s // 60:02d}:{s % 60:02d}"


class PainelGestaoService:
    def __init__(self, empresa_id: int = 1):
        self.empresa_id = empresa_id

    def montar(self) -> dict:
        chave = (self.empresa_id, nucleo.marca_cache(self.empresa_id))
        pronto = _cache_painel.get(chave)
        if pronto is not None:
            return pronto

        df = nucleo.carregar(self.empresa_id)
        if df.empty:
            return {"semana": None, "secoes": [], "charts_flat": []}
        dados = _json_safe(self._montar(df))
        if len(_cache_painel) > 8:
            _cache_painel.clear()
        _cache_painel[chave] = dados
        return dados

    def _montar(self, df: pd.DataFrame) -> dict:
        cores3 = ["vermelho", "amarelo", "verde"]

        # --- janelas ------------------------------------------------------
        # Última semana COMPLETA: 7 dias com dados (tolera 6 se nenhuma
        # semana tiver os 7 — ex.: falha de importação em um dia).
        dias_por_semana = df.groupby("semana_iso")["dia"].nunique()
        completas = sorted(dias_por_semana[dias_por_semana >= 7].index)
        if not completas:
            completas = sorted(dias_por_semana[dias_por_semana >= 6].index)
        semanas = sorted(df["semana_iso"].dropna().unique())
        sem_ult = completas[-1] if completas else (semanas[-1] if semanas else None)
        semana_periodo = None
        if sem_ult:
            ano_iso, num_iso = sem_ult.split("-S")
            segunda = date.fromisocalendar(int(ano_iso), int(num_iso), 1)
            domingo = date.fromisocalendar(int(ano_iso), int(num_iso), 7)
            semana_periodo = (f"{segunda.strftime('%d/%m/%Y')} a "
                              f"{domingo.strftime('%d/%m/%Y')}")
        meses = sorted(df[df["dt_ocorr"].notna()]["dt_ocorr"]
                       .dt.to_period("M").unique())[-12:]
        rot_meses = [m.strftime("%m/%Y") for m in meses]
        mes_de = df["dt_ocorr"].dt.to_period("M")
        df12 = df[mes_de.isin(meses)]

        def ult_semana(dfx):
            return dfx[dfx["semana_iso"] == sem_ult] if sem_ult else dfx.iloc[0:0]

        cap_tr = CAP_TEMPO["tempo_resposta"]

        def tr_validos(dfx):
            return dfx["tempo_resposta"][(dfx["tempo_resposta"] > 0)
                                         & (dfx["tempo_resposta"] < cap_tr)]

        def linha_mensal_tr(base, titulo):
            base12 = base[base["dt_ocorr"].dt.to_period("M").isin(meses)]
            datasets = []
            for turno in ("Geral", "Diurno", "Noturno"):
                sub = base12 if turno == "Geral" else \
                    base12[base12["turno"] == turno]
                v = sub[(sub["tempo_resposta"] > 0)
                        & (sub["tempo_resposta"] < cap_tr)]
                serie = v.groupby(v["dt_ocorr"].dt.to_period("M")
                                  )["tempo_resposta"].mean() / 60
                datasets.append({"label": turno,
                                 "data": [round(float(serie[m]), 2)
                                          if m in serie.index else None
                                          for m in meses],
                                 "color": CORES_PLANTAO[turno]})
            return {"tipo": "line", "titulo": titulo, "labels": rot_meses,
                    "datasets": datasets, "unidade_y": "min"}

        def bar_percentual(dfx, col, titulo):
            vc = dfx[col].dropna().value_counts()
            total = int(vc.sum()) or 1
            spec = {"tipo": "bar", "titulo": f"{titulo} — % dos registros",
                    "labels": [f"{v} (n={int(q)})" for v, q in vc.items()],
                    "datasets": [{"label": "% dos registros",
                                  "data": [round(q / total * 100, 1) for q in vc]}],
                    "horizontal": True}
            if len(vc) > 12:
                spec["height"] = max(240, 20 * len(vc) + 60)
            return spec

        secoes: list[dict] = []

        # ---------------- Tempo Resposta -----------------------------------
        # Somente transporte Pré-hospitalar, nas unidades do convênio
        # (viaturas ISCMV) e cidades do Convênio; KPI único = média da
        # última semana (o recorte por plantão fica nas linhas
        # Geral/Diurno/Noturno do gráfico).
        conv = df[df["convenio"] & df["iscmv"]
                  & (df["transporte"] == "Pré-hospitalar")]
        bases_tr = [
            ("Convênio Verde/Amarelo/Vermelho",
             conv[conv["codigo_cor"].isin(cores3)], True),
            ("USA Vermelho", conv[(conv["codigo_cor"] == "vermelho")
                                  & (conv["recurso"] == "USA")], False),
            ("USB Vermelho", conv[(conv["codigo_cor"] == "vermelho")
                                  & (conv["recurso"] == "USB")], False),
        ]
        blocos_tr = []
        for rotulo, base, largura_total in bases_tr:
            v = tr_validos(ult_semana(base))
            blocos_tr.append({
                "kpis": [{"label": "Última semana",
                          "valor": _mmss(v.mean()) if len(v) else "--:--",
                          "sub": f"semana {sem_ult} · n = {len(v)}"}],
                "chart": linha_mensal_tr(base, f"{rotulo} (12 meses)"),
                "largura_total": largura_total})
        secoes.append({"id": "tr", "titulo": "Tempo Resposta",
                       "icone": "fa-stopwatch", "cor": "primary",
                       "nota": "1ª ambulância a chegar · Pré-hospitalar · "
                               "unidades do convênio (ISCMV) em Vitória, "
                               "Vila Velha, Serra e Cariacica",
                       "blocos": blocos_tr})

        # ---------------- Assertividade ISCMV ------------------------------
        base_a = df[(df["transporte"] == "Pré-hospitalar") & df["iscmv"]
                    & df["codigo_cor"].isin(ADEQUACAO)
                    & df["risco_cor"].notna()]
        ok = pd.Series(False, index=base_a.index)
        for cor, riscos in ADEQUACAO.items():
            ok |= (base_a["codigo_cor"] == cor) & base_a["risco_cor"].isin(riscos)
        base_a = base_a.assign(adequado=ok)
        sem_a = ult_semana(base_a)
        base_a12 = base_a[base_a["dt_ocorr"].dt.to_period("M").isin(meses)]
        serie_a = base_a12.groupby(
            base_a12["dt_ocorr"].dt.to_period("M"))["adequado"].mean() * 100
        # Assertividade por código na última semana (barras)
        cores_codigo = {"vermelho": ("Vermelho", "#dc3545"),
                        "amarelo": ("Amarelo", "#ffc107"),
                        "verde": ("Verde", "#198754")}
        labels_cod, dados_cod, hex_cod = [], [], []
        for cor, (rotulo_c, hexa) in cores_codigo.items():
            grupo = sem_a[sem_a["codigo_cor"] == cor]
            pct = grupo["adequado"].mean() * 100 if len(grupo) else None
            labels_cod.append(f"{rotulo_c} (n={len(grupo)})")
            dados_cod.append(round(float(pct), 1) if pct is not None else None)
            hex_cod.append(hexa)
        secoes.append({
            "id": "assertividade", "titulo": "Assertividade ISCMV",
            "icone": "fa-bullseye", "cor": "success",
            "nota": "código da equipe × risco da triagem — base APH nas "
                    "viaturas do núcleo",
            "blocos": [
                {"kpis": [{"label": "Última semana",
                           "valor": f"{sem_a['adequado'].mean() * 100:.1f}%"
                           if len(sem_a) else "--",
                           "sub": f"semana {sem_ult} · n = {len(sem_a)}"}],
                 "chart": {"tipo": "line",
                           "titulo": "Assertividade ISCMV (12 meses, %)",
                           "labels": rot_meses,
                           "datasets": [{"label": "% adequado",
                                         "data": [round(float(serie_a[m]), 1)
                                                  if m in serie_a.index else None
                                                  for m in meses],
                                         "color": "#198754"}],
                           "max_y": 100}},
                {"kpis": [],
                 "chart": {"tipo": "bar",
                           "titulo": "Assertividade por código — última semana (%)",
                           "labels": labels_cod,
                           "datasets": [{"label": "% adequado",
                                         "data": dados_cod,
                                         "colors": hex_cod}],
                           "max_y": 100}},
            ]})

        # ---------------- Transferência inter-hospitalar ISCMV -------------
        inter = df[df["iscmv"] & (df["transporte"] == "Inter-hospitalar")]
        sem_i = ult_semana(inter)
        v_tr_i = tr_validos(sem_i)
        inter12 = inter[inter["dt_ocorr"].dt.to_period("M").isin(meses)]
        datasets_vol = []
        for turno in ("Geral", "Diurno", "Noturno"):
            sub = inter12 if turno == "Geral" else \
                inter12[inter12["turno"] == turno]
            serie = sub.groupby(sub["dt_ocorr"].dt.to_period("M")).size()
            datasets_vol.append({"label": turno,
                                 "data": [int(serie.get(m, 0)) for m in meses],
                                 "color": CORES_PLANTAO[turno]})
        secoes.append({
            "id": "transferencia", "titulo": "Transferência Inter-hospitalar (ISCMV)",
            "icone": "fa-route", "cor": "info",
            "nota": "transportes inter-hospitalares das viaturas do núcleo",
            "blocos": [
                {"kpis": [{"label": "Última semana", "valor": str(len(sem_i)),
                           "sub": f"semana {sem_ult} · transferências"}],
                 "chart": {"tipo": "line", "titulo": "Volume mensal (12 meses)",
                           "labels": rot_meses, "datasets": datasets_vol}},
                {"kpis": [{"label": "Última semana",
                           "valor": _mmss(v_tr_i.mean()) if len(v_tr_i) else "--:--",
                           "sub": f"semana {sem_ult} · n = {len(v_tr_i)}"}],
                 "chart": linha_mensal_tr(inter, "Tempo Resposta (12 meses)")},
                {"kpis": [],
                 "chart": bar_percentual(sem_i, "codigo_da_ocorrencia",
                                         "Códigos — última semana")},
                {"kpis": [],
                 "chart": bar_percentual(sem_i, "motivo",
                                         "Motivos — última semana")},
            ]})

        # ---------------- Plantão -------------------------------------------
        # Última semana, do pior para o melhor; os ~20% piores (3 de 14)
        # destacados em vermelho (princípio de Pareto 20/80).
        import math

        base_plantao = df[(df["transporte"] == "Pré-hospitalar")
                          & df["convenio"]
                          & df["codigo_cor"].isin(cores3)]
        v_sem = ult_semana(base_plantao)
        v_sem = v_sem[(v_sem["tempo_resposta"] > 0)
                      & (v_sem["tempo_resposta"] < cap_tr)]
        grupo_p = v_sem.groupby("plantao")["tempo_resposta"] \
                       .agg(["mean", "count"]) \
                       .sort_values("mean", ascending=False)
        n_piores = min(math.ceil(len(grupo_p) * 0.2), len(grupo_p))

        # % de despachos por plantão na última semana: ocorrências com
        # despacho de unidade ÷ ocorrências reguladas (com regulador).
        # Só Pré-hospitalar: as inter-hospitalares saem; registros sem
        # transporte (regulados sem despacho) permanecem no denominador.
        base_vol = ult_semana(df[df["convenio"] & df["ocorrencia"].notna()
                                 & (df["transporte"] != "Inter-hospitalar")])
        reguladas = base_vol[base_vol["regulador"].notna()]
        ocorr_p = reguladas.groupby("plantao")["ocorrencia"].nunique()
        com_unidade = set(
            base_vol[base_vol["unidade"].notna()]["ocorrencia"])
        desp_p = reguladas[reguladas["ocorrencia"].isin(com_unidade)] \
            .groupby("plantao")["ocorrencia"].nunique()
        pct_desp = (desp_p.reindex(ocorr_p.index).fillna(0)
                    / ocorr_p * 100).dropna().sort_values(ascending=False)

        # Assertividade por plantão na última semana (base APH do Convênio)
        base_ap = df[(df["transporte"] == "Pré-hospitalar") & df["convenio"]
                     & df["codigo_cor"].isin(ADEQUACAO)
                     & df["risco_cor"].notna()]
        ok_p = pd.Series(False, index=base_ap.index)
        for cor, riscos in ADEQUACAO.items():
            ok_p |= (base_ap["codigo_cor"] == cor) & base_ap["risco_cor"].isin(riscos)
        assert_sem = ult_semana(base_ap.assign(adequado=ok_p))
        grupo_a = assert_sem.groupby("plantao")["adequado"] \
                            .agg(["mean", "count"]).sort_values("mean")

        secoes.append({
            "id": "plantao", "titulo": "Plantão", "icone": "fa-clock",
            "cor": "warning",
            "nota": "Pré-hospitalar · Convênio (Vitória, Vila Velha, Serra, "
                    "Cariacica) · códigos Verde/Amarelo/Vermelho · diurno "
                    "07:00–18:59, noturno 19:00–06:59 · última semana",
            "blocos": [
                {"kpis": [], "largura_total": True, "chart": {
                    "tipo": "bar",
                    "titulo": "Tempo Resposta por plantão e dia da semana — "
                              f"última semana ({sem_ult}), do pior ao melhor "
                              f"(os {n_piores} piores em vermelho)",
                    "labels": [f"{p} (n={int(r['count'])})"
                               for p, r in grupo_p.iterrows()],
                    "datasets": [{"label": "Média (min)",
                                  "data": [round(float(r["mean"]) / 60, 2)
                                           for _, r in grupo_p.iterrows()],
                                  "colors": ["#dc3545" if i < n_piores
                                             else "#adb5bd"
                                             for i in range(len(grupo_p))]}],
                    "horizontal": True, "unidade_y": "min",
                    "height": max(240, 20 * max(len(grupo_p), 1) + 60)}},
                {"kpis": [], "chart": {
                    "tipo": "bar",
                    "titulo": "% de Despachos por plantão — última semana "
                              f"({sem_ult}) · Pré-hospitalar · despachadas ÷ "
                              "reguladas · do maior para o menor",
                    "labels": [f"{p} (n={int(ocorr_p.get(p, 0))} reguladas)"
                               for p in pct_desp.index],
                    "datasets": [{"label": "% de ocorrências despachadas",
                                  "data": [round(float(v), 1)
                                           for v in pct_desp],
                                  "color": "#0d6efd"}],
                    "horizontal": True, "max_y": 100,
                    "height": max(240, 20 * max(len(pct_desp), 1) + 60)}},
                {"kpis": [], "chart": {
                    "tipo": "bar",
                    "titulo": "Assertividade por plantão — última semana "
                              f"({sem_ult}) · Pré-hospitalar · do pior ao melhor (%)",
                    "labels": [f"{p} (n={int(r['count'])})"
                               for p, r in grupo_a.iterrows()],
                    "datasets": [{"label": "% adequado",
                                  "data": [round(float(r["mean"]) * 100, 1)
                                           for _, r in grupo_a.iterrows()],
                                  "color": "#198754"}],
                    "horizontal": True, "max_y": 100,
                    "height": max(240, 20 * max(len(grupo_a), 1) + 60)}},
            ]})

        # ---------------- Desperdício (todas as saídas) ---------------------
        motivo_cod = df["motivo"].fillna("").str.split(" ").str[0].str.upper()
        universo = df[df["dt_inicio_deslocamento"].notna()
                      & ~motivo_cod.isin(MOTIVOS_EXCLUIDOS_DESPERDICIO)]
        sit = universo["situacao_atendimento"].fillna("").map(nucleo.norm_txt)
        cand = sit.isin(SITUACOES_DESPERDICIO)
        real = cand & universo["dt_chegada_no_local"].notna()
        evitado = cand & universo["dt_chegada_no_local"].isna()
        sem_u = universo["semana_iso"] == sem_ult
        n_sem = int(sem_u.sum()) or 1
        uni12 = universo[universo["dt_ocorr"].dt.to_period("M").isin(meses)]
        mes_u = uni12["dt_ocorr"].dt.to_period("M")
        datasets_d = []
        for rotulo, mask, cor in (("Real", real, "#dc3545"),
                                  ("Evitado", evitado, "#198754")):
            por_mes = uni12.assign(flag=mask[uni12.index]) \
                           .groupby(mes_u)["flag"].mean() * 100
            datasets_d.append({"label": rotulo,
                               "data": [round(float(por_mes[m]), 1)
                                        if m in por_mes.index else None
                                        for m in meses],
                               "color": cor})
        univ_sem = universo[sem_u]
        secoes.append({
            "id": "desperdicio", "titulo": "Desperdício",
            "icone": "fa-recycle", "cor": "danger",
            "nota": "todas as saídas · sem necessidade — real: chegou ao "
                    "local · evitado: cancelada no trajeto",
            "blocos": [
                {"kpis": [
                    {"label": "Real — última semana",
                     "valor": f"{(real & sem_u).sum() / n_sem * 100:.1f}%",
                     "sub": f"semana {sem_ult} · "
                            f"{int((real & sem_u).sum())} saídas"},
                    {"label": "Evitado — última semana",
                     "valor": f"{(evitado & sem_u).sum() / n_sem * 100:.1f}%",
                     "sub": f"semana {sem_ult} · "
                            f"{int((evitado & sem_u).sum())} canceladas"},
                 ],
                 "chart": {"tipo": "line",
                           "titulo": "% real × evitado sobre as saídas (12 meses)",
                           "labels": rot_meses, "datasets": datasets_d}},
                {"kpis": [],
                 "chart": bar_percentual(univ_sem[real[univ_sem.index]],
                                         "motivo",
                                         "Motivos do desperdício real — "
                                         "última semana")},
            ]})

        charts_flat = [b["chart"] for s in secoes for b in s["blocos"]]
        return {"semana": sem_ult, "semana_periodo": semana_periodo,
                "secoes": secoes, "charts_flat": charts_flat}
