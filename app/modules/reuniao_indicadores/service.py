"""Reunião de Indicadores (§35.16) — deck de apresentação para a diretoria.

Foco: evolução SEMANAL ao longo do período inteiro + fotografia da última
semana COMPLETA. Consome o núcleo de dados do módulo indicadores; o deck é
cacheado por versão dos dados.
"""

from __future__ import annotations

import math
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

VERDE = "#2ecc71"
AZUL = "#38bdf8"
LARANJA = "#f5a623"
VERMELHO = "#f4645f"
ROXO = "#a78bfa"
CINZA = "#8b98ab"

ROTULO_SITUACAO = {
    "ATENDIMENTO PRE-HOSPITALAR COM RECUSA DE ENCAMINHAMENTO": "Recusa de encaminhamento",
    "VITIMA SOCORRIDA POR TERCEIROS": "Socorrida por terceiros",
    "SOLITANTE/PACIENTE NAO LOCALIZADO": "Paciente não localizado",
    "RECUSA AO ATENDIMENTO PELA VITIMA OU EVASAO": "Recusa/evasão da vítima",
    "DESISTENCIA DO SOLICITANTE": "Desistência do solicitante",
    "OCORRENCIA ENVIADA POR ENGANO": "Enviada por engano",
}

_cache_deck: dict[tuple, dict] = {}
# ids das ocorrências por elemento de gráfico: "slide:dataset:indice" -> [ids]
_cache_drill: dict[tuple, dict] = {}


def _mmss(segundos) -> str:
    if segundos is None or pd.isna(segundos):
        return "--:--"
    s = int(round(segundos))
    return f"{s // 60:02d}:{s % 60:02d}"


