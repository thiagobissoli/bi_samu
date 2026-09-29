"""Adaptador ASGI -> WSGI mínimo.

O a2wsgi mantém um event loop num thread de fundo e, neste uWSGI, a
requisição nunca retorna. Aqui cada requisição roda num loop novo, no próprio
thread do worker — comprovadamente funcional no ambiente (threads e
asyncio.run foram testados antes de escrever isto).

A resposta é montada inteira em memória: serve para requisição/resposta
comuns, não para streaming nem WebSocket, que esta aplicação não usa.
"""

import asyncio
from http import HTTPStatus
from urllib.parse import unquote


def cabecalhos_do_environ(environ):
    saida = []
    for chave, valor in environ.items():
        if chave.startswith("HTTP_"):
            nome = chave[5:].replace("_", "-").lower()
            saida.append((nome.encode("latin-1"), str(valor).encode("latin-1")))
    for chave, nome in (("CONTENT_TYPE", b"content-type"),
                        ("CONTENT_LENGTH", b"content-length")):
        if environ.get(chave):
            saida.append((nome, str(environ[chave]).encode("latin-1")))
    return saida


def ASGIToWSGI(app):
    def application(environ, start_response):
        tamanho = int(environ.get("CONTENT_LENGTH") or 0)
        corpo_req = environ["wsgi.input"].read(tamanho) if tamanho else b""
        caminho = environ.get("PATH_INFO", "") or "/"

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.1"},
            "http_version": "1.1",
            "method": environ["REQUEST_METHOD"].upper(),
            "scheme": environ.get("wsgi.url_scheme", "http"),
            "path": unquote(caminho),
            "raw_path": caminho.encode("latin-1"),
            "query_string": environ.get("QUERY_STRING", "").encode("latin-1"),
            "root_path": environ.get("SCRIPT_NAME", ""),
            "headers": cabecalhos_do_environ(environ),
            "client": (environ.get("REMOTE_ADDR", ""), 0),
            "server": (environ.get("SERVER_NAME", ""),
                       int(environ.get("SERVER_PORT") or 0)),
        }

        resposta = {"status": 500, "headers": [], "corpo": bytearray()}

        async def receive():
            return {"type": "http.request", "body": corpo_req, "more_body": False}

        async def send(mensagem):
            if mensagem["type"] == "http.response.start":
                resposta["status"] = mensagem["status"]
                resposta["headers"] = mensagem.get("headers", [])
            elif mensagem["type"] == "http.response.body":
                resposta["corpo"].extend(mensagem.get("body", b""))

        asyncio.run(app(scope, receive, send))

        try:
            razao = HTTPStatus(resposta["status"]).phrase
        except ValueError:
            razao = ""
        start_response(
            f"{resposta['status']} {razao}".strip(),
            [(c.decode("latin-1"), v.decode("latin-1")) for c, v in resposta["headers"]],
        )
        return [bytes(resposta["corpo"])]

    return application
