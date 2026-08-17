"""Constantes do módulo Indicadores (§35.2).

Definições de negócio herdadas dos sistemas legados (DBSamu / Desperdicio):
cadeia temporal P1–P9, mapas de cor, convênio Grande Vitória, viaturas ISCMV
e a Escala NEWS modificada.
"""

MODULE_NAME = "indicadores"

DATA_HORA_FMT = "%d/%m/%Y %H:%M:%S"

# Convênio = Grande Vitória (cidades normalizadas sem acento, maiúsculas)
CIDADES_CONVENIO = {"VITORIA", "VILA VELHA", "SERRA", "CARIACICA"}

# ISCMV — 42 viaturas do núcleo (definição curada do projeto Desperdicio):
# USA 10..100 (múltiplas de 10) + USB pares 22..98 não múltiplas de 10.
ISCMV_VIATURAS = (
    {f"USA {n}" for n in range(10, 101, 10)}
    | {f"USB {n}" for n in range(22, 99, 2) if n % 10 != 0}
)

# Código da ocorrência (classificação da equipe) -> cor
MAPA_CODIGO_COR = {
    "vermelho": "vermelho",
    "amarelo": "amarelo",
    "verde": "verde",
    "nao urgente": "nao_urgente",
    "orientacao medica": "orientacao_medica",
}

# Risco inicial (triagem da regulação) -> cor
MAPA_RISCO_COR = {
    "emergencia": "vermelho",
    "muito urgente": "vermelho",
    "urgente": "amarelo",
    "pouco urgente": "verde",
    "nao urgente": "azul",
}

# Adequação código (equipe) x risco (triagem) — assertividade
ADEQUACAO = {
    "vermelho": {"vermelho"},
    "amarelo": {"amarelo"},
    "verde": {"verde"},
}

# SLA (segundos) — P1 geral e P2 por cor (DBSamu §6)
SLA_P1 = 90
SLA_P2_POR_COR = {"vermelho": 90, "amarelo": 180, "verde": 240,
                  "orientacao_medica": 240}

# Metas de tempo (segundos) — página Auditoria de Ocorrências.
# A cadeia fecha por construção: central (4 min) + P4 (6 min) = tempo de
# resposta (10 min); dentro do P4, saída de base (2 min) + deslocamento
# (4 min). Assim o descumprimento de uma etapa explica o da seguinte.
# P2 não entra aqui: a meta varia por cor (SLA_P2_POR_COR). P8 fica sem
# meta — o transporte depende da distância até o hospital, que não é
# escolha da equipe.
# Ajustáveis em /configuracoes pela chave indicadores_meta_<coluna>_segundos.
METAS_TEMPO = {
    "t_central": 240,
    "t_p1": SLA_P1,
    "t_p3": 60,
    "t_p4": 360,
    "t_p4_1": 120,
    "t_p4_2": 240,
    "t_p5_6_7": 900,
    "t_p9": 900,
    "tempo_resposta": 600,
}
PREFIXO_CONFIG_META = "indicadores_meta_"

# Indicadores auditados, na ordem do fluxo do atendimento.
AUDITORIA_INDICADORES = [
    ("t_central", "Tempo de Central", "controlador − abertura"),
    ("t_p1", "P1 · Atendimento TARM", "TARM − abertura"),
    ("t_p2", "P2 · Regulação médica", "regulador − TARM"),
    ("t_p3", "P3 · Despacho", "controlador − regulador"),
    ("t_p4_1", "P4.1 · Saída de base", "início desloc. − controlador"),
    ("t_p4_2", "P4.2 · Deslocamento", "chegada − início desloc."),
    ("t_p4", "P4 · Tempo de chegada", "chegada − controlador"),
    ("tempo_resposta", "Tempo de Resposta", "chegada − abertura · 1ª unidade"),
    ("t_p5_6_7", "P5-7 · Tempo de cena", "saída p/ hospital − chegada"),
    ("t_p8", "P8 · Transporte", "chegada hospital − saída p/ hospital"),
    ("t_p9", "P9 · Transf. de cuidados", "encerrado − chegada hospital"),
]

