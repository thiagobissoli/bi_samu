"""Logs (§12) — consulta com filtro por nível e módulo."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.database import get_session
from app.core.pagination import paginate
from app.core.templating import render
from app.models import Log, Usuario

router = APIRouter(prefix="/logs", tags=["Logs"])

NIVEIS = ["INFO", "WARNING", "ERROR", "CRITICAL"]


@router.get("/", include_in_schema=False)
def index(
    request: Request,
    nivel: str = "",
    modulo: str = "",
    page: int = 1,
    usuario: Usuario = Depends(require_permission("log.listar")),
    db: Session = Depends(get_session),
):
    query = select(Log).where(
        Log.empresa_id == usuario.empresa_id
    ).order_by(Log.id.desc())
    if nivel:
        query = query.where(Log.nivel == nivel)
    if modulo:
        query = query.where(Log.modulo == modulo)
    pg = paginate(db, query, page, per_page=20)
    modulos = sorted({m for m in db.scalars(select(Log.modulo).distinct())})
    return render(request, "logs/index.html", usuario, page_title="Logs",
                  pg=pg, niveis=NIVEIS, modulos=modulos,
                  f_nivel=nivel, f_modulo=modulo,
                  qs=f"&nivel={nivel}&modulo={modulo}")
