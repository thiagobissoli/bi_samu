"""Exceções da plataforma (§35.21, §39.26).

Erros de negócio não são erros de programação: quando um service recusa uma
operação, quem chamou precisa saber **por quê** e o usuário precisa ver uma
mensagem em português. Estas exceções carregam mensagem, código HTTP e campo,
e são convertidas automaticamente pelos handlers registrados no main.py —
JSON no formato padrão (§17) para a API, página HTML para as telas.
"""

from __future__ import annotations


class AppException(Exception):
    """Raiz de todas as exceções da aplicação."""

    status_code = 400
    mensagem_padrao = "Não foi possível concluir a operação."

    def __init__(self, mensagem: str | None = None, *, campo: str | None = None,
                 detalhes: dict | None = None):
        self.mensagem = mensagem or self.mensagem_padrao
        self.campo = campo
        self.detalhes = detalhes or {}
        super().__init__(self.mensagem)

    def como_dict(self) -> dict:
        """Formato padrão de resposta (§17)."""
        erro = {"mensagem": self.mensagem, "tipo": type(self).__name__}
        if self.campo:
            erro["campo"] = self.campo
        if self.detalhes:
            erro["detalhes"] = self.detalhes
        return erro


class BusinessException(AppException):
    """Regra de negócio violada (§35.16)."""

    status_code = 422
    mensagem_padrao = "Operação não permitida pelas regras de negócio."


class ValidationException(AppException):
    """Dado inválido — normalmente vindo dos validators (§39.25)."""

    status_code = 422
    mensagem_padrao = "Dados inválidos."


class PermissionException(AppException):
    """Falta permissão (§9)."""

    status_code = 403
    mensagem_padrao = "Permissão negada."


class NotFoundException(AppException):
    status_code = 404
    mensagem_padrao = "Registro não encontrado."


class AuthenticationException(AppException):
    status_code = 401
    mensagem_padrao = "Não autenticado."


class ConflictException(AppException):
    """Conflito de estado — inclui o controle otimista de versão (§15)."""

    status_code = 409
    mensagem_padrao = "O registro foi alterado por outra pessoa. Recarregue a página."


class ExternalServiceException(AppException):
    """Falha em serviço externo (SMTP, storage, integração)."""

    status_code = 502
    mensagem_padrao = "Serviço externo indisponível no momento."


def registrar_handlers(app) -> None:
    """Converte as exceções em resposta HTML ou JSON, conforme o pedido."""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    from app.core.logs import write_log

    @app.exception_handler(AppException)
    def _tratar(request: Request, erro: AppException):
        quer_html = "text/html" in (request.headers.get("accept") or "")

        if erro.status_code >= 500:
            from app.core.database import SessionLocal

            db = SessionLocal()
            try:
                write_log(db, "ERROR", "app", f"{type(erro).__name__}: {erro.mensagem}")
            finally:
                db.close()

        if not quer_html:
            return JSONResponse(
                status_code=erro.status_code,
                content={"success": False, "message": erro.mensagem,
                         "data": None, "errors": [erro.como_dict()]},
            )

        from app.core.auth import user_from_request
        from app.core.database import SessionLocal
        from app.core.templating import render

        db = SessionLocal()
        try:
            usuario = user_from_request(request, db)
        finally:
            db.close()
        resposta = render(request, "erro.html", usuario,
                          page_title="Erro", erro=erro)
        resposta.status_code = erro.status_code
        return resposta
