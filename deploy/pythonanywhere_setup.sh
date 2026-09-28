#!/usr/bin/env bash
# Instalação no PythonAnywhere — rode no console Bash de lá, não na sua máquina.
#
#     bash ~/qualidade_samu/deploy/pythonanywhere_setup.sh
#
# É idempotente: pode rodar de novo depois de corrigir algo.
set -euo pipefail

USUARIO="${USER:-samues}"
PROJETO="$HOME/qualidade_samu"
VENV="$HOME/.virtualenvs/samu"
DOMINIO="$USUARIO.pythonanywhere.com"

echo "== 1/6  Conferindo o ambiente =="
[ -d "$PROJETO" ] || { echo "ERRO: $PROJETO não existe. Clone o repositório primeiro:"; \
  echo "  git clone https://github.com/thiagobissoli/qualidade_samu.git"; exit 1; }
cd "$PROJETO"

if ! command -v mysql >/dev/null 2>&1; then
    echo "AVISO: cliente MySQL não encontrado — o plano gratuito não inclui MySQL."
    echo "       Este projeto precisa do plano Developer ou superior."
fi

echo "== 2/6  Virtualenv =="
if [ ! -x "$VENV/bin/python" ]; then
    python3.13 -m venv "$VENV" 2>/dev/null || python3.12 -m venv "$VENV"
    echo "  criado em $VENV"
else
    echo "  já existe, reaproveitando"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
echo "  instalando dependências (demora alguns minutos)..."
"$VENV/bin/pip" install --quiet -e .

echo "== 3/6  Arquivo .env =="
if [ -f .env ]; then
    echo "  já existe — preservado (apague para recriar)"
else
    CHAVE="$("$VENV/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))')"
    read -r -p "  Senha do MySQL do PythonAnywhere: " -s SENHA; echo
    cat > .env <<ENV
APP_NAME="Qualidade SAMU"
DEBUG=false
SECRET_KEY=$CHAVE
DATABASE_URL=mysql+pymysql://$USUARIO:$SENHA@$USUARIO.mysql.pythonanywhere-services.com/$USUARIO\$samu?charset=utf8mb4
REDIS_URL=redis://localhost:6379/0
UPLOAD_DIR=$PROJETO/uploads
TIMEZONE=America/Sao_Paulo
DEFAULT_LANGUAGE=pt-BR
ENV
    chmod 600 .env
    echo "  criado com SECRET_KEY nova de 48 bytes (diferente da sua máquina, como deve ser)"
fi

echo "== 4/6  Banco de dados =="
mkdir -p uploads
"$VENV/bin/alembic" upgrade head
echo "  schema no head das migrações"

echo "== 5/6  Publicando o site (ASGI) =="
"$VENV/bin/pip" install --quiet --upgrade pythonanywhere
if pa website get --domain "$DOMINIO" >/dev/null 2>&1; then
    pa website reload --domain "$DOMINIO"
    echo "  site já existia — recarregado"
else
    pa website create --domain "$DOMINIO" \
        --command "$VENV/bin/uvicorn --app-dir $PROJETO --uds \${DOMAIN_SOCKET} app.main:app"
    echo "  site criado"
fi

echo "== 6/6  Verificação =="
sleep 5
for rota in /live /health; do
    codigo="$(curl -s -o /dev/null -w '%{http_code}' "https://$DOMINIO$rota" || echo '---')"
    echo "  $rota -> $codigo"
done

cat <<FIM

Pronto. Aplicação em https://$DOMINIO

Próximos passos:
  1. Crie o usuário administrador:
       cd $PROJETO && $VENV/bin/python manage.py criar-usuario \\
         --nome "Seu Nome" --email voce@exemplo.com --perfil Administrador
  2. Os agendadores (APScheduler) não são confiáveis aqui: configure-os na
     aba Tasks. Veja docs/DEPLOY-PYTHONANYWHERE.md.
  3. Logs: tail -f /var/log/$DOMINIO.error.log

Atualizações futuras:
  cd $PROJETO && git pull && $VENV/bin/alembic upgrade head \\
    && pa website reload --domain $DOMINIO
FIM
