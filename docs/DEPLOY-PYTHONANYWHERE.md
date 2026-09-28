# Deploy no PythonAnywhere

Conta: **samues** — site final em `https://samues.pythonanywhere.com`

---

## Antes de começar: o plano gratuito não atende

O plano **Beginner (gratuito)** não roda este projeto. Três impedimentos, não um:

| Limite do plano gratuito | O que o projeto precisa |
|---|---|
| **Sem MySQL** | O projeto usa MySQL (`mysql+pymysql`) |
| **512 MB de disco** | ~400 MB de banco + ~1,1 GB de uploads + venv |
| **Internet só por whitelist** | `download_vsky` e `core/ia.py` chamam serviços externos |

O plano **Developer (US$ 10/mês)** resolve os três: MySQL incluído, 5 GB de disco
e internet liberada. Mesmo nele o espaço fica apertado — o venv com pandas,
matplotlib e reportlab passa de 1 GB. Confira a folga em **Files → quota** antes
de subir os uploads.

---

## 1. Criar o banco MySQL

No painel, aba **Databases**:

1. Defina a senha do MySQL (a primeira vez pede)
2. Em *Create a database*, crie `samu` — o nome final será `samues$samu`

Anote o host: `samues.mysql.pythonanywhere-services.com`

---

## 2. Clonar o repositório

O repositório é privado, então precisa de um token. Crie um em
**github.com → Settings → Developer settings → Personal access tokens**
(escopo `repo`), e no console Bash do PythonAnywhere:

```bash
cd ~
git clone https://SEU_TOKEN@github.com/thiagobissoli/qualidade_samu.git
cd qualidade_samu
```

---

## 3. Virtualenv e dependências

```bash
mkvirtualenv samu --python=python3.13
pip install -e .
```

O projeto exige Python 3.11+; o PythonAnywhere oferece 3.12 e 3.13. Se algum
pacote não tiver wheel para 3.13, troque por `--python=python3.12`.

O `psycopg` está nas dependências mas não é usado (o banco é MySQL). Se faltar
espaço, instale sem ele editando o `pyproject.toml`.

---

## 4. Configurar o `.env`

```bash
cd ~/qualidade_samu
cp .env.example .env
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))"
```

Edite o `.env` com a saída acima e a linha do banco:

```
DEBUG=false
SECRET_KEY=<a chave gerada acima>
DATABASE_URL=mysql+pymysql://samues:SUA_SENHA_MYSQL@samues.mysql.pythonanywhere-services.com/samues$samu?charset=utf8mb4
TIMEZONE=America/Sao_Paulo
UPLOAD_DIR=/home/samues/qualidade_samu/uploads
```

> A `SECRET_KEY` precisa ter 32+ bytes: ela assina os JWT da API e criptografa
> as configurações sensíveis. Trocá-la depois invalida os valores já
> criptografados no banco.

---

## 5. Criar as tabelas e o administrador

```bash
cd ~/qualidade_samu
alembic upgrade head
python manage.py criar-usuario --nome "Administrador" --email seu@email.com --perfil Administrador
```

Se `manage.py` não existir neste projeto, o primeiro acesso cria o admin padrão
pelos seeds — troque a senha logo depois.

---

## 6. Publicar o site (ASGI)

O PythonAnywhere serve WSGI por padrão; FastAPI é ASGI e usa o suporte novo,
ainda em beta, pela linha de comando:

```bash
pip install --upgrade pythonanywhere
```

```bash
pa website create --domain samues.pythonanywhere.com --command '/home/samues/.virtualenvs/samu/bin/uvicorn --app-dir /home/samues/qualidade_samu --uds ${DOMAIN_SOCKET} app.main:app'
```

Depois de cada `git pull`:

```bash
pa website reload --domain samues.pythonanywhere.com
```

Outros comandos úteis:

```bash
pa website get --domain samues.pythonanywhere.com
pa website delete --domain samues.pythonanywhere.com
```

### Arquivos estáticos

O suporte ASGI **não tem mapeamento de estáticos** no painel. Não é problema
aqui: o próprio FastAPI monta `/static` (`app.mount` no `main.py`), então CSS,
JS e imagens são servidos pela aplicação. É um pouco mais lento que o mapeamento
nativo, mas funciona sem configuração extra.

---

## 7. Logs

```
/var/log/samues.pythonanywhere.com.error.log     # erros e startup do uvicorn
/var/log/samues.pythonanywhere.com.server.log    # requisições recebidas
/var/log/samues.pythonanywhere.com.access.log    # log de acesso
```

Acompanhar em tempo real:

```bash
tail -f /var/log/samues.pythonanywhere.com.error.log
```

---

## 8. Uploads

O `.gitignore` exclui `uploads/` — os arquivos não vêm pelo git. Para levá-los,
compacte localmente e envie pela aba **Files** (ou por `scp`, nos planos pagos):

```bash
# na sua máquina
tar -czf uploads.tar.gz uploads/
```

```bash
# no PythonAnywhere, após enviar o arquivo
cd ~/qualidade_samu && tar -xzf ~/uploads.tar.gz
```

São ~1,1 GB. Se a cota apertar, considere subir só o necessário e manter o
histórico fora da aplicação.

---

## 9. O que muda de comportamento neste ambiente

**Agendadores.** O projeto usa APScheduler em processo
(`painel_gestao`, `download_vsky`, `backup`). No PythonAnywhere os workers web
são reciclados, então tarefas em processo não são confiáveis. Use a aba
**Tasks** do painel, que roda comandos em horário fixo:

```bash
cd ~/qualidade_samu && /home/samues/.virtualenvs/samu/bin/python -m app.modules.painel_gestao.scheduler
```

**Cache.** Não há Redis no PythonAnywhere. O `CacheService` detecta isso e cai
para memória automaticamente — funciona, mas o cache não é compartilhado entre
processos. Nada a configurar.

**Celery.** Sem broker, não há worker. O `enfileirar()` executa a tarefa na hora,
de forma síncrona. Para trabalho pesado, prefira a aba **Tasks**.

**E-mail.** SMTP externo exige plano pago (no gratuito a saída é bloqueada).
Configure `smtp_host`, `smtp_port`, `smtp_user` e `smtp_pass` em
**Configurações** dentro do sistema — a senha é criptografada no banco.

---

## 10. Atualizações seguintes

```bash
cd ~/qualidade_samu && git pull && pa website reload --domain samues.pythonanywhere.com
```

Se a atualização mexeu no banco:

```bash
cd ~/qualidade_samu && alembic upgrade head
```