# Faixas de validade por métrica de tempo (segundos) — descarta outliers
CAP_TEMPO = {
    "t_p1": 3600, "t_p2": 3600, "t_p3": 3600,
    "t_p4": 10800, "t_p4_1": 7200, "t_p4_2": 7200,
    "t_p5_6": 14400, "t_p5_6_7": 14400, "t_p7_mais": 14400,
    "t_p8": 7200, "t_p9": 14400,
    "t_central": 3600, "tempo_resposta": 10800,
    "t_saida_gps": 7200, "t_saida_j9": 7200, "t_deslocamento": 7200,
    "t_cena": 14400,
}

PERIODOS = [
    ("t_p1", "P1 — TARM", "Data Tarm − Data ocorrência"),
    ("t_p2", "P2 — Regulação", "Data regulador − Data Tarm"),
    ("t_p3", "P3 — Despacho", "Data controlador − Data regulador"),
    ("t_p4", "P4 — Chegada", "Chegada no local − Data controlador"),
    ("t_p4_1", "P4.1 — Saída de base", "Início deslocamento − Data controlador"),
    ("t_p4_2", "P4.2 — Deslocamento", "Chegada no local − Início deslocamento"),
    ("t_p5_6", "P5-6 — Até J14", "Primeiro J14 − Chegada no local"),
    ("t_p5_6_7", "P5-7 — Cena", "Saída p/ hospital − Chegada no local"),
    ("t_p8", "P8 — Transporte", "Chegada no hospital − Saída p/ hospital"),
    ("t_p9", "P9 — Transf. cuidados", "Atendimento encerrado − Chegada no hospital"),
]

# Desperdício operacional — definição curada (projeto Desperdicio, validada
# com a coordenação): saída efetiva cuja situação final indica que o recurso
# foi mobilizado sem necessidade. "Atendimento no local" NÃO é desperdício
# (houve cuidado efetivo). Valores normalizados (maiúsculas, sem acento).
SITUACOES_DESPERDICIO = {
    "ATENDIMENTO PRE-HOSPITALAR COM RECUSA DE ENCAMINHAMENTO",
    "VITIMA SOCORRIDA POR TERCEIROS",
    "OCORRENCIA ENVIADA POR ENGANO",
    "RECUSA AO ATENDIMENTO PELA VITIMA OU EVASAO",
    "SOLITANTE/PACIENTE NAO LOCALIZADO",  # grafia exata da base vSky
    "DESISTENCIA DO SOLICITANTE",
}
# Motivos excluídos do universo: hipoglicemia revertida e PCR/óbito —
# desfechos clínicos legítimos, não desperdício.
MOTIVOS_EXCLUIDOS_DESPERDICIO = {"PCG3", "PCC3"}

# Escala NEWS modificada (proposta local: FR, FC, PAS, Glasgow + Glicemia).
# Cada parâmetro pontua 0–3; total = soma. Núcleo obrigatório: FR, FC, PAS
# e Glasgow aferidos (0 = não medido, convenção vSky). Glicemia soma se houver.
NEWS_CRITERIOS = [
    ("Frequência respiratória (irpm)", "≤8 → 3 · 9–11 → 1 · 12–20 → 0 · 21–24 → 2 · ≥25 → 3"),
    ("Frequência cardíaca (bpm)", "≤40 → 3 · 41–50 → 1 · 51–90 → 0 · 91–110 → 1 · 111–130 → 2 · ≥131 → 3"),
    ("Pressão arterial sistólica (mmHg)", "≤90 → 3 · 91–100 → 2 · 101–110 → 1 · 111–219 → 0 · ≥220 → 3"),
    ("Escala de Glasgow", "15 → 0 · 13–14 → 1 · 9–12 → 2 · ≤8 → 3"),
    ("Glicemia (mg/dL, opcional)", "≤40 → 3 · 41–60 → 2 · 61–70 → 1 · 71–180 → 0 · 181–300 → 1 · >300 → 2"),
]
NEWS_BANDAS = [
    ("Baixo", "0–4 pontos, nenhum parâmetro = 3"),
    ("Baixo-Médio", "0–4 pontos com algum parâmetro isolado = 3"),
    ("Médio", "5–6 pontos"),
    ("Alto", "≥7 pontos"),
]

