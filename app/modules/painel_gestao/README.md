# Módulo Painel de Gestão

Página executiva com os principais indicadores operacionais, **filtros
pré-estabelecidos** por indicador — sem barra de filtros, pensada para o
gestor abrir e ler.

## Regras de apresentação

- **KPIs** (números grandes): sempre a **última semana ISO completa**
  (≥ 6 dias com dados);
- **Gráficos de linha**: últimos **12 meses**;
- Tempo resposta: sempre a **1ª ambulância a chegar** na ocorrência.

## Seções e filtros fixos

| Seção | Recorte |
|---|---|
| Tempo Resposta | Convênio (GV) códigos V/A/V · USA Vermelho · USB Vermelho — cada um Geral/Diurno/Noturno |
| Assertividade | Base APH nas viaturas ISCMV |
| Transferência | Inter-hospitalar das viaturas ISCMV — volume, TR e códigos |
| Plantão | TR pelos 14 plantões (dia × turno), 12 meses |
| Desperdício | Universo ISCMV — % real × evitado + Pareto de motivos |

## Relatório de Gestão (PDF)

O botão **Relatório de Gestão (PDF)** no topo do painel baixa o
documento completo: capa com o período de referência e o índice, e
depois uma página por seção com os KPIs e os gráficos.

O PDF é gerado **no servidor** (`relatorio.py`, reportlab + matplotlib) a
partir das mesmas especificações de gráfico que o Chart.js usa na tela —
não é captura de tela, então o texto sai vetorial. Gerador único: o botão
e o envio automático por e-mail chamam a mesma `gerar_pdf()`, de modo que
os dois documentos nunca divergem.

## Envio automático por e-mail

Em **/painel_gestao/config** (permissão `painel_gestao.configurar`):
destinatários, frequência (semanal em dia fixo ou diária) e hora. O job
(APScheduler, `scheduler.py`) gera o relatório e o envia em anexo; o
resultado do último envio aparece na própria tela. O botão
**Salvar e enviar agora** dispara um envio imediato para teste.

Depende do SMTP configurado em §22 (`smtp_host`, `smtp_port`,
`smtp_user`, `smtp_pass`, `smtp_from`) — sem ele o conteúdo apenas vai
para os Logs, e a tela avisa.

Chaves de configuração: `relatorio_email_ativo`, `relatorio_email_modo`,
`relatorio_email_dia`, `relatorio_email_hora`,
`relatorio_email_destinatarios`, além de `relatorio_email_status` e
`relatorio_email_ultima` (resultado do último envio).

## Arquitetura

Consome o núcleo de dados do módulo **indicadores** (`nucleo.carregar`,
cache compartilhado) — não persiste nada. Payload cacheado por versão dos
dados (invalida quando o Download vSky importa registros novos).

- `GET /painel_gestao` — página (permissão `painel_gestao.visualizar`)
- `GET /painel_gestao/relatorio.pdf` — Relatório de Gestão em PDF
- `GET|POST /painel_gestao/config` — envio automático (`painel_gestao.configurar`)
- `GET /painel_gestao/api` — payload JSON (formato §17)
