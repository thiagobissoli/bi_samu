# Especificação Base para Plataforma SaaS

**Versão:** 1.0
**Objetivo:** Definir a arquitetura padrão para desenvolvimento de aplicações SaaS modernas, escaláveis e reutilizáveis utilizando Python/FastAPI.

---

# 1. Stack Tecnológica

## Backend

- Python 3.13+
- FastAPI
- SQLAlchemy 2.x
- Alembic
- Pydantic V2
- Uvicorn
- Redis
- Celery (tarefas assíncronas)

---

## Frontend

- Bootstrap 5
- AdminLTE 4
- Jinja2
- HTMX
- Alpine.js
- jQuery (somente para plugins do AdminLTE)

---

## Banco de Dados

- PostgreSQL 16+

---

## Infraestrutura

- Docker
- Docker Compose
- Nginx
- GitHub Actions
- Certificados SSL (Let's Encrypt)

---

# 2. Arquitetura

Modelo:

Monólito Modular

```
Cliente

↓

Nginx

↓

FastAPI

├── Auth
├── IAM
├── Dashboard
├── Empresas
├── Usuários
├── Configurações
├── Auditoria
├── API
└── Módulos do Sistema

↓

PostgreSQL

↓

Redis
```

---

# 3. Organização do Projeto

```
app/

    api/

    auth/

    core/

    database/

    middleware/

    models/

    repositories/

    services/

    schemas/

    security/

    permissions/

    tenants/

    audit/

    dashboard/

    templates/

    static/

    migrations/

    tests/

config/

scripts/

docker/

docs/
```

---

# 4. Princípios

- Clean Architecture
- SOLID
- Repository Pattern
- Service Layer
- Dependency Injection
- DRY
- KISS

---

# 5. Multiempresa (Multi-Tenant)

Todo registro pertence a uma empresa.

```
Empresa

↓

Usuários

↓

Dados
```

Todas as tabelas possuem:

```
empresa_id
```

Nenhum usuário pode visualizar registros de outra empresa.

---

# 6. Identidade (IAM)

## Autenticação

- Login
- Logout
- Recuperação de senha
- Alteração de senha
- Confirmação de e-mail
- MFA (opcional)

Senha:

Argon2

Sessão:

Cookies HTTPOnly

JWT:

Somente APIs externas.

---

# 7. Autorização

Modelo:

RBAC + ABAC

## RBAC

Usuário

↓

Perfil

↓

Permissões

## ABAC

Permissões condicionadas por atributos.

Exemplos:

- Empresa
- Unidade
- Departamento
- Horário
- Status
- Proprietário do registro

---

# 8. Entidades Base

## Empresa

- id
- razão social
- nome fantasia
- CNPJ
- e-mail
- telefone
- plano
- status

---

## Usuário

- id
- empresa_id
- nome
- e-mail
- senha
- ativo
- último login

---

## Perfil

- id
- nome
- descrição

---

## Permissão

- id
- código
- descrição
- módulo

---

## PerfilPermissão

Relacionamento N:N

---

## UsuárioPerfil

Relacionamento N:N

---

# 9. Estrutura de Permissões

Formato:

```
modulo.acao
```

Exemplos

```
usuario.listar

usuario.criar

usuario.editar

usuario.excluir

empresa.editar

dashboard.visualizar

financeiro.aprovar

estoque.movimentar
```

---

# 10. Dashboard

Todo módulo pode fornecer widgets.

Widgets:

- Cards
- Gráficos
- KPIs
- Tabelas
- Alertas

Dashboard personalizado por perfil.

---

# 11. Auditoria

Registrar:

- usuário
- empresa
- IP
- navegador
- data
- ação
- módulo
- registro
- valores anteriores
- valores novos

Nunca apagar auditoria.

---

# 12. Logs

Níveis

- INFO
- WARNING
- ERROR
- CRITICAL

Logs separados por módulo.

---

# 13. Soft Delete

Toda entidade deve possuir

```
deleted_at
deleted_by
```

Nunca excluir fisicamente registros críticos.

---

# 14. Campos Base

Toda tabela possui:

```
id

empresa_id

created_at

updated_at

created_by

updated_by

deleted_at

deleted_by

version
```

---

# 15. Versionamento

Controle otimista.

Campo

```
version
```

Evita sobrescrita concorrente.

---

# 16. API

REST

Padrão

```
GET

POST

PUT

PATCH

DELETE
```

Documentação automática:

Swagger

OpenAPI

---

# 17. Respostas

Formato padrão

```json
{
    "success": true,
    "message": "",
    "data": {},
    "errors": []
}
```

---

# 18. Paginação

Padrão

```
page

per_page

total

pages
```

---

# 19. Pesquisa

Todos os módulos devem possuir

- busca textual
- filtros
- ordenação
- paginação

---

# 20. Upload de Arquivos

Suporte para

- imagens
- PDF
- Excel
- Word

Armazenamento:

```
uploads/

empresa/

modulo/

ano/

mes/
```

---

# 21. Notificações

Tipos

- Sistema
- E-mail
- Push
- WhatsApp (futuro)

---

# 22. Configurações

Cada empresa possui configurações próprias.

Exemplo

- Logo
- Tema
- Idioma
- Fuso horário
- Máscaras
- SMTP

---

# 23. Internacionalização

Preparado para

- pt-BR
- en-US
- es

---

# 24. Temas

AdminLTE

- Claro
- Escuro

---

# 25. Segurança

Headers

- CSP
- HSTS
- X-Frame
- XSS Protection

Proteções

- CSRF
- SQL Injection
- XSS
- Rate Limit
- Brute Force

---

# 26. Cache

Redis

Cache para

- menus
- permissões
- configurações
- dashboard

---

# 27. Tarefas Assíncronas

Celery

Exemplos

- envio de e-mail
- geração de PDF
- importações
- exportações

---

# 28. Testes

Obrigatórios

- Unitários
- Integração
- API

Ferramentas

- Pytest
- HTTPX

---

# 29. CI/CD

GitHub Actions

Pipeline

- Testes
- Lint
- Build Docker
- Deploy

---

# 30. Deploy

```
Docker

↓

Nginx

↓

FastAPI

↓

Redis

↓

PostgreSQL
```

---

# 31. Módulos Base

Todos os SaaS deverão possuir:

- Dashboard
- Empresas
- Usuários
- Perfis
- Permissões
- Auditoria
- Configurações
- Notificações
- API
- Logs
- Uploads

---

# 32. Componentes Reutilizáveis

- DataTable
- Formulários
- Modal
- Wizard
- Cards
- KPIs
- Timeline
- Kanban
- Calendário
- Upload
- Editor HTML
- Editor Markdown
- Visualizador PDF

---

# 33. Qualidade de Código

Padrões

- Black
- Ruff
- isort
- MyPy

---

# 34. Objetivo da Plataforma

Esta arquitetura servirá como base para qualquer sistema SaaS desenvolvido, permitindo a criação de novos módulos sem alteração da infraestrutura principal.

Os módulos deverão compartilhar:

- autenticação;
- autorização;
- auditoria;
- notificações;
- dashboard;
- componentes visuais;
- API;
- banco de dados;
- infraestrutura;
- segurança;
- padrões de desenvolvimento.

O objetivo é manter uma plataforma única, escalável, reutilizável e preparada para aplicações corporativas, incluindo sistemas de gestão, saúde, logística, educação, financeiro e soluções baseadas em inteligência artificial.

# 35. Framework de Desenvolvimento

## 35.1 Objetivo

Estabelecer um conjunto de convenções e componentes reutilizáveis para que todos os sistemas desenvolvidos sobre a plataforma mantenham a mesma arquitetura, organização, experiência do usuário e padrão de código.

Todo novo projeto deverá utilizar esta estrutura como ponto de partida, evitando duplicação de código e reduzindo o tempo de desenvolvimento.

---

# 35.2 Estrutura dos Módulos

Cada módulo deverá possuir exatamente a seguinte estrutura:

```
modulo/

    models.py

    schemas.py

    repository.py

    service.py

    routes.py

    forms.py

    permissions.py

    validators.py

    constants.py

    utils.py

    templates/

    static/
```

Responsabilidades:

| Arquivo | Responsabilidade |
|----------|------------------|
| models.py | Modelos SQLAlchemy |
| schemas.py | DTOs/Pydantic |
| repository.py | Acesso ao banco |
| service.py | Regras de negócio |
| routes.py | Endpoints |
| forms.py | Formulários |
| permissions.py | Permissões do módulo |
| validators.py | Validações |
| constants.py | Constantes |
| utils.py | Funções auxiliares |

---

# 35.3 Fluxo da Aplicação

Nenhuma rota poderá acessar diretamente o banco.

Fluxo obrigatório:

```
View

↓

Service

↓

Repository

↓

Database
```

---

# 35.4 Convenção de Nomenclatura

## Classes

PascalCase

```
Usuario

Empresa

Paciente
```

---

## Arquivos

snake_case

```
user_service.py

patient_repository.py

finance_routes.py
```

---

## Variáveis

snake_case

```
empresa_id

usuario_logado

data_inicio
```

---

## Constantes

UPPER_CASE

```
MAX_UPLOAD_SIZE

DEFAULT_LANGUAGE

SESSION_TIMEOUT
```

---

## URLs

Sempre em minúsculas

```
/usuarios

/empresas

/pacientes
```

Nunca:

```
/Usuarios

/Pacientes
```

---

# 35.5 CRUD Padrão

Todo módulo deverá implementar:

```
Listar

Visualizar

Criar

Editar

Excluir

Restaurar

Duplicar

Exportar
```

Sempre que aplicável.

---

# 35.6 Templates

Todo módulo possuirá:

```
index.html

create.html

edit.html

show.html

form.html

modal.html
```

---

# 35.7 Template Base

Todos herdam

```
base.html
```

Contendo:

- Navbar
- Sidebar
- Breadcrumb
- Alertas
- Rodapé
- Menu dinâmico
- Área de conteúdo

---

# 35.8 Componentes Reutilizáveis

Criar biblioteca de componentes Jinja.

Exemplos:

```
components/

    card.html

    table.html

    modal.html

    form_input.html

    select.html

    textarea.html

    button.html

    badge.html

    pagination.html

    breadcrumb.html

    timeline.html

    alert.html
```

Todos reutilizáveis.

---

# 35.9 Macros Jinja

Criar macros para:

```
Campo texto

Campo data

Campo moeda

Campo CPF

Campo CNPJ

Campo telefone

Botões

Badges

Tabela

Paginação
```

Evitar HTML repetido.

---

# 35.10 DataTable Padrão

Todos os módulos utilizarão o mesmo componente.

Recursos:

- pesquisa
- paginação
- ordenação
- exportação
- filtros
- ações

---

# 35.11 Formulários

Todos os formulários deverão possuir:

- validação frontend
- validação backend
- mensagens padronizadas
- máscaras
- loading
- confirmação antes de excluir

---

# 35.12 Layout

Padrão AdminLTE.

Sidebar:

```
Dashboard

Cadastros

Movimentos

Relatórios

Configurações
```

Sem exceções.

---

# 35.13 Ícones

Utilizar somente:

Font Awesome 6

Nunca misturar bibliotecas.

---

# 35.14 JavaScript

Separar por módulo.

```
usuarios.js

empresas.js

financeiro.js
```

Evitar arquivos gigantes.

---

# 35.15 CSS

```
global.css

adminlte.css

modulo.css
```

Nunca alterar diretamente arquivos do AdminLTE.

---

# 35.16 Serviços

Cada regra de negócio deverá existir apenas no Service.

Exemplo:

```
Criar usuário

↓

UserService

↓

Repository
```

Nunca implementar regra diretamente na rota.

---

# 35.17 Repository

Responsável exclusivamente por:

- SELECT
- INSERT
- UPDATE
- DELETE

Nunca implementar regra de negócio.

---

# 35.18 Schemas

Utilizar Pydantic para:

- entrada
- saída
- validação
- documentação

---

# 35.19 Models

Somente persistência.

Nunca implementar lógica de negócio.

---

# 35.20 Mensagens

Padronizar:

```
Registro criado.

Registro atualizado.

Registro removido.

Operação realizada com sucesso.

Erro ao salvar.

Permissão negada.
```

---

# 35.21 Exceções

Criar exceções próprias.

Exemplo

```
BusinessException

PermissionException

ValidationException

NotFoundException
```

---

# 35.22 Helpers

Criar biblioteca compartilhada.

```
DateHelper

MoneyHelper

FileHelper

ImageHelper

StringHelper

PdfHelper

ExcelHelper

EmailHelper
```

---

# 35.23 Configuração

Toda configuração centralizada.

```
.env

settings.py
```

Nunca utilizar valores fixos.

---

# 35.24 Seeds

Criar dados iniciais.

- empresa exemplo
- administrador
- perfis
- permissões
- configurações

---

# 35.25 CLI

Disponibilizar comandos administrativos.

Exemplos:

```
Criar usuário

Criar empresa

Criar módulo

Importar dados

Exportar dados

Backup

Restore
```

---

# 35.26 Gerador de Módulos (Scaffolding)

Disponibilizar um comando para gerar automaticamente novos módulos.

Exemplo:

```
python manage.py create-module pacientes
```

O comando deverá criar automaticamente:

```
models.py

schemas.py

repository.py

service.py

routes.py

permissions.py

validators.py

templates/

static/
```

Além de registrar automaticamente:

- menu
- permissões
- rotas
- migração inicial (quando aplicável)

---

# 35.27 Checklist de Desenvolvimento

Todo módulo novo deverá possuir:

- CRUD completo
- Permissões
- Auditoria
- Logs
- Testes
- Documentação
- Exportação
- Pesquisa
- Paginação
- Filtros
- Responsividade
- Validações
- Mensagens padronizadas

---

# 35.28 Objetivo Final

A plataforma deverá funcionar como um framework proprietário para desenvolvimento de SaaS, permitindo que novos sistemas sejam criados rapidamente com arquitetura padronizada, componentes reutilizáveis e alta qualidade de código.

Qualquer novo módulo deverá ser implementado seguindo rigorosamente este documento, garantindo consistência visual, facilidade de manutenção, escalabilidade e redução do tempo de desenvolvimento.

# 36. Arquitetura do Banco de Dados

## 36.1 Objetivo

Definir um modelo de dados padronizado para servir como base de todos os sistemas SaaS desenvolvidos sobre a plataforma.

Toda aplicação deverá reutilizar as tabelas-base sempre que possível, evitando duplicação de estruturas e facilitando a manutenção, auditoria e evolução da plataforma.

---

# 36.2 Banco de Dados

Banco oficial da plataforma:

- PostgreSQL 16+

ORM:

- SQLAlchemy 2.x

Migrações:

- Alembic

Charset:

```
UTF-8
```

Timezone:

```
UTC
```

A apresentação das datas será convertida para o fuso horário configurado pela empresa.

---

# 36.3 Convenções

## Nome das tabelas

Sempre no plural.

Exemplo

```
usuarios

empresas

pacientes

produtos

notificacoes
```

---

## Nome das colunas

Sempre em snake_case.

```
created_at

empresa_id

nome_fantasia
```

---

## Chaves Primárias

Todas as tabelas deverão possuir

```
id BIGINT
```

gerado automaticamente.

---

## Chaves Estrangeiras

Nome padrão

```
empresa_id

usuario_id

perfil_id

arquivo_id
```

---

## Índices

Criar índices obrigatórios para:

- Foreign Keys
- Campos de pesquisa
- Campos utilizados em filtros
- Datas de criação
- Status

---

# 36.4 Campos Base

Todas as tabelas deverão possuir obrigatoriamente:

| Campo | Tipo |
|---------|------|
| id | BIGINT |
| empresa_id | BIGINT |
| created_at | TIMESTAMP |
| updated_at | TIMESTAMP |
| created_by | BIGINT |
| updated_by | BIGINT |
| deleted_at | TIMESTAMP NULL |
| deleted_by | BIGINT NULL |
| version | INTEGER |

Esses campos garantem:

- auditoria
- soft delete
- versionamento
- multiempresa

---

# 36.5 Tabelas Base

## empresas

```
id

razao_social

nome_fantasia

cnpj

email

telefone

logo

status

plano_id

timezone

idioma

created_at

updated_at
```

---

## usuarios

```
id

empresa_id

nome

email

senha_hash

telefone

foto

ultimo_login

ultimo_ip

ativo

mfa_habilitado

created_at

updated_at
```

---

## perfis

```
id

empresa_id

nome

descricao

ativo
```

---

## permissoes

```
id

codigo

nome

descricao

modulo

categoria
```

---

## usuarios_perfis

Relacionamento N:N

```
usuario_id

perfil_id
```

---

## perfis_permissoes

Relacionamento N:N

```
perfil_id

permissao_id
```

---

## configuracoes

Armazena configurações da empresa.

```
empresa_id

chave

valor
```

Exemplo

```
smtp_host

smtp_port

tema

idioma

logo
```

---

## auditoria

```
id

empresa_id

usuario_id

tabela

registro_id

acao

valor_anterior

valor_novo

ip

user_agent

created_at
```

---

## logs

```
id

empresa_id

nivel

modulo

mensagem

stacktrace

created_at
```

---

## notificacoes

```
id

empresa_id

usuario_id

titulo

mensagem

tipo

lida

created_at
```

---

## arquivos

```
id

empresa_id

nome_original

nome_servidor

mime_type

tamanho

hash

caminho

created_by

created_at
```

---

## sessoes

```
id

usuario_id

token

ip

user_agent

expires_at
```

---

## tokens

```
id

usuario_id

tipo

token

expira_em

utilizado
```

Tipos

- recuperação senha
- confirmação e-mail
- MFA
- API

---

# 36.6 Tabelas Compartilhadas

Estas tabelas deverão existir em qualquer sistema.

- empresas
- usuarios
- perfis
- permissoes
- usuarios_perfis
- perfis_permissoes
- auditoria
- notificacoes
- arquivos
- configuracoes
- logs
- sessoes
- tokens

---

# 36.7 Soft Delete

Nenhuma tabela deverá utilizar DELETE físico.

Utilizar

```
deleted_at

deleted_by
```

Todas as consultas deverão ignorar registros excluídos, exceto quando explicitamente solicitado.

---

# 36.8 Versionamento

Todas as tabelas possuirão

```
version
```

Incrementado automaticamente a cada UPDATE.

Utilizado para:

- controle otimista
- sincronização
- APIs

---

# 36.9 Multiempresa

Toda tabela funcional deverá possuir

```
empresa_id
```

Exemplo

```
pacientes

empresa_id

nome

cpf
```

Nunca permitir JOIN entre empresas diferentes.

Toda consulta deverá filtrar automaticamente pelo tenant atual.

---

# 36.10 Integridade

Todas as Foreign Keys deverão possuir restrições explícitas.

Preferencialmente

```
ON UPDATE CASCADE

ON DELETE RESTRICT
```

---

# 36.11 Auditoria

Toda alteração deverá gerar registro na tabela

```
auditoria
```

Operações monitoradas

- INSERT
- UPDATE
- DELETE (Soft Delete)
- LOGIN
- LOGOUT
- EXPORTAÇÃO
- IMPORTAÇÃO

---

# 36.12 Arquivos

Os arquivos nunca serão armazenados diretamente no banco.

Banco armazenará apenas metadados.

Estrutura física

```
uploads/

empresa/

modulo/

ano/

mes/

arquivo.ext
```

---

# 36.13 Chaves Únicas

Criar UNIQUE para

```
usuarios.email

empresas.cnpj

permissoes.codigo
```

E demais campos que exijam unicidade por regra de negócio.

---

# 36.14 Índices Obrigatórios

Criar índices para

```
empresa_id

created_at

updated_at

deleted_at

status

codigo

email

cnpj
```

Além de índices específicos para módulos com alto volume de consultas.

---

# 36.15 Views

Criar Views para consultas frequentes.

Exemplos

```
vw_dashboard

vw_usuarios

vw_permissoes

vw_notificacoes
```

---

# 36.16 Materialized Views

Utilizar para

- dashboards
- indicadores
- BI
- estatísticas

Atualização programada conforme necessidade.

---

# 36.17 Funções do Banco

Centralizar funções reutilizáveis.

Exemplos

```
gerar_codigo()

calcular_idade()

formatar_documento()

proximo_numero()
```

---

# 36.18 Triggers

Triggers recomendadas

- atualização automática de updated_at
- incremento de version
- geração de auditoria
- validações críticas
- sincronização de dados derivados

Evitar lógica de negócio complexa em triggers.

---

# 36.19 Backup

Estratégia

- Backup diário completo
- Backup incremental horário
- Retenção conforme política da aplicação
- Testes periódicos de restauração

---

# 36.20 Evolução do Banco

Toda alteração estrutural deverá ser realizada exclusivamente através do Alembic.

É proibido alterar o banco manualmente em ambientes de produção.

---

# 36.21 Objetivo Final

A arquitetura do banco de dados deverá fornecer uma fundação única para todos os sistemas da plataforma SaaS, garantindo:

- consistência entre aplicações;
- isolamento seguro entre empresas (multi-tenant);
- auditoria completa;
- rastreabilidade;
- escalabilidade;
- facilidade de manutenção;
- reutilização de modelos e componentes.

Novos módulos deverão reutilizar essa estrutura sempre que possível, acrescentando apenas as tabelas específicas do domínio de negócio.

# 37. Convenções de Interface (UX/UI)

## 37.1 Objetivo

Padronizar completamente a interface do usuário, garantindo consistência visual, facilidade de uso, acessibilidade e reutilização dos componentes em todos os módulos do sistema.

Toda nova funcionalidade deverá seguir rigorosamente estas diretrizes.

---

# 37.2 Framework Visual

Frontend oficial

- Bootstrap 5
- AdminLTE 4
- Font Awesome 6
- HTMX
- Alpine.js

É proibido utilizar outro framework CSS sem aprovação do projeto.

---

# 37.3 Layout

A estrutura será composta por:

```
Navbar

Sidebar

Breadcrumb

Área principal

Footer

Painel lateral (opcional)
```

---

# 37.4 Sidebar

A organização do menu será sempre:

```
Dashboard

Cadastros

Operações

Relatórios

Financeiro

Configurações

Administração
```

Menus deverão ser gerados automaticamente conforme permissões.

---

# 37.5 Dashboard

Cada módulo poderá fornecer widgets.

Tipos:

- KPI
- Cards
- Gráficos
- Calendário
- Timeline
- Alertas
- Tabelas
- Últimas atividades

---

# 37.6 Breadcrumb

Toda página deverá possuir breadcrumb.

Exemplo

```
Dashboard

↓

Pacientes

↓

Editar
```

---

# 37.7 Formulários

Todos os formulários deverão possuir:

- labels
- placeholders
- ajuda contextual
- mensagens de erro
- validação em tempo real
- confirmação de exclusão
- loading durante envio

---

# 37.8 Componentes

Criar biblioteca única.

Exemplos

```
Card

Accordion

Timeline

Alert

Badge

Progress

Avatar

Button

Dropdown

Table

Modal

Wizard

Tabs

Carousel

Kanban

Calendar

Chart
```

---

# 37.9 Botões

Padrão

```
Novo

Salvar

Cancelar

Editar

Excluir

Duplicar

Exportar

Importar

Voltar
```

Sempre manter mesma posição.

---

# 37.10 Cores

Bootstrap padrão.

Sem utilização de cores aleatórias.

Estados:

Sucesso

```
success
```

Erro

```
danger
```

Aviso

```
warning
```

Informação

```
info
```

---

# 37.11 Ícones

Somente Font Awesome.

Exemplo

```
fa-user

fa-building

fa-hospital

fa-chart-line

fa-cog
```

---

# 37.12 Tabelas

Toda tabela deverá possuir:

- pesquisa
- filtros
- ordenação
- paginação
- exportação
- ações rápidas
- seleção múltipla

---

# 37.13 Modais

Utilizar modais para:

- confirmação
- visualização rápida
- formulários simples

Não utilizar para processos longos.

---

# 37.14 Notificações

Sistema único.

Tipos

- sucesso
- erro
- aviso
- informação

Sempre no canto superior direito.

---

# 37.15 Responsividade

Compatível com

- Desktop
- Notebook
- Tablet
- Smartphone

---

# 37.16 Dark Mode

Suporte obrigatório.

---

# 37.17 Internacionalização

Todo texto deverá utilizar arquivos de tradução.

Nunca escrever textos diretamente no HTML.

---

# 37.18 UX

Prioridades

- poucos cliques
- consistência
- rapidez
- simplicidade
- acessibilidade

---

# 37.19 Acessibilidade

Compatível com WCAG.

Utilizar:

- aria-label
- contraste adequado
- navegação por teclado

---

# 37.20 Objetivo

Toda aplicação deverá parecer um único produto, independentemente do número de módulos instalados.

---

# 38. Arquitetura dos Módulos

## 38.1 Objetivo

Toda funcionalidade do sistema será desenvolvida como um módulo independente, permitindo instalação, atualização e reutilização.

---

# 38.2 Estrutura

Cada módulo possuirá

```
modulo/

models.py

schemas.py

repository.py

service.py

routes.py

permissions.py

validators.py

constants.py

hooks.py

templates/

static/

README.md

manifest.json
```

---

# 38.3 Manifesto

Todo módulo possuirá

```
manifest.json
```

Exemplo

```json
{
    "name": "Pacientes",
    "version": "1.0.0",
    "author": "Framework SaaS",
    "dependencies": [],
    "permissions": [],
    "menu": [],
    "routes": []
}
```

---

# 38.4 Registro

Ao iniciar a aplicação, todos os módulos serão carregados automaticamente.

Fluxo

```
Manifest

↓

Registro

↓

Rotas

↓

Menu

↓

Permissões

↓

Dashboard
```

---

# 38.5 Dependências

Um módulo poderá depender de outro.

Exemplo

Financeiro

↓

Empresas

↓

Usuários

---

# 38.6 Instalação

Instalar automaticamente:

- tabelas
- permissões
- menus
- configurações
- widgets
- APIs

---

# 38.7 Atualização

Cada módulo possuirá controle de versão.

Exemplo

```
1.0.0

1.1.0

2.0.0
```

Migrações executadas automaticamente via Alembic.

---

# 38.8 Remoção

Ao remover um módulo:

- remover menus
- remover permissões
- remover widgets
- manter dados (por padrão)

---

# 38.9 Permissões

Cada módulo define suas próprias permissões.

Exemplo

```
paciente.listar

paciente.editar

paciente.excluir
```

---

# 38.10 Dashboard

Cada módulo poderá registrar widgets.

Exemplo

```
Pacientes internados

Financeiro do mês

Atendimentos

Estoque crítico
```

---

# 38.11 APIs

Cada módulo poderá disponibilizar:

- REST
- Webhooks
- Eventos

---

# 38.12 Hooks

Eventos suportados

```
before_create

after_create

before_update

after_update

before_delete

after_delete
```

Também poderão existir eventos de autenticação, importação, exportação e sincronização.

---

# 38.13 Menu

Cada módulo registra automaticamente seu menu.

Exemplo

```
Cadastros

↓

Pacientes
```

---

# 38.14 Widgets

Cada módulo poderá adicionar:

- Cards
- Gráficos
- KPIs
- Alertas

---

# 38.15 Configurações

Cada módulo poderá possuir configurações próprias.

Exemplo

```
Tempo máximo

Cor padrão

Logo

SMTP específico
```

---

# 38.16 Exportação

Todo módulo deverá suportar exportação quando aplicável.

Formatos

- PDF
- Excel
- CSV

---

# 38.17 Importação

Suporte para:

- CSV
- Excel

Com validação e relatório de inconsistências.

---

# 38.18 Testes

Todo módulo deverá possuir:

- testes unitários
- testes de integração
- cobertura mínima definida pelo projeto

---

# 38.19 Documentação

Cada módulo deverá conter um README com:

- objetivo
- dependências
- permissões
- rotas
- modelos
- configurações
- exemplos de uso

---

# 38.20 Objetivo Final

Os módulos deverão funcionar como plugins da plataforma, podendo ser desenvolvidos, instalados, atualizados ou removidos de forma independente, sem alterar a arquitetura principal do sistema.

Essa abordagem transforma a plataforma em um verdadeiro Framework SaaS modular, permitindo a criação de novos produtos reutilizando a mesma infraestrutura, segurança, interface e componentes compartilhados.

# 39. Núcleo do Framework (Core)

## 39.1 Objetivo

O **Core** é o coração da plataforma SaaS.

Nenhum módulo deverá implementar funcionalidades já existentes no Core.

Todo módulo deverá consumir os serviços disponibilizados pelo Framework.

O objetivo é:

- evitar duplicação de código;
- manter padronização;
- facilitar manutenção;
- permitir evolução da plataforma.

---

# 39.2 Estrutura do Core

```
core/

authentication/

authorization/

audit/

cache/

config/

database/

events/

exceptions/

files/

helpers/

mail/

middleware/

notifications/

reports/

scheduler/

security/

storage/

tenants/

utils/

validators/

logging/
```

---

# 39.3 Serviços do Core

O Framework disponibilizará os seguintes serviços.

```
AuthService

UserService

PermissionService

RoleService

TenantService

AuditService

LogService

NotificationService

MailService

StorageService

UploadService

CacheService

ConfigService

DashboardService

ModuleService

ReportService

ExportService

ImportService

SearchService

SchedulerService

WebhookService

ApiKeyService

HealthService
```

Todos reutilizáveis.

---

# 39.4 AuthService

Responsável por

- Login
- Logout
- Sessões
- MFA
- JWT
- Cookies
- Recuperação de senha
- Renovação de sessão

Nenhum módulo poderá implementar autenticação própria.

---

# 39.5 PermissionService

Responsável por

- RBAC
- ABAC
- Verificação de permissões
- Cache de permissões
- Menu dinâmico

Exemplo

```
PermissionService.has(
    usuario,
    "paciente.editar"
)
```

---

# 39.6 TenantService

Responsável por

- empresa atual
- isolamento de dados
- troca de empresa
- contexto do tenant

Todo Repository deverá utilizar automaticamente o tenant atual.

---

# 39.7 AuditService

Registrar automaticamente

- INSERT
- UPDATE
- DELETE
- LOGIN
- LOGOUT
- EXPORTAÇÃO
- IMPORTAÇÃO

Sem necessidade de implementação pelo módulo.

---

# 39.8 NotificationService

Suportar

- Sistema
- Email
- SMS
- WhatsApp (futuro)
- Push

Exemplo

```
NotificationService.send()
```

---

# 39.9 MailService

Responsável por

- SMTP
- Templates HTML
- Filas
- Anexos

---

# 39.10 StorageService

Abstração de armazenamento.

Suporte para

- Disco local
- S3
- MinIO
- Azure Blob
- Google Cloud Storage

A aplicação nunca acessará diretamente o sistema de arquivos.

---

# 39.11 CacheService

Implementação padrão

Redis

Operações

```
set()

get()

delete()

remember()

invalidate()
```

---

# 39.12 ConfigService

Gerenciar

- configurações globais
- configurações da empresa
- configurações do módulo

Exemplo

```
ConfigService.get(
    "smtp.host"
)
```

---

# 39.13 DashboardService

Registrar

- KPIs
- Widgets
- Cards
- Gráficos

Cada módulo poderá adicionar widgets.

---

# 39.14 ModuleService

Responsável por

- carregar módulos
- registrar módulos
- atualizar módulos
- remover módulos
- verificar dependências

---

# 39.15 ReportService

Geração de

- PDF
- Excel
- CSV

Utilizar templates reutilizáveis.

---

# 39.16 ImportService

Importações

- CSV
- Excel
- JSON

Com relatório de erros.

---

# 39.17 ExportService

Exportações

- PDF
- Excel
- CSV

Com paginação automática.

---

# 39.18 SearchService

Pesquisa unificada.

Suportar

- filtros
- paginação
- ordenação
- pesquisa textual

Todos os módulos utilizarão este serviço.

---

# 39.19 SchedulerService

Gerenciar tarefas agendadas.

Exemplos

- limpeza
- backups
- sincronizações
- notificações
- importações

---

# 39.20 ApiKeyService

Gerenciar

- chaves de API
- escopos
- validade
- revogação
- auditoria

---

# 39.21 HealthService

Endpoints

```
/health

/ready

/live
```

Verificar

- banco
- redis
- disco
- filas
- armazenamento

---

# 39.22 WebhookService

Registrar

- eventos
- destinos
- tentativas
- falhas
- logs

Suportar reenvio automático.

---

# 39.23 EventBus

Comunicação entre módulos.

Eventos

```
UserCreated

UserDeleted

CompanyCreated

PatientCreated

InvoicePaid

NotificationSent
```

Arquitetura baseada em eventos para desacoplamento entre módulos.

---

# 39.24 Helpers

Bibliotecas oficiais

```
DateHelper

StringHelper

MoneyHelper

CpfHelper

CnpjHelper

PhoneHelper

MaskHelper

ImageHelper

ExcelHelper

PdfHelper

JsonHelper

CryptoHelper
```

---

# 39.25 Validators

Biblioteca única

```
CPF

CNPJ

CEP

Telefone

Email

Senha

Arquivo

Imagem
```

---

# 39.26 Exceptions

Exceções oficiais

```
BusinessException

ValidationException

PermissionException

NotFoundException

AuthenticationException

ConflictException

ExternalServiceException
```

---

# 39.27 Middleware

Middleware oficiais

- autenticação
- tenant
- auditoria
- logs
- idioma
- timezone
- rate limit
- compressão
- segurança

---

# 39.28 Logging

Centralizado.

Níveis

```
DEBUG

INFO

WARNING

ERROR

CRITICAL
```

Integração futura com ELK, Loki ou Grafana.

---

# 39.29 Segurança

Serviços

- Hash
- Criptografia
- Tokens
- Assinaturas
- CSRF
- CSP
- XSS
- SQL Injection

---

# 39.30 Objetivo Final

O Core deverá funcionar como uma camada de infraestrutura compartilhada, oferecendo todos os serviços transversais necessários para qualquer módulo da plataforma.

Os módulos devem conter apenas regras de negócio específicas do domínio, delegando ao Core toda responsabilidade por autenticação, autorização, auditoria, notificações, armazenamento, cache, relatórios, importação, exportação, eventos, integrações e demais funcionalidades comuns.

Essa separação garante baixo acoplamento, alta reutilização, facilidade de testes e evolução contínua da plataforma sem impacto direto sobre os módulos existentes.
