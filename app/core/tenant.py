"""TenantService (§39.6) — empresa ativa e isolamento de dados (§36.9).

Todo usuário pertence a uma empresa (`Usuario.empresa_id`). Operadores da
plataforma — quem tem a permissão `empresa.trocar` — podem assumir o contexto
de outra empresa sem trocar de conta; a empresa ativa fica gravada na sessão.

Nas rotas use sempre `usuario.tenant_id` (a empresa ativa), nunca
`usuario.empresa_id` (a empresa de origem do usuário). É `tenant_id` que
garante que a troca de empresa realmente muda o que se vê e o que se grava.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import SESSION_COOKIE, has_permission
from app.models import Empresa, Sessao, Usuario

PERMISSAO_TROCA = "empresa.trocar"


def pode_trocar(usuario: Usuario) -> bool:
    return has_permission(usuario, PERMISSAO_TROCA)


def empresas_disponiveis(db: Session, usuario: Usuario) -> list[Empresa]:
    """Empresas que o usuário pode assumir. Sem a permissão, só a dele."""
    query = select(Empresa).where(Empresa.deleted_at.is_(None))
    if not pode_trocar(usuario):
        query = query.where(Empresa.id == usuario.empresa_id)
    return list(db.scalars(query.order_by(Empresa.nome_fantasia)))


def empresa_ativa(db: Session, usuario: Usuario) -> Empresa | None:
    return db.get(Empresa, usuario.tenant_id)


def aplicar_sessao(usuario: Usuario, sessao: Sessao | None) -> None:
    """Carrega a empresa ativa da sessão no usuário da requisição.

    Se a sessão aponta para outra empresa mas o usuário perdeu a permissão de
    troca, o contexto volta para a empresa de origem — a permissão é checada a
    cada requisição, não apenas no momento da troca.
    """
    if sessao is None or not sessao.empresa_id:
        return
    if sessao.empresa_id == usuario.empresa_id:
        return
    if pode_trocar(usuario):
        usuario.assumir_tenant(sessao.empresa_id)


def trocar_empresa(
    db: Session, usuario: Usuario, empresa_id: int, token: str | None
) -> bool:
    """Grava a empresa ativa na sessão. Devolve False se não for permitido."""
    if not pode_trocar(usuario) and empresa_id != usuario.empresa_id:
        return False
    empresa = db.get(Empresa, empresa_id)
    if empresa is None or empresa.deleted_at is not None:
        return False
    if token:
        sessao = db.scalar(select(Sessao).where(Sessao.token == token))
        if sessao is not None:
            sessao.empresa_id = empresa_id
            db.commit()
    usuario.assumir_tenant(empresa_id)
    return True


def token_da_requisicao(request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)
