# Samu

Aplicação SaaS gerada pelo **Framework SaaS**.
A especificação completa da arquitetura está em [docs/ESPECIFICACAO-BASE-SAAS.md](docs/ESPECIFICACAO-BASE-SAAS.md).

## Desenvolvimento

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
python -m uvicorn app.main:app --reload
```

Acesse `http://localhost:8000` (dashboard) e `http://localhost:8000/api/docs` (API).
Em produção, use `./start.sh` e `./stop.sh`.

> **Sempre no venv, e sempre `python -m uvicorn`** (não o comando
> `uvicorn` solto). O pacote desta aplicação chama-se `app` — um nome
> genérico: se outro projeto instalado no mesmo Python também expuser um
> pacote `app`, o comando `uvicorn` (que não coloca o diretório atual no
> `sys.path`) pode carregar **a outra aplicação**, com outro banco e sem
> as configurações gravadas — o sistema sobe "vazio", como se tivesse
> perdido as credenciais. As duas primeiras linhas do log mostram qual
> código e qual banco estão em uso; confira-as em caso de dúvida.

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
