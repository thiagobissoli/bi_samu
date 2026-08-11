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

## Arquitetura

Consome o núcleo de dados do módulo **indicadores** (`nucleo.carregar`,
cache compartilhado) — não persiste nada. Payload cacheado por versão dos
dados (invalida quando o Download vSky importa registros novos).

- `GET /painel_gestao` — página (permissão `painel_gestao.visualizar`)
- `GET /painel_gestao/api` — payload JSON (formato §17)
