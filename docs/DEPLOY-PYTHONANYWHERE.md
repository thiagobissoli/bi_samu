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

## Atalho: script de instalação

Os passos 2 a 6 estão automatizados. No console Bash do PythonAnywhere:

```bash
git clone https://github.com/thiagobissoli/qualidade_samu.git
bash ~/qualidade_samu/deploy/pythonanywhere_setup.sh
```

O script cria o virtualenv, instala as dependências, gera uma SECRET_KEY nova,
pergunta a senha do MySQL, aplica as migrações e publica o site. É idempotente.
As seções abaixo detalham cada etapa, caso prefira fazer à mão ou precise
depurar algo.

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

O `manage.py` valida o e-mail e a força da senha antes de gravar. Se preferir,
o primeiro acesso também cria o admin padrão pelos seeds — nesse caso troque a
senha logo depois.

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

## 8. Dados: banco e uploads

O código vai por git. Banco e uploads não — e medindo o que existe hoje, a
transferência é bem menor do que os 1,5 GB brutos sugerem:

| Item | Bruto | A transferir |
|---|---|---|
| Banco MySQL | 397 MB | **81 MB** (dump comprimido) |
| PDFs de prontuário + logo | 8,8 MB | **8,6 MB** |
| XLS das importações | 919 MB | **opcional** |
| Backups gerados pelo sistema | 205 MB | não vai |

Gere os pacotes na sua máquina:

```bash
./deploy/preparar_transferencia.sh
```

Envie os dois arquivos pela aba **Files** e, no console do PythonAnywhere:

```bash
cd ~/qualidade_samu
gunzip -c ~/banco.sql.gz | mysql -u samues -p -h samues.mysql.pythonanywhere-services.com 'samues$samu'
tar -xzf ~/uploads-essenciais.tar.gz
```

Importar o dump dispensa o `alembic upgrade head` — o schema vem junto.

### Por que os 919 MB de XLS são opcionais

São os arquivos de origem das importações do vSky. Os dados já estão no banco
(`vsky_registros_analiticos`, mais de 500 mil linhas). Sem eles, o botão
"baixar arquivo original" de uma importação antiga apenas volta para a lista,
sem erro — o código já trata o arquivo ausente. Se quiser levá-los assim mesmo:

```bash
./deploy/preparar_transferencia.sh --historico
```

Os PDFs de prontuário até se recuperam sozinhos (o módulo rebaixa do vSky
quando o arquivo falta), mas levá-los custa 8,6 MB e evita depender do vSky
no primeiro acesso.

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


---

## Carregar os dados (decisão do controlador)

O deploy no plano Beginner sobe com o banco **vazio**. Levar os dados de
produção é uma decisão separada, com implicações de LGPD: este banco contém
prontuários, mais de 500 mil registros de atendimento e investigações
nominais — dados de saúde identificáveis.

Pontos a pesar antes:

- o site fica numa **URL pública**, protegido apenas pelo login da aplicação;
- o plano Beginner dá **512 MB no total**, e o banco em SQLite deve ficar
  entre 350 e 450 MB — sem folga para crescer;
- a infraestrutura é compartilhada e o plano não oferece garantias
  contratuais de tratamento de dados.

Se ainda assim for o caminho, a conversão é feita na sua máquina:

```bash
.venv/bin/python deploy/converter_para_sqlite.py --sem-pessoais
```

`--sem-pessoais` cria as tabelas de prontuário, registros analíticos e
investigações **vazias**, gerando uma base utilizável para homologação sem
transferir conteúdo identificável. Sem a opção, tudo é copiado. Há ainda
`--desde AAAA-MM-DD` para levar só um período recente.

Depois, envie o arquivo pela aba Files e aponte o `.env` de lá:

```
DATABASE_URL=sqlite:////home/samues/qualidade_samu/dados.sqlite3
```

### Proteção adicional recomendada

O PythonAnywhere permite exigir usuário e senha HTTP **antes** de a aplicação
carregar, na aba Web → "Password protection". Com dados reais no ar, é a
diferença entre uma tela de login exposta à internet e um serviço fechado.
