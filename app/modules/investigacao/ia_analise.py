"""Análise da ocorrência por IA: Protocolo de Londres, Ishikawa e matriz
de risco (§35.16).

O modelo NÃO calcula indicadores nem decide se houve atraso — isso já
vem pronto e verificado de `analise.decompor_atraso`. O papel da IA é
interpretar esse material com três instrumentos consagrados de análise
de eventos, produzindo hipóteses que a equipe valida.

Saída em JSON, para a tela renderizar de forma estruturada em vez de
despejar texto corrido.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import ia
from app.modules.investigacao.models import (STATUS_APROVADO,
                                             STATUS_PENDENTE,
                                             STATUS_SUBSTITUIDO,
                                             AnaliseOcorrencia)

SISTEMA = (
    "Você é analista do Núcleo de Segurança do Paciente de um SAMU 192 "
    "brasileiro e redige o formulário FOR.SAMU.038 — Relatório de Evento "
    "Adverso com Investigação de Causa Raiz (RAC), seguindo o Protocolo de "
    "Londres. Responde em português do Brasil, com a objetividade de um "
    "documento institucional: frases completas, sem jargão desnecessário e "
    "sem floreio.\n\n"
    "Regras invioláveis:\n"
    "1. Baseie-se apenas nos dados fornecidos. Não invente horários, nomes, "
    "condutas, relatos de profissionais ou fatos que não estejam no "
    "material.\n"
    "2. Quando um dado faltar, declare a falta no campo próprio — é achado "
    "da investigação, não lacuna a preencher com suposição. Relatos dos "
    "envolvidos e notificação do NCPS só existem se estiverem no material.\n"
    "3. Analise processos e sistema, não pessoas. Não atribua culpa "
    "individual nem sugira punição; nomes de profissionais não entram na "
    "análise de causa.\n"
    "4. Marque apenas os itens de fatores contribuintes que a lista "
    "fornecida contém, e apenas quando houver evidência no material. "
    "Categoria sem evidência recebe 'Não foi identificado.'.\n"
    "5. NUNCA escreva datas ou horários que não estejam no material: a "
    "cronologia oficial é montada pelo sistema a partir das marcações. Em "
    "'eventos_do_prontuario' entram apenas fatos narrados no prontuário, "
    "com o horário só quando ele estiver escrito lá.\n"
    "6. Distinga o que é fato registrado do que é hipótese sua.\n"
    "7. Responda SOMENTE com um objeto JSON válido, sem texto fora dele."
)

ESQUEMA = """{
  "dados_gerais": {
    "titulo_investigacao": "título curto do evento investigado, no padrão do formulário",
    "descricao_incidente": "parágrafo objetivo: quando, onde, qual equipe, o que ocorreu e o desfecho",
    "gravidade": "Leve|Moderada|Grave|Óbito|Alto Potencial",
    "gravidade_justificativa": "por que essa classificação",
    "nivel_investigacao": "Análise de Causa Raiz"
  },
  "risco_antes": {
    "probabilidade": 1,
    "probabilidade_rotulo": "Raro|Improvável|Possível|Provável|Quase certo",
    "consequencia": 1,
    "consequencia_rotulo": "Desprezível|Menor|Moderada|Maior|Catastrófica",
    "justificativa": "por que essa frequência e essa consequência"
  },
  "eventos_do_prontuario": [
    {"quando": "horário APENAS se estiver escrito no prontuário", "evento": "fato relatado no prontuário que não aparece nas marcações do sistema"}
  ],
  "tempo_resposta": {
    "acima_da_meta": true,
    "causa_predominante": "distancia|percurso|transito|origem_da_viatura|processo|indisponibilidade|nao_se_aplica|indeterminado",
    "explicacao": "por que o tempo passou de 10 min, citando os números apurados",
    "fatores": [
      {"fator": "o que contribuiu", "tipo": "distancia|percurso|transito|origem_da_viatura|processo|indisponibilidade",
       "evidencia": "o número que sustenta", "evitavel": "sim|parcialmente|nao",
       "o_que_fazer": "ação concreta para reduzir este fator"}
    ]
  },
  "fatores_contribuintes": [
    {"categoria": "uma das sete categorias da lista fornecida",
     "itens": ["apenas itens que existem na lista daquela categoria"],
     "descricao": "parágrafo explicando o fator com a evidência; ou 'Não foi identificado.'"}
  ],
  "ishikawa": {
    "efeito": "problema central, mensurável",
    "espinhas": [
      {"categoria": "Método|Mão de obra|Máquina|Material|Medida|Meio ambiente",
       "causas": ["causa provável 1", "causa provável 2"]}
    ]
  },
  "conclusao": "parágrafo conclusivo da investigação: o que causou o evento e o que o sustentou",
  "plano_acao": [
    {"numero": 1, "acao": "ação concreta e verificável",
     "tipo": "processo|treinamento|tecnologia|estrutura|documento",
     "prazo": "imediato|curto|medio", "responsavel_sugerido": "área responsável"}
  ],
  "risco_depois": {
    "probabilidade": 1,
    "probabilidade_rotulo": "Raro|Improvável|Possível|Provável|Quase certo",
    "consequencia": 1,
    "consequencia_rotulo": "Desprezível|Menor|Moderada|Maior|Catastrófica",
    "justificativa": "risco residual esperado depois de executado o plano de ação"
  },
  "informacoes_a_coletar": ["o que a equipe de investigação precisa levantar (relatos, notificação, laudos) e que não está no material"],
  "lacunas_de_dados": ["dados ausentes no registro que limitam a análise"]
}"""


def _bloco_indicadores(indicadores: list[dict]) -> str:
    linhas = [f"- {i['rotulo']}: {i['valor']}"
              + (f" ({i['sub']})" if i.get("sub") else "")
              + (f" [{i['situacao'].upper()}]" if i.get("situacao") not in
                 (None, "neutro") else "")
              for i in indicadores]
    return "\n".join(linhas)


def _bloco_atraso(atraso: dict) -> str:
    if not atraso.get("etapas"):
        return "Sem decomposição disponível."
    linhas = []
    for e in atraso["etapas"]:
        if e["valor"] is None:
            linhas.append(f"- {e['rotulo']}: SEM MARCAÇÃO ({e['papel']})")
            continue
        partes = [f"medido {e['valor']}"]
        if e.get("referencia"):
            partes.append(f"referência do serviço {e['referencia']} "
                          f"(n={e['amostra']})")
        if e.get("meta"):
            partes.append(f"meta {e['meta']}"
                          + (" — ESTOUROU" if e["estourou_meta"] else " — ok"))
        if e.get("vezes_referencia"):
            partes.append(f"{e['vezes_referencia']}× a referência")
        linhas.append(f"- {e['rotulo']} ({e['papel']}): " + "; ".join(partes))
    texto = "\n".join(linhas)
    if atraso.get("resumo"):
        texto += f"\n\nLeitura automática: {atraso['resumo']}"
    return texto


def _bloco_fatores_tr(fatores: dict) -> str:
    """Fatores já apurados do tempo de resposta acima de 10 min."""
    if not fatores.get("aplicavel"):
        return fatores.get("motivo", "Tempo de resposta não medido.")
    linhas = [fatores["resumo"]]
    if fatores.get("fatores"):
        linhas.append("Fatores apurados nos dados (com evidência):")
        for f in fatores["fatores"]:
            linhas.append(f"- [{f['tipo']}] {f['titulo']}: {f['evidencia']}")
    return "\n".join(linhas)


def _bloco_ocupacao(inv: dict) -> str:
    if not inv.get("situacoes"):
        return "Não há viatura sediada no município da ocorrência na base."
    linhas = []
    for s in inv["situacoes"]:
        if s["status"] == "ocupada":
            linhas.append(f"- {s['unidade']}: OCUPADA na ocorrência "
                          f"{s['ocorrencia']} ({s['desde']} a {s['ate']}) "
                          f"— {s['detalhe']}")
        elif s["status"] == "atendeu":
            linhas.append(f"- {s['unidade']}: foi a viatura que atendeu")
        else:
            linhas.append(f"- {s['unidade']}: sem empenho registrado no "
                          f"instante ({s['detalhe']})")
    return "\n".join(linhas)


def _bloco_cadeia(inv: dict) -> str:
    """Marcações do chamado — inclusive as que faltam (onde o fluxo parou)."""
    linhas = []
    for m in inv.get("cadeia") or []:
        if m["hora"]:
            linhas.append(f"- {m['rotulo']}: {m['hora']}"
                          + (f" (+{m['desde_anterior']} da etapa anterior)"
                             if m["desde_anterior"] else "")
                          + (f" — {m['papel']}" if m["papel"] else ""))
        else:
            linhas.append(f"- {m['rotulo']}: SEM REGISTRO")
    return "\n".join(linhas) or "Sem marcações registradas."


def montar_prompt(dossie: dict, texto_prontuario: str = "") -> str:
    """Monta o material da análise a partir do dossiê já calculado."""
    inv = dossie["investigacao"]
    com_empenho = inv.get("com_empenho", True)
    partes = [
        "# Ocorrência sob análise",
        f"Número: {inv['ocorrencia']}",
        f"Momento de referência: {inv['momento']}",
        f"Município da ocorrência: {inv['cidade'] or '—'}",
        f"Situação do atendimento: {inv.get('situacao') or '—'}",
    ]
    if com_empenho:
        partes += [
            f"Viatura que atendeu: {inv['unidade']} "
            f"(sediada em {inv['municipio_unidade'] or '—'})",
            f"Viatura de outro município: "
            f"{'SIM' if inv['fora_do_municipio'] else 'não'}",
            f"Tempo de resposta: {inv['tempo_resposta'] or 'não calculado'}",
        ]
    else:
        partes += [
            "ATENÇÃO: este chamado foi encerrado SEM despacho de viatura. "
            "Não há tempo de resposta nem etapas de deslocamento. A análise "
            "deve tratar da condução do chamado na central (recepção, "
            "qualificação e decisão da regulação) e da adequação do "
            "desfecho, não de atraso de viatura.",
        ]
    partes += [
        f"Código/gravidade: {inv['codigo'] or '—'} · "
        f"risco na triagem: {inv['risco'] or '—'}",
        f"Motivo: {inv['motivo'] or '—'} · tipo: {inv.get('tipo') or '—'}",
        "",
        "# Cadeia de marcações do chamado",
        _bloco_cadeia(inv),
        "",
        "# Indicadores medidos deste atendimento",
        _bloco_indicadores(dossie.get("indicadores") or []),
        "",
    ]
    if com_empenho:
        partes += [
            "# Tempo de resposta frente à meta de 10 minutos",
            _bloco_fatores_tr(dossie.get("fatores_tr") or {}),
            "",
        ]
    partes += [
        "# Decomposição do tempo, etapa por etapa",
        "(a 'referência do serviço' é a mediana do próprio SAMU em casos "
        "comparáveis — mesmo código de gravidade e tipo de viatura)",
        _bloco_atraso(dossie.get("atraso") or {}),
        "",
        "# Disponibilidade das viaturas do município no momento de referência",
        _bloco_ocupacao(inv),
        f"Conclusão automática: {inv['veredito']}",
        "OBS: 'sem empenho registrado' não prova que a viatura estava "
        "operacional — pode estar fora de escala ou em manutenção, o que o "
        "relatório não informa.",
    ]
    if texto_prontuario:
        partes += ["", "# Prontuário do atendimento (texto extraído do PDF)",
                   texto_prontuario[:12000]]
    partes += [
        "",
        "# Tarefa",
        ("Este chamado NÃO teve viatura despachada: analise a condução na "
         "central e o desfecho. Se todas as viaturas do município estavam "
         "ocupadas, considere a hipótese de a decisão ter sido condicionada "
         "pela falta de recurso — e diga se os dados sustentam ou não essa "
         "hipótese. Não avalie tempo de resposta nem deslocamento."
         if not com_empenho else
         "A meta de tempo de resposta do serviço é 10 minutos. A prioridade "
         "da análise é explicar o que fez este atendimento passar (ou não) "
         "dessa meta: distância do trajeto, condição do percurso (trânsito, "
         "rota, acesso), origem da viatura, indisponibilidade das viaturas "
         "locais e atrasos nas etapas de processo (P1 a P4.1). Use os "
         "fatores já apurados acima — eles vêm com o número que os sustenta "
         "— e diga quais são evitáveis pelo serviço e quais são estruturais."),
        "",
        "Redija o formulário FOR.SAMU.038 — Relatório de Evento Adverso "
        "com Investigação de Causa Raiz (RAC), pelo Protocolo de Londres. "
        "Complemente com um diagrama de Ishikawa (6M).",
        "",
        "Nos FATORES CONTRIBUINTES, percorra as SETE categorias abaixo, "
        "nesta ordem, marcando apenas os itens listados em cada uma e "
        "apenas quando o material trouxer evidência. Categoria sem "
        "evidência: itens vazios e descrição 'Não foi identificado.'.",
        _lista_fatores(),
        "",
        "Na matriz de risco use a escala do formulário: probabilidade de 1 "
        "(Raro) a 5 (Quase certo) e consequência em 1 (Desprezível), 2 "
        "(Menor), 4 (Moderada), 8 (Maior) ou 16 (Catastrófica) — a "
        "classificação é o produto das duas. Avalie o risco ANTES da "
        "investigação e o risco residual DEPOIS de executado o plano de "
        "ação.",
        "",
        "Responda no formato JSON abaixo, preenchendo todos os campos:",
        ESQUEMA,
    ]
    return "\n".join(partes)


def _lista_fatores() -> str:
    """Lista fechada de categorias e itens do formulário."""
    from app.modules.investigacao.constants import FATORES_CONTRIBUINTES

    linhas = []
    for categoria, itens in FATORES_CONTRIBUINTES:
        linhas.append(f"{categoria}:")
        linhas += [f"  - {i}" for i in itens]
    return "\n".join(linhas)


def analisar(db: Session, empresa_id: int, dossie: dict,
             texto_prontuario: str = "", anonimizar: bool = True,
             nomes: list[str] | None = None, feedback: str = "") -> dict:
    """Gera uma versão do RAC e persiste. Levanta ia.IAError em falha.

    Com `feedback`, produz uma NOVA versão a partir da anterior: o
    histórico completo (relatório e ajustes já pedidos) vai no prompt,
    para o modelo corrigir o que foi apontado sem desfazer o que já
    estava aprovado pela equipe.
    """
    cfg = ia.configuracao(db, empresa_id)
    texto = texto_prontuario or ""
    if texto and anonimizar:
        texto = ia.anonimizar_texto(texto, nomes)

    numero = dossie["investigacao"]["ocorrencia"]
    anteriores = historico(db, empresa_id, numero)
    prompt = montar_prompt(dossie, texto)
    if feedback and anteriores:
        prompt += "\n\n" + _bloco_revisao(anteriores, feedback)
    bruto = ia.gerar(db, prompt, SISTEMA, empresa_id, json_esperado=True)
    dados = ia.extrair_json(bruto)
    if dados is None:
        amostra = " ".join((bruto or "").split())[:180]
        raise ia.IAError(
            "A IA respondeu em formato inesperado (esperava JSON). "
            + (f'Início da resposta: "{amostra}…". ' if amostra
               else "A resposta veio vazia. ")
            + "Modelos pequenos costumam falhar nisso — tente um modelo "
              "maior ou outro provedor.")

    # Versões anteriores passam a "substituído" — o histórico permanece,
    # mas a versão corrente é sempre a última.
    for antiga in anteriores:
        if antiga.status == STATUS_PENDENTE:
            antiga.status = STATUS_SUBSTITUIDO

    registro = AnaliseOcorrencia(
        empresa_id=empresa_id, ocorrencia=numero,
        versao=(anteriores[0].versao + 1) if anteriores else 1,
        status=STATUS_PENDENTE,
        provedor=cfg["provedor"], modelo=cfg["modelo"],
        anonimizado=bool(anonimizar), com_prontuario=bool(texto),
        resultado=json.dumps(dados, ensure_ascii=False)[:1_000_000],
        bruto=bruto[:1_000_000], feedback=(feedback or None),
        gerado_em=datetime.now(timezone.utc))
    db.add(registro)
    db.commit()
    return _formatar(registro)


def historico(db: Session, empresa_id: int, ocorrencia: str
              ) -> list[AnaliseOcorrencia]:
    """Versões do relatório da ocorrência, da mais recente para a mais antiga."""
    return list(db.scalars(
        select(AnaliseOcorrencia)
        .where(AnaliseOcorrencia.empresa_id == empresa_id,
               AnaliseOcorrencia.ocorrencia == ocorrencia,
               AnaliseOcorrencia.deleted_at.is_(None))
        .order_by(AnaliseOcorrencia.versao.desc())))


def _bloco_revisao(anteriores: list[AnaliseOcorrencia], feedback: str) -> str:
    """Relatório anterior + todos os ajustes já pedidos."""
    ultimo = anteriores[0]
    partes = [
        "# REVISÃO SOLICITADA",
        "A equipe de investigação analisou o relatório anterior e pediu "
        "ajustes. Produza uma NOVA versão completa do relatório, no mesmo "
        "formato JSON, corrigindo o que foi apontado e PRESERVANDO o que "
        "não foi questionado. Não repita erros já corrigidos em revisões "
        "anteriores.",
        "",
        f"## Relatório anterior (versão {ultimo.versao})",
        ultimo.resultado[:20000],
        "",
        "## Ajuste pedido agora pela equipe",
        feedback.strip(),
    ]
    passados = [a for a in anteriores if a.feedback]
    if passados:
        partes += ["", "## Ajustes já pedidos em revisões anteriores "
                       "(não reintroduza esses problemas)"]
        partes += [f"- versão {a.versao}: {a.feedback}" for a in
                   reversed(passados)]
    return "\n".join(partes)


def ultima_analise(db: Session, empresa_id: int, ocorrencia: str) -> dict | None:
    """Análise mais recente já feita para a ocorrência (se houver)."""
    versoes = historico(db, empresa_id, ocorrencia)
    return _formatar(versoes[0]) if versoes else None


def _preparar_risco(risco: dict | None) -> dict | None:
    """Calcula C = A × B e o nível, sem depender do que a IA disse."""
    from app.modules.investigacao.constants import nivel_de_risco

    if not isinstance(risco, dict):
        return None
    try:
        prob = int(risco.get("probabilidade") or 0)
        cons = int(risco.get("consequencia") or 0)
    except (TypeError, ValueError):
        return None
    if not (1 <= prob <= 5) or cons not in (1, 2, 4, 8, 16):
        return None
    pontos = prob * cons
    nivel, cor = nivel_de_risco(pontos)
    return {**risco, "probabilidade": prob, "consequencia": cons,
            "classificacao": pontos, "nivel": nivel, "cor": cor}


def _preparar_fatores(fatores) -> list[dict]:
    """Casa o que a IA devolveu com a lista fechada do formulário.

    Garante as sete categorias na ordem oficial e descarta item marcado
    que não exista naquela categoria — o formulário não admite item
    inventado.
    """
    from app.modules.investigacao.constants import FATORES_CONTRIBUINTES

    por_categoria = {}
    for f in (fatores if isinstance(fatores, list) else []):
        if isinstance(f, dict) and f.get("categoria"):
            por_categoria[str(f["categoria"]).strip().casefold()] = f

    resultado = []
    for categoria, itens_validos in FATORES_CONTRIBUINTES:
        f = por_categoria.get(categoria.casefold(), {})
        marcados = f.get("itens") if isinstance(f.get("itens"), list) else []
        validos = {i.casefold(): i for i in itens_validos}
        marcados = [validos[str(m).strip().casefold()] for m in marcados
                    if str(m).strip().casefold() in validos]
        descricao = str(f.get("descricao") or "").strip()
        if not descricao:
            # "Não foi identificado." só cabe quando nada foi marcado —
            # com item marcado seria contraditório no formulário.
            descricao = ("Fator marcado, sem detalhamento na análise."
                         if marcados else "Não foi identificado.")
        resultado.append({
            "categoria": categoria,
            "itens": [{"texto": i, "marcado": i in marcados}
                      for i in itens_validos],
            "tem_marcado": bool(marcados),
            "descricao": descricao,
        })
    return resultado


def cronologia_do_sistema(inv: dict) -> list[dict]:
    """Cronologia factual, montada das marcações — não da IA.

    Datas e horários são o núcleo probatório do relatório; deixá-los a
    cargo do modelo já produziu datas erradas. Aqui saem exatamente as
    marcações registradas no vSky.
    """
    eventos = []
    for m in inv.get("cadeia") or []:
        if not m.get("hora"):
            continue
        texto = m["rotulo"]
        if m.get("papel"):
            texto += f" — {m['papel']}"
        if m.get("desde_anterior"):
            texto += f" (+{m['desde_anterior']} da etapa anterior)"
        eventos.append({"quando": m["hora"], "evento": texto,
                        "origem": "marcação do sistema"})
    return eventos


def _formatar(registro: AnaliseOcorrencia) -> dict:
    try:
        conteudo = json.loads(registro.resultado)
    except (TypeError, json.JSONDecodeError):
        conteudo = {}
    if conteudo:
        conteudo["fatores_contribuintes"] = _preparar_fatores(
            conteudo.get("fatores_contribuintes"))
        conteudo["risco_antes"] = _preparar_risco(conteudo.get("risco_antes"))
        conteudo["risco_depois"] = _preparar_risco(conteudo.get("risco_depois"))
    # Risco pós-investigação registrado pela equipe prevalece sobre a
    # estimativa da IA — é a avaliação institucional do documento.
    registrado = None
    if registro.risco_pos_probabilidade and registro.risco_pos_consequencia:
        registrado = _preparar_risco({
            "probabilidade": registro.risco_pos_probabilidade,
            "consequencia": registro.risco_pos_consequencia,
            "probabilidade_rotulo": _rotulo_probabilidade(
                registro.risco_pos_probabilidade),
            "consequencia_rotulo": _rotulo_consequencia(
                registro.risco_pos_consequencia),
            "justificativa": registro.risco_pos_justificativa or "",
        })
    return {
        "id": registro.id,
        "versao": registro.versao,
        "status": registro.status,
        "feedback": registro.feedback,
        "provedor": ia.PROVEDORES.get(registro.provedor, registro.provedor),
        "modelo": registro.modelo,
        "anonimizado": registro.anonimizado,
        "com_prontuario": registro.com_prontuario,
        "gerado_em": (registro.gerado_em.strftime("%d/%m/%Y %H:%M")
                      if registro.gerado_em else ""),
        "aprovado_em": (registro.aprovado_em.strftime("%d/%m/%Y %H:%M")
                        if registro.aprovado_em else None),
        "aprovado_nome": registro.aprovado_nome,
        "risco_pos_registrado": registrado,
        "notificacao_data": registro.notificacao_data,
        "time_investigacao": registro.time_investigacao,
        "investigacao_inicio": (registro.investigacao_inicio
                                or (registro.gerado_em.strftime("%d/%m/%Y")
                                    if registro.gerado_em else None)),
        **conteudo,
    }


def _rotulo_probabilidade(valor: int) -> str:
    from app.modules.investigacao.constants import PROBABILIDADE
    return next((n for v, n, _ in PROBABILIDADE if v == valor), "")


def _rotulo_consequencia(valor: int) -> str:
    from app.modules.investigacao.constants import CONSEQUENCIA
    return next((n for v, n, _ in CONSEQUENCIA if v == valor), "")
