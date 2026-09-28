"""Autenticação de APIs externas (§6, §39.20) — API Keys e JWT.

A §6 reserva o JWT para APIs externas: as telas continuam usando sessão em
cookie HTTPOnly. O fluxo é o de credenciais de cliente:

    1. o integrador recebe uma API Key (`sk_...`), mostrada só na criação;
    2. troca a chave por um JWT de curta duração em `POST /api/token`;
    3. usa `Authorization: Bearer <jwt>` nas chamadas.

Aceitar a API Key direto no header também funciona (mais simples para
scripts), mas o JWT é preferível: expira sozinho e não trafega o segredo
a cada requisição.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_session, utcnow
from app.core.exceptions import AuthenticationException, PermissionException
from app.models import ApiKey, Usuario

ALGORITMO = "HS256"
DURACAO_TOKEN = timedelta(hours=1)
PREFIXO_CHAVE = "sk"


# --- API Keys ---


def gerar_chave() -> tuple[str, str, str]:
    """Devolve (chave em claro, prefixo, hash). A chave não é recuperável."""
    prefixo = secrets.token_hex(4)
    segredo = secrets.token_urlsafe(32)
    chave = f"{PREFIXO_CHAVE}_{prefixo}_{segredo}"
    return chave, prefixo, hashlib.sha256(chave.encode()).hexdigest()


def buscar_chave(db: Session, chave: str) -> ApiKey | None:
    registro = db.scalar(select(ApiKey).where(
        ApiKey.chave_hash == hashlib.sha256(chave.encode()).hexdigest()
    ))
    return registro if registro is not None and registro.ativa else None


def registrar_uso(db: Session, api_key: ApiKey, ip: str | None) -> None:
    api_key.ultimo_uso = utcnow()
    api_key.ultimo_ip = ip
    api_key.total_usos = (api_key.total_usos or 0) + 1
    db.commit()


# --- JWT ---


def emitir_token(api_key: ApiKey) -> dict:
    agora = utcnow()
    payload = {
        "sub": str(api_key.usuario_id),
        "kid": api_key.id,
        "emp": api_key.empresa_id,
        "scp": api_key.lista_escopos,
        "iat": int(agora.timestamp()),
        "exp": int((agora + DURACAO_TOKEN).timestamp()),
        "iss": settings.app_name,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=ALGORITMO)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": int(DURACAO_TOKEN.total_seconds()),
        "scopes": api_key.lista_escopos,
    }


def ler_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITMO])
    except jwt.ExpiredSignatureError as erro:
        raise AuthenticationException("Token expirado.") from erro
    except jwt.InvalidTokenError as erro:
        raise AuthenticationException("Token inválido.") from erro


# --- Princípio de acesso da API ---


class PrincipalAPI:
    """Quem está chamando a API: o usuário de serviço, limitado aos escopos.

    Mesmo que o usuário dono tenha mais permissões, a chamada só enxerga o que
    a chave declarou — o escopo é o teto, nunca a permissão do usuário.
    """

    def __init__(self, usuario: Usuario, empresa_id: int, escopos: list[str],
                 api_key_id: int | None = None):
        self.usuario = usuario
        self.empresa_id = empresa_id
        self.escopos = set(escopos)
        self.api_key_id = api_key_id

    @property
    def permissoes(self) -> set[str]:
        return self.escopos & self.usuario.permissoes

    def pode(self, escopo: str) -> bool:
        return escopo in self.permissoes


def _principal_da_chave(db: Session, api_key: ApiKey, ip: str | None) -> PrincipalAPI:
    usuario = db.get(Usuario, api_key.usuario_id)
    if usuario is None or not usuario.ativo or usuario.deleted_at is not None:
        raise AuthenticationException("Usuário de serviço inativo.")
    usuario.assumir_tenant(api_key.empresa_id)
    registrar_uso(db, api_key, ip)
    return PrincipalAPI(usuario, api_key.empresa_id, api_key.lista_escopos, api_key.id)


def obter_principal(
    request: Request, db: Session = Depends(get_session)
) -> PrincipalAPI:
    """Aceita `Bearer <jwt>` ou `Bearer sk_...` (a própria API Key)."""
    cabecalho = request.headers.get("authorization") or ""
    if not cabecalho.lower().startswith("bearer "):
        raise AuthenticationException(
            "Informe a credencial em Authorization: Bearer <token>."
        )
    credencial = cabecalho[7:].strip()
    ip = request.client.host if request.client else None

    if credencial.startswith(f"{PREFIXO_CHAVE}_"):
        api_key = buscar_chave(db, credencial)
        if api_key is None:
            raise AuthenticationException("API Key inválida, expirada ou revogada.")
        return _principal_da_chave(db, api_key, ip)

    dados = ler_token(credencial)
    api_key = db.get(ApiKey, dados.get("kid"))
    if api_key is None or not api_key.ativa:
        raise AuthenticationException("A chave deste token foi revogada.")

    usuario = db.get(Usuario, int(dados["sub"]))
    if usuario is None or not usuario.ativo or usuario.deleted_at is not None:
        raise AuthenticationException("Usuário de serviço inativo.")
    usuario.assumir_tenant(dados["emp"])
    return PrincipalAPI(usuario, dados["emp"], dados.get("scp", []), api_key.id)


def require_scope(escopo: str):
    """Dependency das rotas de API: exige o escopo na chave e no usuário."""

    def dependency(principal: PrincipalAPI = Depends(obter_principal)) -> PrincipalAPI:
        if not principal.pode(escopo):
            raise PermissionException(
                f"A credencial não tem o escopo '{escopo}'."
            )
        return principal

    return dependency
