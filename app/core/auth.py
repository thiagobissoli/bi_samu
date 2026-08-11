"""Autenticação e autorização (§6, §7).

Sessão via cookie HTTPOnly; RBAC Usuário -> Perfil -> Permissões,
com ponto de extensão ABAC por atributos.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_session, utcnow
from app.core.security import generate_token
from app.models import Sessao, Usuario

SESSION_COOKIE = "session"
SESSION_HOURS = 8

# --- Sessões (§6) ---


def create_session(db: Session, usuario: Usuario, ip: str | None, user_agent: str | None) -> str:
    token = generate_token()[:64]
    db.add(
        Sessao(
            usuario_id=usuario.id,
            token=token,
            ip=ip,
            user_agent=(user_agent or "")[:500],
            expires_at=utcnow() + timedelta(hours=SESSION_HOURS),
        )
    )
    db.commit()
    return token


def destroy_session(db: Session, token: str) -> None:
    sessao = db.scalar(select(Sessao).where(Sessao.token == token))
    if sessao:
        db.delete(sessao)
        db.commit()


def user_from_request(request: Request, db: Session) -> Usuario | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    sessao = db.scalar(select(Sessao).where(Sessao.token == token))
    if sessao is None:
        return None
    expires = sessao.expires_at
    if expires.tzinfo is None:
        from datetime import timezone

        expires = expires.replace(tzinfo=timezone.utc)
    if expires < utcnow():
        db.delete(sessao)
        db.commit()
        return None
    usuario = db.get(Usuario, sessao.usuario_id)
    if usuario is None or not usuario.ativo or usuario.deleted_at is not None:
        return None
    return usuario


# --- Dependencies ---


def get_current_user(request: Request, db: Session = Depends(get_session)) -> Usuario:
    """Exige usuário autenticado; páginas HTML redirecionam para /login."""
    usuario = user_from_request(request, db)
    if usuario is None:
        accepts_html = "text/html" in (request.headers.get("accept") or "")
        if accepts_html:
            raise HTTPException(status_code=303, headers={"Location": "/login"})
        raise HTTPException(status_code=401, detail="Não autenticado")
    request.state.user = usuario
    return usuario


# --- RBAC + ABAC (§7) ---

_abac_rules: dict[str, Callable[[Usuario, dict], bool]] = {}


def register_abac_rule(codigo: str, rule: Callable[[Usuario, dict], bool]) -> None:
    """Registra condição ABAC para uma permissão (avaliada após o RBAC)."""
    _abac_rules[codigo] = rule


def has_permission(usuario: Usuario, codigo: str, context: dict | None = None) -> bool:
    if codigo not in usuario.permissoes:
        return False
    rule = _abac_rules.get(codigo)
    if rule is not None:
        return rule(usuario, context or {})
    return True


def require_permission(codigo: str):
    """Dependency de rota: exige a permissão informada (§9)."""

    def dependency(usuario: Usuario = Depends(get_current_user)) -> Usuario:
        if not has_permission(usuario, codigo):
            raise HTTPException(status_code=403, detail="Permissão negada.")
        return usuario

    return dependency
