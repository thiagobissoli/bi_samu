# Módulo Investigação de Eventos

Responde à pergunta operacional que motiva a auditoria de um empenho:
**quando uma ocorrência foi atendida por viatura de outro município, as
viaturas do próprio município estavam ocupadas naquele instante?**

## Definição de "ocupada"

Uma viatura está ocupada entre o **início do deslocamento** e o
**encerramento do atendimento** — o intervalo em que não pode receber
novo chamado. Quando falta o início do deslocamento, usa-se a saída para
atendimento (J9); quando falta o encerramento, usa-se a última marcação
conhecida do empenho (chegada ao hospital → saída para hospital →
chegada ao local).

Janelas com fim anterior ao início, ou acima de 24 h (marcação esquecida
em aberto), são descartadas.

> **Ressalva importante:** "sem empenho" significa apenas que não há
> atendimento registrado no instante. A viatura pode estar fora de
> escala, em manutenção ou indisponível por motivo que o relatório do
> vSky não informa. A tela exibe essa ressalva junto dos resultados.

## Município-base da viatura

Extraído do próprio nome da unidade (`USA 50 - CARIACICA` → `CARIACICA`)
e comparado com a cidade da ocorrência, normalizando acentos e caixa. A
divergência entre os dois marca o **empenho de outro município**.

## Telas

| Recurso | O que mostra |
|---|---|
| **Investigar ocorrência** | Dados do empenho + situação de **cada** viatura sediada no município da ocorrência no instante do acionamento (ocupada, com qual ocorrência e até quando / sem empenho) e uma conclusão em texto |
| **Timeline do dia** | Régua de 24 h com uma faixa por viatura; barras vermelhas = ocupada, roxas = ocupada em outro município. Clicar numa barra investiga aquela ocorrência |
| **Empenhos de outro município** | Pauta do dia: todos os casos, com hora, viatura, sede, município atendido e tempo de resposta |

Filtros da timeline: data, município da viatura e viatura (multi-seleção).

## Rotas

- `GET /investigacao` — página (permissão `investigacao.visualizar`)
- `GET /investigacao/api/timeline` — ocupação do dia (JSON §17)
- `GET /investigacao/api/investigar?ocorrencia=` — análise de um empenho

## Arquitetura

Somente leitura: consome o núcleo do módulo **indicadores**
(`nucleo.carregar`, cache compartilhado) e não persiste nada. O tempo de
resposta usa o mesmo teto de validade dos dashboards — valores fora da
faixa aparecem vazios em vez de passarem por medição boa.
