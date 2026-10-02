"""Catálogo inicial dos envios à SESA.

Transcrito da planilha "Processos da qualidade - SESA" e da IT.QUA.002.000
(Emissão de certidões). Entra no banco na primeira vez que o módulo é
aberto (ver service.garantir_catalogo) e a partir daí é editado na tela de
Cadastros — prazos, canal e destinatários mudam sem mexer no código.
A `chave` é estável: é por ela que a carga reconhece o que já existe.
"""

CNPJ_PADRAO = "28.141.190/0011-58"

TIPO_CERTIDOES, TIPO_DOCUMENTOS = "certidoes", "documentos"
RESULTADOS = ("Negativa", "Positiva com efeitos de negativa", "Regular",
              "Positiva", "Irregular")
RESULTADOS_OK = {"Negativa", "Positiva com efeitos de negativa", "Regular"}

# Destinatários de e-mail, como na planilha
_EMAIL_ATENDIMENTOS = ("oliveiralima@saude.es.gov.br; thiagobissoli@saude.es.gov.br; "
                       "arnaldocolnago@saude.es.gov.br; viniciusmacedo@saude.es.gov.br; "
                       "filippialmeida@saude.es.gov.br; julianamelo@saude.es.gov.br")
_EMAIL_ADVERSIDADES = ("urgenciaemergencia@saude.es.gov.br; oliveiralima@saude.es.gov.br; "
                       "thiagobissoli@saude.es.gov.br; arnaldocolnago@saude.es.gov.br")

CERTIDOES = [
    {"chave": "estadual", "nome": "Estadual", "orgao": "SEFAZ-ES",
     "link": "https://s2-internet.sefaz.es.gov.br/certidao/cnd", "validade_dias": 90,
     "instrucoes": "Menu Certidão Negativa de Débito → informar o CNPJ → concluir a "
                   "verificação da Cloudflare → Emitir Certidão → baixar o PDF."},
    {"chave": "uniao", "nome": "União", "orgao": "Receita Federal / PGFN",
     "link": "https://servicos.receitafederal.gov.br/servico/certidoes/#/home",
     "validade_dias": 180,
     "instrucoes": "Certidão de débitos relativos a tributos federais e à dívida ativa "
                   "da União → informar o CNPJ → confirmar a verificação → baixar o PDF."},
    {"chave": "fgts", "nome": "FGTS", "orgao": "Caixa (CRF)",
     "link": "https://consulta-crf.caixa.gov.br/consultacrf/pages/consultaEmpregador.jsf",
     "validade_dias": 30,
     "instrucoes": "Tipo CNPJ, inscrição só com números, UF ES → Consultar → Certificado "
                   "de Regularidade do FGTS - CRF → Visualizar → imprimir e salvar em PDF."},
    {"chave": "serra", "nome": "Prefeitura da Serra", "orgao": "Sec. Municipal da Fazenda",
     "link": "https://tributacao.serra.es.gov.br:8080/tbserra/loginWeb.jsp"
             "?execobj=ServicosWebSite", "validade_dias": 60,
     "instrucoes": "Serviços OnLine → Certidão Negativa de CPF ou CNPJ → informar o CNPJ "
                   "e o texto da imagem → Gerar → baixar o PDF."},
    {"chave": "trabalhista", "nome": "Trabalhista", "orgao": "TST (CNDT)",
     "link": "https://www.tst.jus.br/certidao1", "validade_dias": 180,
     "instrucoes": "Informar o CNPJ → digitar os caracteres da imagem → Emitir Certidão "
                   "→ salvar o PDF."},
]


def _itens(*nomes):
    return [{"chave": f"i{n + 1:02d}", "nome": nome} for n, nome in enumerate(nomes)]


OFICIO = "Ofício de envio"

