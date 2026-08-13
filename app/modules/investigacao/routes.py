"""Endpoints do módulo Investigação de Eventos (§35.2).

Somente leitura: o módulo analisa os registros já importados (núcleo do
módulo indicadores) e não persiste nada.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.database import get_session
from app.core.templating import render
from app.models import Usuario
from app.modules.investigacao.service import InvestigacaoService

router = APIRouter(prefix="/investigacao", tags=["Investigação de Eventos"])


def _params(request: Request) -> dict:
    q = request.query_params
    return {
        "dia": q.get("dia", ""),
        "municipios": q.getlist("municipio"),
        "unidades": q.getlist("unidade"),
        "ocorrencia": q.get("ocorrencia", "").strip(),
    }


@router.get("/", include_in_schema=False)
def index(
    request: Request,
    usuario: Usuario = Depends(require_permission("investigacao.visualizar")),
    db: Session = Depends(get_session),
):
    service = InvestigacaoService(usuario.empresa_id)
    p = _params(request)
    opcoes = service.opcoes()
    dia = p["dia"] or opcoes.get("dia_max") or ""

    investigacao = service.investigar(p["ocorrencia"]) if p["ocorrencia"] else None
    # Investigar uma ocorrência posiciona a timeline no dia dela
    if investigacao and not investigacao.get("erro") and not p["dia"]:
        dia = investigacao["dia"]

    return render(
        request, "investigacao/index.html", usuario,
        page_title="Investigação de Eventos",
        timeline=service.timeline_dia(dia, p["municipios"], p["unidades"]),
        cruzamentos=service.cruzamentos(dia),
        investigacao=investigacao, opcoes=opcoes, filtros={**p, "dia": dia})


@router.get("/api/timeline", summary="Ocupação das viaturas em um dia")
def api_timeline(
    request: Request,
    usuario: Usuario = Depends(require_permission("investigacao.visualizar")),
    db: Session = Depends(get_session),
):
    service = InvestigacaoService(usuario.empresa_id)
    p = _params(request)
    dia = p["dia"] or service.opcoes().get("dia_max") or ""
    return {"success": True, "message": "",
            "data": service.timeline_dia(dia, p["municipios"], p["unidades"]),
            "errors": []}


@router.get("/api/investigar", summary="Análise de um empenho de outro município")
def api_investigar(
    ocorrencia: str,
    usuario: Usuario = Depends(require_permission("investigacao.visualizar")),
    db: Session = Depends(get_session),
):
    dados = InvestigacaoService(usuario.empresa_id).investigar(ocorrencia)
    if dados.get("erro"):
        return {"success": False, "message": dados["erro"], "data": None,
                "errors": [dados["erro"]]}
    return {"success": True, "message": "", "data": dados, "errors": []}
