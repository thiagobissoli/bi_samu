# Módulo NCPS

Notificação de eventos de **segurança do paciente** e de **saúde e segurança
do trabalhador** (NR-1), com a tratativa completa: triagem, classificação,
matriz de risco do PGR, análise sistêmica (Protocolo de Londres / NR-1
1.5.5.5), Ishikawa e plano de ação com verificação de eficácia.

Portado do sistema Flask anterior (`PycharmProjects/samu/app/ncps`)
mantendo os mesmos códigos de classificação e as mesmas regras de acesso.

## Telas

| URL | Quem | O quê |
|---|---|---|
| `/ncps/publico` | qualquer pessoa, sem login | notificação sempre anônima |
| `/ncps/acompanhar` | qualquer pessoa, sem login | andamento pelo protocolo + código |
| `/ncps/notificar` | `ncps.notificar` | notificação identificada (ou anônima, se sigilosa) e "minhas notificações" |
| `/ncps/` | `ncps.listar` | lista com filtros, busca e exportação para Excel |
| `/ncps/{id}` | `ncps.listar` + regra de visibilidade | análise em abas |
| `/ncps/painel` | `ncps.listar` | indicadores |
| `/ncps/cadastros` | `ncps.cadastros` | setores de análise e seus analistas, gestores, locais e token do Power BI |
| `/ncps/pgr` | `ncps.pgr` | GHE e perigos do inventário |
| `/ncps/api/powerbi` | token Bearer | todas as notificações, exceto as sigilosas |

## Quem vê o quê

As regras ficam em `permissions.py`. Um usuário vê uma notificação quando:

- ela é **sigilosa** (violência/assédio) → só com `ncps.sigilosas` (Comissão de Integridade);
- é do **paciente** → `ncps.triar_paciente` (Qualidade) ou `ncps.coordenar`;
- é do **trabalhador** → `ncps.triar_trabalhador` (SESMT);
- ou ele é **analista do setor** a que a NCPS foi encaminhada.

Quem tria (`triar_*` / `sigilosas`) altera tudo e encaminha a NCPS a um
**setor**. Os analistas do setor — usuários com `ncps.coordenar`, vinculados
em Cadastros NCPS → Setores de análise — registram a classificação, a
análise, o risco e as ações, mas não a triagem, e são avisados nas
notificações do sistema quando uma NCPS chega ao setor. NCPS importadas do
sistema anterior mantêm o coordenador de lá.

## Matriz de risco

A mesma do formulário FOR.SAMU.038 usada pela IA na Investigação de Eventos:
probabilidade de Raro (1) a Quase certo (5), consequência Desprezível (1),
Menor (2), Moderada (4), Maior (8) ou Catastrófica (16), classificação
C = A × B (Baixo, Moderado ≥ 4, Elevado ≥ 10, Extremo ≥ 20), avaliada antes
da investigação e como risco residual com o plano executado.

Para reproduzir os perfis do sistema anterior, crie em **Perfis**:

| Perfil | Permissões |
|---|---|
| Qualidade | `ncps.notificar`, `ncps.listar`, `ncps.triar_paciente`, `ncps.exportar`, `ncps.cadastros` |
| SESMT | `ncps.notificar`, `ncps.listar`, `ncps.triar_trabalhador`, `ncps.exportar`, `ncps.pgr` |
| Comissão de Integridade | `ncps.notificar`, `ncps.listar`, `ncps.sigilosas` |
| Coordenador (analista) | `ncps.notificar`, `ncps.listar`, `ncps.coordenar` + vínculo a um setor |
| Colaborador | `ncps.notificar` |

## Protocolo e código de acompanhamento

Toda notificação recebe um **protocolo** (o id) e um **código** de 8
caracteres, mostrado uma única vez; o banco guarda só o hash. A consulta
pública exige os dois. As importadas do sistema anterior sem código (lá só
as sigilosas tinham) continuam consultáveis apenas pelo protocolo, como antes.

O formulário público e a consulta têm limite de tentativas por IP.

## Integração com o vSky

O nº da ocorrência informado é conferido nos dados importados pelo módulo
**Download vSky**. Quando existe, a análise mostra um link para o dossiê
da ocorrência no módulo **Investigação de Eventos**.

## Importar do sistema anterior

```bash
python -m app.modules.ncps.importar_legado --origem "mysql+pymysql://usuario:senha@host:3306/samu"
```

Sem `--aplicar`, apenas simula. A importação é idempotente (pode ser
repetida para trazer as notificações novas), mantém o id de lá como
protocolo e casa os usuários pelo e-mail. Detalhes no docstring do script.
