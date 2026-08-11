# Samu

Aplicação SaaS gerada pelo **Framework SaaS**.
A especificação completa da arquitetura está em [docs/ESPECIFICACAO-BASE-SAAS.md](docs/ESPECIFICACAO-BASE-SAAS.md).

## Desenvolvimento

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn app.main:app --reload
```

Acesse `http://localhost:8000` (dashboard) e `http://localhost:8000/api/docs` (API).

## Novos módulos

```bash
saas create-module pacientes
```

O módulo é criado em `app/modules/pacientes/` com a estrutura da §35.2 e registrado
automaticamente (rotas + menu) ao reiniciar a aplicação.

## Docker

```bash
docker compose up --build
```

## Testes

```bash
pytest
```
