"""Empresas (§8) — CRUD completo com auditoria e permissões."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit, snapshot
from app.core.auth import require_permission
from app.core.database import get_session, utcnow
from app.core.pagination import paginate
from app.core.templating import render
from app.models import Empresa, Usuario

router = APIRouter(prefix="/empresas", tags=["Empresas"])

FIELDS = ["razao_social", "nome_fantasia", "cnpj", "email", "telefone", "plano", "status"]


def _query(search: str | None = None):
    q = select(Empresa).where(Empresa.deleted_at.is_(None)).order_by(Empresa.id.desc())
    if search:
        q = q.where(Empresa.nome_fantasia.ilike(f"%{search}%"))
    return q


@router.get("/", include_in_schema=False)
async def index(
    request: Request,
    q: str | None = None,
    page: int = 1,
    usuario: Usuario = Depends(require_permission("empresa.listar")),
    db: Session = Depends(get_session),
):
    pg = paginate(db, _query(q), page)
    return render(request, "empresas/index.html", usuario,
                  page_title="Empresas", pg=pg, q=q or "", qs=f"&q={q or ''}")


@router.get("/create", include_in_schema=False)
async def create_form(
    request: Request,
    usuario: Usuario = Depends(require_permission("empresa.criar")),
):
    return render(request, "empresas/form.html", usuario,
                  page_title="Empresas", item=None, action="/empresas/create")


@router.post("/create", include_in_schema=False)
async def create(
    request: Request,
    razao_social: str = Form(...),
    nome_fantasia: str = Form(...),
    cnpj: str = Form(...),
    email: str = Form(...),
    telefone: str = Form(""),
    plano: str = Form("basico"),
    status: str = Form("ativa"),
    usuario: Usuario = Depends(require_permission("empresa.criar")),
    db: Session = Depends(get_session),
):
    item = Empresa(
        empresa_id=usuario.empresa_id, razao_social=razao_social,
        nome_fantasia=nome_fantasia, cnpj=cnpj, email=email,
        telefone=telefone or None, plano=plano, status=status,
        created_by=usuario.id,
    )
    db.add(item)
    db.commit()
    record_audit(db, tabela="empresas", acao="INSERT", registro_id=item.id,
                 valor_novo=snapshot(item, FIELDS), usuario=usuario, request=request)
    return RedirectResponse("/empresas/", status_code=303)


@router.get("/{item_id}/edit", include_in_schema=False)
async def edit_form(
    request: Request,
    item_id: int,
    usuario: Usuario = Depends(require_permission("empresa.editar")),
    db: Session = Depends(get_session),
):
    item = db.get(Empresa, item_id)
    if item is None or item.deleted_at is not None:
        return RedirectResponse("/empresas/", status_code=303)
    return render(request, "empresas/form.html", usuario,
                  page_title="Empresas", item=item, action=f"/empresas/{item_id}/edit")


@router.post("/{item_id}/edit", include_in_schema=False)
async def edit(
    request: Request,
    item_id: int,
    razao_social: str = Form(...),
    nome_fantasia: str = Form(...),
    cnpj: str = Form(...),
    email: str = Form(...),
    telefone: str = Form(""),
    plano: str = Form("basico"),
    status: str = Form("ativa"),
    usuario: Usuario = Depends(require_permission("empresa.editar")),
    db: Session = Depends(get_session),
):
    item = db.get(Empresa, item_id)
    if item is None or item.deleted_at is not None:
        return RedirectResponse("/empresas/", status_code=303)
    antes = snapshot(item, FIELDS)
    item.razao_social = razao_social
    item.nome_fantasia = nome_fantasia
    item.cnpj = cnpj
    item.email = email
    item.telefone = telefone or None
    item.plano = plano
    item.status = status
    item.updated_by = usuario.id
    db.commit()
    record_audit(db, tabela="empresas", acao="UPDATE", registro_id=item.id,
                 valor_anterior=antes, valor_novo=snapshot(item, FIELDS),
                 usuario=usuario, request=request)
    return RedirectResponse("/empresas/", status_code=303)


@router.post("/{item_id}/delete", include_in_schema=False)
async def delete(
    request: Request,
    item_id: int,
    usuario: Usuario = Depends(require_permission("empresa.excluir")),
    db: Session = Depends(get_session),
):
    item = db.get(Empresa, item_id)
    if item is not None and item.deleted_at is None:
        antes = snapshot(item, FIELDS)
        item.deleted_at = utcnow()
        item.deleted_by = usuario.id
        db.commit()
        record_audit(db, tabela="empresas", acao="DELETE", registro_id=item.id,
                     valor_anterior=antes, usuario=usuario, request=request)
    return RedirectResponse("/empresas/", status_code=303)
