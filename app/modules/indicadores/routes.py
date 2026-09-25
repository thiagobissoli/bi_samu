"""Endpoints do módulo Indicadores (§35.2).

Todas as páginas compartilham os filtros globais (data inicial/final,
convênio Grande Vitória, ISCM, transporte, motivo, tipo), propagados
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
from app.modules.indicadores import filtros as filtros_mod
from app.modules.indicadores.service import IndicadoresService

router = APIRouter(prefix="/indicadores", tags=["Indicadores"])


def _filtros(request: Request) -> dict:
    return filtros_mod.ler(request.query_params)


def _query_string(filtros: dict) -> str:
    return filtros_mod.query_string(filtros)


def _tela(request: Request, service: IndicadoresService) -> tuple[dict, bool]:
    """Filtros da tela e se o usuário pediu o cálculo (botão Aplicar).

    Sem nenhum filtro na URL, a tela abre com os últimos 30 dias da base
    preenchidos — mas nada é calculado até o usuário aplicar.
    """
    q = request.query_params
    aplicar = q.get("aplicar") == "1"
    chaves_filtro = {k for k in q.keys() if k not in ("aplicar", "page")}
    if chaves_filtro:
        return _filtros(request), aplicar
    return filtros_mod.padrao(service.periodo_disponivel_leve()), aplicar


def _contexto_filtros(filtros: dict) -> dict:
    return {"filtros": filtros, "catalogo": filtros_mod.FILTROS,
            "grupos_filtro": filtros_mod.GRUPOS,
            "tempos_filtraveis": filtros_mod.TEMPOS_FILTRAVEIS,
            "rotulos_cor": filtros_mod.ROTULO_COR,
            "ocultos_ativos": filtros_mod.ativos_ocultos(filtros),
            "qs": _query_string(filtros)}


@router.get("/", include_in_schema=False)
def index(
    request: Request,
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    service = IndicadoresService(usuario.empresa_id)
    filtros = _filtros(request)
    inicio, fim = service.periodo_disponivel_leve(completo=True)
    return render(request, "indicadores/index.html", usuario,
                  page_title="Indicadores", temas=TEMAS, filtros=filtros,
                  qs=_query_string(filtros),
                  periodo_inicio=inicio, periodo_fim=fim)


@router.get("/api/opcoes", summary="Valores dos filtros de seleção múltipla")
def api_opcoes(
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
):
    """Carregado à parte pelas telas: exige o núcleo em memória."""
    opcoes = IndicadoresService(usuario.empresa_id).opcoes_filtros()
    dados = {chave: [[str(v), filtros_mod.rotulo_opcao(chave, v)] for v in valores]
             for chave, valores in opcoes.items()
             if chave in filtros_mod.POR_CHAVE}
    return {"success": True, "message": "", "data": dados, "errors": []}


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
def desempenho(
    request: Request,
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    from app.modules.indicadores.constants import (DIMENSOES_DESEMPENHO,
                                                   METRICAS_DESEMPENHO)
    service = IndicadoresService(usuario.empresa_id)
    filtros, aplicar = _tela(request, service)
    metrica, dimensao, min_n = _params_desempenho(request)
    dados = service.desempenho(metrica, dimensao, filtros, min_n) if aplicar else None
    return render(request, "indicadores/desempenho.html", usuario,
                  page_title="Análise de Desempenho", dados=dados,
                  min_n=min_n, metrica=metrica, dimensao=dimensao,
                  metricas=METRICAS_DESEMPENHO, dimensoes=DIMENSOES_DESEMPENHO,
                  **_contexto_filtros(filtros))


@router.get("/api/desempenho", summary="Análise de desempenho por dimensão")
def api_desempenho(
    request: Request,
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    service = IndicadoresService(usuario.empresa_id)
    metrica, dimensao, min_n = _params_desempenho(request)
    dados = service.desempenho(metrica, dimensao, _filtros(request), min_n)
    return {"success": True, "message": "", "data": dados, "errors": []}


def _params_calendarios(request: Request) -> dict:
    from app.modules.indicadores.constants import (CALENDARIO_DIAS_PADRAO,
                                                   CALENDARIO_INDICADORES,
                                                   CALENDARIO_UNIDADES_MAX)
    q = request.query_params
    escolhidos = [i for i in q.getlist("indicador") if i in CALENDARIO_INDICADORES]

    def _inteiro(nome: str, padrao: int) -> int:
        try:
            return int(q.get(nome, padrao))
        except ValueError:
            return padrao

    return {"indicadores": escolhidos or list(CALENDARIO_INDICADORES),
            # o interruptor "Calendário compacto" manda modo=semana
            "modo": q.get("modo", "mes"),
            "aproximar": q.get("aproximar") == "1",
            "ocorrencias": q.get("ocorrencias") == "1",
            "dias": _inteiro("dias", CALENDARIO_DIAS_PADRAO),
            "unidades": _inteiro("unidades", CALENDARIO_UNIDADES_MAX)}


@router.get("/calendarios", include_in_schema=False)
def calendarios(
    request: Request,
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    from app.modules.indicadores.constants import CALENDARIO_INDICADORES

    service = IndicadoresService(usuario.empresa_id)
    filtros, aplicar = _tela(request, service)
    params = _params_calendarios(request)
    dados = service.calendarios(filtros, **params) if aplicar else None
    return render(request, "indicadores/calendarios.html", usuario,
                  page_title="Calendários de Indicadores", dados=dados,
                  disponiveis=CALENDARIO_INDICADORES, params=params,
                  **_contexto_filtros(filtros))


@router.get("/api/calendarios", summary="Calendário de indicadores por unidade")
def api_calendarios(
    request: Request,
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    service = IndicadoresService(usuario.empresa_id)
    dados = service.calendarios(_filtros(request),
                                **_params_calendarios(request))
    return {"success": True, "message": "", "data": dados, "errors": []}


# ------------------------------------------------------------ correlação

def _params_correlacao(request: Request) -> dict:
    from app.modules.indicadores import correlacao as C

    q = request.query_params
    modo = q.get("modo", "dispersao")
    if modo not in ("dispersao", "matriz", "series"):
        modo = "dispersao"
    x = q.get("x") if q.get("x") in C.METRICAS else "t_central"
    y = q.get("y") if q.get("y") in C.METRICAS else "tempo_resposta"
    metricas = [m for m in q.getlist("metricas") if m in C.METRICAS] \
        or list(C.PADRAO_MATRIZ)
    padrao_dim = "semana" if modo == "series" else "dia"
    dimensao = q.get("dimensao") if q.get("dimensao") in C.DIMENSOES else padrao_dim
    try:
        min_n = max(int(q.get("min_n", "10")), 1)
    except ValueError:
        min_n = 10
    return {"modo": modo, "x": x, "y": y, "metricas": metricas,
            "dimensao": dimensao, "min_n": min_n}


def _correlacao(service, filtros: dict, p: dict) -> dict:
    from app.modules.indicadores import correlacao as C
    from app.modules.indicadores import nucleo

    df = service._filtrar(nucleo.carregar(service.empresa_id), filtros)
    if p["modo"] == "matriz":
        dados = C.matriz(df, p["metricas"], p["dimensao"], p["min_n"])
    elif p["modo"] == "series":
        dados = C.series(df, p["metricas"], p["dimensao"], p["min_n"])
    else:
        dados = C.dispersao(df, p["x"], p["y"], p["dimensao"], p["min_n"])
    return {"modo": p["modo"], "total_filtrado": int(len(df)), **dados}


@router.get("/correlacao", include_in_schema=False)
def correlacao(
    request: Request,
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    from app.modules.indicadores import correlacao as C
    from app.modules.indicadores.service import _json_safe

    service = IndicadoresService(usuario.empresa_id)
    filtros, aplicar = _tela(request, service)
    p = _params_correlacao(request)
    dados = _json_safe(_correlacao(service, filtros, p)) if aplicar else None
    return render(request, "indicadores/correlacao.html", usuario,
                  page_title="Correlação de Indicadores", dados=dados,
                  params=p, metricas=C.METRICAS, dimensoes=C.DIMENSOES,
                  **_contexto_filtros(filtros))


@router.get("/api/correlacao", summary="Correlação entre indicadores")
def api_correlacao(
    request: Request,
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
):
    from app.modules.indicadores.service import _json_safe

    service = IndicadoresService(usuario.empresa_id)
    dados = _correlacao(service, _filtros(request), _params_correlacao(request))
    return {"success": True, "message": "", "data": _json_safe(dados),
            "errors": []}


def _ocorrencias_correlacao(request: Request, usuario):
    from app.modules.indicadores import correlacao as C
    from app.modules.indicadores import drill, nucleo

    q = request.query_params
    dimensao = q.get("dimensao") if q.get("dimensao") in C.DIMENSOES else "dia"
    metrica = q.get("metrica") if q.get("metrica") in C.METRICAS else None
    grupo = q.get("grupo", "")
    service = IndicadoresService(usuario.empresa_id)
    df = service._filtrar(nucleo.carregar(service.empresa_id), _filtros(request))
    rows = C.linhas_do_grupo(df, dimensao, grupo, metrica)
    col = C.coluna_tempo(metrica)
    rotulo = (C.METRICAS[metrica]["rotulo"] + " (mm:ss)") if col else None
    titulo = f"{C.DIMENSOES[dimensao][0]}: {grupo}"
    return rows, col, rotulo, titulo, drill


@router.get("/api/correlacao/ocorrencias", summary="Ocorrências de um grupo")
def api_correlacao_ocorrencias(
    request: Request,
    pagina: int = 1,
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
):
    from app.modules.indicadores.service import _json_safe

    rows, col, rotulo, titulo, drill = _ocorrencias_correlacao(request, usuario)
    dados = drill.pagina(rows, pagina, col, rotulo)
    dados.update({"titulo": "Correlação de indicadores", "recorte": titulo})
    return {"success": True, "message": "", "data": _json_safe(dados), "errors": []}


@router.get("/correlacao/ocorrencias.xlsx", include_in_schema=False)
def correlacao_ocorrencias_xlsx(
    request: Request,
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
):
    from fastapi.responses import Response

    rows, col, rotulo, titulo, drill = _ocorrencias_correlacao(request, usuario)
    return Response(content=drill.planilha(rows, titulo, col, rotulo),
                    media_type="application/vnd.openxmlformats-officedocument."
                               "spreadsheetml.sheet",
                    headers={"Content-Disposition":
                             'attachment; filename="ocorrencias.xlsx"'})


# ------------------------------------------------------------ detalhamento

def _params_detalhe(request: Request) -> tuple[int, int, int | None]:
    q = request.query_params

    def inteiro(nome, padrao=None):
        try:
            return int(q.get(nome))
        except (TypeError, ValueError):
            return padrao
    return inteiro("grafico", -1), inteiro("x", -1), inteiro("s")


@router.get("/api/{tema}/ocorrencias",
            summary="Ocorrências por trás de um ponto de gráfico")
def api_ocorrencias(
    tema: str,
    request: Request,
    pagina: int = 1,
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
):
    from fastapi.responses import JSONResponse

    if tema not in TEMAS:
        return JSONResponse(status_code=404, content={
            "success": False, "message": "Tema desconhecido.", "data": None,
            "errors": ["tema inválido"]})
    grafico, x, s = _params_detalhe(request)
    try:
        dados, _rows, _d = IndicadoresService(usuario.empresa_id).ocorrencias(
            tema, _filtros(request), grafico, x, s, pagina)
    except KeyError as exc:
        return JSONResponse(status_code=400, content={
            "success": False, "message": "Este gráfico não tem detalhamento.",
            "data": None, "errors": [str(exc)]})
    return {"success": True, "message": "", "data": dados, "errors": []}


@router.get("/{tema}/ocorrencias.xlsx", include_in_schema=False)
def ocorrencias_xlsx(
    tema: str,
    request: Request,
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
):
    from fastapi.responses import Response

    from app.modules.indicadores import drill

    if tema not in TEMAS:
        return RedirectResponse("/indicadores/", status_code=303)
    grafico, x, s = _params_detalhe(request)
    try:
        dados, rows, d = IndicadoresService(usuario.empresa_id).ocorrencias(
            tema, _filtros(request), grafico, x, s)
    except KeyError:
        return RedirectResponse(f"/indicadores/{tema}", status_code=303)
    metrica = d.get("metrica")
    from app.modules.indicadores.service import ROTULO_TEMPO
    conteudo = drill.planilha(
        rows, f"{dados['titulo']} — {dados['recorte']}", metrica,
        (ROTULO_TEMPO.get(metrica, "Tempo") + " (mm:ss)") if metrica else None)
    return Response(content=conteudo,
                    media_type="application/vnd.openxmlformats-officedocument."
                               "spreadsheetml.sheet",
                    headers={"Content-Disposition":
                             f'attachment; filename="{tema}-ocorrencias.xlsx"'})


@router.get("/api/{tema}", summary="Dados de um dashboard de indicadores")
def api_tema(
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
def dashboard(
    tema: str,
    request: Request,
    usuario: Usuario = Depends(require_permission("indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    if tema not in TEMAS:
        return RedirectResponse("/indicadores/", status_code=303)
    service = IndicadoresService(usuario.empresa_id)
    filtros, aplicar = _tela(request, service)
    dados = service.dashboard(tema, filtros) if aplicar else None
    titulo, icone, descricao = TEMAS[tema]
    return render(request, "indicadores/dashboard.html", usuario,
                  page_title=titulo, dados=dados, tema=tema, temas=TEMAS,
                  meta_tema={"titulo": titulo, "icone": icone,
                             "descricao": descricao},
                  **_contexto_filtros(filtros))
