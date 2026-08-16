"""Constantes do módulo Backup (§35.2)."""

MODULE_NAME = "backup"
PREFIXO = "samu"                 # nome dos arquivos: samu-AAAAMMDD-HHMMSS.sql.gz
TIMEOUT_DUMP = 1800              # 30 min — a base tem ~460 MB
MANTER_PADRAO = 14               # duas semanas de cópias diárias

CONFIG_ATIVO = "backup_ativo"
CONFIG_HORA = "backup_hora"          # HH:MM
CONFIG_MANTER = "backup_manter"      # quantas cópias preservar
CONFIG_DIRETORIO = "backup_diretorio"
CONFIG_STATUS = "backup_status"      # resultado da última execução
CONFIG_ULTIMA = "backup_ultima"      # data/hora da última execução
