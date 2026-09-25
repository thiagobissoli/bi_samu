# Módulo Indicadores

31 dashboards sobre os registros importados do vSky (`vsky_registros_analiticos`,
módulo download_vsky), mais Correlação, Desempenho e Calendários.

## Como as telas funcionam

- **Nada é calculado ao abrir.** A tela vem com os últimos 30 dias da base
  preenchidos e só monta os dados depois de **Aplicar**. As opções dos
  selects chegam à parte (`/indicadores/api/opcoes`).
- **Filtros** (catálogo único em `filtros.py`): período, hora do dia (aceita
  virar a meia-noite), dia da semana, turno, código e cor, risco, tipo,
  motivo, situação, atendimento, transporte, óbito, tipo de viatura,
  unidade, ISCM, viatura de outro município, cidade, convênio, micro região,
  hospital, sexo, faixa etária, idade, NEWS, profissionais de cada papel e
  "indicador de tempo entre X e Y minutos". Os principais ficam à vista; o
  resto em "Mais filtros".
- **Clique em qualquer gráfico** (barra, ponto, fatia ou célula do mapa de
  calor) abre a lista das ocorrências que formaram aquele valor, com
  paginação, exportação em Excel e link para a Investigação. Cada gráfico
  leva uma descrição de detalhamento (`drill.py`) que fica no servidor; o
  navegador só manda índices.
- **Gráficos novos** nos temas de tempo: mapa de calor dia da semana × hora,
  distribuição acumulada (% concluídos até X min, com a meta) e faixa
  P25–P75 com mediana por unidade; mapa de calor de volume nas saídas.
- **Correlação** (`/indicadores/correlacao`, `correlacao.py`): dispersão
  X × Y com r de Pearson, ρ de Spearman, R², p-valor e reta de tendência;
  matriz de correlação entre vários indicadores; séries lado a lado com
  índice base 100. O agrupamento pode ser dia, semana, mês, hora, dia da
  semana, plantão, unidade, cidade, micro região, código, hospital ou
  profissional. Clicar num ponto lista as ocorrências do grupo.

## Dashboards

Processos P1–P9 · Tempo de Central · Tempo de Cena · Tempo de Saída de Base ·
Assertividade · Códigos da Ocorrência · Situação Atendimento · Cidade/Bairro/
Micro Região · Sexo/Idade/Faixa · Tipo e Motivo · Atendimento · Transporte ·
Unidade · Sinais Vitais + NEWS modificada · Óbito · Apoios Externos · Equipe.

## Regras de negócio (herdadas dos legados DBSamu/Desperdicio)

- `---`/vazio = ausente; 0 em FR/FC/Glasgow/Glicemia e PA `0/0` = **não medido**;
- Períodos P1–P9 derivados das colunas de data/hora; validade por métrica
  (`CAP_TEMPO`) descarta negativos e outliers;
- SLA: P1 ≤ 90 s; P2 por cor (vermelho 90 s, amarelo 180 s, verde/orientação 240 s);
- Assertividade: base APH, código da equipe × risco da triagem
  (vermelho↔Emergência/Muito Urgente, amarelo↔Urgente, verde↔Pouco Urgente);
- Convênio = Vitória + Vila Velha + Serra + Cariacica;
- ISCM = 42 viaturas do núcleo (USA 10–100 e USB pares 22–98 não múltiplas de 10);
- **NEWS modificada** (proposta local): FR, FC, PAS e Glasgow obrigatórios
  (0–3 pontos cada) + Glicemia opcional; bandas Baixo / Baixo-Médio (parâmetro
  isolado = 3) / Médio (5–6) / Alto (≥7).

## Arquitetura

| Arquivo | Responsabilidade |
|---------|------------------|
| nucleo.py | Carga (pandas, cache 5 min por empresa) + todas as derivações |
| filtros.py | Catálogo dos filtros: leitura, aplicação, opções e painel |
| service.py | Um construtor por tema (kpis/charts/tables) + detalhamento |
| drill.py | Descrição de cada gráfico → linhas por trás de cada ponto |
| correlacao.py | Dispersão, matriz e séries; estatística (p-valor sem scipy) |
| routes.py | Telas, `/api/{tema}`, `/api/{tema}/ocorrencias`, `/api/correlacao`, `/api/opcoes` |
| templates/dashboard.html | Renderizador genérico (Chart.js vendorizado) |
| templates/_filtros.html, _ocorrencias.html | Painel de filtros e lista de ocorrências compartilhados |

A API `GET /indicadores/api/{tema}` devolve o payload do dashboard no formato
padrão §17 — os mesmos filtros via query string.
