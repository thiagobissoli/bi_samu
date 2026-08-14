"""Relatório RAC em PDF, no layout do formulário FOR.SAMU.038 (§35.16).

Reproduz o documento oficial: cabeçalho repetido em toda página, seções
com faixa cinza, matriz de risco 5×5 colorida e as caixas de marcação
dos fatores contribuintes. Ao final, um anexo com os dados operacionais
apurados pelo sistema (indicadores, decomposição do tempo e
disponibilidade das viaturas) — é a evidência que sustenta a análise.

Campos que dependem de apuração humana (relatos dos envolvidos,
notificação do NCPS, time de investigação) saem como linhas em branco
para preenchimento, nunca preenchidos por suposição.
"""

from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether,
                                PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

from app.modules.investigacao.constants import (CONSEQUENCIA, GRAVIDADES,
                                                PROBABILIDADE, nivel_de_risco)

FORMULARIO = "FOR.SAMU.038"
VERSAO = "00"
ELABORACAO = "17/01/2024"
MARGEM = 15 * mm
ALTURA_CABECALHO = 26 * mm

CINZA_FAIXA = colors.HexColor("#d9d9d9")
BORDA = colors.HexColor("#7f7f7f")
CORES_RISCO = {"Extremo": colors.HexColor("#e74c3c"),
               "Elevado": colors.HexColor("#e67e22"),
               "Moderado": colors.HexColor("#f4d03f"),
               "Baixo": colors.HexColor("#a9d18e")}

_estilos = getSampleStyleSheet()
P = ParagraphStyle("corpo", parent=_estilos["Normal"], fontName="Helvetica",
                   fontSize=8, leading=10.5)
P_NEGRITO = ParagraphStyle("corpoN", parent=P, fontName="Helvetica-Bold")
P_PEQ = ParagraphStyle("peq", parent=P, fontSize=7, leading=9)
P_CENTRO = ParagraphStyle("centro", parent=P, alignment=TA_CENTER)
P_CENTRO_PEQ = ParagraphStyle("centroPeq", parent=P_PEQ, alignment=TA_CENTER)


def _cabecalho(canvas, doc, logo=None):
    """Cabeçalho e rodapé repetidos em todas as páginas."""
    canvas.saveState()
    largura, altura = A4
    topo = altura - MARGEM
    esquerda, direita = MARGEM, largura - MARGEM
    col_logo = esquerda + 45 * mm

    canvas.setStrokeColor(BORDA)
    canvas.setLineWidth(0.7)
    canvas.rect(esquerda, topo - ALTURA_CABECALHO, direita - esquerda,
                ALTURA_CABECALHO)
    canvas.line(col_logo, topo, col_logo, topo - ALTURA_CABECALHO)
    canvas.line(col_logo, topo - 8.5 * mm, direita, topo - 8.5 * mm)
    canvas.line(col_logo, topo - 17.5 * mm, direita, topo - 17.5 * mm)

    if logo is not None:
        try:
            canvas.drawImage(logo, esquerda + 12 * mm, topo - 23 * mm,
                             width=21 * mm, height=19 * mm,
                             preserveAspectRatio=True, mask="auto")
        except Exception:      # noqa: BLE001 — logo inválida não impede o PDF
            logo = None
    if logo is None:
        canvas.setFont("Helvetica-Bold", 13)
        canvas.setFillColor(colors.HexColor("#c0392b"))
        canvas.drawCentredString((esquerda + col_logo) / 2, topo - 15 * mm,
                                 "SAMU 192")
    canvas.setFillColor(colors.black)

    canvas.setFont("Helvetica", 9)
    canvas.drawCentredString((col_logo + direita) / 2, topo - 6 * mm,
                             "FORMULÁRIO – Qualidade")
    canvas.setFont("Helvetica-BoldOblique", 9)
    canvas.drawCentredString(
        (col_logo + direita) / 2, topo - 14 * mm,
        "Relatório de Evento Adverso com Investigação de Causa Raiz (RAC)")
    canvas.setFont("Helvetica", 8)
    terco = (direita - col_logo) / 3
    canvas.line(col_logo + terco, topo - 17.5 * mm,
                col_logo + terco, topo - ALTURA_CABECALHO)
    canvas.line(col_logo + 2 * terco, topo - 17.5 * mm,
                col_logo + 2 * terco, topo - ALTURA_CABECALHO)
    canvas.drawString(col_logo + 2 * mm, topo - 22.5 * mm,
                      f"Código: {FORMULARIO}")
    canvas.drawString(col_logo + terco + 2 * mm, topo - 22.5 * mm,
                      f"Versão: {VERSAO}")
    canvas.drawString(col_logo + 2 * terco + 2 * mm, topo - 22.5 * mm,
                      f"Elaboração: {ELABORACAO}")

    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#7f7f7f"))
    canvas.drawRightString(direita, MARGEM - 6 * mm, f"Pág. {doc.page}")
    canvas.restoreState()


