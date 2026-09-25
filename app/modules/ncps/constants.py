"""Catálogos da NCPS: segurança do paciente e saúde/segurança do trabalhador (NR-1).

Portados do sistema Flask anterior mantendo os **mesmos códigos**, para que
as notificações importadas de lá continuem com o significado original.

Matriz de risco, GHE e perigos seguem o PGR do SAMU 192 ES (metodologia
SESI 2022): probabilidade e severidade de 2 a 5; nível = P × S.
"""

# ------------------------------------------------------------------ natureza
NATUREZA = {
    "paciente": "Segurança do paciente",
    "trabalhador": "Saúde e segurança do trabalhador",
}

TIPO_EVENTO_TRABALHADOR = {
    "acidente_tipico": "Acidente de trabalho (típico)",
    "acidente_trajeto": "Acidente de trajeto",
    "doenca": "Doença relacionada ao trabalho",
    "quase_acidente": "Quase-acidente (incidente sem lesão)",
    "condicao_insegura": "Condição ou ato inseguro",
    "violencia_assedio": "Violência, agressão ou assédio",
}
# Tipos que caracterizam acidente/doença: exigem análise (NR-1 1.5.5.5) e
# revisão do inventário de riscos (NR-1 1.5.4.4.6 "d")
EVENTOS_ACIDENTE = ("acidente_tipico", "acidente_trajeto", "doenca")
# Violência/assédio: só a Comissão de Integridade vê
EVENTO_CONFIDENCIAL = "violencia_assedio"

# ------------------------------------------------------------------ status
STATUS = {
    "0": "Aguardando análise da qualidade",
    "1": "Analisando pelo coordenador",
    "2": "Análise concluída",
    "3": "Arquivada",
    "4": "Encaminhada ao gestor competente de outra instituição",
}
STATUS_ABERTOS = ("0", "1")

# Situação mostrada a quem notificou: (rótulo, explicação, etapa 1–3)
SITUACAO_ACOMPANHAMENTO = {
    "0": ("Recebida", "A notificação foi registrada e aguarda a análise da "
          "equipe responsável.", 1),
    "1": ("Em análise", "A notificação está sendo analisada e tratada pelo "
          "responsável.", 2),
    "2": ("Análise concluída", "A análise foi concluída e as ações definidas "
          "estão em acompanhamento.", 3),
    "3": ("Arquivada", "A notificação foi analisada e arquivada.", 3),
    "4": ("Encaminhada", "A notificação foi encaminhada ao gestor competente "
          "de outra instituição.", 3),
}

# ------------------------------------------------------------------ segurança do paciente
# "0" = aguardando análise em todos os campos (código legado)
PROCEDENTE = {"0": "Aguardando análise", "1": "Analisando", "2": "Sim",
              "3": "Não", "4": "Em parte"}

CLASSIFICACAO_INCIDENTE = {
    "0": "Aguardando análise",
    "1": "Near miss",
    "2": "Circunstância de risco",
    "3": "Incidente sem dano",
    "4": "Evento adverso",
}

DANO = {"0": "Aguardando análise", "1": "Nenhum", "2": "Leve",
        "3": "Moderado", "4": "Grave", "5": "Óbito"}

MACROPROCESSO = {
    "0": "Aguardando análise",
    "1": "P1 - Abertura de chamado",
    "2": "P2 - Decisão técnica",
    "3": "P3 - Empenho",
    "4": "P4 - Deslocamento ao QTH",
    "5": "P5 - Atendimento no local",
    "6": "P6 - Contra-regulação",
    "7": "P7 - Decisão gestora",
    "8": "P8 - Deslocamento ao destino",
    "9": "P9 - Transferência de cuidados",
    "10": "Prontidão",
    "11": "Administrativo",
    "12": "Sistema",
    "99": "Não se aplica",
}

META_SEGURANCA = {
    "0": "Aguardando análise",
    "1": "Identificação do paciente",
    "2": "Cuidado limpo e seguro",
    "3": "Utilização de cateteres e sondas",
    "4": "Procedimento seguro",
    "5": "Administração segura de medicamentos e soluções",
    "6": "Envolvimento do paciente com sua própria segurança",
    "7": "Comunicação efetiva",
    "8": "Prevenção de queda e acidente",
    "9": "Prevenção de úlceras por pressão",
    "10": "Segurança na utilização de tecnologia",
    "99": "Não se aplica",
}

