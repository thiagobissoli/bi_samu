"""Constantes do módulo Investigação de Eventos (§35.2)."""

MODULE_NAME = "investigacao"

# Janelas de ocupação acima disso não representam um único empenho
# (marcação esquecida em aberto) — descartadas da timeline.
DURACAO_MAXIMA_HORAS = 24

# Teto de linhas da timeline, para a página não ficar impraticável
LIMITE_UNIDADES_TIMELINE = 120

# --------------------------------------------------------------- RAC
# Estrutura do formulário FOR.SAMU.038 — Relatório de Evento Adverso com
# Investigação de Causa Raiz. As categorias e os itens são os do próprio
# formulário: a IA só pode marcar o que existe aqui.
FATORES_CONTRIBUINTES = [
    ("Fatores do Paciente", [
        "Condição (complexidade e gravidade)",
        "Comunicação e linguagem",
        "Fatores sociais e de personalidade",
    ]),
    ("Fatores da Tarefa e Tecnologia", [
        "Clareza da estrutura e desenho da tarefa",
        "Disponibilidade e uso de protocolos",
        "Disponibilidade e acurácia dos testes auxiliares à tomada de decisão",
    ]),
    ("Fatores Individuais (pessoas)", [
        "Conhecimento, habilidades, experiência específica",
        "Saúde física e mental",
    ]),
    ("Fatores do Time (equipes)", [
        "Comunicação verbal",
        "Comunicação escrita",
        "Disponibilidade de ajuda e supervisão",
        "Estrutura do time (congruência, consistência, liderança, etc.)",
    ]),
    ("Fatores do Ambiente de Trabalho", [
        "Interrupções, barulho, conforto térmico, iluminação, etc.",
        "Padrões de turno e carga de trabalho",
        "Manutenção, design e disponibilidade de equipamentos",
        "Apoio administrativo e gerencial no ambiente de trabalho",
    ]),
    ("Fatores Organizacionais e Gerenciais", [
        "Restrições financeiras",
        "Estrutura organizacional",
        "Políticas, padrões, protocolos ambíguos, normas pouco claras",
        "Cultura de segurança e prioridades",
    ]),
    ("Fatores do Contexto Institucional", [
        "Contexto regulatório e econômico",
        "Sistema de saúde loco regional",
        "Ligação com organizações externas",
    ]),
]

# Matriz de risco do formulário: C = probabilidade × consequência
PROBABILIDADE = [
    (5, "Quase certo", "Pode ser que ocorra semanalmente — 71 a 90%"),
    (4, "Provável", "Pode ser que ocorra mensalmente — 51 a 70%"),
    (3, "Possível", "Pode ser que ocorra mais de uma vez dentro de um ano — 31 a 50%"),
    (2, "Improvável", "Pode ser que ocorra uma vez dentro de um ano — 11 a 30%"),
    (1, "Raro", "Não é provável que aconteça"),
]
CONSEQUENCIA = [
    (16, "Catastrófica", "Consequências MÁXIMAS sem possibilidade de recuperação"),
    (8, "Maior", "Consequências SIGNIFICANTES com possibilidade remota de recuperação"),
    (4, "Moderada", "Consequências MEDIANAS em curto e médio prazo com "
                    "possibilidade de recuperação"),
    (2, "Menor", "Consequências MÍNIMAS"),
    (1, "Desprezível", "Consequências INSIGNIFICANTES"),
]
GRAVIDADES = ["Leve", "Moderada", "Grave", "Óbito", "Alto Potencial"]


def nivel_de_risco(pontuacao: int) -> tuple[str, str]:
    """Faixa e cor do formulário para a pontuação C = A × B."""
    if pontuacao >= 20:
        return "Extremo", "danger"
    if pontuacao >= 10:
        return "Elevado", "warning"
    if pontuacao >= 4:
        return "Moderado", "info"
    return "Baixo", "success"