class ReuniaoIndicadoresService:
    def __init__(self, empresa_id: int = 1):
        self.empresa_id = empresa_id

    def montar(self) -> dict:
        chave = (self.empresa_id, nucleo.marca_cache(self.empresa_id))
        pronto = _cache_deck.get(chave)
        if pronto is not None:
            return pronto
        df = nucleo.carregar(self.empresa_id)
        if df.empty:
            return {"titulo": "", "slides": []}
        self._drill = {}
        deck = _json_safe(self._montar(df))
        if len(_cache_deck) > 4:
            _cache_deck.clear()
            _cache_drill.clear()
        _cache_deck[chave] = deck
        _cache_drill[chave] = self._drill
        return deck

    def ids_drill(self, chave_elemento: str) -> list[int]:
        """IDs das ocorrências que compõem um elemento de gráfico."""
        self.montar()  # garante os caches na versão atual dos dados
        chave = (self.empresa_id, nucleo.marca_cache(self.empresa_id))
        return _cache_drill.get(chave, {}).get(chave_elemento, [])

    # ------------------------------------------------------------------
    def _montar(self, df: pd.DataFrame) -> dict:
        cap_tr = CAP_TEMPO["tempo_resposta"]

        # ---- janelas -----------------------------------------------------
        dias_sem = df.groupby("semana_iso")["dia"].nunique()
        completas = sorted(dias_sem[dias_sem >= 7].index) or \
            sorted(dias_sem[dias_sem >= 6].index)
        semanas = sorted(df["semana_iso"].dropna().unique())
        sem_ult = completas[-1] if completas else semanas[-1]
        # séries semanais só até a última completa (sem cauda parcial)
        semanas = [s for s in semanas if s <= sem_ult]
        rot_sem = [str(i + 1) for i in range(len(semanas))]

        ano_iso, num_iso = sem_ult.split("-S")
        seg_ult = date.fromisocalendar(int(ano_iso), int(num_iso), 1)
        sem_data = seg_ult.strftime("%d/%m")

        dt_min, dt_max = df["dt_ocorr"].min(), df["dt_ocorr"].max()
        periodo = (f"{dt_min.strftime('%d/%m/%Y')} a "
                   f"{dt_max.strftime('%d/%m/%Y')}")

        def serie_semanal(base: pd.DataFrame, agrega) -> list:
            grupos = agrega(base)
            return [grupos.get(s) for s in semanas]

        drill = self._drill

        def drill_semanal(si: int, dsi: int, base: pd.DataFrame) -> None:
            """Registra os ids de cada ponto de uma série semanal."""
            g = base.groupby("semana_iso")["id"].apply(list)
            for i, s in enumerate(semanas):
                drill[f"{si}:{dsi}:{i}"] = [int(x) for x in g.get(s, [])]

        def drill_ids(chave: str, base: pd.DataFrame) -> None:
            drill[chave] = [int(x) for x in base["id"]]

        def linha(titulo, datasets, unidade_y=None, max_y=None):
            spec = {"tipo": "line", "titulo": titulo, "labels": rot_sem,
                    "labels_full": semanas, "datasets": datasets}
            if unidade_y:
                spec["unidade_y"] = unidade_y
            if max_y:
                spec["max_y"] = max_y
            return spec

        slides: list[dict] = []

        # ---- 1. capa -------------------------------------------------------
        slides.append({
            "tipo": "capa",
            "kicker": "SAMU 192 · Espírito Santo · Central de Regulação",
            "titulo": "Reunião de Indicadores de Desempenho e "
                      "Desperdício do SAMU 192/ES",
            "subtitulo": f"Período: {periodo} · última semana completa em "
                         f"{sem_data}. Indicadores recalculados ao vivo do "
                         "banco de dados operacional.",
        })

        # ---- 2/3. ocorrências despachadas (ISCMV, por transporte) -----------
        def slide_despachos(rotulo_transporte: str, transporte: str,
                            unidades_extra: set | None = None,
                            si: int = 0) -> dict:
            frota = df["iscmv"]
            nota_frota = "viaturas ISCMV"
            if unidades_extra:
                frota = frota | df["unidade_curta"].isin(unidades_extra)
                nota_frota += " + " + "/".join(sorted(unidades_extra))
            base = df[df["unidade"].notna() & frota
                      & (df["transporte"] == transporte)]
            drill_semanal(si, 0, base)
            sem_b = base[base["semana_iso"] == sem_ult]
            n_ocorr = int(sem_b["ocorrencia"].nunique())
            emp_ub = sem_b[sem_b["recurso"].isin(["USA", "USB"])]
            n_emp = len(emp_ub) or 1
            n_usb = int((emp_ub["recurso"] == "USB").sum())
            n_usa = int((emp_ub["recurso"] == "USA").sum())
            return {
                "kicker": "Indicadores operacionais · Despachos · ISCMV",
                "titulo": f"Ocorrências Despachadas — {rotulo_transporte}",
                "subtitulo": f"{nota_frota} · transporte {transporte} · "
                             "evolução semanal · números = última semana "
                             f"({sem_data})",
                "kpis": [
                    {"valor": f"{n_ocorr:,}".replace(",", "."),
                     "label": "Ocorrências despachadas (últ. sem.)",
                     "sub": nota_frota, "cor": VERDE},
                    {"valor": f"{n_usb / n_emp * 100:.1f}".replace(".", ","),
                     "unidade": "%", "label": "USB",
                     "sub": f"{n_usb} de {n_emp} despachos", "cor": VERDE},
                    {"valor": f"{n_usa / n_emp * 100:.1f}".replace(".", ","),
                     "unidade": "%", "label": "USA",
                     "sub": f"{n_usa} de {n_emp} despachos", "cor": LARANJA},
                ],
                "chart_titulo": "Total de ocorrências despachadas por semana",
                "chart": linha("", [
                    {"label": nota_frota, "color": AZUL,
                     "data": serie_semanal(
                         base, lambda b: b.groupby("semana_iso")["ocorrencia"]
                         .nunique().to_dict())},
                ]),
            }

        slides.append(slide_despachos("Pré-Hospitalar", "Pré-hospitalar",
                                      si=len(slides)))
        slides.append(slide_despachos("Inter-Hospitalar", "Inter-hospitalar",
                                      {"USA TF001", "USA TF002"},
                                      si=len(slides)))

        # ---- 3. assertividade ISCMV ----------------------------------------
        base_a = df[(df["transporte"] == "Pré-hospitalar") & df["iscmv"]
                    & df["codigo_cor"].isin(ADEQUACAO)
                    & df["risco_cor"].notna()]
        ok = pd.Series(False, index=base_a.index)
        for cor, riscos in ADEQUACAO.items():
            ok |= (base_a["codigo_cor"] == cor) & base_a["risco_cor"].isin(riscos)
        base_a = base_a.assign(adequado=ok)
        sem_a = base_a[base_a["semana_iso"] == sem_ult]
        pct_sem = base_a.groupby("semana_iso")["adequado"].mean() * 100
        drill_semanal(len(slides), 0, base_a)
        slides.append({
            "kicker": "Assertividade · ISCMV",
            "titulo": "Taxa de Assertividade — ISCMV",
            "subtitulo": "núcleo ISCMV · adequação código × risco inicial "
                         "(APH) · evolução semanal · destaque = última "
                         f"semana ({sem_data})",
            "kpis": [{"valor": f"{sem_a['adequado'].mean() * 100:.1f}"
                      .replace(".", ","), "unidade": "%",
                      "label": "Assertividade · ISCMV (última sem.)",
                      "sub": f"{int(sem_a['adequado'].sum())}/{len(sem_a)} "
                             "classificados", "cor": LARANJA}],
            "chart": linha("", [{"label": "ISCMV", "color": VERDE,
                                 "data": [round(float(pct_sem[s]), 1)
                                          if s in pct_sem.index else None
                                          for s in semanas]}]),
        })

        # ---- 4. tempo resposta convênio APH --------------------------------
        base_tr = df[df["convenio"] & (df["transporte"] == "Pré-hospitalar")]
        tr_ok = base_tr[(base_tr["tempo_resposta"] > 0)
                        & (base_tr["tempo_resposta"] < cap_tr)]
        media_periodo = float(tr_ok["tempo_resposta"].mean())
        tr_sem_ult = tr_ok[tr_ok["semana_iso"] == sem_ult]["tempo_resposta"]
        medias_sem = tr_ok.groupby("semana_iso")["tempo_resposta"].mean() / 60
        drill_semanal(len(slides), 0, tr_ok)
        slides.append({
            "kicker": "Tempo Resposta · Convênio · Pré-hospitalar",
            "titulo": "Tempo Resposta",
            "subtitulo": "Solicitação = Pré-hospitalar (APH) · VITORIA, VILA "
                         "VELHA, SERRA, CARIACICA · 1ª unidade a chegar por "
                         "ocorrência · média semanal (mm:ss) · média do "
                         f"período {_mmss(media_periodo)}",
            "kpis": [
                {"valor": _mmss(tr_sem_ult.mean()), "unidade": "min:seg",
                 "label": f"Tempo resposta · última semana ({sem_data})",
                 "sub": f"{len(tr_sem_ult)} atendimentos · média do período "
                        f"{_mmss(media_periodo)}", "cor": VERDE},
                {"valor": _mmss(media_periodo), "unidade": "min:seg",
                 "label": "Média do período",
                 "sub": f"{len(semanas)} semanas", "cor": CINZA},
            ],
            "chart": linha("", [{"label": "Tempo resposta (Convênio)",
                                 "color": AZUL,
                                 "data": [round(float(medias_sem[s]), 2)
                                          if s in medias_sem.index else None
                                          for s in semanas]}],
                           unidade_y="min"),
        })

        # ---- 5. curvas normais: 1º terço × última semana --------------------
        corte = dt_min + (dt_max - dt_min) / 3
        terco = tr_ok[tr_ok["dt_ocorr"] <= corte]["tempo_resposta"]
        mu1, sd1, n1 = float(terco.mean()), float(terco.std()) or 1.0, len(terco)
        mu2 = float(tr_sem_ult.mean())
        sd2, n2 = float(tr_sem_ult.std()) or 1.0, len(tr_sem_ult)
        x_max = max(mu1 + 3 * sd1, mu2 + 3 * sd2)
        xs = [x_max * i / 120 for i in range(121)]

        def pdf(mu, sd):
            return [math.exp(-((x - mu) ** 2) / (2 * sd ** 2))
                    / (sd * math.sqrt(2 * math.pi)) for x in xs]

        si_gauss = len(slides)
        drill_ids(f"{si_gauss}:0:0", tr_ok[tr_ok["dt_ocorr"] <= corte])
        drill_ids(f"{si_gauss}:1:0", tr_ok[tr_ok["semana_iso"] == sem_ult])
        slides.append({
            "kicker": "1º terço do período × última semana",
            "titulo": "Distribuição do Tempo Resposta",
            "subtitulo": "curva normal ajustada (mm:ss) · "
                         f"1º terço ({dt_min.strftime('%d/%m')}–"
                         f"{corte.strftime('%d/%m')}) · μ {_mmss(mu1)} · n {n1}"
                         f" — última semana ({sem_data}) · μ {_mmss(mu2)} · "
                         f"n {n2} · Δ média {'-' if mu2 <= mu1 else '+'}"
                         f"{_mmss(abs(mu1 - mu2))}",
            "kpis": [],
            "chart": {"tipo": "gauss", "titulo": "",
                      "labels": [_mmss(x) for x in xs],
                      "medias": [{"pos": mu1 / x_max, "rotulo": _mmss(mu1),
                                  "cor": CINZA},
                                 {"pos": mu2 / x_max, "rotulo": _mmss(mu2),
                                  "cor": AZUL}],
                      "datasets": [
                          {"label": f"1º terço · μ {_mmss(mu1)} · n {n1}",
                           "color": CINZA, "data": pdf(mu1, sd1)},
                          {"label": f"última semana · μ {_mmss(mu2)} · n {n2}",
                           "color": AZUL, "data": pdf(mu2, sd2)},
                      ]},
        })

        # ---- 6. matriz diagnóstica por plantão ------------------------------
        dias_ordem = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta",
                      "Sábado", "Domingo"]
        abrev = {"Segunda": "SEG", "Terça": "TER", "Quarta": "QUA",
                 "Quinta": "QUI", "Sexta": "SEX", "Sábado": "SAB",
                 "Domingo": "DOM"}
        idx_ult = semanas.index(sem_ult)
        sem_anteriores = semanas[max(0, idx_ult - 4):idx_ult]
        pontos = []
        medias_plantao = []
        si_matriz = len(slides)
        for dia in dias_ordem:
            for turno in ("Diurno", "Noturno"):
                plantao = f"{dia} {turno}"
                g = tr_ok[tr_ok["plantao"] == plantao]
                if not len(g):
                    continue
                drill_ids(f"{si_matriz}:p:{abrev[dia]}-{turno}", g)
                media_p = float(g["tempo_resposta"].mean())
                ult = g[g["semana_iso"] == sem_ult]["tempo_resposta"].mean()
                ant = g[g["semana_iso"].isin(sem_anteriores)]["tempo_resposta"].mean()
                if pd.isna(ult) or pd.isna(ant) or not ant:
                    continue
                variacao = (float(ult) - float(ant)) / float(ant) * 100
                medias_plantao.append(media_p)
                pontos.append({"rotulo": f"{abrev[dia]}-{turno}",
                               "x": round(variacao, 1),
                               "y": round(media_p / 60, 2)})
        # Limiar horizontal = corte de Pareto 80/20: exatamente os ~20%
        # piores plantões (3 de 14) ficam ACIMA da linha — traçada no ponto
        # médio entre o 3º e o 4º piores tempos médios.
        n_piores_matriz = 0
        limiar = 0.0
        if medias_plantao:
            ordenadas = sorted(medias_plantao, reverse=True)
            n_piores_matriz = min(math.ceil(len(ordenadas) * 0.2),
                                  len(ordenadas))
            if len(ordenadas) > n_piores_matriz:
                limiar = (ordenadas[n_piores_matriz - 1]
                          + ordenadas[n_piores_matriz]) / 2 / 60
            else:
                limiar = ordenadas[-1] / 60
        media_geral = (sum(medias_plantao) / len(medias_plantao) / 60
                       if medias_plantao else 0)
        for p in pontos:
            if p["y"] > limiar:
                p["classe"] = "Crítico" if p["x"] > 0 else "Em Recuperação"
            else:
                p["classe"] = "Alerta" if p["x"] > 0 else "Saudável"
        slides.append({
            "kicker": "Tempo Resposta · Diagnóstico · Convênio · Pré-hospitalar",
            "titulo": "Matriz Diagnóstica: Tempo Resposta × Variação",
            "subtitulo": "por plantão (dia+turno) · X = variação % da última "
                         "semana COMPARADA À MÉDIA DAS 4 SEMANAS ANTERIORES "
                         "(0 = igual às 4 semanas; direita piorou, esquerda "
                         "melhorou) · Y = média do período (mm:ss) · linha "
                         f"horizontal = Pareto 80/20 ({_mmss(limiar * 60)}): "
                         f"os {n_piores_matriz} piores plantões acima dela · "
                         "canto superior direito = ação prioritária",
            "kpis": [],
            "chart": {"tipo": "matriz", "titulo": "",
                      "pontos": pontos, "limiar": round(limiar, 2),
                      "media_geral": round(media_geral, 2),
                      "cores": {"Saudável": VERDE, "Em Recuperação": LARANJA,
                                "Alerta": "#f7d154", "Crítico": VERMELHO}},
        })

        # ---- 7. pareto TR por plantão (última semana) ------------------------
        grupo_p = tr_ok[tr_ok["semana_iso"] == sem_ult] \
            .groupby("plantao")["tempo_resposta"].agg(["mean", "count"]) \
            .sort_values("mean", ascending=False)
        n_piores = min(math.ceil(len(grupo_p) * 0.2), len(grupo_p))
        rotulos_p = []
        si_pareto = len(slides)
        tr_sem_rows = tr_ok[tr_ok["semana_iso"] == sem_ult]
        for i, (p, r) in enumerate(grupo_p.iterrows()):
            dia, turno = p.rsplit(" ", 1)
            rotulos_p.append(f"{abrev.get(dia, dia)}-{turno} ({int(r['count'])})")
            drill_ids(f"{si_pareto}:0:{i}", tr_sem_rows[tr_sem_rows["plantao"] == p])
        slides.append({
            "kicker": "Tempo Resposta · Pareto · Convênio · Pré-hospitalar",
            "titulo": "Tempo Resposta por Dia + Plantão",
            "subtitulo": "Solicitação = Pré-hospitalar (APH) · 1ª unidade a "
                         f"chegar · última semana ({sem_data}) · média (mm:ss)"
                         f" · em vermelho os {n_piores} piores plantões (20%) "
                         f"· tracejado = média do período ({_mmss(media_periodo)})",
            "kpis": [],
            "chart": {"tipo": "bar", "titulo": "", "horizontal": True,
                      "unidade_y": "min", "mostrar_valores": "tempo",
                      "linha_meta": round(media_periodo / 60, 2),
                      "labels": rotulos_p,
                      "datasets": [{"label": "Média (min)",
                                    "data": [round(float(r["mean"]) / 60, 2)
                                             for _, r in grupo_p.iterrows()],
                                    "colors": [VERMELHO if i < n_piores
                                               else VERDE
                                               for i in range(len(grupo_p))]}]},
        })

        # ---- 8. TR Vermelho USA × USB (mediana, última semana) ---------------
        # tempo_resposta só existe na linha da 1ª ambulância a chegar
        # (regra do núcleo) — o recurso/turno considerado é o dela.
        verm = tr_ok[(tr_ok["codigo_cor"] == "vermelho")
                     & (tr_ok["semana_iso"] == sem_ult)]
        kpis8, dados8 = [], {"Diurno": [], "Noturno": [], "Total": []}
        si_verm = len(slides)
        for ri, recurso in enumerate(("USA", "USB")):
            base_r = verm[verm["recurso"] == recurso]
            for di, turno in enumerate(("Diurno", "Noturno", "Total")):
                sub = base_r if turno == "Total" else \
                    base_r[base_r["turno"] == turno]
                drill_ids(f"{si_verm}:{di}:{ri}", sub)
                med = sub["tempo_resposta"].median()
                dados8[turno].append(round(float(med) / 60, 2)
                                     if len(sub) else None)
                kpis8.append({"valor": _mmss(med), "unidade": "min:seg",
                              "label": f"{recurso} · {turno}"
                              + (" (dia+noite)" if turno == "Total" else ""),
                              "sub": f"{len(sub)} atend.",
                              "cor": VERMELHO if recurso == "USA" else VERDE})
        slides.append({
            "kicker": "Tempo Resposta · Convênio · Vermelho · Pré-hospitalar",
            "titulo": "Tempo Resposta — Vermelho",
            "subtitulo": "Solicitação = Pré-hospitalar (APH) · código Vermelho"
                         " · somente a 1ª ambulância a chegar na ocorrência · "
                         "VITORIA, VILA VELHA, SERRA, CARIACICA · USA e USB "
                         f"por turno · última semana ({sem_data}) · mediana "
                         "(mm:ss)",
            "kpis": kpis8,
            "chart": {"tipo": "bar", "titulo": "", "labels": ["USA", "USB"],
                      "unidade_y": "min",
                      "datasets": [
                          {"label": "Diurno", "color": LARANJA,
                           "data": dados8["Diurno"]},
                          {"label": "Noturno", "color": AZUL,
                           "data": dados8["Noturno"]},
                          {"label": "Total (dia+noite)", "color": ROXO,
                           "data": dados8["Total"]},
                      ]},
        })

        # ---- 9/10/11/12. desperdício ----------------------------------------
        motivo_cod = df["motivo"].fillna("").str.split(" ").str[0].str.upper()
        universo = df[df["dt_inicio_deslocamento"].notna() & df["iscmv"]
                      & ~motivo_cod.isin(MOTIVOS_EXCLUIDOS_DESPERDICIO)]
        sit = universo["situacao_atendimento"].fillna("").map(nucleo.norm_txt)
        cand = sit.isin(SITUACOES_DESPERDICIO)
        real = cand & universo["dt_chegada_no_local"].notna()
        evitado = cand & universo["dt_chegada_no_local"].isna()
        u_sem = universo["semana_iso"] == sem_ult
        n_saidas_sem = int(u_sem.sum()) or 1
        n_real_sem = int((real & u_sem).sum())
        n_evit_sem = int((evitado & u_sem).sum())
        reais_periodo = int(real.sum())

        def serie_mask(mask):
            g = universo[mask].groupby("semana_iso").size()
            return [int(g.get(s, 0)) for s in semanas]

        si_desp = len(slides)
        drill_semanal(si_desp, 0, universo[real])
        drill_semanal(si_desp, 1, universo[evitado])
        slides.append({
            "kicker": "Desperdício operacional · Saída efetiva · ISCMV",
            "titulo": "Desperdícios operacionais com saída efetiva",
            "subtitulo": "Saída efetiva de viatura · núcleo ISCMV · exclui "
                         "hipoglicemia revertida (PCG3) e PCR/Óbito (PCC3) · "
                         "desperdício REAL (chegou ao local) × EVITADO "
                         "(mitigado no trajeto) · números = última semana "
                         f"({sem_data})",
            "kpis": [
                {"valor": str(n_real_sem),
                 "label": f"Desperdício REAL · última semana ({sem_data})",
                 "sub": f"chegou ao local · taxa "
                        f"{n_real_sem / n_saidas_sem * 100:.1f}% das saídas "
                        "efetivas".replace(".", ","), "cor": VERMELHO},
                {"valor": str(n_evit_sem),
                 "label": f"Desperdício EVITADO · última semana ({sem_data})",
                 "sub": "mitigado no trajeto (sem chegada no local)",
                 "cor": VERDE},
                {"valor": f"{n_saidas_sem:,}".replace(",", "."),
                 "label": "Saídas efetivas ISCMV",
                 "sub": f"denominador · última semana ({sem_data})",
                 "cor": LARANJA},
                {"valor": f"{reais_periodo:,}".replace(",", "."),
                 "label": "Desperdício REAL no período",
                 "sub": f"{len(semanas)} semanas · evitado {int(evitado.sum())}"
                        f" · taxa real {real.sum() / (len(universo) or 1) * 100:.1f}%"
                        .replace(".", ","), "cor": LARANJA},
            ],
            "chart_titulo": "Desperdício por semana · real × evitado",
            "chart": linha("", [
                {"label": "Real (chegou ao local)", "color": VERMELHO,
                 "data": serie_mask(real)},
                {"label": "Evitado (mitigado no trajeto)", "color": VERDE,
                 "data": serie_mask(evitado)},
            ]),
        })

        # 10. desperdício por tipo de unidade
        kpis10 = []
        series10 = []
        si_tipo = len(slides)
        for dsi, (recurso, cor) in enumerate((("USA", VERMELHO),
                                              ("USB", LARANJA))):
            m_rec = universo["recurso"] == recurso
            drill_semanal(si_tipo, dsi, universo[real & m_rec])
            n_r = int((real & m_rec & u_sem).sum())
            n_e = int((evitado & m_rec & u_sem).sum())
            n_s = int((m_rec & u_sem).sum()) or 1
            kpis10.append({"valor": str(n_r),
                           "label": f"{recurso} · real · últ. sem.",
                           "sub": f"taxa {n_r / n_s * 100:.1f}% · evitado "
                                  f"{n_e} · {n_r / (n_real_sem or 1) * 100:.0f}%"
                                  " do total real".replace(".", ","),
                           "cor": cor})
            series10.append({"label": recurso, "color": cor,
                             "data": serie_mask(real & m_rec)})
        kpis10.append({"valor": str(n_real_sem),
                       "label": "Total real · última semana",
                       "sub": f"evitado {n_evit_sem} · taxa "
                              f"{n_real_sem / n_saidas_sem * 100:.1f}% das saídas"
                              .replace(".", ","), "cor": CINZA})
        slides.append({
            "kicker": "Desperdício · Por tipo de unidade",
            "titulo": "Distribuição de desperdício por tipo de unidade",
            "subtitulo": "viatura ISCMV · USA × USB · desperdício REAL "
                         "(chegou ao local) · evolução semanal · números = "
                         f"última semana ({sem_data})",
            "kpis": kpis10,
            "chart_titulo": "Desperdício real por semana · USA × USB",
            "chart": linha("", series10),
        })

        # 11. motivos do desperdício real (última semana)
        reais_sem = universo[real & u_sem]
        motivos = reais_sem["motivo"].dropna().value_counts()
        top = motivos.head(12)
        si_mot = len(slides)
        for i, motivo in enumerate(top.index):
            drill_ids(f"{si_mot}:0:{i}", reais_sem[reais_sem["motivo"] == motivo])
        slides.append({
            "kicker": "Desperdício · Motivos · Real · Última semana",
            "titulo": "Motivos para o desperdício",
            "subtitulo": "desperdício REAL (chegou ao local) · motivo da "
                         f"ocorrência · última semana ({sem_data}) · top "
                         f"{len(top)} de {len(motivos)} motivos",
            "kpis": [],
            "chart": {"tipo": "bar", "titulo": "", "horizontal": True,
                      "mostrar_valores": "int",
                      "labels": [m[:34] for m in top.index],
                      "datasets": [{"label": "desp.",
                                    "data": [int(x) for x in top],
                                    "colors": [LARANJA] * len(top)}]},
        })

        # 12. distribuição dos tipos de desperdício
        rotulos_sit = sit[real & u_sem].map(
            lambda s: ROTULO_SITUACAO.get(s, s.title()))
        tipos = rotulos_sit.value_counts()
        si_tipos = len(slides)
        for i, rotulo in enumerate(tipos.index):
            drill_ids(f"{si_tipos}:0:{i}",
                      reais_sem[rotulos_sit == rotulo])
        slides.append({
            "kicker": "Desperdício · Tipos · Real · Última semana",
            "titulo": "Distribuição de tipos de desperdício",
            "subtitulo": "desperdício REAL (chegou ao local) · tipo (situação "
                         f"da ocorrência) · última semana ({sem_data}) · "
                         f"{n_real_sem} desperdícios reais",
            "kpis": [],
            "chart": {"tipo": "doughnut", "titulo": "",
                      "centro": {"valor": str(n_real_sem), "rotulo": "desp."},
                      "labels": list(tipos.index),
                      "datasets": [{"label": "desp.",
                                    "data": [int(x) for x in tipos],
                                    "colors": [LARANJA, AZUL, ROXO, VERDE,
                                               VERMELHO, "#f7d154",
                                               CINZA][:len(tipos)]}]},
        })

        return {"titulo": "Reunião de Indicadores",
                "periodo": periodo, "semana": sem_ult,
                "semana_data": sem_data, "slides": slides}
