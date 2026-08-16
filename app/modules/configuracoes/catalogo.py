"""Catálogo das configurações do sistema.

A tela de Configurações listava só o que já estava gravado no banco: quem
não soubesse o nome exato da chave não tinha como criá-la, e não havia
onde explicar o que cada uma faz. Aqui ficam todas as chaves conhecidas,
agrupadas por assunto, cada uma com a explicação que a tela mostra no (?).

Chave nova no sistema entra aqui junto com o código que a lê — é o que
mantém a tela completa.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.modules.backup.constants import MANTER_PADRAO
from app.modules.download_vsky.constants import DEFAULT_BASE_URL
from app.modules.indicadores.constants import (AUDITORIA_INDICADORES,
                                               METAS_TEMPO,
                                               PREFIXO_CONFIG_META)
from app.modules.indicadores.nucleo import DESCONTO_P41_PADRAO

# Tipos de campo que a tela sabe desenhar
TEXTO, SENHA, NUMERO, HORA, LISTA, BOOLEANO = (
    "texto", "senha", "numero", "hora", "lista", "booleano")


@dataclass(frozen=True)
class Chave:
    chave: str
    rotulo: str
    ajuda: str                      # texto do (?)
    padrao: str = ""                # o que vale quando está em branco
    tipo: str = TEXTO
    opcoes: tuple = ()              # para tipo LISTA
    somente_leitura: bool = False   # preenchida pelo próprio sistema
    gerida_em: str = ""             # tela própria que edita esta chave


@dataclass(frozen=True)
class Grupo:
    titulo: str
    icone: str
    descricao: str = ""
    chaves: tuple[Chave, ...] = field(default_factory=tuple)


def _metas_indicadores() -> tuple[Chave, ...]:
    """Uma chave por indicador com meta, na ordem do fluxo do atendimento."""
    rotulos = {col: (rotulo, sub) for col, rotulo, sub in AUDITORIA_INDICADORES}
    itens = []
    for col, padrao in METAS_TEMPO.items():
        rotulo, sub = rotulos.get(col, (col, ""))
        itens.append(Chave(
            f"{PREFIXO_CONFIG_META}{col}_segundos",
            f"Meta de {rotulo}",
            f"Em segundos. {rotulo} = {sub}. Acima disso o atendimento conta "
            f"como fora da meta na Auditoria de Ocorrências. Padrão "
            f"{padrao} s ({padrao // 60:02d}:{padrao % 60:02d}). As metas "
            "foram montadas para fechar a cadeia — central + P4 = tempo de "
            "resposta, e saída de base + deslocamento = P4 —, então ao mexer "
            "numa vale revisar as outras.",
            padrao=str(padrao), tipo=NUMERO))
    return tuple(itens)


CATALOGO: tuple[Grupo, ...] = (
    Grupo("Portal vSky", "fa-cloud-arrow-down",
          "Acesso ao portal de onde vêm os dados e os prontuários.", (
              Chave("vsky_base_url", "Endereço do portal",
                    "Raiz do vSky, sem barra no fim. Só mude se o portal "
                    "trocar de domínio.", padrao=DEFAULT_BASE_URL),
              Chave("vsky_usuario", "Usuário",
                    "Login usado para baixar o relatório analítico e as "
                    "fichas em PDF. Sem ele o download automático e o botão "
                    "'Investigar evento' não funcionam."),
              Chave("vsky_senha", "Senha",
                    "Senha do usuário acima. Guardada criptografada; a tela "
                    "nunca mostra o valor. Deixar em branco mantém a atual.",
                    tipo=SENHA),
              Chave("vsky_cliente_id", "Cliente (ID)",
                    "Opcional. Em branco usa o cliente padrão da conta. "
                    "Só preencha se o portal exigir escolher o cliente."),
          )),

    Grupo("Importação automática do vSky", "fa-rotate",
          "Agendamento do download do relatório analítico.", (
              Chave("vsky_auto_ativo", "Importação automática ligada",
                    "1 liga, vazio desliga. Ligada, o sistema busca os dados "
                    "sozinho no horário ou intervalo definido abaixo.",
                    tipo=BOOLEANO),
              Chave("vsky_auto_modo", "Modo",
                    "'diario' roda uma vez por dia na hora marcada; "
                    "'intervalo' roda de tantos em tantos minutos, para "
                    "manter os painéis quase em tempo real.",
                    padrao="diario", tipo=LISTA,
                    opcoes=("diario", "intervalo")),
              Chave("vsky_auto_hora", "Hora (modo diário)",
                    "HH:MM. Prefira a madrugada: a importação concorre com o "
                    "uso do portal.", padrao="03:00", tipo=HORA),
              Chave("vsky_auto_intervalo", "Intervalo em minutos",
                    "Usado só no modo 'intervalo'. Abaixo de 20 minutos o "
                    "ganho é pequeno e a carga no portal cresce.",
                    padrao="60", tipo=NUMERO),
              Chave("vsky_auto_dias", "Dias reimportados",
                    "Quantos dias para trás cada execução rebaixa. O vSky "
                    "corrige registros depois de fechados, então reimportar "
                    "alguns dias recupera essas correções.",
                    padrao="2", tipo=NUMERO),
              Chave("vsky_auto_ultima", "Última execução",
                    "Quando a importação automática rodou pela última vez. "
                    "Escrito pelo sistema; se estiver muito atrasado, o "
                    "agendamento parou.", somente_leitura=True),
              Chave("vsky_auto_status", "Resultado da última execução",
                    "Sucesso ou o erro da última importação. É aqui que "
                    "aparece credencial vencida ou portal fora do ar.",
                    somente_leitura=True),
          )),

    Grupo("Indicadores", "fa-chart-line",
          "Régua usada para julgar os tempos do atendimento.", (
              Chave("indicadores_p41_desconto_segundos",
                    "Desconto de transmissão no P4.1",
                    "Segundos descontados da saída de base para compensar o "
                    "atraso do GPS/rede móvel até a marcação chegar ao "
                    "sistema. Não se aplica quando o tempo bruto é menor que "
                    "o próprio desconto. Mudar aqui recalcula os painéis na "
                    "hora, sem reimportar.",
                    padrao=str(DESCONTO_P41_PADRAO), tipo=NUMERO),
          ) + _metas_indicadores()),

    Grupo("Cópia de segurança", "fa-database",
          "Backup do banco. Ajustável também na própria tela de Backup.", (
              Chave("backup_ativo", "Cópia diária ligada",
                    "1 liga, vazio desliga. Sem isso não existe cópia "
                    "automática — só a manual, feita a cada clique.",
                    tipo=BOOLEANO, gerida_em="/backup/"),
              Chave("backup_hora", "Hora da cópia",
                    "HH:MM. A cópia não trava as tabelas, mas concorre por "
                    "disco; madrugada é o melhor horário.",
                    padrao="02:00", tipo=HORA, gerida_em="/backup/"),
              Chave("backup_manter", "Cópias a manter",
                    "Quantas cópias ficam guardadas. As mais antigas são "
                    "apagadas depois de cada nova cópia.",
                    padrao=str(MANTER_PADRAO), tipo=NUMERO,
                    gerida_em="/backup/"),
              Chave("backup_diretorio", "Pasta de destino",
                    "Em branco grava em uploads/backups. Apontar para um "
                    "disco diferente do banco é o que protege contra falha "
                    "de hardware — no destino padrão, o disco leva a base e "
                    "a cópia juntas.", gerida_em="/backup/"),
              Chave("backup_status", "Resultado da última cópia",
                    "Sucesso (com nome e tamanho do arquivo) ou o erro. "
                    "Escrito pelo sistema a cada execução.",
                    somente_leitura=True),
              Chave("backup_ultima", "Data da última cópia",
                    "Quando a última cópia foi tentada. Data velha aqui "
                    "significa que não há cópia recente do banco.",
                    somente_leitura=True),
          )),

    Grupo("Inteligência artificial", "fa-robot",
          "Modelo usado na análise de causa raiz da Investigação de Eventos.", (
              Chave("ia_provedor", "Provedor",
                    "openai, anthropic, gemini ou ollama. O ollama roda "
                    "local: nenhum dado de paciente sai da máquina, ao custo "
                    "de ser bem mais lento.",
                    padrao="ollama", tipo=LISTA,
                    opcoes=("openai", "anthropic", "gemini", "ollama")),
              Chave("ia_modelo", "Modelo",
                    "Nome exato do modelo no provedor. A tela de "
                    "Investigação > Configuração lista os disponíveis.",
                    gerida_em="/investigacao/config"),
              Chave("ia_api_key", "Chave da API",
                    "Credencial do provedor. Guardada criptografada. O "
                    "ollama local dispensa. Chave exposta em texto deve ser "
                    "trocada no provedor, não só aqui.", tipo=SENHA),
              Chave("ia_base_url", "Endereço do provedor",
                    "Só para ollama ou endpoint próprio. Em branco usa o "
                    "endereço oficial do provedor escolhido.",
                    padrao="http://localhost:11434"),
              Chave("ia_timeout", "Tempo limite em segundos",
                    "Quanto esperar pela resposta. Modelo local de "
                    "raciocínio passa de 3 minutos numa análise completa; "
                    "abaixo de 300 s a análise costuma ser cortada no meio.",
                    padrao="600", tipo=NUMERO),
          )),

    Grupo("Investigação de eventos", "fa-magnifying-glass-chart",
          "Preenchimento padrão do relatório RAC (FOR.SAMU.038).", (
              Chave("rac_time_investigacao", "Time de investigação",
                    "Nomes que entram por padrão em DADOS GERAIS do RAC. "
                    "Pode ser trocado em cada relatório."),
          )),

    Grupo("Relatório de gestão por e-mail", "fa-envelope",
          "Envio automático do PDF do painel de gestão.", (
              Chave("relatorio_email_ativo", "Envio automático ligado",
                    "1 liga, vazio desliga. Exige o SMTP configurado abaixo.",
                    tipo=BOOLEANO, gerida_em="/painel_gestao/"),
              Chave("relatorio_email_modo", "Frequência",
                    "'semanal' envia no dia da semana escolhido; 'diario' "
                    "envia todo dia.", padrao="semanal", tipo=LISTA,
                    opcoes=("semanal", "diario"), gerida_em="/painel_gestao/"),
              Chave("relatorio_email_dia", "Dia da semana",
                    "Sigla em inglês usada pelo agendador: mon, tue, wed, "
                    "thu, fri, sat, sun. Vale só no modo semanal.",
                    padrao="mon", gerida_em="/painel_gestao/"),
              Chave("relatorio_email_hora", "Hora do envio",
                    "HH:MM.", padrao="07:00", tipo=HORA,
                    gerida_em="/painel_gestao/"),
              Chave("relatorio_email_destinatarios", "Destinatários",
                    "E-mails separados por vírgula ou ponto e vírgula.",
                    gerida_em="/painel_gestao/"),
              Chave("relatorio_email_status", "Resultado do último envio",
                    "Sucesso ou o erro do SMTP. Escrito pelo sistema.",
                    somente_leitura=True),
              Chave("relatorio_email_ultima", "Data do último envio",
                    "Quando o relatório foi enviado pela última vez.",
                    somente_leitura=True),
          )),

    Grupo("Envio de e-mail (SMTP)", "fa-paper-plane",
          "Sem isto o sistema não envia nada — nem relatório, nem "
          "recuperação de senha.", (
              Chave("smtp_host", "Servidor",
                    "Endereço do servidor de saída, ex.: smtp.gmail.com."),
              Chave("smtp_port", "Porta",
                    "587 para STARTTLS (o usual), 465 para SSL.",
                    padrao="587", tipo=NUMERO),
              Chave("smtp_user", "Usuário",
                    "Conta que autentica no servidor."),
              Chave("smtp_pass", "Senha",
                    "Guardada criptografada. No Gmail e similares use senha "
                    "de aplicativo, não a senha da conta.", tipo=SENHA),
              Chave("smtp_from", "Remetente",
                    "Endereço que aparece como remetente. Muitos servidores "
                    "exigem que seja o mesmo do usuário."),
          )),

    Grupo("Sistema", "fa-sliders", "", (
              Chave("timezone", "Fuso horário",
                    "Fuso de exibição das datas, ex.: America/Sao_Paulo. "
                    "Não altera o que está gravado no banco.",
                    padrao="America/Sao_Paulo"),
              Chave("idioma", "Idioma", "Idioma da interface.",
                    padrao="pt-BR"),
          )),

    Grupo("Aparência", "fa-palette",
          "Editável na tela de Aparência, com pré-visualização.", (
              Chave("brand_nome", "Nome exibido", "Nome do sistema no topo e "
                    "no rodapé.", gerida_em="/configuracoes/aparencia"),
              Chave("logo_arquivo_id", "Logo (id do arquivo)",
                    "Preenchido ao enviar a imagem na tela de Aparência.",
                    gerida_em="/configuracoes/aparencia"),
              Chave("tema", "Tema", "claro ou escuro.", padrao="claro",
                    tipo=LISTA, opcoes=("claro", "escuro"),
                    gerida_em="/configuracoes/aparencia"),
              Chave("cor_primaria", "Cor primária",
                    "Cor em hexadecimal (#0d6efd). Em branco usa a padrão.",
                    gerida_em="/configuracoes/aparencia"),
              Chave("sidebar_tema", "Tema do menu lateral",
                    "auto, claro ou escuro.", padrao="auto", tipo=LISTA,
                    opcoes=("auto", "claro", "escuro"),
                    gerida_em="/configuracoes/aparencia"),
              Chave("sidebar_mini", "Menu compacto", "1 liga, vazio desliga.",
                    tipo=BOOLEANO, gerida_em="/configuracoes/aparencia"),
              Chave("sidebar_colapsada", "Menu recolhido ao abrir",
                    "1 liga, vazio desliga.", tipo=BOOLEANO,
                    gerida_em="/configuracoes/aparencia"),
              Chave("layout_fixo", "Layout fixo", "sim ou nao.",
                    padrao="nao", tipo=LISTA, opcoes=("sim", "nao"),
                    gerida_em="/configuracoes/aparencia"),
              Chave("header_fixo", "Topo fixo", "sim ou nao.", padrao="nao",
                    tipo=LISTA, opcoes=("sim", "nao"),
                    gerida_em="/configuracoes/aparencia"),
              Chave("footer_fixo", "Rodapé fixo", "sim ou nao.",
                    padrao="nao", tipo=LISTA, opcoes=("sim", "nao"),
                    gerida_em="/configuracoes/aparencia"),
          )),
)


def catalogadas() -> dict[str, Chave]:
    """Todas as chaves conhecidas, indexadas pelo nome."""
    return {c.chave: c for grupo in CATALOGO for c in grupo.chaves}
