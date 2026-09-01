"""Endpoints do módulo Download vSky (§35.2).

Rotas protegidas por permissão (§9) e auditadas (§11).
Nenhuma rota acessa o banco diretamente — sempre via Service (§35.3).
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.audit import record_audit, snapshot
from app.core.auth import require_permission
from app.core.config_service import get_config, set_config
from app.core.database import get_session
from app.core.pagination import paginate
from app.core.templating import render
from app.models import Usuario
from app.modules.download_vsky.constants import (
    AUTO_INTERVALO_MINIMO,
    COLUNAS,
    CONFIG_AUTO_ATIVO,
    CONFIG_AUTO_DIAS,
    CONFIG_AUTO_HORA,
    CONFIG_AUTO_INTERVALO,
    CONFIG_AUTO_MODO,
    CONFIG_AUTO_STATUS,
    CONFIG_AUTO_ULTIMA,
    CONFIG_BASE_URL,
    CONFIG_CLIENTE_ID,
    CONFIG_SENHA,
    CONFIG_USUARIO,
    DEFAULT_BASE_URL,
    STATUS_CONCLUIDO,
    STATUS_LABELS,
)
from app.modules.download_vsky.schemas import ImportacaoCreate, ImportacaoRead
from app.modules.download_vsky.service import DownloadVskyService, absolute_path
from app.modules.download_vsky.validators import data_iso_para_br, normalizar_base_url

router = APIRouter(prefix="/download_vsky", tags=["Download vSky"])


@router.on_event("startup")
def _iniciar_download_automatico() -> None:
    """Restaura o agendamento salvo quando o servidor sobe."""
    from app.modules.download_vsky import scheduler
    try:
        scheduler.sincronizar()
    except Exception:  # noqa: BLE001 — agendador não pode impedir o boot
        import logging
        logging.getLogger("download_vsky.auto").exception(
            "Falha ao iniciar o download automático")

FIELDS = ["data_inicial", "data_final", "status", "total_linhas",
          "linhas_novas", "linhas_superadas", "linhas_duplicadas",
          "tamanho", "erro"]


def _credenciais(db: Session, empresa_id: int) -> dict | None:
    usuario = get_config(db, CONFIG_USUARIO, empresa_id=empresa_id)
    senha = get_config(db, CONFIG_SENHA, empresa_id=empresa_id)
    if not usuario or not senha:
        return None
    return {
        "base_url": get_config(db, CONFIG_BASE_URL, DEFAULT_BASE_URL,
                               empresa_id=empresa_id),
        "usuario_vsky": usuario,
        "senha_vsky": senha,
        "cliente_id": get_config(db, CONFIG_CLIENTE_ID, empresa_id=empresa_id) or None,
    }


@router.get("/", include_in_schema=False)
def index(
    request: Request,
    q: str | None = None,
    page: int = 1,
    msg: str | None = None,
    erro: str | None = None,
    usuario: Usuario = Depends(require_permission("download_vsky.listar")),
    db: Session = Depends(get_session),
):
    service = DownloadVskyService(db, usuario.empresa_id)
    pg = paginate(db, service.query(q), page)
    configurado = _credenciais(db, usuario.empresa_id) is not None
    return render(request, "download_vsky/index.html", usuario,
                  page_title="Download vSky", pg=pg, q=q or "", qs=f"&q={q or ''}",
                  msg=msg, erro=erro, configurado=configurado,
                  total_registros=service.total_registros(),
                  calendario=service.calendario_cobertura(),
                  status_labels=STATUS_LABELS, status_concluido=STATUS_CONCLUIDO)


@router.post("/importar", include_in_schema=False)
def importar(
    request: Request,
    data_inicial: str = Form(...),
    data_final: str = Form(...),
    usuario: Usuario = Depends(require_permission("download_vsky.baixar")),
    db: Session = Depends(get_session),
):
    credenciais = _credenciais(db, usuario.empresa_id)
    if credenciais is None:
        return RedirectResponse(
            "/download_vsky/?erro=" + quote(
                "Configure usuário e senha do vSky antes de importar."),
            status_code=303)

    service = DownloadVskyService(db, usuario.empresa_id)
    try:
        item = service.importar_periodo(
            data_iso_para_br(data_inicial), data_iso_para_br(data_final),
            created_by=usuario.id, **credenciais)
    except ValueError as exc:
        return RedirectResponse("/download_vsky/?erro=" + quote(str(exc)),
                                status_code=303)

    record_audit(db, tabela="vsky_importacoes", acao="IMPORT", registro_id=item.id,
                 valor_novo=snapshot(item, FIELDS), usuario=usuario, request=request)
    if item.status == STATUS_CONCLUIDO:
        return RedirectResponse(
            "/download_vsky/?msg=" + quote(
                f"Importação concluída: {item.linhas_novas} novas, "
                f"{item.linhas_superadas} atualizadas, "
                f"{item.linhas_duplicadas} duplicadas de "
                f"{item.total_linhas} linhas."),
            status_code=303)
    return RedirectResponse(
        "/download_vsky/?erro=" + quote(f"Falha na importação: {item.erro}"),
        status_code=303)


@router.post("/substituir", include_in_schema=False)
def substituir(
    request: Request,
    data_inicial: str = Form(...),
    data_final: str = Form(...),
    usuario: Usuario = Depends(require_permission("download_vsky.baixar")),
    db: Session = Depends(get_session),
):
    """Apaga o período e o reinsere com o que o vSky tem agora.

    Serve para o que a importação normal não alcança: registro que o portal
    apagou continuaria na base, porque a reconciliação só toca as chaves que
    o arquivo traz.
    """
    credenciais = _credenciais(db, usuario.empresa_id)
    if credenciais is None:
        return RedirectResponse(
            "/download_vsky/?erro=" + quote(
                "Configure usuário e senha do vSky antes de importar."),
            status_code=303)

    service = DownloadVskyService(db, usuario.empresa_id)
    try:
        item = service.substituir_periodo(
            data_iso_para_br(data_inicial), data_iso_para_br(data_final),
            created_by=usuario.id, **credenciais)
    except ValueError as exc:
        return RedirectResponse("/download_vsky/?erro=" + quote(str(exc)),
                                status_code=303)

    record_audit(db, tabela="vsky_importacoes", acao="REPLACE",
                 registro_id=item.id, valor_novo=snapshot(item, FIELDS),
                 usuario=usuario, request=request)
    if item.status == STATUS_CONCLUIDO:
        return RedirectResponse(
            "/download_vsky/?msg=" + quote(
                f"Período substituído: {item.linhas_superadas} registros "
                f"apagados e {item.linhas_novas} inseridos de "
                f"{item.total_linhas} linhas do vSky."),
            status_code=303)
    return RedirectResponse(
        "/download_vsky/?erro=" + quote(
            f"Falha ao substituir (nada foi apagado): {item.erro}"),
        status_code=303)


@router.get("/registros", include_in_schema=False)
def registros(
    request: Request,
    q: str | None = None,
    page: int = 1,
    usuario: Usuario = Depends(require_permission("download_vsky.listar")),
    db: Session = Depends(get_session),
):
    service = DownloadVskyService(db, usuario.empresa_id)
    pg = paginate(db, service.query_registros(q), page)
    return render(request, "download_vsky/registros.html", usuario,
                  page_title="Registros vSky", pg=pg, q=q or "", qs=f"&q={q or ''}",
                  colunas=COLUNAS)


@router.get("/{item_id}/arquivo", include_in_schema=False)
def arquivo(
    item_id: int,
    usuario: Usuario = Depends(require_permission("download_vsky.listar")),
    db: Session = Depends(get_session),
):
    service = DownloadVskyService(db, usuario.empresa_id)
    item = service.get(item_id)
    if item is None or not item.caminho:
        return RedirectResponse("/download_vsky/", status_code=303)
    path = absolute_path(item)
    if not path.is_file():
        return RedirectResponse("/download_vsky/", status_code=303)
    nome = f"registros_analitico_{item.data_inicial}_{item.data_final}.xls".replace("/", "-")
    return FileResponse(path, filename=nome, media_type="application/vnd.ms-excel")


@router.post("/{item_id}/delete", include_in_schema=False)
def delete(
    request: Request,
    item_id: int,
    usuario: Usuario = Depends(require_permission("download_vsky.excluir")),
    db: Session = Depends(get_session),
):
    service = DownloadVskyService(db, usuario.empresa_id)
    item = service.get(item_id)
    if item is not None:
        antes = snapshot(item, FIELDS)
        service.delete(item_id)
        record_audit(db, tabela="vsky_importacoes", acao="DELETE", registro_id=item_id,
                     valor_anterior=antes, usuario=usuario, request=request)
    return RedirectResponse("/download_vsky/", status_code=303)


@router.get("/config", include_in_schema=False)
def config_form(
    request: Request,
    erro: str | None = None,
    usuario: Usuario = Depends(require_permission("download_vsky.configurar")),
    db: Session = Depends(get_session),
):
    from app.modules.download_vsky import scheduler
    emp = usuario.empresa_id
    return render(request, "download_vsky/config.html", usuario,
                  page_title="Configuração vSky", erro=erro,
                  base_url=get_config(db, CONFIG_BASE_URL, DEFAULT_BASE_URL,
                                      empresa_id=emp),
                  usuario_vsky=get_config(db, CONFIG_USUARIO, empresa_id=emp) or "",
                  cliente_id=get_config(db, CONFIG_CLIENTE_ID, empresa_id=emp) or "",
                  senha_definida=bool(get_config(db, CONFIG_SENHA, empresa_id=emp)),
                  auto_ativo=get_config(db, CONFIG_AUTO_ATIVO, empresa_id=emp) == "1",
                  auto_modo=get_config(db, CONFIG_AUTO_MODO, "diario", emp),
                  auto_hora=get_config(db, CONFIG_AUTO_HORA, "06:00", emp),
                  auto_intervalo=get_config(db, CONFIG_AUTO_INTERVALO, "60", emp),
                  auto_dias=get_config(db, CONFIG_AUTO_DIAS, "2", emp),
                  auto_ultima=get_config(db, CONFIG_AUTO_ULTIMA, empresa_id=emp),
                  auto_status=get_config(db, CONFIG_AUTO_STATUS, empresa_id=emp),
                  auto_proxima=scheduler.proxima_execucao(),
                  auto_intervalo_minimo=AUTO_INTERVALO_MINIMO)


@router.post("/config", include_in_schema=False)
def config_save(
    request: Request,
    base_url: str = Form(""),
    usuario_vsky: str = Form(""),
    senha_vsky: str = Form(""),
    cliente_id: str = Form(""),
    auto_ativo: str = Form(""),
    auto_modo: str = Form("diario"),
    auto_hora: str = Form("06:00"),
    auto_intervalo: str = Form("60"),
    auto_dias: str = Form("2"),
    usuario: Usuario = Depends(require_permission("download_vsky.configurar")),
    db: Session = Depends(get_session),
):
    try:
        base_url_limpa = normalizar_base_url(base_url) or DEFAULT_BASE_URL
    except ValueError as exc:
        return RedirectResponse("/download_vsky/config?erro=" + quote(str(exc)),
                                status_code=303)
    emp, uid = usuario.empresa_id, usuario.id
    set_config(db, CONFIG_BASE_URL, base_url_limpa, empresa_id=emp, updated_by=uid)
    set_config(db, CONFIG_USUARIO, usuario_vsky.strip() or None,
               empresa_id=emp, updated_by=uid)
    set_config(db, CONFIG_CLIENTE_ID, cliente_id.strip() or None,
               empresa_id=emp, updated_by=uid)
    if senha_vsky.strip():  # em branco = mantém a senha atual
        set_config(db, CONFIG_SENHA, senha_vsky.strip(),
                   empresa_id=emp, updated_by=uid)

    # --- download automático -------------------------------------------
    set_config(db, CONFIG_AUTO_ATIVO, "1" if auto_ativo else None,
               empresa_id=emp, updated_by=uid)
    set_config(db, CONFIG_AUTO_MODO,
               "intervalo" if auto_modo == "intervalo" else "diario",
               empresa_id=emp, updated_by=uid)
    set_config(db, CONFIG_AUTO_HORA, auto_hora.strip() or "06:00",
               empresa_id=emp, updated_by=uid)
    set_config(db, CONFIG_AUTO_INTERVALO,
               str(max(int(auto_intervalo or 60), AUTO_INTERVALO_MINIMO)),
               empresa_id=emp, updated_by=uid)
    set_config(db, CONFIG_AUTO_DIAS, str(max(int(auto_dias or 2), 1)),
               empresa_id=emp, updated_by=uid)

    from app.modules.download_vsky import scheduler
    agendamento = scheduler.sincronizar(emp)

    record_audit(db, tabela="configuracoes", acao="UPDATE",
                 valor_novo={"vsky_base_url": base_url_limpa,
                             "vsky_usuario": usuario_vsky.strip(),
                             "download_automatico": agendamento or "desativado"},
                 usuario=usuario, request=request)
    msg = "Configuração do vSky salva."
    if agendamento:
        msg += f" Download automático {agendamento}."
    return RedirectResponse(
        "/download_vsky/?msg=" + quote(msg), status_code=303)


# --- API REST (formato padrão §17) ---

@router.get("/api", summary="Listar importações vSky")
def api_list(
    q: str | None = None,
    usuario: Usuario = Depends(require_permission("download_vsky.listar")),
    db: Session = Depends(get_session),
):
    service = DownloadVskyService(db, usuario.empresa_id)
    data = [ImportacaoRead.model_validate(i).model_dump()
            for i in service.importacoes.list(q)]
    return {"success": True, "message": "", "data": data, "errors": []}


@router.post("/api", summary="Importar período do vSky", status_code=201)
def api_importar(
    payload: ImportacaoCreate,
    usuario: Usuario = Depends(require_permission("download_vsky.baixar")),
    db: Session = Depends(get_session),
):
    credenciais = _credenciais(db, usuario.empresa_id)
    if credenciais is None:
        return JSONResponse(status_code=400, content={
            "success": False, "message": "Credenciais do vSky não configuradas.",
            "data": None, "errors": ["vsky_usuario/vsky_senha ausentes"]})

    service = DownloadVskyService(db, usuario.empresa_id)
    try:
        item = service.importar_periodo(
            data_iso_para_br(payload.data_inicial),
            data_iso_para_br(payload.data_final),
            created_by=usuario.id, **credenciais)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "success": False, "message": str(exc), "data": None, "errors": [str(exc)]})

    record_audit(db, tabela="vsky_importacoes", acao="IMPORT", registro_id=item.id,
                 valor_novo=snapshot(item, FIELDS), usuario=usuario)
    ok = item.status == STATUS_CONCLUIDO
    return JSONResponse(status_code=201 if ok else 502, content={
        "success": ok,
        "message": "Importação concluída." if ok else f"Falha: {item.erro}",
        "data": ImportacaoRead.model_validate(item).model_dump(),
        "errors": [] if ok else [item.erro],
    })
