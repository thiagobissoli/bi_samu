"""Ponte WSGI para o PythonAnywhere (plano Beginner).

A conta gratuita não tem a API de sites ASGI — só aplicações WSGI. Como o
FastAPI é ASGI, o adaptador em deploy/asgi_wsgi.py faz a ponte. O a2wsgi foi
tentado antes e trava neste uWSGI: ele mantém o event loop num thread de
fundo e a requisição nunca retorna.

As dependências que o PythonAnywhere não traz (PyJWT, pydantic-settings,
APScheduler, python-multipart e segno) vêm de `deploy/deps.zip`, importado
diretamente pelo zipimport: são Python puro, e assim a instalação não
depende de console nem gasta a cota de CPU com pip.

Aponte o campo "WSGI configuration file" da aba Web para este arquivo.
"""

import os
import sys
from pathlib import Path

PROJETO = Path(__file__).resolve().parent.parent

# O pacote 'app' precisa resolver para ESTE projeto: outro projeto no mesmo
# Python que exponha um 'app' seria carregado no lugar, com outro banco.
sys.path.insert(0, str(PROJETO))

# Dependências que faltam no sistema, importadas de dentro do zip.
DEPS = PROJETO / "deploy" / "deps.zip"
if DEPS.is_file():
    sys.path.insert(0, str(DEPS))

os.chdir(PROJETO)

from deploy.asgi_wsgi import ASGIToWSGI  # noqa: E402

from app.main import app as fastapi_app  # noqa: E402

application = ASGIToWSGI(fastapi_app)
