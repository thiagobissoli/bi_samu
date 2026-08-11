"""Endpoints do módulo Painel de Gestão (§35.2)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.database import get_session
from app.core.templating import render
from app.models import Usuario
from app.modules.painel_gestao.service import PainelGestaoService

router = APIRouter(prefix="/painel_gestao", tags=["Painel de Gestão"])


@router.get("/", include_in_schema=False)
async def painel(
    request: Request,
    usuario: Usuario = Depends(require_permission("painel_gestao.visualizar")),
    db: Session = Depends(get_session),
):
    dados = PainelGestaoService(usuario.empresa_id).montar()
    return render(request, "painel_gestao/painel.html", usuario,
                  page_title="Painel de Gestão", dados=dados)


@router.get("/api", summary="Indicadores do Painel de Gestão")
async def api(
    usuario: Usuario = Depends(require_permission("painel_gestao.visualizar")),
    db: Session = Depends(get_session),
):
    dados = PainelGestaoService(usuario.empresa_id).montar()
    return {"success": True, "message": "", "data": dados, "errors": []}
