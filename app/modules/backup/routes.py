"""Endpoints do módulo Backup (§35.2)."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth import require_permission
from app.core.config_service import get_config, set_config
from app.core.database import get_session
from app.core.templating import render
from app.models import Usuario
from app.modules.backup import scheduler, service
from app.modules.backup.constants import (CONFIG_ATIVO, CONFIG_DIRETORIO,
                                          CONFIG_HORA, CONFIG_MANTER,
                                          CONFIG_STATUS, CONFIG_ULTIMA,
                                          MANTER_PADRAO)

router = APIRouter(prefix="/backup", tags=["Backup"])


@router.on_event("startup")
def _agendar() -> None:
    """Restaura o agendamento ao subir a aplicação."""
    try:
        scheduler.sincronizar()
    except Exception:  # noqa: BLE001 — não impedir o start
        import logging
        logging.getLogger("backup").exception("Falha ao agendar o backup")


def _contexto(db: Session, emp: int, **extra) -> dict:
    return {
        "ativo": get_config(db, CONFIG_ATIVO, empresa_id=emp) == "1",
        "hora": get_config(db, CONFIG_HORA, "02:00", emp),
        "manter": get_config(db, CONFIG_MANTER, str(MANTER_PADRAO), emp),
        "diretorio": str(service.diretorio(db, emp)),
        "status": get_config(db, CONFIG_STATUS, empresa_id=emp),
        "ultima": get_config(db, CONFIG_ULTIMA, empresa_id=emp),
        "proxima": scheduler.proxima_execucao(),
        "copias": service.listar(db, emp),
        **extra,
    }


@router.get("/", include_in_schema=False)
def index(
    request: Request,
    usuario: Usuario = Depends(require_permission("backup.visualizar")),
    db: Session = Depends(get_session),
):
    return render(request, "backup/index.html", usuario,
                  page_title="Backup do banco",
                  **_contexto(db, usuario.empresa_id, erro=None, ok=None))


@router.post("/config", include_in_schema=False)
def salvar_config(
    request: Request,
    ativo: bool = Form(False),
    hora: str = Form("02:00"),
    manter: str = Form(str(MANTER_PADRAO)),
    diretorio: str = Form(""),
    usuario: Usuario = Depends(require_permission("backup.executar")),
    db: Session = Depends(get_session),
):
    emp, uid = usuario.empresa_id, usuario.id
    set_config(db, CONFIG_ATIVO, "1" if ativo else None, emp, uid)
    set_config(db, CONFIG_HORA, hora.strip() or "02:00", emp, uid)
    try:
        quantas = max(int(manter), 1)
    except ValueError:
        quantas = MANTER_PADRAO
    set_config(db, CONFIG_MANTER, str(quantas), emp, uid)
    set_config(db, CONFIG_DIRETORIO, diretorio.strip() or None, emp, uid)
    scheduler.sincronizar(emp)
    record_audit(db, tabela="configuracoes", acao="UPDATE", registro_id=0,
                 valor_novo={"backup_ativo": ativo, "backup_hora": hora,
                             "backup_manter": quantas},
                 usuario=usuario, request=request)
    return RedirectResponse("/backup/", status_code=303)


@router.post("/executar", include_in_schema=False)
def executar_agora(
    request: Request,
    usuario: Usuario = Depends(require_permission("backup.executar")),
    db: Session = Depends(get_session),
):
    """Gera uma cópia imediatamente."""
    emp = usuario.empresa_id
    try:
        arquivo = service.executar(db, emp)
        tamanho = arquivo.stat().st_size / 1024 / 1024
        mensagem = f"Cópia gerada: {arquivo.name} ({tamanho:.1f} MB)."
        erro = None
        set_config(db, CONFIG_STATUS, f"sucesso — {arquivo.name} "
                   f"({tamanho:.1f} MB)", emp, usuario.id)
    except service.BackupError as exc:
        mensagem, erro = None, str(exc)
        set_config(db, CONFIG_STATUS, f"erro: {exc}"[:500], emp, usuario.id)
    from datetime import datetime
    set_config(db, CONFIG_ULTIMA, datetime.now().strftime("%d/%m/%Y %H:%M"),
               emp, usuario.id)
    record_audit(db, tabela="backup", acao="INSERT", registro_id=0,
                 valor_novo={"manual": True, "erro": erro},
                 usuario=usuario, request=request)
    return render(request, "backup/index.html", usuario,
                  page_title="Backup do banco",
                  **_contexto(db, emp, erro=erro, ok=mensagem))


@router.get("/baixar", include_in_schema=False)
def baixar(
    nome: str,
    usuario: Usuario = Depends(require_permission("backup.executar")),
    db: Session = Depends(get_session),
):
    """Baixa uma cópia. O nome é resolvido dentro da pasta de backups."""
    from fastapi.responses import JSONResponse
    try:
        caminho = service.caminho_seguro(db, usuario.empresa_id, nome)
    except service.BackupError as exc:
        return JSONResponse(status_code=404, content={
            "success": False, "message": str(exc), "data": None,
            "errors": [str(exc)]})
    return FileResponse(caminho, media_type="application/gzip",
                        filename=caminho.name)


@router.get("/api", summary="Situação das cópias de segurança")
def api(
    usuario: Usuario = Depends(require_permission("backup.visualizar")),
    db: Session = Depends(get_session),
):
    emp = usuario.empresa_id
    copias = service.listar(db, emp)
    return {"success": True, "message": "", "data": {
        "ativo": get_config(db, CONFIG_ATIVO, empresa_id=emp) == "1",
        "ultima": get_config(db, CONFIG_ULTIMA, empresa_id=emp),
        "status": get_config(db, CONFIG_STATUS, empresa_id=emp),
        "proxima": scheduler.proxima_execucao(),
        "total": len(copias), "copias": copias}, "errors": []}
