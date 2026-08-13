"""Constantes do módulo Investigação de Eventos (§35.2)."""

MODULE_NAME = "investigacao"

# Janelas de ocupação acima disso não representam um único empenho
# (marcação esquecida em aberto) — descartadas da timeline.
DURACAO_MAXIMA_HORAS = 24

# Teto de linhas da timeline, para a página não ficar impraticável
LIMITE_UNIDADES_TIMELINE = 120
