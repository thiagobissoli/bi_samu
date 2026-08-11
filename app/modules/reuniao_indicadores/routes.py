"""Endpoints do módulo Reunião de Indicadores (§35.2)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.database import get_session
from app.core.templating import render
from app.models import Usuario
from app.modules.reuniao_indicadores.service import ReuniaoIndicadoresService

router = APIRouter(prefix="/reuniao_indicadores",
                   tags=["Reunião de Indicadores"])


@router.get("/", include_in_schema=False)
def apresentacao(
    request: Request,
    usuario: Usuario = Depends(require_permission("reuniao_indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    deck = ReuniaoIndicadoresService(usuario.empresa_id).montar()
    return render(request, "reuniao_indicadores/apresentacao.html", usuario,
                  page_title="Reunião de Indicadores", deck=deck)


@router.get("/api", summary="Deck da Reunião de Indicadores")
def api(
    usuario: Usuario = Depends(require_permission("reuniao_indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    deck = ReuniaoIndicadoresService(usuario.empresa_id).montar()
    return {"success": True, "message": "", "data": deck, "errors": []}


DRILL_LIMITE = 300


def _tempo_resposta_mmss(registro) -> str | None:
    """Chegada no local − abertura, em mm:ss (nulo se ausente/inválido)."""
    from datetime import datetime

    from app.modules.download_vsky.constants import DATA_HORA_FMT
    try:
        abertura = datetime.strptime(registro.data_ocorrencia, DATA_HORA_FMT)
        chegada = datetime.strptime(registro.chegada_no_local, DATA_HORA_FMT)
    except (TypeError, ValueError):
        return None
    segundos = (chegada - abertura).total_seconds()
    if not 0 < segundos < 10800:
        return None
    return f"{int(segundos) // 60:02d}:{int(segundos) % 60:02d}"


@router.get("/drill", summary="Ocorrências que compõem um elemento de gráfico")
def drill(
    chave: str,
    usuario: Usuario = Depends(require_permission("reuniao_indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    from sqlalchemy import select

    from app.modules.download_vsky.models import VskyRegistroAnalitico as R

    ids = ReuniaoIndicadoresService(usuario.empresa_id).ids_drill(chave)
    linhas = []
    if ids:
        registros = db.scalars(
            select(R).where(R.id.in_(ids[:DRILL_LIMITE]))
            .order_by(R.data_ocorrencia_dt)).all()
        linhas = [{
            "id": r.id,
            "ocorrencia": r.ocorrencia,
            "data": r.data_ocorrencia,
            "tr": _tempo_resposta_mmss(r),
            "cidade": r.cidade,
            "bairro": r.bairro,
            "unidade": r.unidade,
            "codigo": r.codigo_da_ocorrencia,
            "risco": r.risco_inicial,
            "situacao": r.situacao_atendimento,
            "motivo": r.motivo,
        } for r in registros]
    return {"success": True, "message": "",
            "data": {"total": len(ids), "exibidos": len(linhas),
                     "ocorrencias": linhas}, "errors": []}


@router.get("/ocorrencia", summary="Detalhe completo de uma ocorrência")
def ocorrencia(
    id: int,
    usuario: Usuario = Depends(require_permission("reuniao_indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    from sqlalchemy import select

    from app.modules.download_vsky.constants import COLUNAS
    from app.modules.download_vsky.models import VskyRegistroAnalitico as R

    registro = db.scalar(select(R).where(
        R.id == id, R.empresa_id == usuario.empresa_id,
        R.deleted_at.is_(None)))
    if registro is None:
        return {"success": False, "message": "Ocorrência não encontrada.",
                "data": None, "errors": ["id inválido"]}

    campos = [{"rotulo": titulo, "valor": getattr(registro, slug) or None}
              for slug, titulo in COLUNAS]
    campos.insert(1, {"rotulo": "Tempo Resposta (este empenho)",
                      "valor": _tempo_resposta_mmss(registro)})

    # Demais empenhos (viaturas) da mesma ocorrência
    empenhos = []
    if registro.ocorrencia:
        irmaos = db.scalars(
            select(R).where(R.ocorrencia == registro.ocorrencia,
                            R.empresa_id == usuario.empresa_id,
                            R.deleted_at.is_(None))
            .order_by(R.chegada_no_local)).all()
        empenhos = [{"id": r.id, "atual": r.id == registro.id,
                     "unidade": r.unidade, "veiculo": r.veiculo,
                     "chegada": r.chegada_no_local,
                     "tr": _tempo_resposta_mmss(r)} for r in irmaos]

    return {"success": True, "message": "",
            "data": {"id": registro.id, "ocorrencia": registro.ocorrencia,
                     "campos": campos, "empenhos": empenhos}, "errors": []}


@router.get("/prontuario", summary="Baixa o PDF do prontuário da ocorrência")
def prontuario(
    id: int,
    usuario: Usuario = Depends(require_permission("reuniao_indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    from urllib.parse import quote

    from fastapi.responses import JSONResponse
    from sqlalchemy import select

    from app.modules.download_vsky.models import VskyRegistroAnalitico as R
    from app.modules.download_vsky.service import obter_prontuario

    registro = db.scalar(select(R).where(
        R.id == id, R.empresa_id == usuario.empresa_id,
        R.deleted_at.is_(None)))
    if registro is None or not registro.ocorrencia:
        return JSONResponse(status_code=404, content={
            "success": False, "message": "Ocorrência não encontrada.",
            "data": None, "errors": ["id inválido"]})
    try:
        caminho = obter_prontuario(db, usuario.empresa_id, registro.ocorrencia)
    except ValueError as exc:
        return JSONResponse(status_code=502, content={
            "success": False, "message": str(exc), "data": None,
            "errors": [str(exc)]})
    return FileResponse(
        caminho, media_type="application/pdf",
        filename=f"prontuario_{registro.ocorrencia}.pdf",
        headers={"Content-Disposition":
                 f'inline; filename="prontuario_{quote(registro.ocorrencia)}.pdf"'})
