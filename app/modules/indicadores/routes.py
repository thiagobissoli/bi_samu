"""Endpoints do módulo Indicadores (§35.2).

Todas as páginas compartilham os filtros globais (data inicial/final,
convênio Grande Vitória, ISCMV, transporte, motivo, tipo), propagados
via query string.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.database import get_session
from app.core.templating import render
from app.models import Usuario
from app.modules.indicadores.constants import TEMAS
from app.modules.indicadores.service import IndicadoresService

router = APIRouter(prefix="/indicadores", tags=["Indicadores"])


def _filtros(request: Request) -> dict:
    q = request.query_params
    return {
        "data_inicial": q.get("data_inicial", ""),
        "data_final": q.get("data_final", ""),
        "convenio": q.get("convenio", ""),
        "iscmv": q.get("iscmv", ""),
        # seleção múltipla — parâmetro repetido na query string
        "transporte": q.getlist("transporte"),
        "recurso": q.getlist("recurso"),
        "codigo": q.getlist("codigo"),
        "motivo": q.getlist("motivo"),
        "tipo": q.getlist("tipo"),
        "unidade": q.getlist("unidade"),
        "cidade": q.getlist("cidade"),
        "risco": q.getlist("risco"),
        # dashboards de profissional: restringe os indicadores individuais
        "profissional": q.getlist("profissional"),
    }


def _query_string(filtros: dict) -> str:
    from urllib.parse import urlencode
    return urlencode({k: v for k, v in filtros.items() if v}, doseq=True)


@router.get("/", include_in_schema=False)
async def index(
    request: Request,
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    service = IndicadoresService(usuario.empresa_id)
    filtros = _filtros(request)
    inicio, fim = service.periodo_disponivel()
    return render(request, "indicadores/index.html", usuario,
                  page_title="Indicadores", temas=TEMAS, filtros=filtros,
                  qs=_query_string(filtros),
                  periodo_inicio=inicio, periodo_fim=fim)


def _params_desempenho(request: Request) -> tuple[str, str, int]:
    from app.modules.indicadores.constants import (DIMENSOES_DESEMPENHO,
                                                   METRICAS_DESEMPENHO)
    q = request.query_params
    metrica = q.get("metrica", "tempo-resposta")
    if metrica not in METRICAS_DESEMPENHO:
        metrica = "tempo-resposta"
    dimensao = q.get("dimensao", "unidade")
    if dimensao not in DIMENSOES_DESEMPENHO:
        dimensao = "unidade"
    try:
        min_n = max(int(q.get("min_n", "10")), 1)
    except ValueError:
        min_n = 10
    return metrica, dimensao, min_n


@router.get("/desempenho", include_in_schema=False)
async def desempenho(
    request: Request,
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    from app.modules.indicadores.constants import (DIMENSOES_DESEMPENHO,
                                                   METRICAS_DESEMPENHO)
    service = IndicadoresService(usuario.empresa_id)
    filtros = _filtros(request)
    metrica, dimensao, min_n = _params_desempenho(request)
    dados = service.desempenho(metrica, dimensao, filtros, min_n)
    return render(request, "indicadores/desempenho.html", usuario,
                  page_title="Análise de Desempenho", dados=dados,
                  filtros=filtros, min_n=min_n,
                  metricas=METRICAS_DESEMPENHO, dimensoes=DIMENSOES_DESEMPENHO,
                  opcoes=service.opcoes_filtros())


@router.get("/api/desempenho", summary="Análise de desempenho por dimensão")
async def api_desempenho(
    request: Request,
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    service = IndicadoresService(usuario.empresa_id)
    metrica, dimensao, min_n = _params_desempenho(request)
    dados = service.desempenho(metrica, dimensao, _filtros(request), min_n)
    return {"success": True, "message": "", "data": dados, "errors": []}


@router.get("/api/{tema}", summary="Dados de um dashboard de indicadores")
async def api_tema(
    tema: str,
    request: Request,
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    service = IndicadoresService(usuario.empresa_id)
    try:
        dados = service.dashboard(tema, _filtros(request))
    except KeyError:
        return {"success": False, "message": f"Tema desconhecido: {tema}",
                "data": None, "errors": ["tema inválido"]}
    return {"success": True, "message": "", "data": dados, "errors": []}


@router.get("/{tema}", include_in_schema=False)
async def dashboard(
    tema: str,
    request: Request,
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    if tema not in TEMAS:
        return RedirectResponse("/indicadores/", status_code=303)
    service = IndicadoresService(usuario.empresa_id)
    filtros = _filtros(request)
    dados = service.dashboard(tema, filtros)
    opcoes = service.opcoes_filtros()
    return render(request, "indicadores/dashboard.html", usuario,
                  page_title=dados["titulo"], dados=dados, tema=tema,
                  temas=TEMAS, filtros=filtros, opcoes=opcoes,
                  qs=_query_string(filtros))
