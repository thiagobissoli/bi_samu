"""Investigação de Eventos — ocupação das viaturas no tempo (§35.16).

Responde à pergunta operacional: quando uma ocorrência foi atendida por
uma viatura de OUTRO município, as viaturas do próprio município estavam
ocupadas naquele instante?

Uma viatura é considerada **ocupada** entre o início do deslocamento e o
encerramento do atendimento — é o intervalo em que ela não está
disponível para um novo chamado. Quando falta o início do deslocamento,
usa-se a saída para atendimento (J9); quando falta o encerramento,
usa-se a última marcação conhecida do empenho.

IMPORTANTE: "sem empenho" não é prova de que a viatura estava operacional
— ela pode estar fora de escala, em manutenção ou indisponível por outro
motivo que o relatório não registra. O módulo mostra o que há de
registro, e a tela deixa isso explícito.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import select

from app.modules.indicadores import nucleo
from app.modules.investigacao.constants import (
    DURACAO_MAXIMA_HORAS,
    LIMITE_UNIDADES_TIMELINE,
)

# Marcações que encerram a ocupação, da mais para a menos precisa
FIM_ALTERNATIVOS = ["dt_atendimento_encerrado", "dt_chegada_no_hospital",
                    "dt_saida_para_hospital", "dt_chegada_no_local"]
INICIO_ALTERNATIVOS = ["dt_inicio_deslocamento", "dt_saida_para_atendimento",
                       "dt_data_controlador"]


class InvestigacaoService:
    def __init__(self, empresa_id: int = 1):
        self.empresa_id = empresa_id

    # ------------------------------------------------------------ base

    def _empenhos(self) -> pd.DataFrame:
        """Empenhos com viatura e janela de ocupação calculada."""
        df = nucleo.carregar(self.empresa_id)
        base = df[df["unidade"].notna() & df["unidade"].ne("")].copy()
        if base.empty:
            return base

        base["inicio"] = base[INICIO_ALTERNATIVOS].bfill(axis=1).iloc[:, 0]
        base["fim"] = base[FIM_ALTERNATIVOS].bfill(axis=1).iloc[:, 0]
        base = base[base["inicio"].notna() & base["fim"].notna()]
        # Descarta janelas impossíveis (fim antes do início) e as longas
        # demais para representarem um único empenho.
        duracao = (base["fim"] - base["inicio"]).dt.total_seconds()
        base = base[(duracao > 0) & (duracao <= DURACAO_MAXIMA_HORAS * 3600)]
        # municipio_base vem do núcleo, que só aceita como base o complemento
        # que também existe como cidade de ocorrência. A versão local daqui
        # tomava qualquer sufixo por município e fazia o aeromédico, o VIR-01
        # e o NEP 33 aparecerem como "viatura de outro município".
        return base

    def opcoes(self) -> dict:
        """Municípios-base e unidades disponíveis para os filtros."""
        base = self._empenhos()
        if base.empty:
            return {"municipios": [], "unidades": [], "dia_min": "", "dia_max": ""}
        return {
            "municipios": sorted(base["municipio_base"].dropna().unique()),
            "unidades": sorted(base["unidade"].dropna().unique()),
            "dia_min": base["inicio"].min().strftime("%Y-%m-%d"),
            "dia_max": base["inicio"].max().strftime("%Y-%m-%d"),
        }

    # -------------------------------------------------------- timeline

    def timeline_dia(self, dia: str, municipios: list[str] | None = None,
                     unidades: list[str] | None = None) -> dict:
        """Ocupação de cada viatura ao longo de um dia (00h–24h)."""
        try:
            alvo = datetime.strptime(dia, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            alvo = date.today()

        base = self._empenhos()
        if base.empty:
            return {"dia": alvo.strftime("%Y-%m-%d"), "unidades": [],
                    "total_periodos": 0}

        inicio_dia = pd.Timestamp(alvo)
        fim_dia = inicio_dia + timedelta(days=1)
        # Um empenho entra no dia se qualquer parte dele cair nele
        no_dia = base[(base["inicio"] < fim_dia) & (base["fim"] > inicio_dia)]
        if municipios:
            no_dia = no_dia[no_dia["municipio_base"].isin(municipios)]
        if unidades:
            no_dia = no_dia[no_dia["unidade"].isin(unidades)]

        linhas = []
        for unidade, grupo in no_dia.groupby("unidade"):
            periodos = []
            for _, r in grupo.sort_values("inicio").iterrows():
                # Recorta no dia para posicionar na régua de 24h
                ini = max(r["inicio"], inicio_dia)
                fim = min(r["fim"], fim_dia)
                periodos.append({
                    "ocorrencia": r["ocorrencia"],
                    "inicio": r["inicio"].strftime("%d/%m %H:%M"),
                    "fim": r["fim"].strftime("%d/%m %H:%M"),
                    "duracao": _duracao(r["inicio"], r["fim"]),
                    "cidade": _txt(r["cidade"]),
                    "codigo": _txt(r["codigo_da_ocorrencia"]),
                    "motivo": _txt(r["motivo"]),
                    "esquerda": round(
                        (ini - inicio_dia).total_seconds() / 864, 4),
                    "largura": max(round(
                        (fim - ini).total_seconds() / 864, 4), 0.4),
                    "fora": bool(_fora_do_municipio(r)),
                })
            linhas.append({
                "unidade": unidade,
                "municipio": _txt(grupo.iloc[0]["municipio_base"]),
                "periodos": periodos,
                "ocupacao_pct": round(sum(p["largura"] for p in periodos), 1),
            })

        linhas.sort(key=lambda x: _ordem_unidade(x["unidade"]))
        return {
            "dia": alvo.strftime("%Y-%m-%d"),
            "unidades": linhas[:LIMITE_UNIDADES_TIMELINE],
            "total_unidades": len(linhas),
            "total_periodos": sum(len(u["periodos"]) for u in linhas),
        }

    # ----------------------------------------------------- investigação

    def investigar(self, numero: str) -> dict:
        """Analisa um empenho: por que veio viatura de fora do município?

        Devolve a ocorrência, a viatura que atendeu e — no instante do
        acionamento — a situação de TODAS as viaturas sediadas no
        município da ocorrência.
        """
        numero = str(numero or "").strip()
        if not numero:
            return {"erro": "Informe o número da ocorrência."}

        base = self._empenhos()
        alvos = base[base["ocorrencia"] == numero]
        df = nucleo.carregar(self.empresa_id)
        linhas_oc = df[df["ocorrencia"] == numero]
        if linhas_oc.empty:
            return {"erro": f"Ocorrência {numero} não encontrada."}

        com_empenho = not alvos.empty
        if com_empenho:
            # Empenho de referência: o primeiro a se deslocar
            alvo = alvos.sort_values("inicio").iloc[0]
            momento = alvo["inicio"]
        else:
            # Chamado sem viatura despachada (orientação médica, cancelado,
            # sem recurso...) — ainda assim há o que analisar: a cadeia do
            # atendimento e a disponibilidade de viaturas no momento.
            alvo = linhas_oc.sort_values("dt_ocorr").iloc[0]
            momento = _primeiro_horario(alvo)
            if momento is None:
                return {"erro": (f"A ocorrência {numero} não tem nenhum "
                                 "horário registrado — não há o que analisar.")}
        cidade = _txt(alvo["cidade"])
        base_alvo = _txt(alvo.get("municipio_base")) if com_empenho else ""

        # Viaturas sediadas no município da ocorrência (histórico completo)
        norm_cidade = nucleo.norm_txt(cidade) if cidade else ""
        do_municipio = base[base["municipio_base"].map(
            lambda m: bool(m) and nucleo.norm_txt(m) == norm_cidade)] \
            if norm_cidade else base.iloc[0:0]

        situacoes = []
        for unidade, grupo in do_municipio.groupby("unidade"):
            ocupando = grupo[(grupo["inicio"] <= momento)
                             & (grupo["fim"] >= momento)]
            se_atendeu = (grupo["ocorrencia"] == numero).any()
            if not ocupando.empty:
                o = ocupando.sort_values("inicio").iloc[0]
                situacoes.append({
                    "unidade": unidade,
                    "status": "atendeu" if se_atendeu else "ocupada",
                    "ocorrencia": o["ocorrencia"],
                    "desde": o["inicio"].strftime("%d/%m %H:%M"),
                    "ate": o["fim"].strftime("%d/%m %H:%M"),
                    "detalhe": " · ".join(x for x in (
                        _txt(o["cidade"]), _txt(o["codigo_da_ocorrencia"]),
                        _txt(o["motivo"])) if x),
                })
            else:
                # Último empenho antes e primeiro depois: mostra se a
                # viatura estava em atividade naquele dia
                antes = grupo[grupo["fim"] < momento].sort_values("fim")
                depois = grupo[grupo["inicio"] > momento].sort_values("inicio")
                situacoes.append({
                    "unidade": unidade,
                    "status": "sem_empenho",
                    "ocorrencia": None,
                    "desde": (antes.iloc[-1]["fim"].strftime("%d/%m %H:%M")
                              if len(antes) else None),
                    "ate": (depois.iloc[0]["inicio"].strftime("%d/%m %H:%M")
                            if len(depois) else None),
                    "detalhe": _atividade_no_dia(grupo, momento),
                })
        ordem = {"ocupada": 0, "atendeu": 1, "sem_empenho": 2}
        situacoes.sort(key=lambda s: (ordem[s["status"]],
                                      _ordem_unidade(s["unidade"])))

        ocupadas = [s for s in situacoes if s["status"] == "ocupada"]
        livres = [s for s in situacoes if s["status"] == "sem_empenho"]
        fora = bool(_fora_do_municipio(alvo)) if com_empenho else False

        if not com_empenho:
            # Sem viatura despachada: a pergunta deixa de ser "por que veio
            # de fora" e passa a ser "havia viatura disponível?".
            situacao = _txt(alvo.get("situacao_atendimento")) or "não informada"
            if not situacoes:
                veredito = (f"Chamado encerrado sem despacho de viatura "
                            f"(situação: {situacao}). Não há viatura sediada "
                            f"em {cidade or '—'} na base para comparar.")
            elif not livres:
                veredito = (
                    f"Chamado encerrado sem despacho de viatura (situação: "
                    f"{situacao}). No momento do chamado, TODAS as "
                    f"{len(situacoes)} viaturas de {cidade} estavam ocupadas "
                    "— vale verificar se a decisão foi clínica ou "
                    "condicionada pela falta de recurso.")
            else:
                veredito = (
                    f"Chamado encerrado sem despacho de viatura (situação: "
                    f"{situacao}). No momento do chamado, {len(livres)} de "
                    f"{len(situacoes)} viaturas de {cidade} estavam sem "
                    "empenho registrado — a decisão não parece ter sido "
                    "por falta de recurso.")
        elif not fora:
            veredito = ("A ocorrência foi atendida por viatura do próprio "
                        "município.")
        elif not situacoes:
            veredito = (f"Não há viatura sediada em {cidade or '—'} na base "
                        "de dados — o apoio de outro município é o esperado.")
        elif not livres:
            veredito = (f"Todas as {len(situacoes)} viaturas de {cidade} "
                        "estavam ocupadas no momento do acionamento.")
        else:
            veredito = (
                f"{len(livres)} de {len(situacoes)} viaturas de {cidade} "
                "estavam SEM empenho registrado no momento do acionamento "
                f"({', '.join(s['unidade'] for s in livres[:4])}"
                f"{'…' if len(livres) > 4 else ''}).")

        return {
            "ocorrencia": numero,
            "registro_id": int(alvo["id"]),
            "com_empenho": com_empenho,
            "momento": momento.strftime("%d/%m/%Y %H:%M"),
            "dia": momento.strftime("%Y-%m-%d"),
            "cidade": cidade,
            "unidade": _txt(alvo["unidade"]),
            "municipio_unidade": base_alvo,
            "fora_do_municipio": fora,
            "codigo": _txt(alvo["codigo_da_ocorrencia"]),
            "motivo": _txt(alvo["motivo"]),
            "tipo": _txt(alvo.get("tipo")),
            "risco": _txt(alvo["risco_inicial"]),
            "situacao": _txt(alvo.get("situacao_atendimento")),
            "transporte": _txt(alvo.get("transporte")),
            "tempo_resposta": _mmss(alvo.get("tempo_resposta")),
            "empenhos_na_ocorrencia": len(alvos),
            "linhas_na_ocorrencia": len(linhas_oc),
            "cadeia": _cadeia_do_chamado(alvo),
            "equipe": _equipe(alvo),
            "situacoes": situacoes,
            "n_ocupadas": len(ocupadas),
            "n_livres": len(livres),
            "veredito": veredito,
        }

    def dossie(self, db, numero: str) -> dict:
        """Tudo que se sabe da ocorrência, para a tela e para a IA.

        Reúne: a investigação de disponibilidade, os indicadores medidos
        (mesma fonte dos dashboards), a decomposição do atraso, o
        prontuário já baixado e a última análise por IA.
        """
        from app.modules.download_vsky.models import VskyProntuario
        from app.modules.indicadores.ocorrencia import indicadores_da_ocorrencia
        from app.modules.investigacao.analise import (decompor_atraso,
                                                      fatores_tempo_resposta)
        from app.modules.investigacao.ia_analise import (cronologia_do_sistema,
                                                         historico,
                                                         ultima_analise)

        inv = self.investigar(numero)
        if inv.get("erro"):
            return {"investigacao": inv}

        from app.modules.download_vsky.models import VskyRegistroAnalitico as R

        registro_id = inv.get("registro_id")
        # Nome do paciente vem da tabela bruta (fora do núcleo): serve só
        # para a anonimização antes de enviar texto a provedor externo.
        registro = db.scalar(select(R).where(R.id == registro_id)) \
            if registro_id else None
        inv["paciente"] = (registro.paciente or "") if registro else ""
        # Iniciais no lugar do nome, como no formulário impresso (LGPD)
        inv["paciente_iniciais"] = _iniciais(inv["paciente"])
        inv["idade"] = (registro.idade or "") if registro else ""
        inv["sexo"] = (registro.sexo or "") if registro else ""
        inv["endereco"] = " · ".join(x for x in (
            (registro.endereco or "") if registro else "",
            (registro.bairro or "") if registro else "",
            inv.get("cidade") or "") if x)
        prontuario = db.scalar(select(VskyProntuario).where(
            VskyProntuario.empresa_id == self.empresa_id,
            VskyProntuario.ocorrencia == numero,
            VskyProntuario.deleted_at.is_(None)))
        return {
            "investigacao": inv,
            "indicadores": (indicadores_da_ocorrencia(self.empresa_id,
                                                      registro_id)
                            if registro_id else []),
            "atraso": (decompor_atraso(self.empresa_id, registro_id)
                       if registro_id else {}),
            "fatores_tr": (fatores_tempo_resposta(self.empresa_id, registro_id,
                                                  inv)
                           if registro_id else {}),
            "prontuario": {
                "baixado_em": (prontuario.baixado_em.strftime("%d/%m/%Y %H:%M")
                               if prontuario and prontuario.baixado_em else None),
                "paginas": prontuario.paginas if prontuario else 0,
                "tamanho_kb": round(prontuario.tamanho / 1024) if prontuario else 0,
                "texto": prontuario.texto if prontuario else None,
            } if prontuario else None,
            # Cronologia é dado factual: sai das marcações, não da IA
            "cronologia": cronologia_do_sistema(inv),
            "analise_ia": ultima_analise(db, self.empresa_id, numero),
            "relatos": _relatos_da_ocorrencia(db, self.empresa_id, numero),
            "versoes": [{
                "id": v.id, "versao": v.versao, "status": v.status,
                "gerado_em": v.gerado_em.strftime("%d/%m/%Y %H:%M")
                             if v.gerado_em else "",
                "feedback": v.feedback,
                "aprovado_em": v.aprovado_em.strftime("%d/%m/%Y %H:%M")
                               if v.aprovado_em else None,
                "aprovado_nome": v.aprovado_nome,
            } for v in historico(db, self.empresa_id, numero)],
        }

    def cruzamentos(self, dia: str) -> dict:
        """Empenhos de outro município no dia — pauta de investigação."""
        try:
            alvo = datetime.strptime(dia, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            alvo = date.today()
        base = self._empenhos()
        if base.empty:
            return {"dia": alvo.strftime("%Y-%m-%d"), "casos": []}
        no_dia = base[base["inicio"].dt.date == alvo]
        fora = no_dia[no_dia.apply(_fora_do_municipio, axis=1)]
        casos = [{
            "ocorrencia": r["ocorrencia"],
            "hora": r["inicio"].strftime("%H:%M"),
            "unidade": _txt(r["unidade"]),
            "municipio_unidade": _txt(r["municipio_base"]),
            "cidade": _txt(r["cidade"]),
            "codigo": _txt(r["codigo_da_ocorrencia"]),
            "tempo_resposta": _mmss(r.get("tempo_resposta")),
        } for _, r in fora.sort_values("inicio").iterrows()]
        return {"dia": alvo.strftime("%Y-%m-%d"), "casos": casos}


# ------------------------------------------------------------ helpers

def _fora_do_municipio(linha) -> bool:
    """Viatura sediada em município diferente do da ocorrência."""
    base, cidade = linha.get("municipio_base"), linha.get("cidade")
    if not base or not cidade or pd.isna(base) or pd.isna(cidade):
        return False
    return nucleo.norm_txt(base) != nucleo.norm_txt(cidade)


def _txt(valor) -> str:
    return "" if valor is None or pd.isna(valor) else str(valor)


def _duracao(inicio, fim) -> str:
    minutos = int((fim - inicio).total_seconds() // 60)
    return f"{minutos // 60}h{minutos % 60:02d}" if minutos >= 60 \
        else f"{minutos} min"


def _mmss(segundos) -> str:
    """Tempo de resposta em mm:ss, com o mesmo teto de validade dos
    dashboards — valores fora da faixa são registro defeituoso e saem
    como vazio, em vez de aparecerem como medição boa."""
    from app.modules.indicadores.constants import CAP_TEMPO

    if segundos is None or pd.isna(segundos):
        return ""
    s = float(segundos)
    if not 0 < s < CAP_TEMPO.get("tempo_resposta", 14400):
        return ""
    s = int(round(s))
    return f"{s // 60:02d}:{s % 60:02d}"


def _atividade_no_dia(grupo: pd.DataFrame, momento) -> str:
    """Resumo do dia da viatura — distingue 'parada' de 'fora de escala'."""
    dia = grupo[grupo["inicio"].dt.date == momento.date()]
    if dia.empty:
        return "sem nenhum empenho neste dia"
    return f"{len(dia)} empenho(s) no dia"


def _ordem_unidade(nome: str) -> tuple:
    """Ordena USA/USB pelo número da viatura, não pelo texto."""
    import re
    m = re.search(r"\b(USA|USB|VIR)\b\s*(\d+)?", str(nome).upper())
    if not m:
        return (9, 9999, str(nome))
    prefixo = {"USA": 0, "USB": 1, "VIR": 2}.get(m.group(1), 3)
    return (prefixo, int(m.group(2)) if m.group(2) else 9999, str(nome))


# Cadeia de marcações do chamado, da abertura ao encerramento. Vale
# também para chamados sem viatura: mostra até onde o fluxo avançou.
MARCACOES = [
    ("dt_ocorr", "Abertura do chamado", "telefone atendido"),
    ("dt_data_tarm", "TARM", "chamado qualificado"),
    ("dt_data_regulador", "Regulação médica", "decisão do regulador"),
    ("dt_data_controlador", "Despacho", "viatura acionada"),
    ("dt_inicio_deslocamento", "Início do deslocamento", "viatura a caminho"),
    ("dt_saida_para_atendimento", "Saída p/ atendimento (J9)", ""),
    ("dt_chegada_no_local", "Chegada no local", ""),
    ("dt_primeiro_j14", "Primeiro J14", "início do atendimento"),
    ("dt_saida_para_hospital", "Saída para o hospital", ""),
    ("dt_chegada_no_hospital", "Chegada no hospital", ""),
    ("dt_atendimento_encerrado", "Atendimento encerrado", ""),
]


def _primeiro_horario(linha):
    """Marcação mais próxima do acionamento entre as disponíveis."""
    for col in ("dt_data_controlador", "dt_data_regulador", "dt_data_tarm",
                "dt_ocorr"):
        v = linha.get(col)
        if v is not None and not pd.isna(v):
            return v
    return None


def _cadeia_do_chamado(linha) -> list[dict]:
    """Marcações registradas, com o intervalo desde a anterior.

    O que falta aparece como ausente — num chamado sem despacho é
    justamente onde o fluxo parou que interessa.
    """
    itens, anterior = [], None
    for col, rotulo, papel in MARCACOES:
        v = linha.get(col)
        if v is None or pd.isna(v):
            itens.append({"rotulo": rotulo, "papel": papel, "hora": None,
                          "desde_anterior": None})
            continue
        intervalo = None
        if anterior is not None:
            segundos = (v - anterior).total_seconds()
            if segundos >= 0:
                intervalo = _mmss(segundos)
        itens.append({"rotulo": rotulo, "papel": papel,
                      "hora": v.strftime("%d/%m/%Y %H:%M:%S"),
                      "desde_anterior": intervalo})
        anterior = v
    return itens


def _equipe(linha) -> list[dict]:
    """Profissionais registrados no chamado (só os preenchidos)."""
    papeis = [("tarm_nome", "TARM"), ("regulador_nome", "Médico regulador"),
              ("controlador_nome", "Controlador"), ("medico_nome", "Médico"),
              ("enfermeiro_nome", "Enfermeiro"),
              ("tec_enfermagem_nome", "Téc. enfermagem"),
              ("condutor_nome", "Condutor")]
    return [{"papel": rotulo, "nome": _txt(linha.get(col))}
            for col, rotulo in papeis if _txt(linha.get(col))]


# Preposições não entram nas iniciais: "WILSON DE VALADARES" -> "W.V."
_PREPOSICOES = {"DE", "DA", "DO", "DAS", "DOS", "E"}


def _iniciais(nome: str) -> str:
    """Nome do paciente reduzido às iniciais, como no formulário impresso.

    O RAC circula fora do sistema; o formulário oficial usa iniciais
    (ex.: "W.V.") em vez do nome completo.
    """
    partes = [p for p in str(nome or "").upper().split()
              if p and p not in _PREPOSICOES]
    return ".".join(p[0] for p in partes) + "." if partes else ""


def _relatos_da_ocorrencia(db, empresa_id: int, numero: str) -> str:
    """Relatos dos envolvidos registrados na versão corrente do RAC."""
    from app.modules.investigacao.ia_analise import historico

    versoes = historico(db, empresa_id, numero)
    return (versoes[0].relatos or "") if versoes else ""
