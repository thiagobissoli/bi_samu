"""Endpoints da página inicial (a página em si é o dashboard "/", em main.py)."""

from fastapi import APIRouter, Depends

from app.core.auth import require_permission
from app.models import Usuario
from app.modules.inicio.service import gestao

router = APIRouter(prefix="/inicio", tags=["Início"])


@router.get("/api/gestao", summary="Resumo de gestão da última semana completa")
def api_gestao(usuario: Usuario = Depends(require_permission("indicadores.visualizar"))):
    """Carregado à parte pela página inicial: usa o núcleo dos Indicadores."""
    return {"success": True, "message": "", "data": gestao(usuario.empresa_id),
            "errors": []}