# Página de Desempenho: métricas e dimensões analisáveis
METRICAS_DESEMPENHO = {
    "tempo-resposta": ("tempo_resposta", "Tempo de Resposta"),
    "tempo-central": ("t_central", "Tempo de Central"),
    "saida-base": ("t_p4_1", "Saída de Base (P4.1)"),
    "deslocamento": ("t_p4_2", "Deslocamento (P4.2)"),
    "cena": ("t_p5_6_7", "Tempo de Cena (P5-7)"),
    "transferencia": ("t_p9", "Transferência de Cuidados (P9)"),
}
DIMENSOES_DESEMPENHO = {
    "unidade": ("unidade_curta", "Unidade"),
    "plantao": ("plantao", "Plantão (dia + turno)"),
    "dia": ("plantao_dia_semana", "Dia da semana"),
    "cidade": ("cidade", "Cidade"),
    "medico": ("medico_nome", "Médico"),
    "enfermeiro": ("enfermeiro_nome", "Enfermeiro"),
    "tec-enfermagem": ("tec_enfermagem_nome", "Téc. Enfermagem"),
    "condutor": ("condutor_nome", "Condutor"),
    "tarm": ("tarm_nome", "TARM"),
    "regulador": ("regulador_nome", "Regulador"),
    "controlador": ("controlador_nome", "Controlador"),
}

# Papéis profissionais (slug da coluna, rótulo)
PAPEIS = [
    ("tarm", "TARM"),
    ("regulador", "Regulador"),
    ("controlador", "Controlador"),
    ("medico", "Médico"),
    ("enfermeiro", "Enfermeiro"),
    ("tec_enfermagem", "Téc. Enfermagem"),
    ("condutor", "Condutor"),
]

# Registro dos dashboards: slug -> (título, ícone FontAwesome, descrição)
TEMAS = {
    "processos": ("Processos P1–P9", "fa-timeline",
                  "Tempos de cada etapa do fluxo e cumprimento de SLA"),
    "tempo-central": ("Tempo de Central", "fa-headset",
                      "Data controlador − Data ocorrência (P1+P2+P3)"),
    "tempo-cena": ("Tempo de Cena", "fa-truck-medical",
                   "Saída p/ hospital − Chegada no local"),
    "tempo-saida-base": ("Tempo de Saída de Base (P4.1)", "fa-house-flag",
                         "Início deslocamento − Data controlador"),
    "tempo-deslocamento": ("Tempo de Deslocamento (P4.2)", "fa-route",
                           "Chegada no local − Início deslocamento"),
    "tempo-resposta": ("Tempo de Resposta", "fa-stopwatch",
                       "Chegada no local − Data ocorrência"),
    "transferencia-cuidados": ("Transferência de Cuidados (P9)", "fa-bed-pulse",
                               "Atendimento encerrado − Chegada no hospital"),
    "assertividade": ("Assertividade", "fa-bullseye",
                      "Código da equipe × risco da triagem (base APH)"),
    "codigos": ("Códigos da Ocorrência", "fa-flag",
                "Distribuição por código e % das 4 cores"),
    "situacao": ("Situação Atendimento", "fa-clipboard-check",
                 "Desfechos das ocorrências"),
    "auditoria-ocorrencias": ("Auditoria de Ocorrências", "fa-scale-balanced",
                              "Atendimento por viatura de outro município e "
                              "descumprimento de meta por indicador"),
    "localidade": ("Cidade e Micro Região", "fa-map-location-dot",
                   "Distribuição geográfica das ocorrências"),
    "perfil-paciente": ("Sexo, Idade e Faixa", "fa-user",
                        "Perfil demográfico dos pacientes"),
    "tipo-motivo": ("Tipo e Motivo", "fa-stethoscope",
                    "Classificação clínica das ocorrências"),
    "atendimento": ("Atendimento", "fa-hand-holding-medical",
                    "Com × sem atendimento"),
    "transporte": ("Transporte", "fa-route",
                   "Pré-hospitalar × inter-hospitalar"),
    "saidas-ambulancia": ("Total de Saídas de Ambulâncias", "fa-truck-fast",
                          "Empenhos com início de deslocamento — "
                          "por dia, semana e mês"),
    "regulacoes": ("Total de Regulações", "fa-clipboard-list",
                   "Ocorrências reguladas (com regulador) — "
                   "por dia, semana e mês"),
    "unidade": ("Unidade", "fa-ambulance",
                "Volume e desempenho por viatura"),
    "sinais-vitais": ("Sinais Vitais e NEWS", "fa-heart-pulse",
                      "FR, FC, PA, Glasgow, Glicemia e Escala NEWS modificada"),
    "obito": ("Óbito", "fa-cross",
              "Óbitos constatados nas ocorrências"),
    "plantao": ("Plantão", "fa-clock",
                "Diurno 07:00–18:59 × Noturno 19:00–06:59 "
                "(noturno atribuído ao dia de início)"),
    "desperdicio": ("Desperdício", "fa-recycle",
                    "Saídas sem necessidade — real (chegou ao local) × "
                    "evitado (cancelada no trajeto)"),
    "apoio": ("Apoios Externos", "fa-handshake",
              "Polícia Militar, Bombeiros e USA"),
    "equipe": ("Equipe", "fa-user-nurse",
               "TARM, regulador, controlador e equipes de campo"),
    "prof-tarm": ("Profissional — TARM", "fa-headset",
                  "Volume, P1 e assertividade por TARM"),
    "prof-regulador": ("Profissional — Regulador", "fa-user-doctor",
                       "Volume, P2, tempo resposta, % envio RO e assertividade"),
    "prof-medico": ("Profissional — Médico", "fa-briefcase-medical",
                    "Volume, P4 a P9 e assertividade por médico"),
    "prof-controlador": ("Profissional — Controlador", "fa-tower-broadcast",
                         "Volume, P3, tempo resposta e assertividade"),
    "prof-enfermeiro": ("Profissional — Enfermeiro", "fa-user-nurse",
                        "Volume, P4 a P9, tempo resposta e assertividade"),
    "prof-tec-enfermagem": ("Profissional — Téc. Enfermagem", "fa-syringe",
                            "Volume, P4 a P9, tempo resposta e assertividade"),
    "prof-condutor": ("Profissional — Condutor", "fa-car-side",
                      "Volume, P4 a P9, tempo resposta e assertividade"),
}

