# Módulo Indicadores

17 dashboards sobre os registros importados do vSky (`vsky_registros_analiticos`,
módulo download_vsky), com filtros globais em todas as páginas: **data inicial,
data final, convênio (Grande Vitória), ISCMV, transporte, motivo e tipo**.

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
- ISCMV = 42 viaturas do núcleo (USA 10–100 e USB pares 22–98 não múltiplas de 10);
- **NEWS modificada** (proposta local): FR, FC, PAS e Glasgow obrigatórios
  (0–3 pontos cada) + Glicemia opcional; bandas Baixo / Baixo-Médio (parâmetro
  isolado = 3) / Médio (5–6) / Alto (≥7).

## Arquitetura

| Arquivo | Responsabilidade |
|---------|------------------|
| nucleo.py | Carga (pandas, cache 5 min por empresa) + todas as derivações |
| service.py | Filtros globais + um construtor por tema (kpis/charts/tables) |
| routes.py | `/indicadores` (índice), `/indicadores/{tema}`, `/indicadores/api/{tema}` |
| templates/dashboard.html | Renderizador genérico (Chart.js vendorizado) |

A API `GET /indicadores/api/{tema}` devolve o payload do dashboard no formato
padrão §17 — os mesmos filtros via query string.
