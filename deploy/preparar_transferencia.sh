#!/usr/bin/env bash
# Prepara os pacotes para levar ao PythonAnywhere. Rode NA SUA MÁQUINA.
#
#     ./deploy/preparar_transferencia.sh            # essencial (~90 MB)
#     ./deploy/preparar_transferencia.sh --historico # inclui os XLS (~250 MB a mais)
#
# O código vai por git; aqui só o que o git não carrega: banco e uploads.
set -euo pipefail

cd "$(dirname "$0")/.."
SAIDA="${SAIDA:-./transferencia}"
mkdir -p "$SAIDA"

URL="$(grep '^DATABASE_URL=' .env | cut -d= -f2-)"
USUARIO="$(sed -E 's|.*://([^:]+):.*|\1|' <<< "$URL")"
SENHA="$(sed -E 's|.*://[^:]+:([^@]*)@.*|\1|' <<< "$URL")"
BANCO="$(sed -E 's|.*/([^/?]+)(\?.*)?$|\1|' <<< "$URL")"

echo "== Banco ($BANCO) =="
mysqldump --host=127.0.0.1 --user="$USUARIO" --password="$SENHA" \
    --single-transaction --quick --no-tablespaces "$BANCO" 2>/dev/null \
    | gzip -6 > "$SAIDA/banco.sql.gz"
echo "   $(du -h "$SAIDA/banco.sql.gz" | cut -f1)"

# Só o que a aplicação precisa ter em disco:
#   sistema/     -> logo e afins, referenciados na tabela arquivos
#   prontuarios/ -> PDFs do visualizador (o módulo rebaixa do vSky se faltar,
#                   mas levar evita depender do vSky no primeiro acesso)
echo "== Uploads essenciais =="
tar -czf "$SAIDA/uploads-essenciais.tar.gz" \
    $(find uploads -type d \( -name sistema -o -name prontuarios \) 2>/dev/null) 2>/dev/null || true
echo "   $(du -h "$SAIDA/uploads-essenciais.tar.gz" | cut -f1)"

if [ "${1:-}" = "--historico" ]; then
    # XLS de origem das importações. Os dados já estão no banco; sem eles,
    # só o botão "baixar arquivo original" volta para a lista, sem erro.
    echo "== Histórico (XLS das importações) =="
    tar -czf "$SAIDA/uploads-historico.tar.gz" \
        --exclude="backups" --exclude="prontuarios" --exclude="sistema" \
        uploads 2>/dev/null || true
    echo "   $(du -h "$SAIDA/uploads-historico.tar.gz" | cut -f1)"
fi

echo
echo "Pacotes em $SAIDA:"
du -h "$SAIDA"/* | sed 's/^/  /'
cat <<'FIM'

Envie pela aba Files do PythonAnywhere (ou 'pa' CLI) e, no console de lá:

  cd ~/qualidade_samu
  gunzip -c ~/banco.sql.gz | mysql -u SEU_USUARIO -p \
      -h SEU_USUARIO.mysql.pythonanywhere-services.com 'SEU_USUARIO$samu'
  tar -xzf ~/uploads-essenciais.tar.gz

Importar o dump dispensa rodar 'alembic upgrade head': o schema vem junto.
FIM
