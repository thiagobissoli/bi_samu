"""Constantes do módulo Painel Gestao (§35.2)."""

MODULE_NAME = "painel_gestao"

# Envio automático do Relatório de Gestão por e-mail (§22 — ConfigService)
CONFIG_EMAIL_ATIVO = "relatorio_email_ativo"
CONFIG_EMAIL_MODO = "relatorio_email_modo"            # semanal | diario
CONFIG_EMAIL_DIA = "relatorio_email_dia"              # dia da semana (cron)
CONFIG_EMAIL_HORA = "relatorio_email_hora"            # HH:MM
CONFIG_EMAIL_DESTINATARIOS = "relatorio_email_destinatarios"
CONFIG_EMAIL_STATUS = "relatorio_email_status"        # resultado do último envio
CONFIG_EMAIL_ULTIMA = "relatorio_email_ultima"        # data/hora do último envio

DIAS_SEMANA_CRON = {
    "mon": "segunda-feira", "tue": "terça-feira", "wed": "quarta-feira",
    "thu": "quinta-feira", "fri": "sexta-feira", "sat": "sábado",
    "sun": "domingo",
}
