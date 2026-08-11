#!/usr/bin/env bash
# Para o servidor iniciado pelo start.sh.
set -euo pipefail

cd "$(dirname "$0")"

PID_FILE=".uvicorn.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "Nenhum PID registrado ($PID_FILE não existe). Servidor parado?"
    exit 0
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    # Aguarda encerrar; força com SIGKILL se demorar mais de 10s.
    for _ in $(seq 1 10); do
        kill -0 "$PID" 2>/dev/null || break
        sleep 1
    done
    if kill -0 "$PID" 2>/dev/null; then
        echo "Processo não encerrou; enviando SIGKILL."
        kill -9 "$PID" 2>/dev/null || true
    fi
    echo "Servidor parado (PID $PID)."
else
    echo "Processo $PID não está mais rodando."
fi

rm -f "$PID_FILE"