EVENTO_SENTINELA = {
    "0": "Aguardando análise",
    "1": "Ato de violação intencional à prontidão",
    "2": "Endereço errado em chamado prioritário",
    "3": "Decisão técnica do MR inapropriada (apoio imediato de USA)",
    "4": "Não empenho de recurso prioritário pelo RO",
    "5": "Insubordinação às decisões da Central de Regulação",
    "6": "Deslocamento inadequado com demora no percurso",
    "7": "Contra-regulação inadequada, incoerente, distorcida ou ausente",
    "8": "Administração de medicamentos de vigilância sem prescrição médica",
    "9": "Intercorrência inesperada e crítica após medicação",
    "10": "Intercorrência inesperada e crítica após procedimento",
    "11": "Recusa coerente de paciente pelo primeiro destino",
    "12": "Acidente de trânsito em atendimento",
    "13": "Abandono de paciente",
    "14": "Queda de paciente",
    "15": "Atraso em situação tempo-dependente",
    "16": "Acidente com material biológico ou perfurocortante",
    "17": "Agressão física à equipe",
    "18": "Atendimento em cena insegura",
    "99": "Não se aplica",
}

# Campos de classificação do paciente → catálogo (usado na tela e na exportação)
CLASSIFICACAO_PACIENTE = {
    "classificacao_incidente": ("Classificação do incidente", CLASSIFICACAO_INCIDENTE),
    "dano": ("Grau do dano", DANO),
    "macroprocesso": ("Macroprocesso", MACROPROCESSO),
    "seguranca": ("Meta de segurança do paciente", META_SEGURANCA),
    "sentinela": ("Evento sentinela", EVENTO_SENTINELA),
}

# ------------------------------------------------------------------ riscos ocupacionais (NR-1 1.5.3.1.4)
GRUPO_RISCO = {
    "fisico": "Físico",
    "quimico": "Químico",
    "biologico": "Biológico",
    "ergonomico": "Ergonômico",
    "psicossocial": "Ergonômico (psicossocial)",
    "acidente": "Acidente / mecânico",
}

PARTE_CORPO = [
    "Cabeça", "Olhos", "Face", "Pescoço", "Tórax", "Abdome", "Coluna / dorso",
    "Ombro", "Braço / antebraço", "Mão / punho", "Dedos da mão", "Quadril",
    "Perna / joelho", "Pé / tornozelo", "Múltiplas partes",
    "Sistema nervoso / saúde mental", "Não se aplica",
]

# ------------------------------------------------------------------ matriz de risco (PGR, Quadros 5 e 6)
PROBABILIDADE = {
    2: ("Improvável", "Exposição rara ou controles adequados e mantidos; sem "
        "histórico de ocorrência."),
    3: ("Pouco provável", "Exposição ocasional; controles adequados, mas sem "
        "garantia de manutenção."),
    4: ("Provável", "Exposição frequente ou controles com desvios; há "
        "histórico de ocorrências."),
    5: ("Altamente provável", "Exposição contínua; controles inexistentes ou "
        "inadequados."),
}
SEVERIDADE = {
    2: ("Mínima", "Sem dano ou dano leve e reversível, sem afastamento / sem "
        "prolongar o cuidado."),
    3: ("Mediana", "Dano moderado reversível; afastamento até 15 dias / "
        "intervenção adicional."),
    4: ("Considerável", "Dano grave ou irreversível; afastamento acima de 15 "
        "dias / dano permanente."),
    5: ("Crítica", "Incapacidade permanente ou óbito."),
}
# (nível mínimo do produto, rótulo, classificação, cor, conduta)
NIVEIS_RISCO = [
    (25, "Crítico", "PR1", "critico",
     "Ações corretivas imediatas pelo plano de ação; reavaliar o risco após "
     "implantá-las."),
    (15, "Alto", "PR2", "alto",
     "Reavaliar rotinas e implantar novas medidas de controle."),
    (10, "Médio", "PR3", "medio",
     "Monitorar as medidas existentes e avaliar a necessidade de novas "
     "medidas."),
    (6, "Baixo", "PR4", "baixo",
     "Manter o controle; avaliar medidas adicionais e monitoramento."),
    (4, "Irrelevante", "NA", "irrelevante",
     "Nenhuma nova medida; manter as existentes."),
]
MOMENTO_RISCO = {"inicial": "Risco inicial",
                 "residual": "Risco residual (após as ações)"}