OBRIGACOES = [
    {"chave": "certidoes", "nome": "Certidões", "tipo": TIPO_CERTIDOES,
     "prazo_tipo": "util", "prazo_dia": 1, "canal": "E-Docs", "destinatario": "NERUE",
     "itens": CERTIDOES},
    {"chave": "bpa", "nome": "Relatório BPA", "prazo_tipo": "util", "prazo_dia": 2,
     "canal": "E-mail", "destinatario": "sesanepaes@gmail.com",
     "itens": _itens("Relatório BPA")},
    {"chave": "atendimentos_mensais", "nome": "Relatório de atendimentos mensais",
     "prazo_tipo": "util", "prazo_dia": 5, "canal": "E-mail",
     "destinatario": _EMAIL_ATENDIMENTOS,
     "itens": _itens("Relatório de Dados de Atendimento Sintético")},
    {"chave": "adversidades", "nome": "Relatório de Adversidades, Encaminhamentos SAMU e Censo",
     "prazo_tipo": "util", "prazo_dia": 5, "canal": "E-mail",
     "destinatario": _EMAIL_ADVERSIDADES,
     "itens": _itens("Encaminhamento dos Hospitais", "Adversidades Hospitalares",
                     "Censo Hospitais")},
    {"chave": "convenio_007", "nome": "Prestação de Contas — Convênio 007",
     "prazo_tipo": "util", "prazo_dia": 5, "canal": "E-Docs", "destinatario": "GECORP",
     "itens": _itens(OFICIO, "Metas Quantitativas", "Tempo de Deslocamento", "Saída de USA",
                     "Pesquisa de Satisfação", "Capacitação NEP",
                     "Empregados de Férias (Controladoria)",
                     "Empregados Totais (Controladoria)")},
    {"chave": "convenio_008", "nome": "Prestação de Contas — Convênio 008",
     "prazo_tipo": "util", "prazo_dia": 5, "canal": "E-Docs", "destinatario": "GECORP",
     "itens": _itens(OFICIO, "Relatório de Dados de Atendimento Sintético", "Saída de USA",
                     "Pesquisa de Satisfação", "Capacitação NEP", "Queixas e Tratativa")},
    {"chave": "monitoramento_hospitais", "nome": "Relatório de Monitoramento dos Hospitais",
     "prazo_tipo": "util", "prazo_dia": 5, "canal": "E-Docs", "destinatario": "NERUE",
     "itens": _itens("Relatório de Monitoramento dos Hospitais")},
    {"chave": "dados_mensais", "nome": "Relatório de dados mensais",
     "prazo_tipo": "util", "prazo_dia": 5, "canal": "E-Docs", "destinatario": "NERUE",
     "itens": _itens("Relatório de Dados de Atendimento Sintético",
                     "Sintético por Município", "Sintético por Unidade",
                     "Saída de Ambulância por Município", "Saída de Ambulância por Código",
                     "Tempo de deslocamento")},
    {"chave": "ranking", "nome": "Ranking de Acionamento", "prazo_tipo": "util",
     "prazo_dia": 5, "canal": "E-mail",
     "destinatario": "thiagobissoli@saude.es.gov.br; qualidadesamu192es@gmail.com",
     "itens": _itens("Ranking de Acionamento")},
    {"chave": "fluxo_mensal", "nome": "Fluxo mensal — demanda da SESA",
     "prazo_tipo": "util", "prazo_dia": 5, "canal": "E-Docs", "destinatario": "NERUE",
     "itens": _itens(OFICIO, "Planilha da Frota", "Quantidade de macas",
                     "Escalas (Médico, Enf., Téc., Condutor, RO e TARM)", "Dados das Bases",
                     "Contatos dos Coordenadores")},
    {"chave": "ncps_externas", "nome": "NCPS externas", "prazo_tipo": "corrido",
     "prazo_dia": 10, "canal": "E-Docs", "destinatario": "NERUE",
     "itens": _itens("NCPS que não pertencem à ISCMV",
                     "Lista com nomes dos pacientes e ID das NCPS")},
    {"chave": "fes_007", "nome": "Relatório trimestral FES 007", "periodicidade": "trimestral",
     "meses": "1,4,7,10", "prazo_tipo": "util", "prazo_dia": 5, "canal": "E-Docs",
     "destinatario": "FES",
     "itens": _itens(OFICIO, "Indicadores de Qualidade", "NEP", "Certidões dos 3 meses",
                     "Relatório de Bens adquiridos (Manutenção)")},
    {"chave": "fes_008", "nome": "Relatório trimestral FES 008", "periodicidade": "trimestral",
     "meses": "1,4,7,10", "prazo_tipo": "util", "prazo_dia": 5, "canal": "E-Docs",
     "destinatario": "FES",
     "itens": _itens(OFICIO, "Relação dos Bens adquiridos", "NEP", "Certidões dos 3 meses",
                     "Relatório de Bens adquiridos (Manutenção)")},
]

PERIODICIDADES = {"mensal": "Mensal", "trimestral": "Trimestral", "anual": "Anual"}


# Itens com documento gerado pelo sistema: (obrigação, item) → tela do gerador
GERADORES = {
    ("adversidades", "i01"): "/sesa/encaminhamentos",
    ("convenio_007", "i04"): "/sesa/saida-usa",
    ("convenio_008", "i03"): "/sesa/saida-usa",
}
CONFIG_LOGO = "sesa_logo_arquivo_id"
