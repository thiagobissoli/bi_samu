"""Configurações por empresa (§22) — chave/valor com cache (§39.12),
criptografia de chaves sensíveis (§39.29) e auditoria mascarada."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth import require_permission
from app.core.config_service import get_config, invalidate_config, set_config
from app.core.crypto import is_sensitive, mask_value
from app.core.database import get_session, utcnow
from app.core.templating import render
from app.models import Configuracao, Usuario

router = APIRouter(prefix="/configuracoes", tags=["Configuracoes"])


@router.get("/", include_in_schema=False)
async def index(
    request: Request,
    usuario: Usuario = Depends(require_permission("configuracao.listar")),
    db: Session = Depends(get_session),
):
    registros = list(db.scalars(
        select(Configuracao).where(
            Configuracao.deleted_at.is_(None),
            Configuracao.empresa_id == usuario.empresa_id,
        ).order_by(Configuracao.chave)
    ))
    items = [
        {
            "id": c.id,
            "chave": c.chave,
            "sensivel": is_sensitive(c.chave),
            "valor": "" if is_sensitive(c.chave) else (c.valor or ""),
            "definido": bool(c.valor),
        }
        for c in registros
    ]
    return render(request, "configuracoes/index.html", usuario,
                  page_title="Configurações", items=items)


@router.post("/salvar", include_in_schema=False)
async def salvar(
    request: Request,
    chave: str = Form(...),
    valor: str = Form(""),
    usuario: Usuario = Depends(require_permission("configuracao.editar")),
    db: Session = Depends(get_session),
):
    chave = chave.strip()
    # Campo sensível em branco = manter o valor atual (não sobrescrever).
    if not valor and is_sensitive(chave):
        atual = get_config(db, chave, empresa_id=usuario.empresa_id)
        if atual:
            return RedirectResponse("/configuracoes/", status_code=303)

    anterior = get_config(db, chave, empresa_id=usuario.empresa_id)
    existia = anterior is not None
    item = set_config(db, chave, valor, usuario.empresa_id, updated_by=usuario.id)

    record_audit(
        db, tabela="configuracoes",
        acao="UPDATE" if existia else "INSERT",
        registro_id=item.id,
        valor_anterior=(
            {"chave": chave, "valor": mask_value(chave, anterior)} if existia else None
        ),
        valor_novo={"chave": chave, "valor": mask_value(chave, valor)},
        usuario=usuario, request=request,
    )
    return RedirectResponse("/configuracoes/", status_code=303)


@router.post("/{item_id}/delete", include_in_schema=False)
async def delete(
    request: Request,
    item_id: int,
    usuario: Usuario = Depends(require_permission("configuracao.excluir")),
    db: Session = Depends(get_session),
):
    """Exclusão lógica de uma chave (§36.7) — some da tela e o get_config
    volta a usar o valor padrão; o histórico permanece na auditoria."""
    item = db.get(Configuracao, item_id)
    if item is not None and item.deleted_at is None and item.empresa_id == usuario.empresa_id:
        anterior = get_config(db, item.chave, empresa_id=usuario.empresa_id)
        item.deleted_at = utcnow()
        item.deleted_by = usuario.id
        db.commit()
        invalidate_config(usuario.empresa_id, item.chave)
        record_audit(db, tabela="configuracoes", acao="DELETE", registro_id=item.id,
                     valor_anterior={"chave": item.chave,
                                     "valor": mask_value(item.chave, anterior)},
                     usuario=usuario, request=request)
    return RedirectResponse("/configuracoes/", status_code=303)
