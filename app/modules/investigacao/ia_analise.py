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
from app.modules.investigacao.models import AnaliseOcorrencia

SISTEMA = (
    "Você é um analista de segurança do paciente de um SAMU (serviço de "
    "atendimento móvel de urgência) brasileiro, com experiência em análise "
    "de eventos assistenciais. Responde sempre em português do Brasil, com "
    "objetividade e sem floreio.\n\n"
    "Regras invioláveis:\n"
    "1. Baseie-se apenas nos dados fornecidos. Não invente horários, nomes, "
    "condutas ou fatos que não estejam no material.\n"
    "2. Quando um dado faltar, diga que falta — é achado relevante, não "
    "lacuna a preencher com suposição.\n"
    "3. Analise processos e sistema, não pessoas. Não atribua culpa "
    "individual nem sugira punição.\n"
    "4. Distinga claramente o que é fato registrado do que é hipótese sua.\n"
    "5. Responda SOMENTE com um objeto JSON válido, sem texto fora dele."
)

ESQUEMA = """{
  "sintese": "2-3 frases sobre o que aconteceu e o que chama atenção",
  "tempo_resposta": {
    "acima_da_meta": true,
    "causa_predominante": "distancia|percurso|transito|origem_da_viatura|processo|indisponibilidade|indeterminado",
    "explicacao": "por que o tempo passou de 10 min, citando os números apurados",
    "fatores": [
      {"fator": "o que contribuiu", "tipo": "distancia|percurso|transito|origem_da_viatura|processo|indisponibilidade",
       "evidencia": "o número que sustenta", "evitavel": "sim|parcialmente|nao",
       "o_que_fazer": "ação concreta para reduzir este fator"}
    ]
  },
  "londres": {
    "incidente": "o que ocorreu, em uma frase",
    "falhas_ativas": ["ações ou omissões na ponta que afetaram o caso"],
    "fatores_contribuintes": [
      {"categoria": "Paciente|Tarefa e tecnologia|Indivíduo|Equipe|Ambiente de trabalho|Organização e gestão|Contexto institucional",
       "fator": "descrição objetiva",
       "evidencia": "o dado que sustenta"}
    ],
    "barreiras_que_falharam": ["controles que deveriam ter evitado"],
    "recomendacoes": [
      {"acao": "o que fazer", "prazo": "imediato|curto|medio",
       "responsavel_sugerido": "área", "tipo": "processo|treinamento|tecnologia|estrutura"}
    ]
  },
  "ishikawa": {
    "efeito": "problema central, mensurável",
    "espinhas": [
      {"categoria": "Método|Mão de obra|Máquina|Material|Medida|Meio ambiente",
       "causas": ["causa provável 1", "causa provável 2"]}
    ]
  },
  "matriz_risco": {
    "probabilidade": "raro|improvavel|possivel|provavel|quase_certo",
    "impacto": "insignificante|menor|moderado|maior|catastrofico",
    "nivel": "baixo|moderado|alto|extremo",
    "justificativa": "por que essa combinação",
    "mitigacoes": ["medida para reduzir probabilidade ou impacto"]
  },
  "lacunas_de_dados": ["informações que faltaram e limitam a análise"]
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
        "Analise o evento com três instrumentos: (1) Protocolo de Londres "
        "(análise de causa raiz de incidentes assistenciais), (2) Diagrama "
        "de Ishikawa (6M) e (3) matriz de risco probabilidade × impacto.",
        "Responda no formato JSON abaixo, preenchendo todos os campos:",
        ESQUEMA,
    ]
    return "\n".join(partes)


def analisar(db: Session, empresa_id: int, dossie: dict,
             texto_prontuario: str = "", anonimizar: bool = True,
             nomes: list[str] | None = None) -> dict:
    """Chama a IA e persiste o resultado. Levanta ia.IAError em falha."""
    cfg = ia.configuracao(db, empresa_id)
    texto = texto_prontuario or ""
    if texto and anonimizar:
        texto = ia.anonimizar_texto(texto, nomes)

    prompt = montar_prompt(dossie, texto)
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

    registro = AnaliseOcorrencia(
        empresa_id=empresa_id,
        ocorrencia=dossie["investigacao"]["ocorrencia"],
        provedor=cfg["provedor"], modelo=cfg["modelo"],
        anonimizado=bool(anonimizar), com_prontuario=bool(texto),
        resultado=json.dumps(dados, ensure_ascii=False)[:1_000_000],
        bruto=bruto[:1_000_000],
        gerado_em=datetime.now(timezone.utc))
    db.add(registro)
    db.commit()
    return _formatar(registro)


def ultima_analise(db: Session, empresa_id: int, ocorrencia: str) -> dict | None:
    """Análise mais recente já feita para a ocorrência (se houver)."""
    registro = db.scalar(
        select(AnaliseOcorrencia)
        .where(AnaliseOcorrencia.empresa_id == empresa_id,
               AnaliseOcorrencia.ocorrencia == ocorrencia,
               AnaliseOcorrencia.deleted_at.is_(None))
        .order_by(AnaliseOcorrencia.id.desc()))
    return _formatar(registro) if registro else None


def _formatar(registro: AnaliseOcorrencia) -> dict:
    try:
        conteudo = json.loads(registro.resultado)
    except (TypeError, json.JSONDecodeError):
        conteudo = {}
    return {
        "id": registro.id,
        "provedor": ia.PROVEDORES.get(registro.provedor, registro.provedor),
        "modelo": registro.modelo,
        "anonimizado": registro.anonimizado,
        "com_prontuario": registro.com_prontuario,
        "gerado_em": (registro.gerado_em.strftime("%d/%m/%Y %H:%M")
                      if registro.gerado_em else ""),
        **conteudo,
    }
