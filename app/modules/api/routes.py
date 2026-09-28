"""Módulo API (§31) — gestão de chaves e endpoints externos (§16, §39.20)."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.api_auth import (
    PrincipalAPI,
    buscar_chave,
    emitir_token,
    gerar_chave,
    require_scope,
)
from app.core.audit import record_audit
from app.core.auth import require_permission
from app.core.database import get_session, utcnow
from app.core.exceptions import AuthenticationException
from app.core.pagination import paginate
from app.core.templating import render
from app.models import ApiKey, Permissao, Usuario

router = APIRouter(tags=["API"])


# --- Telas de gestão das chaves ---


@router.get("/api-keys", include_in_schema=False)
def index(
    request: Request,
    page: int = 1,
    usuario: Usuario = Depends(require_permission("apikey.listar")),
    db: Session = Depends(get_session),
):
    query = select(ApiKey).where(
        ApiKey.empresa_id == usuario.tenant_id,
        ApiKey.deleted_at.is_(None),
    ).order_by(ApiKey.id.desc())
    pg = paginate(db, query, page)
    return render(request, "api/index.html", usuario,
                  page_title="API", pg=pg, qs="",
                  chave_nova=request.query_params.get("chave"))


@router.get("/api-keys/create", include_in_schema=False)
def create_form(
    request: Request,
    usuario: Usuario = Depends(require_permission("apikey.criar")),
    db: Session = Depends(get_session),
):
    escopos = list(db.scalars(
        select(Permissao).where(Permissao.deleted_at.is_(None))
        .order_by(Permissao.modulo, Permissao.codigo)
    ))
    return render(request, "api/form.html", usuario,
                  page_title="API", escopos=escopos)


@router.post("/api-keys/create", include_in_schema=False)
def create(
    request: Request,
    nome: str = Form(...),
    escopos: list[str] = Form([]),
    dias_validade: int = Form(0),
    usuario: Usuario = Depends(require_permission("apikey.criar")),
    db: Session = Depends(get_session),
):
    chave, prefixo, chave_hash = gerar_chave()
    item = ApiKey(
        empresa_id=usuario.tenant_id, nome=nome, prefixo=prefixo,
        chave_hash=chave_hash, usuario_id=usuario.id,
        escopos=",".join(escopos), created_by=usuario.id,
        expira_em=(utcnow() + timedelta(days=dias_validade)) if dias_validade else None,
    )
    db.add(item)
    db.commit()
    record_audit(db, tabela="api_keys", acao="INSERT", registro_id=item.id,
                 valor_novo={"nome": nome, "prefixo": prefixo, "escopos": escopos},
                 usuario=usuario, request=request)
    # A chave em claro viaja uma única vez, para ser exibida na próxima tela.
    return RedirectResponse(f"/api-keys?chave={chave}", status_code=303)


@router.post("/api-keys/{item_id}/revogar", include_in_schema=False)
def revogar(
    request: Request,
    item_id: int,
    usuario: Usuario = Depends(require_permission("apikey.revogar")),
    db: Session = Depends(get_session),
):
    item = db.get(ApiKey, item_id)
    if item is not None and item.empresa_id == usuario.tenant_id:
        item.revogada = True
        item.updated_by = usuario.id
        db.commit()
        record_audit(db, tabela="api_keys", acao="REVOGACAO", registro_id=item.id,
                     valor_anterior={"nome": item.nome, "prefixo": item.prefixo},
                     usuario=usuario, request=request)
    return RedirectResponse("/api-keys", status_code=303)


# --- Endpoints externos (§16) ---


@router.post("/api/token", tags=["API"], summary="Trocar API Key por um JWT")
def token(payload: dict, db: Session = Depends(get_session)):
    """Credenciais de cliente: envie `{"api_key": "sk_..."}`."""
    chave = (payload or {}).get("api_key", "")
    api_key = buscar_chave(db, chave)
    if api_key is None:
        raise AuthenticationException("API Key inválida, expirada ou revogada.")
    return {"success": True, "message": "", "data": emitir_token(api_key), "errors": []}


@router.get("/api/v1/me", tags=["API"], summary="Identidade da credencial")
def me(principal: PrincipalAPI = Depends(require_scope("apikey.listar"))):
    return {
        "success": True, "message": "",
        "data": {
            "usuario": principal.usuario.nome,
            "empresa_id": principal.empresa_id,
            "escopos": sorted(principal.permissoes),
        },
        "errors": [],
    }


@router.get("/api/v1/usuarios", tags=["API"], summary="Listar usuários (externo)")
def api_usuarios(
    principal: PrincipalAPI = Depends(require_scope("usuario.listar")),
    db: Session = Depends(get_session),
):
    """Exemplo de endpoint externo — isolado pelo tenant da chave (§36.9)."""
    itens = list(db.scalars(
        select(Usuario).where(
            Usuario.deleted_at.is_(None),
            Usuario.empresa_id == principal.empresa_id,
        ).order_by(Usuario.id)
    ))
    return {
        "success": True, "message": "",
        "data": [{"id": u.id, "nome": u.nome, "email": u.email, "ativo": u.ativo}
                 for u in itens],
        "errors": [],
    }
