"""Permissões (§9) — catálogo somente leitura, sincronizado dos módulos."""

from itertools import groupby

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.database import get_session
from app.core.templating import render
from app.models import Permissao, Usuario

router = APIRouter(prefix="/permissoes", tags=["Permissoes"])


@router.get("/", include_in_schema=False)
async def index(
    request: Request,
    usuario: Usuario = Depends(require_permission("permissao.listar")),
    db: Session = Depends(get_session),
):
    permissoes = list(db.scalars(
        select(Permissao).where(Permissao.deleted_at.is_(None))
        .order_by(Permissao.modulo, Permissao.codigo)
    ))
    grupos = [(m, list(itens)) for m, itens in groupby(permissoes, key=lambda p: p.modulo)]
    return render(request, "permissoes/index.html", usuario,
                  page_title="Permissões", grupos=grupos, total=len(permissoes))
