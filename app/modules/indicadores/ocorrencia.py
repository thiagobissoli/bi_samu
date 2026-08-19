"""Indicadores calculados de UMA ocorrência (§35.16).

Lê as derivações que o núcleo já faz para os dashboards (P1–P9, tempo de
central e de resposta, assertividade, NEWS, plantão) — assim a ficha de
uma ocorrência mostra exatamente os mesmos números dos gráficos, sem
recálculo paralelo que possa divergir.

Consumido pela Reunião de Indicadores (modal da ocorrência) e pela
Investigação de Eventos.
"""

from __future__ import annotations

import pandas as pd

from app.modules.indicadores import nucleo
from app.modules.indicadores.constants import (ADEQUACAO, CAP_TEMPO, SLA_P1,
                                               SLA_P2_POR_COR)

# Metas por etapa, em segundos. Só entram as que o sistema já usa em
# outros pontos — P4.1 espelha a régua do ranking de saída de base.
META_P4_1 = 120


def mmss(segundos) -> str | None:
    """Segundos -> mm:ss (None quando ausente)."""
    if segundos is None or pd.isna(segundos):
        return None
    s = int(round(float(segundos)))
    return f"{s // 60:02d}:{s % 60:02d}"


def _fora_da_faixa(cap: float) -> str:
    return (f"acima da faixa de validade ({mmss(cap)}) — medido, mas fora "
            "das médias dos painéis")


def linha_da_ocorrencia(empresa_id: int, registro_id: int):
    """Linha do núcleo correspondente ao empenho (None se não achar)."""
    df = nucleo.carregar(empresa_id)
    linha = df[df["id"] == registro_id]
    return None if linha.empty else linha.iloc[0]


def indicadores_da_ocorrencia(empresa_id: int, registro_id: int) -> list[dict]:
    """Indicadores deste empenho, com `situacao` (ok/alerta/ruim/neutro)."""
    r = linha_da_ocorrencia(empresa_id, registro_id)
    if r is None:
        return []
    return indicadores_da_linha(r)


def indicadores_da_linha(r) -> list[dict]:
    """Mesma lógica, quando a linha do núcleo já está em mãos."""
    from app.modules.indicadores.service import ROTULO_COR

    itens: list[dict] = []

    def add(rotulo, valor, sub="", situacao="neutro"):
        itens.append({"rotulo": rotulo, "valor": valor or "—",
                      "sub": sub, "situacao": situacao})

    def tempo(col, rotulo, sub="", limite=None):
        v = r.get(col)
        cap = CAP_TEMPO.get(col, 14400)
        if pd.isna(v) or float(v) <= 0:
            # "—" sozinho não diz se falta a marcação ou se a etapa não se
            # aplica; numa investigação essa diferença muda a conclusão.
            add(rotulo, None, (sub + " · " if sub else "") + "sem marcação")
            return
        v = float(v)
        situacao = "neutro"
        if limite:
            situacao = "ok" if v <= limite else "ruim"
            sub = (sub + " · " if sub else "") + f"meta {mmss(limite)}"
        if v >= cap:
            # O teto existe para uma marcação errada não destruir a média dos
            # painéis. Aqui é uma ocorrência só: esconder o valor esconde
            # justamente o atraso que motivou olhar para ela.
            situacao = "ruim"
            sub = (sub + " · " if sub else "") + _fora_da_faixa(cap)
        add(rotulo, mmss(v), sub, situacao)

    # --- tempos do fluxo (mesmas definições dos dashboards) ---
    cor = r.get("codigo_cor")
    tempo("t_central", "Tempo de Central", "controlador − abertura")
    tempo("t_p1", "P1 · Atendimento TARM", "TARM − abertura", SLA_P1)
    tempo("t_p2", "P2 · Regulação médica", "regulador − TARM",
          SLA_P2_POR_COR.get(cor))
    tempo("t_p3", "P3 · Despacho", "controlador − regulador")
    tempo("t_p4", "P4 · Tempo de chegada", "chegada − controlador")
    # O P4.1 exibido já vem com o desconto do atraso de transmissão
    # (GPS/rede). Sem dizer isso, o valor não fecha com os horários que a
    # própria tela mostra na cadeia do chamado.
    tempo("t_p4_1", "P4.1 · Saída de base", _sub_p4_1(r), META_P4_1)
    tempo("t_p4_2", "P4.2 · Deslocamento", "chegada − início desloc.")
    tempo("t_p5_6_7", "P5-7 · Tempo de cena", "saída p/ hospital − chegada")
    tempo("t_p8", "P8 · Transporte", "chegada hospital − saída p/ hospital")
    tempo("t_p9", "P9 · Transf. de cuidados", "encerrado − chegada hospital")

    tr = r.get("tempo_resposta")
    cap_tr = CAP_TEMPO.get("tempo_resposta", 14400)
    if pd.isna(tr):
        add("Tempo de Resposta", None,
            "outra viatura chegou antes nesta ocorrência")
    elif float(tr) <= 0:
        add("Tempo de Resposta", None, "sem marcação válida")
    else:
        sub, situacao = "chegada − abertura · 1ª unidade", "neutro"
        if float(tr) >= cap_tr:
            sub, situacao = f"{sub} · {_fora_da_faixa(cap_tr)}", "ruim"
        add("Tempo de Resposta", mmss(tr), sub, situacao)

    # --- classificações ---
    risco = r.get("risco_cor")
    if cor in ADEQUACAO and not pd.isna(risco):
        ok = risco in ADEQUACAO[cor]
        add("Assertividade", "Adequado" if ok else "Inadequado",
            f"código {ROTULO_COR.get(cor, cor)} × triagem "
            f"{ROTULO_COR.get(risco, risco)}", "ok" if ok else "ruim")
    news = r.get("news_total")
    if not pd.isna(news):
        banda = r.get("news_risco")
        add("NEWS modificada", f"{int(news)} · {banda}",
            "FR+FC+PAS+Glasgow aferidos",
            {"Alto": "ruim", "Médio": "alerta",
             "Baixo-Médio": "alerta"}.get(banda, "ok"))
    add("Plantão", r.get("plantao"), r.get("semana_iso") or "")
    add("Tipo de unidade", r.get("recurso"), r.get("unidade_curta") or "")
    perfil = [nome for chave, nome in
              (("iscmv", "ISCMV"), ("convenio", "Convênio"))
              if bool(r.get(chave))]
    add("Perfil", " · ".join(perfil) if perfil else "Fora do recorte", "")
    if bool(r.get("obito_constatado")):
        add("Óbito", "Constatado", "", "ruim")
    return itens


def _sub_p4_1(r) -> str:
    """Explica o P4.1: bruto, desconto aplicado e piso, quando houver.

    O valor mostrado é o ajustado; sem esta memória de cálculo ele não
    bate com a diferença entre os horários exibidos na cadeia do chamado.
    """
    from app.modules.indicadores import nucleo

    base = "início desloc. − controlador"
    inicio, controlador = r.get("dt_inicio_deslocamento"), r.get("dt_data_controlador")
    if pd.isna(inicio) or pd.isna(controlador):
        return base
    bruto = (inicio - controlador).total_seconds()
    desconto = nucleo.desconto_p41()
    if bruto <= 0 or not desconto:
        return base
    if bruto <= desconto:
        # Marcação abaixo do próprio atraso: o desconto não se aplica a
        # ela, e o valor medido vale como está.
        return (f"{base} = {mmss(bruto)} · abaixo do atraso de transmissão "
                f"({mmss(desconto)}), medido sem desconto")
    return f"{base} = {mmss(bruto)} − {mmss(desconto)} de transmissão"