def nivel_risco(probabilidade, severidade) -> dict | None:
    """Classificação do risco pela matriz do PGR; None se incompleto."""
    if not probabilidade or not severidade:
        return None
    pontos = int(probabilidade) * int(severidade)
    for minimo, rotulo, classe, cor, conduta in NIVEIS_RISCO:
        if pontos >= minimo:
            return {"pontos": pontos, "rotulo": rotulo, "classe": classe,
                    "cor": cor, "conduta": conduta}
    return None


# ------------------------------------------------------------------ análise de causas
# Protocolo de Londres — mesmos códigos do campo legado "causa"
FATORES_LONDRES = {
    "1": "Fatores do paciente",
    "2": "Fatores da tarefa e tecnologia",
    "3": "Fatores individuais (profissional)",
    "4": "Fatores da equipe",
    "5": "Fatores do ambiente de trabalho",
    "6": "Fatores organizacionais e gerenciais",
    "7": "Fatores do contexto institucional",
}
CATEGORIAS_ISHIKAWA = {
    "metodo": "Método",
    "maquina": "Máquina",
    "material": "Material",
    "mao_de_obra": "Mão de obra",
    "meio_ambiente": "Meio ambiente",
    "medida": "Medida",
}
METODOS_CAUSA = {"londres": FATORES_LONDRES, "ishikawa": CATEGORIAS_ISHIKAWA}

# ------------------------------------------------------------------ plano de ação
# Hierarquia de controle (NR-1 1.5.5.1.2) + tipos da segurança do paciente
TIPO_ACAO = {
    "eliminacao": "Eliminação / substituição do perigo",
    "epc": "Proteção coletiva / engenharia",
    "administrativa": "Administrativa / organização do trabalho",
    "epi": "Equipamento de proteção individual (EPI)",
    "estrutural": "Estrutural",
    "construtiva": "Construtiva",
    "educacional": "Educacional / treinamento",
    "disciplinar": "Disciplinar",
}
# Campo legado "acao" (um único tipo por NCPS) → tipo de ação atual
TIPO_ACAO_LEGADO = {"1": "estrutural", "2": "construtiva", "3": "educacional",
                    "4": "disciplinar", "5": "administrativa"}
STATUS_ACAO = {
    "pendente": "Não iniciada",
    "andamento": "Em andamento",
    "concluida": "Concluída",
    "cancelada": "Cancelada",
}
STATUS_ACAO_ABERTOS = ("pendente", "andamento")
EFICACIA_ACAO = {
    "nao_verificada": "Não verificada",
    "eficaz": "Eficaz",
    "parcial": "Parcialmente eficaz",
    "ineficaz": "Ineficaz",
}

# Código de acompanhamento: sem 0/O/1/I para evitar confusão na digitação
ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
TAMANHO_CODIGO = 8

# ------------------------------------------------------------------ dados do PGR (carga inicial)
GHE_PGR = [
    ("01", "Administrativo", "Assessores administrativos, Assessor de Informática, Contador, Controlador Administrativo, Enfermeiro Supervisor da Qualidade, Supervisores (DP, Operações Técnicas, Prestação de Contas)"),
    ("02", "Administrativo / Aprendizes", "Aprendiz"),
    ("03", "Segurança do Trabalho", "Engenheiro e Técnico de Segurança do Trabalho"),
    ("04", "Medicina do Trabalho", "Enfermeiro do Trabalho, Médico do Trabalho"),
    ("05", "Administrativo / Socorristas", "Coordenadores, Enfermeiro Socorrista, Médico RT, Médico Socorrista, Motorista Socorrista, Técnico de Enfermagem Socorrista"),
    ("06", "Farmácia", "Auxiliar de Farmácia, Farmacêutico, Farmacêutico RT, Supervisor de Estoques"),
    ("07", "CAF", "Assessor Administrativo"),
    ("08", "Intervenção / Básica (USB)", "Técnico de Enfermagem Socorrista"),
    ("09", "Intervenção / Avançada (USA)", "Enfermeiro Socorrista, Médico Socorrista"),
    ("10", "Regulação / Intervenção", "Médico Socorrista"),
    ("11", "Condutores", "Motorista Socorrista"),
    ("12", "Administrativo / NEP", "Analista de RH, Assessor Administrativo, Psicólogo"),
    ("13", "Supervisão de Frota", "Motorista Socorrista, Supervisor de Frota, Supervisor de Logística"),
    ("14", "Radioperação / TARM", "Telefonista TARM, Radioperador TARM"),
    ("15", "Supervisão / TARM", "Supervisor de Teleatendimento"),
    ("16", "CME", "Enfermeiro Socorrista, Técnico de Enfermagem Socorrista"),
    ("17", "Manutenção Predial / Elétrica", "Técnico em Elétrica"),
    ("18", "Manutenção Predial / Civil", "Oficial"),
]

