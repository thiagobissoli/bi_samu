"""Endpoints do módulo Investigação de Eventos (§35.2).

Somente leitura: o módulo analisa os registros já importados (núcleo do
módulo indicadores) e não persiste nada.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core import ia
from app.core.audit import record_audit
from app.core.auth import require_permission
from app.core.config_service import get_config, set_config
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

    dossie = service.dossie(db, p["ocorrencia"]) if p["ocorrencia"] else None
    investigacao = dossie["investigacao"] if dossie else None
    # Investigar uma ocorrência posiciona a timeline no dia dela
    if investigacao and not investigacao.get("erro") and not p["dia"]:
        dia = investigacao["dia"]

    return render(
        request, "investigacao/index.html", usuario,
        page_title="Investigação de Eventos",
        timeline=service.timeline_dia(dia, p["municipios"], p["unidades"]),
        cruzamentos=service.cruzamentos(dia),
        investigacao=investigacao, dossie=dossie,
        ia_config=ia.configuracao(db, usuario.empresa_id),
        erro_ia=request.query_params.get("erro_ia"),
        opcoes=opcoes, filtros={**p, "dia": dia})


@router.post("/analisar", include_in_schema=False)
def analisar(
    request: Request,
    ocorrencia: str = Form(...),
    incluir_prontuario: bool = Form(False),
    anonimizar: bool = Form(False),
    usuario: Usuario = Depends(require_permission("investigacao.visualizar")),
    db: Session = Depends(get_session),
):
    """Dispara a análise por IA (Londres + Ishikawa + matriz de risco)."""
    from urllib.parse import urlencode

    from app.modules.investigacao.ia_analise import analisar as rodar_analise

    service = InvestigacaoService(usuario.empresa_id)
    dossie = service.dossie(db, ocorrencia.strip())
    inv = dossie["investigacao"]
    destino = {"ocorrencia": ocorrencia.strip()}

    if inv.get("erro"):
        destino["erro_ia"] = inv["erro"]
        return RedirectResponse(f"/investigacao/?{urlencode(destino)}",
                                status_code=303)

    texto = ""
    if incluir_prontuario:
        try:                       # baixa do vSky se ainda não houver
            from app.modules.download_vsky.service import obter_prontuario
            obter_prontuario(db, usuario.empresa_id, ocorrencia.strip())
            dossie = service.dossie(db, ocorrencia.strip())
        except ValueError as exc:
            destino["erro_ia"] = f"Prontuário indisponível: {exc}"
            return RedirectResponse(f"/investigacao/?{urlencode(destino)}",
                                    status_code=303)
        texto = (dossie.get("prontuario") or {}).get("texto") or ""

    try:
        rodar_analise(db, usuario.empresa_id, dossie, texto,
                      anonimizar=anonimizar,
                      nomes=[inv.get("paciente", "")])
    except ia.IAError as exc:
        destino["erro_ia"] = str(exc)
        return RedirectResponse(f"/investigacao/?{urlencode(destino)}",
                                status_code=303)

    record_audit(db, tabela="investigacao_analises", acao="INSERT",
                 registro_id=0,
                 valor_novo={"ocorrencia": ocorrencia.strip(),
                             "com_prontuario": bool(texto),
                             "anonimizado": bool(anonimizar)},
                 usuario=usuario, request=request)
    return RedirectResponse(f"/investigacao/?{urlencode(destino)}",
                            status_code=303)


@router.get("/prontuario", include_in_schema=False)
def prontuario(
    ocorrencia: str,
    usuario: Usuario = Depends(require_permission("investigacao.visualizar")),
    db: Session = Depends(get_session),
):
    """Baixa (ou serve do cache) o PDF do prontuário e registra o texto."""
    from urllib.parse import quote

    from fastapi.responses import FileResponse, JSONResponse

    from app.modules.download_vsky.service import obter_prontuario

    numero = (ocorrencia or "").strip()
    try:
        caminho = obter_prontuario(db, usuario.empresa_id, numero)
    except ValueError as exc:
        return JSONResponse(status_code=502, content={
            "success": False, "message": str(exc), "data": None,
            "errors": [str(exc)]})
    return FileResponse(
        caminho, media_type="application/pdf",
        filename=f"prontuario_{numero}.pdf",
        headers={"Content-Disposition":
                 f'inline; filename="prontuario_{quote(numero)}.pdf"'})


@router.get("/config", include_in_schema=False)
def config(
    request: Request,
    usuario: Usuario = Depends(require_permission("investigacao.configurar")),
    db: Session = Depends(get_session),
):
    return render(request, "investigacao/config.html", usuario,
                  page_title="Configuração da IA",
                  cfg=ia.configuracao(db, usuario.empresa_id),
                  provedores=ia.PROVEDORES, sugeridos=ia.MODELOS_SUGERIDOS,
                  erro=None, ok=None)


@router.post("/config", include_in_schema=False)
def salvar_config(
    request: Request,
    provedor: str = Form(""),
    modelo: str = Form(""),
    api_key: str = Form(""),
    base_url: str = Form(""),
    testar: str = Form(""),
    usuario: Usuario = Depends(require_permission("investigacao.configurar")),
    db: Session = Depends(get_session),
):
    emp, uid = usuario.empresa_id, usuario.id
    provedor = provedor.strip()
    if provedor and provedor not in ia.PROVEDORES:
        provedor = ""
    set_config(db, ia.CONFIG_PROVEDOR, provedor or None, emp, uid)
    set_config(db, ia.CONFIG_MODELO,
               modelo.strip() or ia.MODELOS_SUGERIDOS.get(provedor), emp, uid)
    set_config(db, ia.CONFIG_BASE_URL,
               base_url.strip() or ia.OLLAMA_PADRAO, emp, uid)
    if api_key.strip():        # em branco = mantém a chave atual
        set_config(db, ia.CONFIG_API_KEY, api_key.strip(), emp, uid)
    record_audit(db, tabela="configuracoes", acao="UPDATE", registro_id=0,
                 valor_novo={"ia_provedor": provedor, "ia_modelo": modelo},
                 usuario=usuario, request=request)

    ok = erro = None
    if testar:
        try:
            resposta = ia.gerar(
                db, "Responda apenas: OK", "Você é um teste de conexão.", emp)
            ok = f"Conexão bem-sucedida. Resposta do modelo: {resposta[:80]}"
        except ia.IAError as exc:
            erro = str(exc)
    return render(request, "investigacao/config.html", usuario,
                  page_title="Configuração da IA",
                  cfg=ia.configuracao(db, emp), provedores=ia.PROVEDORES,
                  sugeridos=ia.MODELOS_SUGERIDOS, erro=erro, ok=ok)


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