def _faixa(titulo: str) -> Table:
    """Faixa cinza de seção, como no formulário."""
    t = Table([[Paragraph(f"<b>{titulo}</b>", P_CENTRO)]],
              colWidths=[180 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CINZA_FAIXA),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDA),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _tabela(dados, larguras, estilo_extra=None) -> Table:
    t = Table(dados, colWidths=larguras)
    estilo = [
        ("GRID", (0, 0), (-1, -1), 0.7, BORDA),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    t.setStyle(TableStyle(estilo + (estilo_extra or [])))
    return t


def _marcacao(marcado: bool) -> str:
    return "( <b>X</b> )" if marcado else "(&nbsp;&nbsp;&nbsp;)"


def _matriz_risco(risco: dict | None) -> list:
    """Matriz 5×5 colorida com a célula escolhida destacada."""
    if not risco:
        return [Paragraph("Não avaliado.", P)]

    cabecalho = [Paragraph("<b>PROBABILIDADE<br/>(frequência)</b>", P_CENTRO_PEQ)]
    cabecalho += [Paragraph(f"<b>{nome}</b><br/>({valor})", P_CENTRO_PEQ)
                  for valor, nome, _ in CONSEQUENCIA]
    linhas = [cabecalho]
    estilo = [("SPAN", (0, 0), (0, 0))]

    for i, (p, pnome, _) in enumerate(PROBABILIDADE, start=1):
        linha = [Paragraph(f"<b>{pnome}</b> ({p})", P_CENTRO_PEQ)]
        for j, (c, _, _) in enumerate(CONSEQUENCIA, start=1):
            pontos = p * c
            nivel, _cor = nivel_de_risco(pontos)
            escolhida = (risco["probabilidade"] == p
                         and risco["consequencia"] == c)
            texto = f"<b>{pontos}</b>" if escolhida else str(pontos)
            linha.append(Paragraph(texto, P_CENTRO_PEQ))
            estilo.append(("BACKGROUND", (j, i), (j, i), CORES_RISCO[nivel]))
            if escolhida:
                estilo += [("BOX", (j, i), (j, i), 2.0, colors.black)]
        linhas.append(linha)

    largura_col = 30 * mm
    matriz = _tabela(linhas, [30 * mm] + [largura_col] * 5, estilo)

    nivel = risco["nivel"]
    abc = _tabela(
        [[Paragraph("<b>A</b><br/>Probabilidade (1 a 5)", P_CENTRO_PEQ),
          Paragraph("<b>B</b><br/>Consequência (1 a 16)", P_CENTRO_PEQ),
          Paragraph("<b>C</b><br/>Classificação (C = A × B)", P_CENTRO_PEQ)],
         [Paragraph(f"{risco['probabilidade']} · "
                    f"{risco.get('probabilidade_rotulo', '')}", P_CENTRO),
          Paragraph(f"{risco['consequencia']} · "
                    f"{risco.get('consequencia_rotulo', '')}", P_CENTRO),
          Paragraph(f"<b>{risco['classificacao']} — risco {nivel.lower()}</b>",
                    P_CENTRO)]],
        [60 * mm, 60 * mm, 60 * mm],
        [("BACKGROUND", (2, 1), (2, 1), CORES_RISCO[nivel])])

    saida = [matriz, Spacer(1, 3), abc]
    if risco.get("justificativa"):
        saida += [Spacer(1, 3), Paragraph(risco["justificativa"], P_PEQ)]
    return saida


def _dados_gerais(inv: dict, g: dict, analise: dict) -> list:
    gravidade = " ".join(
        f"{nivel} {_marcacao(g.get('gravidade') == nivel)}"
        for nivel in GRAVIDADES)
    linhas = [
        [Paragraph("<b>Título da Investigação:</b> "
                   + (g.get("titulo_investigacao") or "—"), P)],
        [Paragraph("<b>Descrição do Incidente:</b> "
                   + (g.get("descricao_incidente") or "—"), P)],
        [Paragraph(f"<b>Gravidade:</b> {gravidade}"
                   + (f"<br/>{g['gravidade_justificativa']}"
                      if g.get("gravidade_justificativa") else ""), P)],
    ]
    tabela_larga = _tabela(linhas, [180 * mm])

    def _ou_linha(valor, tamanho=22):
        """Valor preenchido, ou uma linha para preencher à mão."""
        return valor if valor else "_" * tamanho

    idade = inv.get("idade")
    local = " · ".join(x for x in (inv.get("unidade"),
                                   inv.get("endereco") or inv.get("cidade"),
                                   inv.get("momento")) if x)
    pares = _tabela([
        [Paragraph(f"<b>Data do Incidente:</b> {inv.get('momento', '—')}", P),
         Paragraph("<b>Data da Notificação:</b> "
                   + _ou_linha(analise.get("notificacao_data")), P)],
        [Paragraph(f"<b>Local e Horário da Ocorrência:</b> {local or '—'}", P),
         Paragraph("<b>Data do Início da Investigação:</b> "
                   + _ou_linha(analise.get("investigacao_inicio")), P)],
        [Paragraph("<b>Nome do Paciente:</b> "
                   + (inv.get("paciente_iniciais") or _ou_linha(None)), P),
         Paragraph("<b>Idade:</b> "
                   + (f"{idade} anos" if idade else _ou_linha(None, 10))
                   + (f" · Sexo: {inv['sexo']}" if inv.get("sexo") else ""), P)],
        [Paragraph(f"<b>ID da Ocorrência:</b> {inv.get('ocorrencia', '—')}", P),
         Paragraph("<b>Nível de investigação:</b> "
                   + (g.get("nivel_investigacao") or "Análise de Causa Raiz"), P)],
        [Paragraph("<b>Time de Investigação:</b> "
                   + _ou_linha(analise.get("time_investigacao"), 40), P),
         Paragraph("", P)],
    ], [90 * mm, 90 * mm])
    return [tabela_larga, pares]


def _fatores(fatores: list[dict]) -> list:
    saida = []
    for f in fatores or []:
        itens = "<br/>".join(f"{_marcacao(i['marcado'])} {i['texto']}"
                             for i in f["itens"])
        bloco = _tabela([[Paragraph(f"<b>{f['categoria']}</b>", P),
                          Paragraph(itens, P)],
                         [Paragraph(f.get("descricao") or
                                    "Não foi identificado.", P)]],
                        [55 * mm, 125 * mm],
                        [("SPAN", (0, 1), (1, 1))])
        saida += [KeepTogether([bloco]), Spacer(1, 4)]
    return saida


def _anexo_operacional(dossie: dict) -> list:
    """Evidência apurada pelo sistema, que sustenta a análise."""
    inv = dossie.get("investigacao") or {}
    saida = [_faixa("ANEXO — DADOS OPERACIONAIS APURADOS PELO SISTEMA"),
             Spacer(1, 4)]

    cadeia = [c for c in (inv.get("cadeia") or [])]
    if cadeia:
        linhas = [[Paragraph("<b>Marcação</b>", P_PEQ),
                   Paragraph("<b>Horário</b>", P_PEQ),
                   Paragraph("<b>Desde a anterior</b>", P_PEQ)]]
        linhas += [[Paragraph(c["rotulo"], P_PEQ),
                    Paragraph(c["hora"] or "sem registro", P_PEQ),
                    Paragraph(c["desde_anterior"] or "", P_PEQ)]
                   for c in cadeia]
        saida += [Paragraph("<b>Cadeia de marcações do chamado</b>", P),
                  Spacer(1, 2),
                  _tabela(linhas, [70 * mm, 60 * mm, 50 * mm]), Spacer(1, 6)]

    atraso = dossie.get("atraso") or {}
    if atraso.get("etapas"):
        linhas = [[Paragraph("<b>Etapa</b>", P_PEQ),
                   Paragraph("<b>Medido</b>", P_PEQ),
                   Paragraph("<b>Meta</b>", P_PEQ),
                   Paragraph("<b>Referência do serviço</b>", P_PEQ),
                   Paragraph("<b>Comparação</b>", P_PEQ)]]
        for e in atraso["etapas"]:
            linhas.append([
                Paragraph(e["rotulo"], P_PEQ),
                Paragraph(e["valor"] or "—", P_PEQ),
                Paragraph((e.get("meta") or "—")
                          + (" (estourou)" if e.get("estourou_meta") else ""),
                          P_PEQ),
                Paragraph((e.get("referencia") or "—")
                          + (f" (n={e['amostra']})" if e.get("amostra") else ""),
                          P_PEQ),
                Paragraph(f"{e['vezes_referencia']}×"
                          if e.get("vezes_referencia") else "—", P_PEQ)])
        saida += [Paragraph("<b>Decomposição do tempo, etapa por etapa</b>", P),
                  Spacer(1, 2),
                  _tabela(linhas, [50 * mm, 22 * mm, 30 * mm, 48 * mm, 30 * mm]),
                  Spacer(1, 2),
                  Paragraph(atraso.get("resumo") or "", P_PEQ), Spacer(1, 6)]

    fatores_tr = dossie.get("fatores_tr") or {}
    if fatores_tr.get("aplicavel") and fatores_tr.get("fatores"):
        linhas = [[Paragraph("<b>Fator</b>", P_PEQ),
                   Paragraph("<b>Evidência</b>", P_PEQ)]]
        linhas += [[Paragraph(f["titulo"], P_PEQ),
                    Paragraph(f["evidencia"], P_PEQ)]
                   for f in fatores_tr["fatores"]]
        saida += [Paragraph(f"<b>Tempo de resposta — {fatores_tr['resumo']}</b>",
                            P), Spacer(1, 2),
                  _tabela(linhas, [55 * mm, 125 * mm]), Spacer(1, 6)]

    if inv.get("situacoes"):
        linhas = [[Paragraph("<b>Viatura</b>", P_PEQ),
                   Paragraph("<b>Situação no momento</b>", P_PEQ),
                   Paragraph("<b>Detalhe</b>", P_PEQ)]]
        rotulo = {"ocupada": "Ocupada", "atendeu": "Atendeu esta ocorrência",
                  "sem_empenho": "Sem empenho registrado"}
        for s in inv["situacoes"]:
            situacao = rotulo.get(s["status"], s["status"])
            if s.get("ocorrencia"):
                situacao += (f" — oc. {s['ocorrencia']} "
                             f"({s['desde']} a {s['ate']})")
            linhas.append([Paragraph(s["unidade"], P_PEQ),
                           Paragraph(situacao, P_PEQ),
                           Paragraph(s.get("detalhe") or "", P_PEQ)])
        saida += [
            Paragraph("<b>Disponibilidade das viaturas do município</b>", P),
            Spacer(1, 2), _tabela(linhas, [45 * mm, 80 * mm, 55 * mm]),
            Spacer(1, 2),
            Paragraph("<i>“Sem empenho registrado” indica apenas ausência de "
                      "atendimento no instante; a viatura pode estar fora de "
                      "escala ou em manutenção, o que o relatório do vSky não "
                      "informa.</i>", P_PEQ)]
    return saida


def gerar_rac_pdf(dossie: dict, logo_path: str | None = None,
                  gerado_em: datetime | None = None) -> bytes:
    """Monta o RAC completo em PDF. Requer análise já gerada no dossiê."""
    analise = dossie.get("analise_ia") or {}
    inv = dossie.get("investigacao") or {}
    gerado_em = gerado_em or datetime.now()

    buffer = io.BytesIO()
    doc = BaseDocTemplate(
        buffer, pagesize=A4, leftMargin=MARGEM, rightMargin=MARGEM,
        topMargin=MARGEM + ALTURA_CABECALHO + 4 * mm, bottomMargin=MARGEM,
        title=f"RAC {inv.get('ocorrencia', '')}", author="SAMU 192")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                  id="corpo")
    doc.addPageTemplates([PageTemplate(
        id="rac", frames=[frame],
        onPage=lambda c, d: _cabecalho(c, d, logo_path))])

    fluxo: list = []
    fluxo += [_faixa("DADOS GERAIS"), Spacer(1, 4)]
    fluxo += _dados_gerais(inv, analise.get("dados_gerais") or {},
                           analise)
    fluxo += [Spacer(1, 8)]

    fluxo += [_faixa("AVALIAÇÃO DO RISCO GERAL ANTES DA INVESTIGAÇÃO"),
              Spacer(1, 4)]
    fluxo += _matriz_risco(analise.get("risco_antes"))
    fluxo += [Spacer(1, 8)]

    cronologia = list(dossie.get("cronologia") or [])
    cronologia += [{"quando": c.get("quando") or "—",
                    "evento": f"{c.get('evento', '')} (relatado no prontuário)"}
                   for c in analise.get("eventos_do_prontuario") or []]
    if cronologia:
        linhas = [[Paragraph(f"<b>{c.get('quando', '')}</b>", P),
                   Paragraph(c.get("evento", ""), P)]
                  for c in cronologia]
        fluxo += [_faixa("CRONOLOGIA DETALHADA DOS EVENTOS"), Spacer(1, 4),
                  _tabela(linhas, [40 * mm, 140 * mm]), Spacer(1, 8)]

    if analise.get("fatores_contribuintes"):
        fluxo += [_faixa("FATORES CONTRIBUINTES"), Spacer(1, 4)]
        fluxo += _fatores(analise["fatores_contribuintes"])
        fluxo += [Spacer(1, 4)]

    ishikawa = analise.get("ishikawa") or {}
    if ishikawa.get("espinhas"):
        linhas = [[Paragraph(f"<b>{e.get('categoria', '')}</b>", P),
                   Paragraph("<br/>".join(f"• {c}" for c in e.get("causas") or []),
                             P)] for e in ishikawa["espinhas"]]
        fluxo += [_faixa("DIAGRAMA DE ISHIKAWA (6M)"), Spacer(1, 4)]
        if ishikawa.get("efeito"):
            fluxo += [Paragraph(f"<b>Efeito:</b> {ishikawa['efeito']}", P),
                      Spacer(1, 3)]
        fluxo += [_tabela(linhas, [45 * mm, 135 * mm]), Spacer(1, 8)]

    fluxo += [_faixa("CONCLUSÃO"), Spacer(1, 4),
              _tabela([[Paragraph(analise.get("conclusao") or "", P)]],
                      [180 * mm]), Spacer(1, 8)]

    if analise.get("plano_acao"):
        linhas = [[Paragraph("<b>#</b>", P_PEQ), Paragraph("<b>Ação</b>", P_PEQ),
                   Paragraph("<b>Prazo</b>", P_PEQ),
                   Paragraph("<b>Tipo</b>", P_PEQ),
                   Paragraph("<b>Responsável</b>", P_PEQ)]]
        for i, x in enumerate(analise["plano_acao"], start=1):
            linhas.append([Paragraph(str(x.get("numero") or i), P_PEQ),
                           Paragraph(x.get("acao", ""), P_PEQ),
                           Paragraph(x.get("prazo", ""), P_PEQ),
                           Paragraph(x.get("tipo", ""), P_PEQ),
                           Paragraph(x.get("responsavel_sugerido", ""), P_PEQ)])
        fluxo += [_faixa("PLANO DE AÇÃO"), Spacer(1, 4),
                  _tabela(linhas, [10 * mm, 95 * mm, 22 * mm, 25 * mm, 28 * mm]),
                  Spacer(1, 8)]

    fluxo += [_faixa("AVALIAÇÃO DO RISCO GERAL PÓS INVESTIGAÇÃO"), Spacer(1, 4)]
    # O risco registrado pela equipe é o oficial; sem ele, sai a
    # estimativa da IA, identificada como tal.
    registrado = analise.get("risco_pos_registrado")
    if registrado:
        fluxo += [Paragraph("Risco registrado pela equipe de investigação"
                            + (f" — {analise['aprovado_nome']}"
                               if analise.get("aprovado_nome") else "")
                            + (f", em {analise['aprovado_em']}"
                               if analise.get("aprovado_em") else "") + ".",
                            P_PEQ), Spacer(1, 3)]
        fluxo += _matriz_risco(registrado)
    else:
        fluxo += [Paragraph("<i>Estimativa da IA — o risco oficial é "
                            "registrado pela equipe na aprovação.</i>", P_PEQ),
                  Spacer(1, 3)]
        fluxo += _matriz_risco(analise.get("risco_depois"))
    fluxo += [Spacer(1, 8)]

    pendencias = []
    for titulo, itens in (("A coletar pela equipe de investigação",
                           analise.get("informacoes_a_coletar")),
                          ("Lacunas no registro que limitam a análise",
                           analise.get("lacunas_de_dados"))):
        if itens:
            pendencias.append([Paragraph(f"<b>{titulo}</b><br/>"
                                         + "<br/>".join(f"• {i}" for i in itens),
                                         P)])
    if pendencias:
        fluxo += [_faixa("PENDÊNCIAS DA INVESTIGAÇÃO"), Spacer(1, 4),
                  _tabela(pendencias, [180 * mm]), Spacer(1, 8)]

    fluxo += _anexo_operacional(dossie)
    fluxo += [Spacer(1, 6),
              Paragraph(
                  "Documento gerado automaticamente em "
                  f"{gerado_em.strftime('%d/%m/%Y às %H:%M')} a partir dos "
                  "registros do vSky. A análise de causa foi produzida com "
                  f"apoio de IA ({analise.get('provedor', '—')} · "
                  f"{analise.get('modelo', '—')}) e <b>requer validação da "
                  "equipe de investigação</b> antes de virar conclusão "
                  "institucional.", P_PEQ)]
    if analise.get("status") == "aprovado":
        fluxo += [Spacer(1, 3),
                  Paragraph(
                      f"<b>Relatório aprovado</b> (versão {analise.get('versao')})"
                      + (f" por {analise['aprovado_nome']}"
                         if analise.get("aprovado_nome") else "")
                      + (f" em {analise['aprovado_em']}"
                         if analise.get("aprovado_em") else "") + ".", P_PEQ)]

    doc.build(fluxo)
    return buffer.getvalue()
