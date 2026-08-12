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
                     "indicadores": _indicadores_da_ocorrencia(
                         usuario.empresa_id, registro.id),
                     "campos": campos, "empenhos": empenhos,
                     "prontuario": prontuario}, "errors": []}


def _mmss(segundos) -> str | None:
    """Segundos -> mm:ss (None quando ausente)."""
    import pandas as pd

    if segundos is None or pd.isna(segundos):
        return None
    s = int(round(float(segundos)))
    return f"{s // 60:02d}:{s % 60:02d}"


def _indicadores_da_ocorrencia(empresa_id: int, registro_id: int) -> list[dict]:
    """Indicadores calculados deste empenho, direto do núcleo.

    Reaproveita as derivações já feitas para os dashboards (P1–P9, tempo
    de central e de resposta, assertividade, NEWS, plantão) — assim o
    modal mostra exatamente os mesmos números dos gráficos, sem recálculo
    paralelo. Cada item traz `situacao` (ok/alerta/ruim/neutro) para o
    template colorir.
    """
    import pandas as pd

    from app.modules.indicadores import nucleo
    from app.modules.indicadores.constants import (ADEQUACAO, CAP_TEMPO,
                                                   SLA_P1, SLA_P2_POR_COR)

    df = nucleo.carregar(empresa_id)
    linha = df[df["id"] == registro_id]
    if linha.empty:
        return []
    r = linha.iloc[0]
    itens: list[dict] = []

    def add(rotulo, valor, sub="", situacao="neutro"):
        itens.append({"rotulo": rotulo, "valor": valor or "—",
                      "sub": sub, "situacao": situacao})

    def tempo(col, rotulo, sub="", limite=None):
        v = r.get(col)
        cap = CAP_TEMPO.get(col, 14400)
        if pd.isna(v) or not (0 < float(v) < cap):
            add(rotulo, None, sub or "sem registro válido")
            return
        situacao = "neutro"
        if limite:
            situacao = "ok" if float(v) <= limite else "ruim"
            sub = (sub + " · " if sub else "") + f"meta {_mmss(limite)}"
        add(rotulo, _mmss(v), sub, situacao)

    # --- tempos do fluxo (mesmas definições dos dashboards) ---
    cor = r.get("codigo_cor")
    tempo("t_central", "Tempo de Central", "controlador − abertura")
    tempo("t_p1", "P1 · Atendimento TARM", "TARM − abertura", SLA_P1)
    tempo("t_p2", "P2 · Regulação médica", "regulador − TARM",
          SLA_P2_POR_COR.get(cor))
    tempo("t_p3", "P3 · Despacho", "controlador − regulador")
    tempo("t_p4", "P4 · Tempo de chegada", "chegada − controlador")
    tempo("t_p4_1", "P4.1 · Saída de base", "início desloc. − controlador",
          120)
    tempo("t_p4_2", "P4.2 · Deslocamento", "chegada − início desloc.")
    tempo("t_p5_6_7", "P5-7 · Tempo de cena", "saída p/ hospital − chegada")
    tempo("t_p8", "P8 · Transporte", "chegada hospital − saída p/ hospital")
    tempo("t_p9", "P9 · Transf. de cuidados", "encerrado − chegada hospital")

    tr = r.get("tempo_resposta")
    if pd.isna(tr):
        add("Tempo de Resposta", None,
            "outra viatura chegou antes nesta ocorrência")
    elif not (0 < float(tr) < CAP_TEMPO.get("tempo_resposta", 14400)):
        add("Tempo de Resposta", None, "fora da faixa de validade")
    else:
        add("Tempo de Resposta", _mmss(tr), "chegada − abertura · 1ª unidade")

    # --- classificações ---
    from app.modules.indicadores.service import ROTULO_COR
    risco = r.get("risco_cor")
    if cor in ADEQUACAO and not pd.isna(risco):
        ok = risco in ADEQUACAO[cor]
        add("Assertividade", "Adequado" if ok else "Inadequado",
            f"código {ROTULO_COR.get(cor, cor)} × triagem "
            f"{ROTULO_COR.get(risco, risco)}", "ok" if ok else "ruim")
    news = r.get("news_total")
    if not pd.isna(news):
        banda = r.get("news_risco")
        add("NEWS modificada", f"{int(news)} · {banda}",
            "FR+FC+PAS+Glasgow aferidos",
            {"Alto": "ruim", "Médio": "alerta",
             "Baixo-Médio": "alerta"}.get(banda, "ok"))
    add("Plantão", r.get("plantao"), r.get("semana_iso") or "")
    add("Tipo de unidade", r.get("recurso"), r.get("unidade_curta") or "")
    perfil = [nome for chave, nome in
              (("iscmv", "ISCMV"), ("convenio", "Convênio"))
              if bool(r.get(chave))]
    add("Perfil", " · ".join(perfil) if perfil else "Fora do recorte", "")
    if bool(r.get("obito_constatado")):
        add("Óbito", "Constatado", "", "ruim")
    return itens


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
