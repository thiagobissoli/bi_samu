# Módulo Reuniao Indicadores

Gerado pelo Framework SaaS (`saas create-module`).

## Estrutura (§35.2)

| Arquivo | Responsabilidade |
|---------|------------------|
| models.py | Modelos SQLAlchemy |
| schemas.py | DTOs/Pydantic |
| repository.py | Acesso ao banco |
| service.py | Regras de negócio |
| routes.py | Endpoints |
| permissions.py | Permissões do módulo |
| validators.py | Validações |
| constants.py | Constantes |
| utils.py | Funções auxiliares |
| hooks.py | Eventos (§38.12) |
| manifest.json | Manifesto do módulo (§38.3) |

## Rotas

- `GET /reuniao_indicadores` — listagem (HTML)
- `GET /reuniao_indicadores/api` — listagem (JSON, formato padrão §17)
