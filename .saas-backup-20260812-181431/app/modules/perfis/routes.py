"""Perfis (§8) — CRUD com vínculo de permissões (RBAC §7)."""

from itertools import groupby

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit, snapshot
from app.core.auth import require_permission
from app.core.database import get_session, utcnow
from app.core.templating import render
from app.models import Perfil, Permissao, Usuario

router = APIRouter(prefix="/perfis", tags=["Perfis"])

FIELDS = ["nome", "descricao", "ativo"]


def _permissoes_agrupadas(db: Session):
    permissoes = list(db.scalars(
        select(Permissao).where(Permissao.deleted_at.is_(None))
        .order_by(Permissao.modulo, Permissao.codigo)
    ))
    return [(modulo, list(itens)) for modulo, itens in groupby(permissoes, key=lambda p: p.modulo)]


@router.get("/", include_in_schema=False)
def index(
    request: Request,
    usuario: Usuario = Depends(require_permission("perfil.listar")),
    db: Session = Depends(get_session),
):
    items = list(db.scalars(
        select(Perfil).where(Perfil.deleted_at.is_(None)).order_by(Perfil.nome)
    ))
    return render(request, "perfis/index.html", usuario, page_title="Perfis", items=items)


@router.get("/create", include_in_schema=False)
def create_form(
    request: Request,
    usuario: Usuario = Depends(require_permission("perfil.criar")),
    db: Session = Depends(get_session),
):
    return render(request, "perfis/form.html", usuario, page_title="Perfis",
                  item=None, grupos=_permissoes_agrupadas(db), action="/perfis/create")


@router.post("/create", include_in_schema=False)
def create(
    request: Request,
    nome: str = Form(...),
    descricao: str = Form(""),
    ativo: bool = Form(False),
    permissao_ids: list[int] = Form([]),
    usuario: Usuario = Depends(require_permission("perfil.criar")),
    db: Session = Depends(get_session),
):
    item = Perfil(empresa_id=usuario.empresa_id, nome=nome,
                  descricao=descricao or None, ativo=ativo, created_by=usuario.id)
    todas = list(db.scalars(select(Permissao).where(Permissao.id.in_(permissao_ids or [-1]))))
    item.permissoes.extend(todas)
    db.add(item)
    db.commit()
    record_audit(db, tabela="perfis", acao="INSERT", registro_id=item.id,
                 valor_novo=snapshot(item, FIELDS), usuario=usuario, request=request)
    return RedirectResponse("/perfis/", status_code=303)


@router.get("/{item_id}/edit", include_in_schema=False)
def edit_form(
    request: Request,
    item_id: int,
    usuario: Usuario = Depends(require_permission("perfil.editar")),
    db: Session = Depends(get_session),
):
    item = db.get(Perfil, item_id)
    if item is None or item.deleted_at is not None:
        return RedirectResponse("/perfis/", status_code=303)
    return render(request, "perfis/form.html", usuario, page_title="Perfis",
                  item=item, grupos=_permissoes_agrupadas(db), action=f"/perfis/{item_id}/edit")


@router.post("/{item_id}/edit", include_in_schema=False)
def edit(
    request: Request,
    item_id: int,
    nome: str = Form(...),
    descricao: str = Form(""),
    ativo: bool = Form(False),
    permissao_ids: list[int] = Form([]),
    usuario: Usuario = Depends(require_permission("perfil.editar")),
    db: Session = Depends(get_session),
):
    item = db.get(Perfil, item_id)
    if item is None or item.deleted_at is not None:
        return RedirectResponse("/perfis/", status_code=303)
    antes = snapshot(item, FIELDS)
    item.nome = nome
    item.descricao = descricao or None
    item.ativo = ativo
    item.permissoes.clear()
    todas = list(db.scalars(select(Permissao).where(Permissao.id.in_(permissao_ids or [-1]))))
    item.permissoes.extend(todas)
    item.updated_by = usuario.id
    db.commit()
    record_audit(db, tabela="perfis", acao="UPDATE", registro_id=item.id,
                 valor_anterior=antes, valor_novo=snapshot(item, FIELDS),
                 usuario=usuario, request=request)
    return RedirectResponse("/perfis/", status_code=303)


@router.post("/{item_id}/delete", include_in_schema=False)
def delete(
    request: Request,
    item_id: int,
    usuario: Usuario = Depends(require_permission("perfil.excluir")),
    db: Session = Depends(get_session),
):
    item = db.get(Perfil, item_id)
    if item is not None and item.deleted_at is None and item.nome != "Administrador":
        antes = snapshot(item, FIELDS)
        item.deleted_at = utcnow()
        item.deleted_by = usuario.id
        db.commit()
        record_audit(db, tabela="perfis", acao="DELETE", registro_id=item.id,
                     valor_anterior=antes, usuario=usuario, request=request)
    return RedirectResponse("/perfis/", status_code=303)
