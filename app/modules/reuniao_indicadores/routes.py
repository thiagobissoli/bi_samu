"""Endpoints do módulo Reunião de Indicadores (§35.2)."""

import pandas as pd
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.database import get_session
from app.core.templating import render
from app.models import Usuario
from app.modules.indicadores.ocorrencia import indicadores_da_ocorrencia
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
    from app.modules.indicadores import nucleo

    ids = ReuniaoIndicadoresService(usuario.empresa_id).ids_drill(chave)
    linhas = []
    if ids:
        # Os tempos vêm do núcleo (mesma fonte dos gráficos e dos
        # indicadores do modal) — nada é recalculado aqui.
        df = nucleo.carregar(usuario.empresa_id)
        sel = df[df["id"].isin(ids[:DRILL_LIMITE])].sort_values("dt_ocorr")

        def mm(valor):
            """mm:ss do valor medido; None só quando não há marcação.

            Sem teto de validade: ele tira o valor das médias dos painéis,
            mas o tempo continua sendo o que aconteceu — e é justamente a
            linha extrema que interessa a quem abre a lista para investigar.
            """
            if valor is None or pd.isna(valor) or float(valor) <= 0:
                return None
            return _mmss(valor)

        for _, r in sel.iterrows():
            data = r["dt_ocorr"]
            linhas.append({
                "id": int(r["id"]),
                "ocorrencia": r["ocorrencia"],
                "data": None if pd.isna(data)
                        else data.strftime("%d/%m/%Y %H:%M"),
                "cidade": _texto(r["cidade"]),
                "motivo": _texto(r["motivo"]),
                "unidade": _texto(r["unidade_curta"]) or _texto(r["unidade"]),
                "codigo": _texto(r["codigo_da_ocorrencia"]),
                "tr": mm(r["tempo_resposta"]),
                "p2": mm(r["t_p2"]),
                "p3": mm(r["t_p3"]),
                "p4_1": mm(r["t_p4_1"]),
                "p4_2": mm(r["t_p4_2"]),
            })
    return {"success": True, "message": "",
            "data": {"total": len(ids), "exibidos": len(linhas),
                     "ocorrencias": linhas}, "errors": []}


def _texto(valor) -> str | None:
    """Valor de célula do DataFrame como texto (NaN vira None)."""
    return None if valor is None or pd.isna(valor) else str(valor)


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

    # Prontuário já baixado do vSky (registro criado no download)
    from app.modules.download_vsky.models import VskyProntuario
    pront = db.scalar(select(VskyProntuario).where(
        VskyProntuario.empresa_id == usuario.empresa_id,
        VskyProntuario.ocorrencia == registro.ocorrencia,
        VskyProntuario.deleted_at.is_(None))) if registro.ocorrencia else None
    prontuario = None
    if pront is not None:
        prontuario = {
            "baixado_em": pront.baixado_em.strftime("%d/%m/%Y %H:%M")
                          if pront.baixado_em else None,
            "tamanho_kb": round(pront.tamanho / 1024),
            "paginas": pront.paginas,
            "texto": pront.texto,
        }

    return {"success": True, "message": "",
            "data": {"id": registro.id, "ocorrencia": registro.ocorrencia,
                     "indicadores": indicadores_da_ocorrencia(
                         usuario.empresa_id, registro.id),
                     "campos": campos, "empenhos": empenhos,
                     "prontuario": prontuario}, "errors": []}


def _mmss(segundos) -> str | None:
    """Segundos -> mm:ss (None quando ausente)."""
    from app.modules.indicadores.ocorrencia import mmss
    return mmss(segundos)


@router.get("/investigar", summary="Prepara a ocorrência para investigação")
def investigar(
    id: int,
    usuario: Usuario = Depends(require_permission("reuniao_indicadores.visualizar")),
    db: Session = Depends(get_session),
):
    """Garante o PDF do prontuário e devolve o destino da investigação.

    O botão do modal chama isto antes de abrir a tela de investigação: sem a
    ficha em PDF a análise fica cega à evolução clínica. Se o download falhar
    (portal fora do ar, credencial vencida) a investigação ainda é oferecida,
    com o aviso do que faltou — melhor investigar sem o PDF do que não
    investigar.
    """
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

    numero = str(registro.ocorrencia).strip()
    destino = f"/investigacao/?ocorrencia={quote(numero)}"
    try:
        caminho = obter_prontuario(db, usuario.empresa_id, numero)
        aviso, baixado = None, caminho.is_file()
    except ValueError as exc:
        aviso, baixado = str(exc), False
    return {"success": True, "message": aviso or "", "errors": [],
            "data": {"ocorrencia": numero, "prontuario": baixado,
                     "aviso": aviso, "destino": destino}}


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
