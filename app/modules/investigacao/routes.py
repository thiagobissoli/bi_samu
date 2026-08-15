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

    from app.modules.investigacao.constants import (CONSEQUENCIA, GRAVIDADES,
                                                    PROBABILIDADE)

    return render(
        request, "investigacao/index.html", usuario,
        page_title="Investigação de Eventos",
        timeline=service.timeline_dia(dia, p["municipios"], p["unidades"]),
        cruzamentos=service.cruzamentos(dia),
        investigacao=investigacao, dossie=dossie,
        ia_config=ia.configuracao(db, usuario.empresa_id),
        erro_ia=request.query_params.get("erro_ia"),
        # escalas do formulário FOR.SAMU.038, para desenhar a matriz
        probabilidades=PROBABILIDADE, consequencias=CONSEQUENCIA,
        gravidades=GRAVIDADES,
        # time de investigação costuma se repetir entre relatórios
        time_padrao=get_config(db, "rac_time_investigacao",
                               empresa_id=usuario.empresa_id) or "",
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


@router.post("/modelos", include_in_schema=False)
def modelos(
    provedor: str = Form(""),
    api_key: str = Form(""),
    base_url: str = Form(""),
    usuario: Usuario = Depends(require_permission("investigacao.configurar")),
    db: Session = Depends(get_session),
):
    """Modelos disponíveis no provedor, para preencher o dropdown.

    É POST porque a chave pode vir do formulário ainda não salvo — numa
    query string ela acabaria nos logs de acesso.
    """
    from fastapi.responses import JSONResponse

    try:
        lista = ia.listar_modelos(db, usuario.empresa_id, provedor=provedor,
                                  chave=api_key, base_url=base_url)
    except ia.IAError as exc:
        return JSONResponse(status_code=400, content={
            "success": False, "message": str(exc), "data": None,
            "errors": [str(exc)]})
    return {"success": True, "message": "",
            "data": {"modelos": lista, "total": len(lista)}, "errors": []}


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


# ------------------------------------------------ aprovação do relatório

@router.post("/aprovar", include_in_schema=False)
def aprovar(
    request: Request,
    ocorrencia: str = Form(...),
    risco_pos_probabilidade: str = Form(""),
    risco_pos_consequencia: str = Form(""),
    risco_pos_justificativa: str = Form(""),
    notificacao_data: str = Form(""),
    time_investigacao: str = Form(""),
    investigacao_inicio: str = Form(""),
    usuario: Usuario = Depends(require_permission("investigacao.aprovar")),
    db: Session = Depends(get_session),
):
    """Aprova a versão corrente do RAC e guarda o PDF no banco."""
    from datetime import datetime, timezone
    from urllib.parse import urlencode

    from app.modules.investigacao.ia_analise import historico
    from app.modules.investigacao.models import STATUS_APROVADO
    from app.modules.investigacao.rac_pdf import gerar_rac_pdf

    numero = ocorrencia.strip()
    versoes = historico(db, usuario.empresa_id, numero)
    destino = {"ocorrencia": numero}
    if not versoes:
        destino["erro_ia"] = "Não há relatório gerado para aprovar."
        return RedirectResponse(f"/investigacao/?{urlencode(destino)}",
                                status_code=303)

    atual = versoes[0]
    # Risco pós-investigação é decisão da equipe, não estimativa da IA
    def _inteiro(valor, validos):
        try:
            n = int(valor)
        except (TypeError, ValueError):
            return None
        return n if n in validos else None

    atual.risco_pos_probabilidade = _inteiro(risco_pos_probabilidade,
                                             {1, 2, 3, 4, 5})
    atual.risco_pos_consequencia = _inteiro(risco_pos_consequencia,
                                            {1, 2, 4, 8, 16})
    atual.risco_pos_justificativa = risco_pos_justificativa.strip() or None
    # Campos do formulário que só a equipe conhece
    atual.notificacao_data = notificacao_data.strip() or None
    atual.time_investigacao = time_investigacao.strip() or None
    atual.investigacao_inicio = investigacao_inicio.strip() or None
    if time_investigacao.strip():   # reaproveitado nos próximos relatórios
        set_config(db, "rac_time_investigacao", time_investigacao.strip(),
                   usuario.empresa_id, usuario.id)
    atual.status = STATUS_APROVADO
    atual.aprovado_em = datetime.now(timezone.utc)
    atual.aprovado_por = usuario.id
    atual.aprovado_nome = usuario.nome
    db.commit()

    # PDF do documento aprovado — imutável, guardado no próprio banco
    service = InvestigacaoService(usuario.empresa_id)
    dossie = service.dossie(db, numero)
    atual.pdf = gerar_rac_pdf(dossie, logo_path=_logo(db, usuario.empresa_id))
    db.commit()

    record_audit(db, tabela="investigacao_analises", acao="UPDATE",
                 registro_id=atual.id,
                 valor_novo={"ocorrencia": numero, "versao": atual.versao,
                             "status": STATUS_APROVADO}, usuario=usuario,
                 request=request)
    destino["aprovado"] = "1"
    return RedirectResponse(f"/investigacao/?{urlencode(destino)}",
                            status_code=303)


@router.post("/relatos", include_in_schema=False)
def salvar_relatos(
    request: Request,
    ocorrencia: str = Form(...),
    relatos: str = Form(""),
    usuario: Usuario = Depends(require_permission("investigacao.visualizar")),
    db: Session = Depends(get_session),
):
    """Registra os relatos dos envolvidos, colhidos pela equipe.

    Ficam na versão corrente do RAC e passam a alimentar a análise: sem
    eles o Protocolo de Londres fica restrito ao que o registro
    operacional mostra.
    """
    from urllib.parse import urlencode

    from app.modules.investigacao.ia_analise import historico
    from app.modules.investigacao.models import STATUS_APROVADO
    from app.modules.investigacao.rac_pdf import gerar_rac_pdf

    numero = ocorrencia.strip()
    versoes = historico(db, usuario.empresa_id, numero)
    destino = {"ocorrencia": numero}
    if not versoes:
        destino["erro_ia"] = "Gere o relatório antes de registrar os relatos."
        return RedirectResponse(f"/investigacao/?{urlencode(destino)}",
                                status_code=303)

    atual = versoes[0]
    atual.relatos = relatos.strip() or None
    db.commit()

    if atual.status == STATUS_APROVADO and atual.pdf:
        dossie = InvestigacaoService(usuario.empresa_id).dossie(db, numero)
        atual.pdf = gerar_rac_pdf(dossie,
                                  logo_path=_logo(db, usuario.empresa_id))
        db.commit()

    record_audit(db, tabela="investigacao_analises", acao="UPDATE",
                 registro_id=atual.id,
                 valor_novo={"ocorrencia": numero,
                             "relatos_caracteres": len(atual.relatos or "")},
                 usuario=usuario, request=request)
    destino["relatos_salvos"] = "1"
    return RedirectResponse(f"/investigacao/?{urlencode(destino)}",
                            status_code=303)


@router.post("/dados-gerais", include_in_schema=False)
def salvar_dados_gerais(
    request: Request,
    ocorrencia: str = Form(...),
    notificacao_data: str = Form(""),
    time_investigacao: str = Form(""),
    investigacao_inicio: str = Form(""),
    usuario: Usuario = Depends(require_permission("investigacao.visualizar")),
    db: Session = Depends(get_session),
):
    """Edita os campos de DADOS GERAIS que a equipe preenche.

    Vale a qualquer momento, inclusive depois de aprovado: são dados
    administrativos do formulário, não a análise em si. Quando o
    relatório já está aprovado, o PDF guardado é regerado para não ficar
    divergente do que a tela mostra.
    """
    from urllib.parse import urlencode

    from app.modules.investigacao.ia_analise import historico
    from app.modules.investigacao.models import STATUS_APROVADO
    from app.modules.investigacao.rac_pdf import gerar_rac_pdf

    numero = ocorrencia.strip()
    versoes = historico(db, usuario.empresa_id, numero)
    destino = {"ocorrencia": numero}
    if not versoes:
        destino["erro_ia"] = "Não há relatório gerado para editar."
        return RedirectResponse(f"/investigacao/?{urlencode(destino)}",
                                status_code=303)

    atual = versoes[0]
    atual.notificacao_data = notificacao_data.strip() or None
    atual.time_investigacao = time_investigacao.strip() or None
    atual.investigacao_inicio = investigacao_inicio.strip() or None
    if time_investigacao.strip():   # vira padrão dos próximos relatórios
        set_config(db, "rac_time_investigacao", time_investigacao.strip(),
                   usuario.empresa_id, usuario.id)
    db.commit()

    if atual.status == STATUS_APROVADO and atual.pdf:
        dossie = InvestigacaoService(usuario.empresa_id).dossie(db, numero)
        atual.pdf = gerar_rac_pdf(dossie,
                                  logo_path=_logo(db, usuario.empresa_id))
        db.commit()

    record_audit(db, tabela="investigacao_analises", acao="UPDATE",
                 registro_id=atual.id,
                 valor_novo={"ocorrencia": numero,
                             "notificacao_data": atual.notificacao_data,
                             "time_investigacao": atual.time_investigacao,
                             "investigacao_inicio": atual.investigacao_inicio},
                 usuario=usuario, request=request)
    destino["dados_salvos"] = "1"
    return RedirectResponse(f"/investigacao/?{urlencode(destino)}",
                            status_code=303)


@router.post("/ajustar", include_in_schema=False)
def ajustar(
    request: Request,
    ocorrencia: str = Form(...),
    feedback: str = Form(...),
    usuario: Usuario = Depends(require_permission("investigacao.visualizar")),
    db: Session = Depends(get_session),
):
    """Pede ajuste: gera nova versão considerando as anteriores."""
    from urllib.parse import urlencode

    from app.modules.investigacao.ia_analise import analisar as rodar_analise

    numero = ocorrencia.strip()
    destino = {"ocorrencia": numero}
    if not feedback.strip():
        destino["erro_ia"] = "Descreva o que precisa ser ajustado."
        return RedirectResponse(f"/investigacao/?{urlencode(destino)}",
                                status_code=303)

    service = InvestigacaoService(usuario.empresa_id)
    dossie = service.dossie(db, numero)
    if dossie["investigacao"].get("erro"):
        destino["erro_ia"] = dossie["investigacao"]["erro"]
        return RedirectResponse(f"/investigacao/?{urlencode(destino)}",
                                status_code=303)

    texto = ""
    anterior = dossie.get("analise_ia") or {}
    if anterior.get("com_prontuario"):
        texto = (dossie.get("prontuario") or {}).get("texto") or ""
    try:
        rodar_analise(db, usuario.empresa_id, dossie, texto,
                      anonimizar=bool(anterior.get("anonimizado", True)),
                      nomes=[dossie["investigacao"].get("paciente", "")],
                      feedback=feedback.strip())
    except ia.IAError as exc:
        destino["erro_ia"] = str(exc)
    return RedirectResponse(f"/investigacao/?{urlencode(destino)}",
                            status_code=303)


def _logo(db: Session, empresa_id: int) -> str | None:
    """Caminho da logo da empresa, para o cabeçalho do formulário."""
    from app.core.storage import absolute_path
    from app.models import Arquivo

    arquivo_id = get_config(db, "logo_arquivo_id", empresa_id=empresa_id)
    if not arquivo_id:
        return None
    arquivo = db.get(Arquivo, int(arquivo_id))
    if arquivo is None or arquivo.deleted_at is not None:
        return None
    caminho = absolute_path(arquivo)
    return str(caminho) if caminho.is_file() else None


@router.get("/rac.pdf", include_in_schema=False)
def rac_pdf(
    ocorrencia: str,
    versao: int | None = None,
    usuario: Usuario = Depends(require_permission("investigacao.visualizar")),
    db: Session = Depends(get_session),
):
    """PDF do RAC. Versão aprovada vem do banco; as demais são geradas."""
    from fastapi.responses import JSONResponse, Response

    from app.modules.investigacao.ia_analise import historico
    from app.modules.investigacao.rac_pdf import gerar_rac_pdf

    numero = (ocorrencia or "").strip()
    versoes = historico(db, usuario.empresa_id, numero)
    if not versoes:
        return JSONResponse(status_code=404, content={
            "success": False, "message": "Nenhum relatório gerado para esta "
            "ocorrência.", "data": None, "errors": ["sem análise"]})

    alvo = next((v for v in versoes if v.versao == versao), versoes[0])
    if alvo.pdf:                      # aprovado: documento imutável
        conteudo = alvo.pdf
    else:
        service = InvestigacaoService(usuario.empresa_id)
        conteudo = gerar_rac_pdf(service.dossie(db, numero),
                                 logo_path=_logo(db, usuario.empresa_id))
    nome = f"RAC_{numero}_v{alvo.versao}.pdf"
    return Response(content=conteudo, media_type="application/pdf",
                    headers={"Content-Disposition":
                             f'inline; filename="{nome}"'})


@router.get("/relatorios", include_in_schema=False)
def relatorios(
    request: Request,
    usuario: Usuario = Depends(require_permission("investigacao.visualizar")),
    db: Session = Depends(get_session),
):
    """Relatórios RAC gerados no sistema, com status e versões."""
    from sqlalchemy import select

    from app.modules.investigacao.models import AnaliseOcorrencia

    status = request.query_params.get("status", "")
    consulta = select(AnaliseOcorrencia).where(
        AnaliseOcorrencia.empresa_id == usuario.empresa_id,
        AnaliseOcorrencia.deleted_at.is_(None))
    if status:
        consulta = consulta.where(AnaliseOcorrencia.status == status)
    registros = list(db.scalars(
        consulta.order_by(AnaliseOcorrencia.ocorrencia.desc(),
                          AnaliseOcorrencia.versao.desc())))

    import json as _json
    linhas = []
    for r in registros:
        try:
            conteudo = _json.loads(r.resultado)
        except (TypeError, ValueError):
            conteudo = {}
        linhas.append({
            "id": r.id, "ocorrencia": r.ocorrencia, "versao": r.versao,
            "status": r.status,
            "titulo": (conteudo.get("dados_gerais") or {}).get(
                "titulo_investigacao") or "—",
            "gravidade": (conteudo.get("dados_gerais") or {}).get("gravidade"),
            "provedor": r.provedor, "modelo": r.modelo,
            "gerado_em": r.gerado_em.strftime("%d/%m/%Y %H:%M")
                         if r.gerado_em else "",
            "feedback": r.feedback,
            "aprovado_em": r.aprovado_em.strftime("%d/%m/%Y %H:%M")
                           if r.aprovado_em else None,
            "aprovado_nome": r.aprovado_nome,
            "tem_pdf": bool(r.pdf),
        })
    resumo = {
        "total": len(registros),
        "aprovados": sum(1 for x in linhas if x["status"] == "aprovado"),
        "pendentes": sum(1 for x in linhas if x["status"] == "pendente"),
        "ocorrencias": len({x["ocorrencia"] for x in linhas}),
    }
    return render(request, "investigacao/relatorios.html", usuario,
                  page_title="Relatórios RAC", linhas=linhas, resumo=resumo,
                  status=status)
