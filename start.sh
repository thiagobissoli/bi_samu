#!/usr/bin/env bash
# Inicia o servidor da aplicação em segundo plano.
# Uso: ./start.sh [porta]   (padrão: 8000)
set -euo pipefail

cd "$(dirname "$0")"

PORT="${1:-8000}"
PID_FILE=".uvicorn.pid"
LOG_FILE="uvicorn.log"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Servidor já está rodando (PID $(cat "$PID_FILE")). Use ./stop.sh antes."
    exit 1
fi

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "A porta $PORT já está em uso por outro processo:"
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN | tail -n +2
    echo "Encerre esse processo (ex.: Ctrl+C no terminal do uvicorn) ou use outra porta: ./start.sh 8001"
    exit 1
fi

# Usa o venv se existir; senão, o python3 do sistema.
if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="python3"
fi

# Garante que "app" resolva para ESTE projeto. Sem isso, outro projeto
# instalado no mesmo Python que também exponha um pacote "app" pode ser
# carregado no lugar — com outro banco e sem as credenciais do vSky.
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

nohup "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" \
    >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

sleep 2
if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Servidor iniciado (PID $(cat "$PID_FILE"))."
    echo "  Aplicação: http://127.0.0.1:$PORT"
    echo "  Swagger:   http://127.0.0.1:$PORT/api/docs"
    echo "  Log:       tail -f $LOG_FILE"
else
    echo "Falha ao iniciar. Últimas linhas do log:"
    tail -20 "$LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi
