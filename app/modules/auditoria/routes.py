"""Auditoria (§11) — consulta somente leitura. Nunca apagar auditoria."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.database import get_session
from app.core.pagination import paginate
from app.core.templating import render
from app.models import Auditoria, Usuario

router = APIRouter(prefix="/auditoria", tags=["Auditoria"])


@router.get("/", include_in_schema=False)
def index(
    request: Request,
    tabela: str = "",
    acao: str = "",
    page: int = 1,
    usuario: Usuario = Depends(require_permission("auditoria.listar")),
    db: Session = Depends(get_session),
):
    query = select(Auditoria).where(
        Auditoria.empresa_id == usuario.empresa_id
    ).order_by(Auditoria.id.desc())
    if tabela:
        query = query.where(Auditoria.tabela == tabela)
    if acao:
        query = query.where(Auditoria.acao == acao)
    pg = paginate(db, query, page, per_page=20)
    tabelas = sorted({a for a in db.scalars(select(Auditoria.tabela).distinct())})
    acoes = sorted({a for a in db.scalars(select(Auditoria.acao).distinct())})
    return render(request, "auditoria/index.html", usuario, page_title="Auditoria",
                  pg=pg, tabelas=tabelas, acoes=acoes,
                  f_tabela=tabela, f_acao=acao,
                  qs=f"&tabela={tabela}&acao={acao}")
