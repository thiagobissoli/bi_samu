"""Endpoints do módulo Painel de Gestão (§35.2)."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth import require_permission
from app.core.config_service import get_config, set_config
from app.core.database import get_session
from app.core.templating import render
from app.models import Usuario
from app.modules.painel_gestao.constants import (
    CONFIG_EMAIL_ATIVO,
    CONFIG_EMAIL_DESTINATARIOS,
    CONFIG_EMAIL_DIA,
    CONFIG_EMAIL_HORA,
    CONFIG_EMAIL_MODO,
    CONFIG_EMAIL_STATUS,
    CONFIG_EMAIL_ULTIMA,
    DIAS_SEMANA_CRON,
)
from app.modules.painel_gestao.service import PainelGestaoService

router = APIRouter(prefix="/painel_gestao", tags=["Painel de Gestão"])


@router.on_event("startup")
def _agendar_envio() -> None:
    """Restaura o agendamento do envio automático ao subir a aplicação."""
    from app.modules.painel_gestao import scheduler
    try:
        scheduler.sincronizar()
    except Exception:  # noqa: BLE001 — não impedir o start da aplicação
        import logging
        logging.getLogger("painel_gestao.email").exception(
            "Falha ao agendar o envio do Relatório de Gestão")


@router.get("/", include_in_schema=False)
def painel(
    request: Request,
    usuario: Usuario = Depends(require_permission("painel_gestao.visualizar")),
    db: Session = Depends(get_session),
):
    dados = PainelGestaoService(usuario.empresa_id).montar()
    return render(request, "painel_gestao/painel.html", usuario,
                  page_title="Painel de Gestão", dados=dados)


@router.get("/relatorio.pdf", include_in_schema=False)
def relatorio_pdf(
    usuario: Usuario = Depends(require_permission("painel_gestao.visualizar")),
    db: Session = Depends(get_session),
):
    """Relatório de Gestão em PDF — mesmo documento do envio automático."""
    from fastapi.responses import JSONResponse, Response

    try:
        from app.modules.painel_gestao.relatorio import gerar_pdf
    except ImportError as exc:
        # Instalação desatualizada (matplotlib/reportlab entraram depois):
        # mensagem acionável em vez de 500 com stack trace.
        return JSONResponse(status_code=503, content={
            "success": False,
            "message": ("Bibliotecas do relatório ausentes nesta instalação "
                        f"({exc.name}). Atualize as dependências: ative o "
                        "ambiente virtual e rode 'pip install -e .' na pasta "
                        "do projeto, depois reinicie o servidor."),
            "data": None, "errors": [str(exc)]})

    dados = PainelGestaoService(usuario.empresa_id).montar()
    pdf = gerar_pdf(dados)
    nome = f"relatorio-gestao-{(dados.get('semana') or 'atual')}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition":
                             f'attachment; filename="{nome}"'})


def _contexto_config(db: Session, emp: int, **extra) -> dict:
    from app.modules.painel_gestao import scheduler
    return {
        "email_ativo": get_config(db, CONFIG_EMAIL_ATIVO, empresa_id=emp) == "1",
        "email_modo": get_config(db, CONFIG_EMAIL_MODO, "semanal", emp),
        "email_dia": get_config(db, CONFIG_EMAIL_DIA, "mon", emp),
        "email_hora": get_config(db, CONFIG_EMAIL_HORA, "07:00", emp),
        "destinatarios": get_config(db, CONFIG_EMAIL_DESTINATARIOS,
                                    empresa_id=emp) or "",
        "status": get_config(db, CONFIG_EMAIL_STATUS, empresa_id=emp),
        "ultima": get_config(db, CONFIG_EMAIL_ULTIMA, empresa_id=emp),
        "proxima": scheduler.proxima_execucao(),
        "smtp_configurado": bool(get_config(db, "smtp_host", empresa_id=emp)),
        "dias": DIAS_SEMANA_CRON,
        **extra,
    }


@router.get("/config", include_in_schema=False)
def config(
    request: Request,
    usuario: Usuario = Depends(require_permission("painel_gestao.configurar")),
    db: Session = Depends(get_session),
):
    return render(request, "painel_gestao/config.html", usuario,
                  page_title="Envio automático do Relatório",
                  **_contexto_config(db, usuario.empresa_id, erro=None, ok=None))


@router.post("/config", include_in_schema=False)
def salvar_config(
    request: Request,
    email_ativo: bool = Form(False),
    email_modo: str = Form("semanal"),
    email_dia: str = Form("mon"),
    email_hora: str = Form("07:00"),
    destinatarios: str = Form(""),
    enviar_agora: str = Form(""),
    usuario: Usuario = Depends(require_permission("painel_gestao.configurar")),
    db: Session = Depends(get_session),
):
    from app.modules.painel_gestao import scheduler

    emp, uid = usuario.empresa_id, usuario.id
    lista = [e.strip() for e in destinatarios.replace(";", ",").split(",")
             if e.strip()]
    invalidos = [e for e in lista if "@" not in e or "." not in e.split("@")[-1]]
    if invalidos:
        return render(request, "painel_gestao/config.html", usuario,
                      page_title="Envio automático do Relatório",
                      **_contexto_config(
                          db, emp, ok=None,
                          erro="E-mail inválido: " + ", ".join(invalidos)))
    if email_ativo and not lista:
        return render(request, "painel_gestao/config.html", usuario,
                      page_title="Envio automático do Relatório",
                      **_contexto_config(
                          db, emp, ok=None,
                          erro="Informe ao menos um destinatário para ativar "
                               "o envio automático."))

    set_config(db, CONFIG_EMAIL_ATIVO, "1" if email_ativo else None, emp, uid)
    set_config(db, CONFIG_EMAIL_MODO,
               "diario" if email_modo == "diario" else "semanal", emp, uid)
    set_config(db, CONFIG_EMAIL_DIA,
               email_dia if email_dia in DIAS_SEMANA_CRON else "mon", emp, uid)
    set_config(db, CONFIG_EMAIL_HORA, email_hora.strip() or "07:00", emp, uid)
    set_config(db, CONFIG_EMAIL_DESTINATARIOS, ", ".join(lista) or None,
               emp, uid)
    record_audit(db, tabela="configuracoes", acao="UPDATE", registro_id=0,
                 valor_novo={"relatorio_email_ativo": email_ativo,
                             "relatorio_email_modo": email_modo,
                             "relatorio_email_destinatarios": ", ".join(lista)},
                 usuario=usuario, request=request)
    scheduler.sincronizar(emp)

    if enviar_agora:
        resultado = scheduler.enviar_relatorio(emp)
        return render(request, "painel_gestao/config.html", usuario,
                      page_title="Envio automático do Relatório",
                      **_contexto_config(db, emp, erro=None,
                                         ok=f"Envio executado: {resultado}"))
    return RedirectResponse("/painel_gestao/config", status_code=303)


@router.get("/api", summary="Indicadores do Painel de Gestão")
def api(
    usuario: Usuario = Depends(require_permission("painel_gestao.visualizar")),
    db: Session = Depends(get_session),
):
    dados = PainelGestaoService(usuario.empresa_id).montar()
    return {"success": True, "message": "", "data": dados, "errors": []}
