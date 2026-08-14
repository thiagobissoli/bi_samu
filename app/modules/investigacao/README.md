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

## Dossiê da ocorrência

Ao investigar um número, além da disponibilidade das viaturas a página
reúne:

1. **Indicadores medidos** — os mesmos dos dashboards (P1–P9, tempo de
   central e de resposta, assertividade, NEWS, plantão), lidos do núcleo;
2. **Onde o tempo foi consumido** — cada etapa comparada à sua meta e à
   **referência do serviço** (mediana do próprio SAMU em casos com o
   mesmo código de gravidade e tipo de viatura, com o n da amostra). As
   etapas acima da meta ou 1,5× acima da referência são apontadas como
   contribuintes do atraso, com o excesso em mm:ss e o % do tempo de
   resposta. Quando faltam marcações, o resumo informa quanto do tempo
   **não** é explicado — esse vão não se atribui a ninguém;
3. **Fatores do tempo de resposta (meta 10 min)** — ver abaixo;
4. **Prontuário** — baixa o PDF do vSky (ou serve do cache), registra
   páginas/tamanho e extrai o texto;
5. **Análise do evento por IA** — ver abaixo.

## Fatores do tempo de resposta

A meta é **10 minutos**. Passando disso, a página separa o que é
**distância estrutural** do que é **anormalidade no percurso**, do
**horário** e do **atraso de processo** — cada um com o número que o
sustenta:

| Fator | Como é apurado |
|---|---|
| Distância | O mesmo trajeto (aquela viatura → aquela cidade) costuma levar quanto? Se o caso está até 1,25× dessa mediana, o trajeto é longo por si só |
| Percurso | Acima disso, o deslocamento foi atípico *para aquele mesmo trajeto* — trânsito, rota ou acesso; a causa concreta precisa ser apurada com a equipe |
| Horário | A faixa horária é sistematicamente mais lenta naquela cidade? Compara a mediana da faixa com as demais; quando a diferença é pequena, o texto diz que o horário **não** explica |
| Origem da viatura | Quanto as viaturas sediadas na cidade levam até lá, versus o que esta levou |
| Processo | Etapas P1–P4.1 acima da meta ou da referência — tempo gasto antes de a viatura estar a caminho |

O vSky não registra rota nem condição de tráfego. O que o sistema pode
afirmar é a comparação com o histórico do próprio serviço — e é isso que
ele afirma, nada além.

## Análise por IA — formulário RAC

A saída segue o **FOR.SAMU.038 — Relatório de Evento Adverso com
Investigação de Causa Raiz**, na mesma ordem do formulário oficial:

1. **Dados gerais** — título, descrição do incidente, gravidade
   (Leve/Moderada/Grave/Óbito/Alto Potencial), local, ID e nível de
   investigação;
2. **Avaliação do risco antes** — matriz 5×5 do formulário, com a célula
   escolhida destacada. C = A × B é **recalculado no servidor**: o valor
   que a IA declara não é aceito, e combinação fora da escala é recusada;
3. **Cronologia detalhada dos eventos**;
4. **Fatores contribuintes (Protocolo de Londres)** — as sete categorias
   sempre aparecem, com os itens exatos do formulário em caixas de
   marcação. Item que não exista na categoria é descartado no
   pós-processamento; categoria sem evidência recebe
   "Não foi identificado.";
5. **Diagrama de Ishikawa (6M)** — complementar ao formulário;
6. **Conclusão**;
7. **Plano de ação** — ações numeradas com prazo, tipo e responsável;
8. **Avaliação do risco pós investigação** — risco residual esperado;
9. **A coletar / lacunas** — relatos dos envolvidos, notificação do NCPS
   e laudos **não** são inventados: entram como pendência da equipe.

O modelo não calcula indicadores nem decide se houve atraso — recebe
esse material pronto e verificado, e o interpreta. O prompt proíbe
inventar dados, exige declarar o que falta e orienta a analisar
processo, não pessoas. O resultado é persistido
(`investigacao_analises`) para não repetir a chamada a cada abertura.

### Provedores

Configuráveis em `/investigacao/config` (permissão
`investigacao.configurar`): **OpenAI**, **Anthropic** e **Ollama
(local)**. Chaves guardadas criptografadas (§39.29). Há botão de teste
de conexão.

Modelos de raciocínio no Ollama (qwen3, deepseek-r1…) devolvem o texto
no campo `thinking` em vez de `response` — o cliente trata os dois.

### Privacidade (LGPD)

OpenAI e Anthropic processam o conteúdo **fora da rede do SAMU**, e o
prontuário contém dados pessoais e de saúde (LGPD art. 11). Para
analisar o texto integral, o indicado é o **Ollama local**. Ao usar
provedor externo, a anonimização vem ligada por padrão: remove nome do
paciente, CPF, CNS e telefone — mas não garante que a narrativa deixe de
identificar alguém, e a tela diz isso.