# Especificação dos dashboards por profissional:
# col = coluna do papel; tempos = períodos específicos do papel;
# tempo_resposta / envio_ro = indicadores adicionais aplicáveis.
_TEMPOS_CAMPO = ["t_p4", "t_p5_6", "t_p5_6_7", "t_p8", "t_p9"]
PROFISSIONAIS_SPEC = {
    "prof-tarm": {"col": "tarm", "rotulo": "TARM", "tempos": ["t_p1"],
                  "tempo_resposta": False, "envio_ro": False,
                  "assertividade": False, "codigo": False,
                  "sla_p1": True, "situacao": True},
    "prof-regulador": {"col": "regulador", "rotulo": "Regulador",
                       "tempos": ["t_p2"], "tempo_resposta": True,
                       "envio_ro": True, "desperdicio": True},
    "prof-medico": {"col": "medico", "rotulo": "Médico",
                    "tempos": _TEMPOS_CAMPO, "tempo_resposta": False,
                    "envio_ro": False},
    "prof-controlador": {"col": "controlador", "rotulo": "Controlador",
                         "tempos": ["t_p3"], "tempo_resposta": True,
                         "envio_ro": False, "assertividade": False,
                         "desperdicio": True},
    "prof-enfermeiro": {"col": "enfermeiro", "rotulo": "Enfermeiro",
                        "tempos": _TEMPOS_CAMPO, "tempo_resposta": True,
                        "envio_ro": False},
    "prof-tec-enfermagem": {"col": "tec_enfermagem", "rotulo": "Téc. Enfermagem",
                            "tempos": _TEMPOS_CAMPO, "tempo_resposta": True,
                            "envio_ro": False},
    "prof-condutor": {"col": "condutor", "rotulo": "Condutor",
                      "tempos": _TEMPOS_CAMPO, "tempo_resposta": True,
                      "envio_ro": False, "assertividade": False},
}