# (grupo, perigo, fonte/circunstância, possíveis lesões ou agravos)
PERIGOS_PGR = [
    ("fisico", "Ruído", "Ambulâncias; ferramentas elétricas (furadeira, esmerilhadeira)", "Perda auditiva induzida por ruído (PAINPSE)"),
    ("fisico", "Vibração de corpo inteiro", "Condução de ambulâncias", "Patologias osteomusculares, transtornos de nervos periféricos, cinetose"),
    ("fisico", "Umidade", "Limpeza no CME; manutenção hidráulica", "Dermatite de contato"),
    ("quimico", "Detergentes enzimáticos e neutros", "Limpeza e esterilização de materiais no CME", "Dermatite"),
    ("quimico", "Solventes, tintas, cimento e argamassa", "Manutenção predial", "Dermatite, irritação de vias aéreas"),
    ("biologico", "Agentes biológicos infecciosos", "Atendimento a pacientes (sangue, secreções, saliva); materiais contaminados; esgoto", "Doenças infecciosas diversas"),
    ("acidente", "Acidente de trânsito", "Condução e acompanhamento de ocorrências em viatura", "Lesões imediatas, politrauma"),
    ("acidente", "Queda de mesmo nível ou de níveis diferentes", "Desníveis, ladeiras, escadas, piso escorregadio", "Contusões, fraturas"),
    ("acidente", "Objetos perfurocortantes", "Agulhas, cateteres, seringas", "Cortes, exposição a material biológico"),
    ("acidente", "Superfícies aquecidas", "Autoclave (CME)", "Queimaduras"),
    ("acidente", "Eletricidade", "Tomadas, lâmpadas, interruptores (baixa tensão)", "Choque elétrico"),
    ("acidente", "Trabalho em altura", "Atividades acima de 2 m", "Queda, fraturas"),
    ("acidente", "Ferramentas manuais e rotativas", "Manutenção", "Escoriações, cortes"),
    ("acidente", "Agressão física", "Atendimento em cena insegura; pacientes ou terceiros", "Lesões, trauma psicológico"),
    ("ergonomico", "Postura sentada por longos períodos", "Regulação, TARM, administrativo", "Sobrecarga da coluna, redução do retorno venoso"),
    ("ergonomico", "Postura em pé por longos períodos", "Atividades operacionais", "Varizes, dores lombares"),
    ("ergonomico", "Movimentos repetitivos", "Uso de mouse e teclado", "DORT / LER"),
    ("ergonomico", "Uso prolongado de tela", "Atividades em computador", "Fadiga ocular, cefaleia"),
    ("ergonomico", "Levantamento e transporte manual de cargas", "Transporte de macas, pacientes e caixas", "Lombalgia, lesões osteomusculares"),
    ("ergonomico", "Trabalho noturno", "Escalas de plantão", "Alterações psicofisiológicas, distúrbios do sono"),
    ("ergonomico", "Membros superiores em posição inadequada", "Elevação dos braços acima do ombro", "Lesões de ombro"),
    ("psicossocial", "Alta pressão de ritmo de trabalho", "Decisão rápida e pressão por tempo-resposta", "Exaustão, distúrbios do sono, risco cardiovascular"),
    ("psicossocial", "Alta demanda cognitiva", "Alto nível de concentração, atenção e memória", "Fadiga mental, erros operacionais"),
    ("psicossocial", "Desequilíbrio entre esforço e recompensa", "Baixa remuneração ou reconhecimento", "Depressão, doença coronariana, síndrome metabólica"),
    ("psicossocial", "Interrupções frequentes", "Alternância constante entre tarefas", "Fadiga mental, aumento do cortisol"),
    ("psicossocial", "Baixa autonomia / sem controle sobre o volume", "Sem poder de decisão sobre método ou carga", "Depressão, ansiedade, doença cardiovascular"),
    ("psicossocial", "Eventos violentos ou traumáticos", "Ocorrências críticas, óbitos, cenas violentas", "Estresse pós-traumático, ansiedade"),
    ("psicossocial", "Assédio moral ou sexual", "Relações de trabalho", "Ansiedade, depressão, adoecimento mental"),
]
