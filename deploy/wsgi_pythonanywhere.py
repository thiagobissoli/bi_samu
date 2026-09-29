"""Ponte WSGI para o PythonAnywhere (plano Beginner).

A conta gratuita não tem a API de sites ASGI — só aplicações WSGI. Como o
FastAPI é ASGI, o `a2wsgi` faz a adaptação. Requisição/resposta comuns
funcionam normalmente; o que não funciona é streaming e WebSocket, que este
sistema não usa.

Aponte a aplicação web do PythonAnywhere para este arquivo.
"""

import os
import sys
from pathlib import Path

PROJETO = Path(__file__).resolve().parent.parent

# O pacote 'app' precisa resolver para ESTE projeto: outro projeto no mesmo
# Python que exponha um 'app' seria carregado no lugar, com outro banco.
sys.path.insert(0, str(PROJETO))

# Pacotes instalados com 'pip install --user' (não há venv no plano gratuito
# quando se reaproveita o site-packages do sistema).
LOCAL = Path.home() / ".local" / "lib"
for versao in sorted(LOCAL.glob("python3.*/site-packages"), reverse=True):
    sys.path.insert(0, str(versao))

os.chdir(PROJETO)

from a2wsgi import ASGIMiddleware  # noqa: E402

from app.main import app as fastapi_app  # noqa: E402

application = ASGIMiddleware(fastapi_app)
