"""Constantes do módulo Download vSky (§35.2)."""

MODULE_NAME = "download_vsky"

# Chaves de configuração (ConfigService §39.12)
CONFIG_BASE_URL = "vsky_base_url"
CONFIG_USUARIO = "vsky_usuario"
CONFIG_SENHA = "vsky_senha"  # criptografada automaticamente (marker "senha")
CONFIG_CLIENTE_ID = "vsky_cliente_id"  # opcional — vazio usa o cliente padrão do vSky

DEFAULT_BASE_URL = "https://gestao-es.vskysamu.com.br"

# Download automático (agendado) — chaves de configuração
CONFIG_AUTO_ATIVO = "vsky_auto_ativo"          # "1" = ligado
CONFIG_AUTO_MODO = "vsky_auto_modo"            # "diario" | "intervalo"
CONFIG_AUTO_HORA = "vsky_auto_hora"            # HH:MM (modo diário)
CONFIG_AUTO_INTERVALO = "vsky_auto_intervalo"  # minutos (modo intervalo)
CONFIG_AUTO_DIAS = "vsky_auto_dias"            # importa os últimos N dias
CONFIG_AUTO_ULTIMA = "vsky_auto_ultima"        # última execução (dd/mm HH:MM)
CONFIG_AUTO_STATUS = "vsky_auto_status"        # resultado da última execução
AUTO_INTERVALO_MINIMO = 15  # minutos

# Status de uma importação
STATUS_PENDENTE = "pendente"
STATUS_CONCLUIDO = "concluido"
STATUS_ERRO = "erro"

STATUS_LABELS = {
    STATUS_PENDENTE: "Pendente",
    STATUS_CONCLUIDO: "Concluído",
    STATUS_ERRO: "Erro",
}

HTTP_TIMEOUT = 300  # segundos — a geração do relatório no vSky pode demorar
DATA_FMT = "%d/%m/%Y"
DATA_HORA_FMT = "%d/%m/%Y %H:%M:%S"

# Nome do relatório no menu do vSky (usado para localizar o item dinamicamente)
RELATORIO_MENU_LABEL = "Total de Registros Analítico"

# Prontuário (ficha "Detalhes do Atendimento") — navegação de consulta
CONSULTA_OCORRENCIA_PATH = "/vskymanagement/restrito/consultar_ocorrencia.xhtml"
CAMPO_NUMERO_OCORRENCIA = "frm_consultar_ocorrencias:itNumeroOcorrencia"
CAMPO_CONSULTA_DATA_INICIAL = "frm_consultar_ocorrencias:itDataInicial_input"
PRONTUARIO_PDF_LABEL = "Gerar Detalhes do Atendimento"
PRONTUARIO_TIMEOUT = 120  # segundos — geração do PDF pode demorar

# Colunas do relatório "Total de Registros Analítico", na ordem do XLS.
# (slug usado como coluna no banco, título exibido no cabeçalho do relatório)
COLUNAS: list[tuple[str, str]] = [
    ("ocorrencia", "Ocorrência"),
    ("codigo_da_ocorrencia", "Código da ocorrência"),
    ("status_da_ocorrencia", "Status da ocorrência"),
    ("situacao_atendimento", "Situação atendimento"),
    ("atendimento", "Atendimento"),
    ("transporte", "Transporte"),
    ("unidade", "Unidade"),
    ("veiculo", "Veículo"),
    ("cidade", "Cidade"),
    ("bairro", "Bairro"),
    ("endereco", "Endereço"),
    ("numero", "Número"),
    ("referencia", "Referência"),
    ("lat_local_atendimento", "Lat. Local Atendimento"),
    ("long_local_atendimento", "Long. Local Atendimento"),
    ("paciente", "Paciente"),
    ("sexo", "Sexo"),
    ("idade", "Idade"),
    ("faixa", "Faixa"),
    ("tipo", "Tipo"),
    ("motivo", "Motivo"),
    ("risco_inicial", "Risco Inicial"),
    ("frq_respiratoria", "Frq. Respiratória"),
    ("frq_cardiaca", "Frq. Cardíaca"),
    ("pressao_arterial", "Pressão Arterial"),
    ("escala_glasgow", "Escala Glasgow"),
    ("glicemia", "Glicemia"),
    ("obito", "Óbito"),
    ("data_ocorrencia", "Data ocorrência"),
    ("tarm", "Tarm"),
    ("data_tarm", "Data Tarm"),
    ("regulador", "Regulador"),
    ("data_regulador", "Data regulador"),
    ("controlador", "Controlador"),
    ("data_controlador", "Data controlador"),
    ("inicio_deslocamento", "Início deslocamento"),
    ("saida_para_atendimento", "Saída para atendimento"),
    ("chegada_no_local", "Chegada no local"),
    ("saida_para_hospital", "Saída para hospital"),
    ("chegada_no_hospital", "Chegada no hospital"),
    ("atendimento_encerrado", "Atendimento encerrado"),
    ("chegada_na_base", "Chegada na base"),
    ("hospital_origem", "Hospital origem"),
    ("hospital_destino", "Hospital destino"),
    ("lat_hospital_destino", "Lat. Hospital destino"),
    ("long_hospital_destino", "Long. Hospital destino"),
    ("solicitante", "Solicitante"),
    ("telefone", "Telefone"),
    ("protocolo_telefone", "Protocolo telefone"),
    ("micro_regiao", "Micro Região"),
    ("apoio_policia_militar", "Apoio Polícia Militar"),
    ("apoio_bombeiros", "Apoio Bombeiros"),
    ("apoio_usa", "Apoio USA"),
    ("tec_enfermagem", "Tec. Enfermagem"),
    ("condutor", "Condutor"),
    ("enfermeiro", "Enfermeiro"),
    ("medico", "Médico"),
    ("primeiro_j14", "Primeiro J14"),
    ("ultimo_j14", "Último J14"),
    ("primeiro_j15", "Primeiro J15"),
    ("ultimo_j15", "Último J15"),
]

SLUGS = [slug for slug, _ in COLUNAS]
