#!/usr/bin/env bash
# Instalação no PythonAnywhere — plano Beginner (gratuito).
# Rode no console Bash de lá:
#
#     bash ~/qualidade_samu/deploy/pythonanywhere_beginner.sh
#
# Diferenças em relação ao plano pago:
#   - banco SQLite (o gratuito não tem MySQL)
#   - sem virtualenv: reaproveita o site-packages do sistema, que já traz
#     fastapi, pydantic, sqlalchemy, alembic, pandas, numpy, matplotlib,
#     reportlab, openpyxl, cryptography, argon2, httpx, pypdf e xlrd.
#     Só 4 pacotes pequenos são instalados, o que cabe nos 100s de CPU/dia.
#   - aplicação WSGI com a ponte a2wsgi (a API de sites ASGI não existe aqui)
set -euo pipefail

USUARIO="${USER:-samues}"
PROJETO="$HOME/qualidade_samu"
cd "$PROJETO"

echo "== 1/4  Pacotes que faltam =="
# --user porque não há virtualenv; são 4 pacotes Python puro, rápidos.
# Não é preciso instalar nada: deploy/deps.zip traz os pacotes que faltam
# (PyJWT, pydantic-settings, APScheduler, python-multipart), importados
# por zipimport. Assim a instalação não gasta a cota de CPU com pip.
true
echo "  dependências vêm de deploy/deps.zip (zipimport)"

echo "== 2/4  Configuração =="
if [ -f .env ]; then
    echo "  .env já existe — preservado"
else
    CHAVE="$(python3.13 -c 'import secrets; print(secrets.token_urlsafe(48))')"
    cat > .env <<ENV
APP_NAME="Qualidade SAMU"
DEBUG=false
SECRET_KEY=$CHAVE
DATABASE_URL=sqlite:///$PROJETO/dados.sqlite3
UPLOAD_DIR=$PROJETO/uploads
TIMEZONE=America/Sao_Paulo
DEFAULT_LANGUAGE=pt-BR
ENV
    chmod 600 .env
    echo "  .env criado com SECRET_KEY nova de 48 bytes"
fi
mkdir -p uploads

echo "== 3/4  Banco =="
# Cria o schema vazio. Nenhum dado de paciente é transferido por este script.
python3.13 -m alembic upgrade head
echo "  schema criado (banco vazio)"

echo "== 4/4  Aplicação web =="
echo "  Configure na aba Web do painel:"
echo "    Source code:  $PROJETO"
echo "    WSGI file:    $PROJETO/deploy/wsgi_pythonanywhere.py"
echo "    Python:       3.13"
echo "  (ou deixe que seja criada pela API e só recarregue)"

cat <<FIM

Falta criar o primeiro usuário:
  cd $PROJETO && python3.13 manage.py criar-usuario \\
    --nome "Seu Nome" --email voce@exemplo.com --perfil Administrador

Limites deste plano que afetam o sistema:
  - download_vsky e a IA não funcionam: a saída de internet é por whitelist
  - agendadores não rodam: tarefas agendadas exigem plano pago
  - 512 MB de disco no total
FIM
