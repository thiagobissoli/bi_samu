"""Usuários (§8) — CRUD com Argon2, perfis (RBAC §7) e confirmação de e-mail."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit, snapshot
from app.core.auth import require_permission
from app.core.database import get_session, utcnow
from app.core.logs import write_log
from app.core.pagination import paginate
from app.core.security import generate_token, hash_password
from app.core.templating import render
from app.models import Perfil, TokenSeguranca, Usuario

router = APIRouter(prefix="/usuarios", tags=["Usuarios"])

FIELDS = ["nome", "email", "telefone", "ativo", "email_confirmado"]


def _perfis(db: Session) -> list[Perfil]:
    return list(db.scalars(
        select(Perfil).where(Perfil.deleted_at.is_(None), Perfil.ativo.is_(True))
        .order_by(Perfil.nome)
    ))


@router.get("/", include_in_schema=False)
async def index(
    request: Request,
    q: str | None = None,
    page: int = 1,
    usuario: Usuario = Depends(require_permission("usuario.listar")),
    db: Session = Depends(get_session),
):
    # Isolamento multi-tenant (§36.9): somente usuários da empresa atual.
    query = select(Usuario).where(
        Usuario.deleted_at.is_(None),
        Usuario.empresa_id == usuario.empresa_id,
    ).order_by(Usuario.id.desc())
    if q:
        query = query.where(Usuario.nome.ilike(f"%{q}%") | Usuario.email.ilike(f"%{q}%"))
    pg = paginate(db, query, page)
    return render(request, "usuarios/index.html", usuario,
                  page_title="Usuários", pg=pg, q=q or "", qs=f"&q={q or ''}")


@router.get("/create", include_in_schema=False)
async def create_form(
    request: Request,
    usuario: Usuario = Depends(require_permission("usuario.criar")),
    db: Session = Depends(get_session),
):
    return render(request, "usuarios/form.html", usuario, page_title="Usuários",
                  item=None, perfis=_perfis(db), action="/usuarios/create")


@router.post("/create", include_in_schema=False)
async def create(
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    telefone: str = Form(""),
    senha: str = Form(...),
    ativo: bool = Form(False),
    perfil_ids: list[int] = Form([]),
    usuario: Usuario = Depends(require_permission("usuario.criar")),
    db: Session = Depends(get_session),
):
    item = Usuario(
        empresa_id=usuario.empresa_id, nome=nome, email=email.strip().lower(),
        telefone=telefone or None, senha_hash=hash_password(senha),
        ativo=ativo, created_by=usuario.id,
    )
    for perfil in _perfis(db):
        if perfil.id in perfil_ids:
            item.perfis.append(perfil)
    db.add(item)
    db.commit()

    # Confirmação de e-mail (§6) — link registrado em log (sem SMTP).
    token = generate_token()[:64]
    db.add(TokenSeguranca(usuario_id=item.id, tipo="confirmacao_email", token=token,
                          expira_em=utcnow() + timedelta(days=3)))
    db.commit()
    write_log(db, "INFO", "usuarios",
              f"Confirmação de e-mail para {item.email}: /confirmar-email/{token}")

    record_audit(db, tabela="usuarios", acao="INSERT", registro_id=item.id,
                 valor_novo=snapshot(item, FIELDS), usuario=usuario, request=request)
    return RedirectResponse("/usuarios/", status_code=303)


@router.get("/{item_id}/edit", include_in_schema=False)
async def edit_form(
    request: Request,
    item_id: int,
    usuario: Usuario = Depends(require_permission("usuario.editar")),
    db: Session = Depends(get_session),
):
    item = db.get(Usuario, item_id)
    if item is None or item.deleted_at is not None:
        return RedirectResponse("/usuarios/", status_code=303)
    return render(request, "usuarios/form.html", usuario, page_title="Usuários",
                  item=item, perfis=_perfis(db), action=f"/usuarios/{item_id}/edit")


@router.post("/{item_id}/edit", include_in_schema=False)
async def edit(
    request: Request,
    item_id: int,
    nome: str = Form(...),
    email: str = Form(...),
    telefone: str = Form(""),
    senha: str = Form(""),
    ativo: bool = Form(False),
    perfil_ids: list[int] = Form([]),
    usuario: Usuario = Depends(require_permission("usuario.editar")),
    db: Session = Depends(get_session),
):
    item = db.get(Usuario, item_id)
    if item is None or item.deleted_at is not None:
        return RedirectResponse("/usuarios/", status_code=303)
    antes = snapshot(item, FIELDS)
    item.nome = nome
    item.email = email.strip().lower()
    item.telefone = telefone or None
    item.ativo = ativo
    if senha:
        item.senha_hash = hash_password(senha)
    item.perfis.clear()
    for perfil in _perfis(db):
        if perfil.id in perfil_ids:
            item.perfis.append(perfil)
    item.updated_by = usuario.id
    db.commit()
    record_audit(db, tabela="usuarios", acao="UPDATE", registro_id=item.id,
                 valor_anterior=antes, valor_novo=snapshot(item, FIELDS),
                 usuario=usuario, request=request)
    return RedirectResponse("/usuarios/", status_code=303)


@router.post("/{item_id}/delete", include_in_schema=False)
async def delete(
    request: Request,
    item_id: int,
    usuario: Usuario = Depends(require_permission("usuario.excluir")),
    db: Session = Depends(get_session),
):
    item = db.get(Usuario, item_id)
    if item is not None and item.deleted_at is None and item.id != usuario.id:
        antes = snapshot(item, FIELDS)
        item.deleted_at = utcnow()
        item.deleted_by = usuario.id
        db.commit()
        record_audit(db, tabela="usuarios", acao="DELETE", registro_id=item.id,
                     valor_anterior=antes, usuario=usuario, request=request)
    return RedirectResponse("/usuarios/", status_code=303)
