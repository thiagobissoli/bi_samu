"""Notificações (§21) — caixa de entrada do usuário e envio manual."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth import require_permission
from app.core.database import get_session, utcnow
from app.core.notifications import notify
from app.core.pagination import paginate
from app.core.templating import render
from app.models import Notificacao, Usuario

router = APIRouter(prefix="/notificacoes", tags=["Notificacoes"])


@router.get("/", include_in_schema=False)
async def index(
    request: Request,
    page: int = 1,
    usuario: Usuario = Depends(require_permission("notificacao.listar")),
    db: Session = Depends(get_session),
):
    query = select(Notificacao).where(
        Notificacao.usuario_id == usuario.id,
        Notificacao.deleted_at.is_(None),
    ).order_by(Notificacao.lida, Notificacao.id.desc())
    pg = paginate(db, query, page)
    return render(request, "notificacoes/index.html", usuario,
                  page_title="Notificações", pg=pg, qs="")


@router.post("/{item_id}/ler", include_in_schema=False)
async def marcar_lida(
    item_id: int,
    usuario: Usuario = Depends(require_permission("notificacao.listar")),
    db: Session = Depends(get_session),
):
    item = db.get(Notificacao, item_id)
    if item is not None and item.usuario_id == usuario.id and not item.lida:
        item.lida = True
        item.lida_em = utcnow()
        db.commit()
    return RedirectResponse("/notificacoes/", status_code=303)


@router.post("/ler-todas", include_in_schema=False)
async def marcar_todas(
    usuario: Usuario = Depends(require_permission("notificacao.listar")),
    db: Session = Depends(get_session),
):
    pendentes = db.scalars(select(Notificacao).where(
        Notificacao.usuario_id == usuario.id, Notificacao.lida.is_(False)
    ))
    agora = utcnow()
    for item in pendentes:
        item.lida = True
        item.lida_em = agora
    db.commit()
    return RedirectResponse("/notificacoes/", status_code=303)


@router.get("/enviar", include_in_schema=False)
async def enviar_form(
    request: Request,
    usuario: Usuario = Depends(require_permission("notificacao.enviar")),
    db: Session = Depends(get_session),
):
    usuarios = list(db.scalars(select(Usuario).where(
        Usuario.deleted_at.is_(None), Usuario.ativo.is_(True),
        Usuario.empresa_id == usuario.empresa_id,
    ).order_by(Usuario.nome)))
    return render(request, "notificacoes/enviar.html", usuario,
                  page_title="Notificações", usuarios=usuarios)


@router.post("/enviar", include_in_schema=False)
async def enviar(
    request: Request,
    usuario_id: int = Form(...),
    titulo: str = Form(...),
    mensagem: str = Form(...),
    tipo: str = Form("info"),
    usuario: Usuario = Depends(require_permission("notificacao.enviar")),
    db: Session = Depends(get_session),
):
    item = notify(db, usuario_id, titulo, mensagem, tipo, empresa_id=usuario.empresa_id)
    record_audit(db, tabela="notificacoes", acao="INSERT", registro_id=item.id,
                 valor_novo={"usuario_id": usuario_id, "titulo": titulo, "tipo": tipo},
                 usuario=usuario, request=request)
    return RedirectResponse("/notificacoes/", status_code=303)
