"""Endpoints do módulo NCPS (§35.2).

Páginas públicas (sem login): formulário de notificação anônima e
consulta de andamento por protocolo + código. As demais exigem login e
as permissões `ncps.*` (ver permissions.py).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import date
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth import require_permission
from app.core.config_service import get_config, set_config
from app.core.database import get_session, utcnow
from app.core.middleware import LoginRateLimiter
from app.core.pagination import paginate
from app.core.templating import render, templates
from app.models import Usuario
from app.modules.ncps import constants as cat
from app.modules.ncps import service
from app.modules.ncps.models import (Ncps, NcpsGestor, NcpsGhe, NcpsLocal,
                                     NcpsOcupacional, NcpsPerigo, NcpsSetor)
from app.modules.ncps.permissions import (naturezas_triagem, pode_tratar,
                                          pode_triar, pode_ver)

router = APIRouter(prefix="/ncps", tags=["NCPS"])

# zip nos templates: monta as opções (id, rótulo) dos selects a partir de listas
templates.env.filters.setdefault("zip", lambda a, b: list(zip(a, b)))

# Formulário público e consulta por código: sem login, então com limite por IP
# (evita spam de notificações e tentativa de adivinhar códigos)
_limite_envio = LoginRateLimiter(max_attempts=10, window_seconds=600)
_limite_consulta = LoginRateLimiter(max_attempts=10, window_seconds=300)

# Empresa das páginas públicas (o formulário não tem login para saber qual)
EMPRESA_PUBLICA = 1
CONFIG_TOKEN_POWERBI = "ncps_powerbi_token_hash"

CADASTROS = {"gestores": (NcpsGestor, "Gestor"), "locais": (NcpsLocal, "Local")}


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _redirecionar(url: str, **params) -> RedirectResponse:
    params = {k: v for k, v in params.items() if v}
    sufixo = ("&" if "?" in url else "?") + urlencode(params) if params else ""
    return RedirectResponse(url + sufixo, status_code=303)


def _contexto_form(db: Session, empresa_id: int) -> dict:
    return {"cat": cat, "ghes": service.ghes(db, empresa_id)}


# ================================================================== públicas

@router.get("/publico", include_in_schema=False)
def publico(request: Request, db: Session = Depends(get_session)):
    """Formulário público: qualquer pessoa notifica, sempre de forma anônima."""
    return render(request, "ncps/publico.html", None,
                  **_contexto_form(db, EMPRESA_PUBLICA), dados={}, erros={},
                  enviada=None)


@router.post("/publico", include_in_schema=False)
async def publico_enviar(request: Request, db: Session = Depends(get_session)):
    form = await request.form()
    ctx = _contexto_form(db, EMPRESA_PUBLICA)
    if _limite_envio.blocked(_ip(request)):
        return render(request, "ncps/publico.html", None, **ctx, dados=form,
                      erros={"geral": "Muitas notificações enviadas deste "
                             "endereço. Aguarde alguns minutos."},
                      enviada=None)
    erros = service.validar_notificacao(form)
    if erros:
        return render(request, "ncps/publico.html", None, **ctx, dados=form,
                      erros=erros, enviada=None)
    _limite_envio.register(_ip(request))
    n, codigo = service.registrar(db, EMPRESA_PUBLICA, form, usuario=None)
    record_audit(db, tabela="ncps", acao="INSERT", registro_id=n.id,
                 valor_novo={"natureza": n.natureza, "publico": True},
                 request=request)
    # Mostrado uma única vez, direto na resposta (sem ir para a URL)
    return render(request, "ncps/publico.html", None, **ctx, dados={},
                  erros={}, enviada={"id": n.id, "codigo": codigo})


@router.get("/acompanhar", include_in_schema=False)
def acompanhar(request: Request):
    return render(request, "ncps/acompanhar.html", None, ncp=None, erro=None,
                  protocolo="", cat=cat)


@router.post("/acompanhar", include_in_schema=False)
async def acompanhar_consultar(request: Request,
                               db: Session = Depends(get_session)):
    """Consulta por protocolo + código. É POST para o código não ir à URL."""
    form = await request.form()
    protocolo = (form.get("protocolo") or "").strip()
    if _limite_consulta.blocked(_ip(request)):
        return render(request, "ncps/acompanhar.html", None, ncp=None,
                      protocolo=protocolo, cat=cat,
                      erro="Muitas consultas seguidas. Aguarde alguns minutos.")
    n = service.buscar_acompanhamento(db, EMPRESA_PUBLICA, protocolo,
                                      form.get("codigo"))
    if n is None:
        _limite_consulta.register(_ip(request))
    return render(request, "ncps/acompanhar.html", None, ncp=n, cat=cat,
                  protocolo=protocolo,
                  tz=service.fuso(db, EMPRESA_PUBLICA).key,
                  erro=None if n else "Notificação não encontrada. Confira o "
                  "protocolo e o código de acompanhamento.")


# ================================================================== notificar (logado)

@router.get("/notificar", include_in_schema=False)
def notificar(
    request: Request,
    usuario: Usuario = Depends(require_permission("ncps.notificar")),
    db: Session = Depends(get_session),
):
    return _tela_notificar(request, db, usuario, dados={}, erros={},
                           enviada=None)


@router.post("/notificar", include_in_schema=False)
async def notificar_enviar(
    request: Request,
    usuario: Usuario = Depends(require_permission("ncps.notificar")),
    db: Session = Depends(get_session),
):
    form = await request.form()
    erros = service.validar_notificacao(form)
    if erros:
        return _tela_notificar(request, db, usuario, dados=form, erros=erros,
                               enviada=None)
    n, codigo = service.registrar(db, usuario.empresa_id, form, usuario)
    record_audit(db, tabela="ncps", acao="INSERT", registro_id=n.id,
                 valor_novo={"natureza": n.natureza, "anonima": n.anonima},
                 usuario=None if n.anonima else usuario, request=request)
    return _tela_notificar(request, db, usuario, dados={}, erros={},
                           enviada={"id": n.id, "codigo": codigo})


def _tela_notificar(request, db, usuario, **ctx):
    minhas = list(db.scalars(select(Ncps).where(
        Ncps.notificante_id == usuario.id, Ncps.deleted_at.is_(None),
        Ncps.empresa_id == usuario.empresa_id,
    ).order_by(Ncps.id.desc()).limit(50)))
    return render(request, "ncps/notificar.html", usuario,
                  page_title="Notificar evento (NCPS)", minhas=minhas,
                  **_contexto_form(db, usuario.empresa_id), **ctx)


# ================================================================== gestão

@router.get("/", include_in_schema=False)
def index(
    request: Request,
    page: int = 1,
    usuario: Usuario = Depends(require_permission("ncps.listar")),
    db: Session = Depends(get_session),
):
    filtros = service.filtros_da_requisicao(request.query_params)
    pg = paginate(db, service.consulta(db, usuario, filtros), page, 25)
    qs = "&" + urlencode({k: ("1" if v is True else v)
                          for k, v in filtros.items() if v})
    return render(
        request, "ncps/index.html", usuario, page_title="NCPS", pg=pg,
        qs=qs if len(qs) > 1 else "", filtros=filtros, cat=cat, hoje=date.today(),
        gestores=service.cadastro(db, NcpsGestor, usuario.empresa_id, so_ativos=False),
        locais=service.cadastro(db, NcpsLocal, usuario.empresa_id, so_ativos=False),
        triagem=naturezas_triagem(usuario.permissoes),
        atrasadas=service.acoes_atrasadas,
        msg=request.query_params.get("msg"), erro=request.query_params.get("erro"))


@router.get("/exportar", include_in_schema=False)
def exportar(
    request: Request,
    usuario: Usuario = Depends(require_permission("ncps.exportar")),
    db: Session = Depends(get_session),
):
    filtros = service.filtros_da_requisicao(request.query_params)
    conteudo = service.gerar_planilha(db, usuario, filtros)
    record_audit(db, tabela="ncps", acao="EXPORT", registro_id=0,
                 valor_novo={k: v for k, v in filtros.items() if v},
                 usuario=usuario, request=request)
    nome = f"ncps_{date.today().isoformat()}.xlsx"
    return Response(
        content=conteudo,
        media_type="application/vnd.openxmlformats-officedocument."
                   "spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'})


@router.get("/painel", include_in_schema=False)
def painel(
    request: Request,
    usuario: Usuario = Depends(require_permission("ncps.listar")),
    db: Session = Depends(get_session),
):
    filtros = service.filtros_da_requisicao(request.query_params)
    return render(
        request, "ncps/painel.html", usuario, page_title="Indicadores NCPS",
        ind=service.indicadores(db, usuario, filtros), filtros=filtros, cat=cat,
        qs=urlencode({k: v for k, v in filtros.items() if v and v is not True}),
        gestores=service.cadastro(db, NcpsGestor, usuario.empresa_id, so_ativos=False),
        locais=service.cadastro(db, NcpsLocal, usuario.empresa_id, so_ativos=False))


@router.get("/api/indicadores", summary="Indicadores das NCPS visíveis ao usuário")
def api_indicadores(
    request: Request,
    usuario: Usuario = Depends(require_permission("ncps.listar")),
    db: Session = Depends(get_session),
):
    filtros = service.filtros_da_requisicao(request.query_params)
    return {"success": True, "message": "",
            "data": service.indicadores(db, usuario, filtros), "errors": []}


@router.get("/api/powerbi", summary="Notificações para o Power BI (token)")
def api_powerbi(request: Request, db: Session = Depends(get_session)):
    """Fonte de dados do Power BI.

    Autentica pelo header `Authorization: Bearer <token>` (gerado em
    Cadastros NCPS). Devolve todas as notificações, **nunca as sigilosas**,
    com as mesmas colunas da planilha.
    """
    cabecalho = request.headers.get("authorization", "")
    token = cabecalho[7:].strip() if cabecalho.lower().startswith("bearer ") else ""
    esperado = get_config(db, CONFIG_TOKEN_POWERBI, empresa_id=EMPRESA_PUBLICA)
    recebido = hashlib.sha256(token.encode()).hexdigest()
    if not token or not esperado or not hmac.compare_digest(recebido, esperado):
        return JSONResponse(status_code=401, content={
            "success": False, "message": "Token inválido.", "data": None,
            "errors": ["não autorizado"]})
    zona = service.fuso(db, EMPRESA_PUBLICA)
    lista = db.scalars(select(Ncps).where(
        Ncps.empresa_id == EMPRESA_PUBLICA, Ncps.deleted_at.is_(None),
        Ncps.confidencial.is_(False)).order_by(Ncps.id))
    linhas = []
    for n in lista:
        linha = service.linha_exportacao(n, zona)
        linhas.append({k: (v.isoformat() if hasattr(v, "isoformat") else v)
                       for k, v in linha.items()})
    return {"success": True, "message": "", "data": linhas, "errors": []}


# ------------------------------------------------------------------ análise

def _carregar(db: Session, usuario: Usuario, ncps_id: int) -> Ncps:
    n = service.obter(db, usuario.empresa_id, ncps_id)
    if n is None or not pode_ver(n, usuario):
        # não revela a existência de notificações fora do alcance do perfil
        raise HTTPException(status_code=404, detail="Notificação não encontrada.")
    return n


@router.get("/{ncps_id:int}", include_in_schema=False)
def analise(
    request: Request,
    ncps_id: int,
    usuario: Usuario = Depends(require_permission("ncps.listar")),
    db: Session = Depends(get_session),
):
    n = _carregar(db, usuario, ncps_id)
    emp = usuario.empresa_id
    return render(
        request, "ncps/analise.html", usuario, page_title=f"NCPS #{n.id}",
        n=n, cat=cat, hoje=date.today(),
        pode_triar=pode_triar(n, usuario), pode_tratar=pode_tratar(n, usuario),
        ghes=service.ghes(db, emp, n.ghe_id),
        perigos=service.perigos(db, emp, n.ocupacional.perigo_id
                                if n.ocupacional else None),
        gestores=service.cadastro(db, NcpsGestor, emp, n.gestor_id),
        locais=service.cadastro(db, NcpsLocal, emp, n.local_id),
        setores=service.setores(db, emp, n.setor_id),
        legado=service.dados_legados(n),
        tem_vsky=_ocorrencia_no_vsky(db, emp, n.id_ocorrencia),
        msg=request.query_params.get("msg"), erro=request.query_params.get("erro"))


def _ocorrencia_no_vsky(db: Session, empresa_id: int, ocorrencia) -> bool:
    """A ocorrência informada existe nos dados importados do vSky?"""
    if not ocorrencia:
        return False
    try:
        from app.modules.download_vsky.models import VskyRegistroAnalitico as R
    except ImportError:
        return False
    return db.scalar(select(R.id).where(
        R.empresa_id == empresa_id,
        R.ocorrencia == str(ocorrencia).strip()).limit(1)) is not None


@router.post("/{ncps_id:int}", include_in_schema=False)
async def analise_salvar(
    request: Request,
    ncps_id: int,
    usuario: Usuario = Depends(require_permission("ncps.listar")),
    db: Session = Depends(get_session),
):
    form = await request.form()
    n = _carregar(db, usuario, ncps_id)
    secao = form.get("secao", "")
    antes = {"status": n.status, "setor_id": n.setor_id,
             "natureza": n.natureza}
    try:
        aba = service.salvar_secao(db, n, secao, form, usuario)
    except service.NcpsProibido as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.NcpsErro as exc:
        db.rollback()
        return _redirecionar(f"/ncps/{n.id}", erro=str(exc))
    record_audit(db, tabela="ncps", acao="UPDATE", registro_id=n.id,
                 valor_anterior=antes,
                 valor_novo={"secao": secao, "status": n.status,
                             "setor_id": n.setor_id,
                             "natureza": n.natureza},
                 usuario=usuario, request=request)
    return RedirectResponse(
        f"/ncps/{n.id}?msg={quote('Alterações salvas.')}#{aba}", status_code=303)


@router.post("/{ncps_id:int}/excluir", include_in_schema=False)
def excluir(
    request: Request,
    ncps_id: int,
    usuario: Usuario = Depends(require_permission("ncps.listar")),
    db: Session = Depends(get_session),
):
    n = _carregar(db, usuario, ncps_id)
    try:
        service.excluir(db, n, usuario)
    except service.NcpsProibido as exc:
        return _redirecionar(f"/ncps/{n.id}", erro=str(exc))
    record_audit(db, tabela="ncps", acao="DELETE", registro_id=n.id,
                 usuario=usuario, request=request)
    return _redirecionar("/ncps/", msg=f"NCPS #{n.id} excluída.")


# ================================================================== cadastros

@router.get("/cadastros", include_in_schema=False)
def cadastros(
    request: Request,
    usuario: Usuario = Depends(require_permission("ncps.cadastros")),
    db: Session = Depends(get_session),
):
    return _tela_cadastros(request, db, usuario)


def _tela_cadastros(request, db, usuario, token_novo=None):
    emp = usuario.empresa_id
    usos = {
        "gestores": _usos(db, Ncps.gestor_id, emp),
        "locais": _usos(db, Ncps.local_id, emp),
    }
    return render(
        request, "ncps/cadastros.html", usuario, page_title="Cadastros NCPS",
        listas={t: service.cadastro(db, m, emp, so_ativos=False)
                for t, (m, _r) in CADASTROS.items()},
        usos=usos, setores=service.setores(db, emp, so_ativos=False),
        analistas=service.analistas(db, emp),
        usos_setor=_usos(db, Ncps.setor_id, emp),
        token_configurado=bool(get_config(
            db, CONFIG_TOKEN_POWERBI, empresa_id=EMPRESA_PUBLICA)),
        token_novo=token_novo, msg=request.query_params.get("msg"),
        erro=request.query_params.get("erro"))


def _usos(db: Session, coluna, empresa_id: int) -> dict[int, int]:
    from sqlalchemy import func

    return dict(db.execute(select(coluna, func.count()).where(
        coluna.isnot(None), Ncps.empresa_id == empresa_id,
        Ncps.deleted_at.is_(None)).group_by(coluna)).all())


@router.post("/cadastros/{tipo}", include_in_schema=False)
async def cadastro_salvar(
    request: Request,
    tipo: str,
    usuario: Usuario = Depends(require_permission("ncps.cadastros")),
    db: Session = Depends(get_session),
):
    """Cria, renomeia, ativa/desativa ou exclui um gestor ou local."""
    if tipo not in CADASTROS:
        raise HTTPException(status_code=404)
    modelo, rotulo = CADASTROS[tipo]
    form = await request.form()
    acao = form.get("acao", "salvar")
    nome = (form.get("nome") or "").strip()[:120]
    item_id = service._inteiro(form, "id")
    item = db.scalar(select(modelo).where(
        modelo.id == item_id, modelo.empresa_id == usuario.empresa_id,
        modelo.deleted_at.is_(None))) if item_id else None

    if acao == "excluir" and item:
        coluna = Ncps.gestor_id if tipo == "gestores" else Ncps.local_id
        if _usos(db, coluna, usuario.empresa_id).get(item.id):
            return _redirecionar("/ncps/cadastros", erro=f"{rotulo} "
                                 f"\"{item.nome}\" é usado em notificações; "
                                 "desative-o em vez de excluir.")
        item.deleted_at, item.deleted_by = utcnow(), usuario.id
        msg = f"{rotulo} \"{item.nome}\" excluído."
    elif acao == "alternar" and item:
        item.ativo = not item.ativo
        msg = f"{rotulo} \"{item.nome}\" {'ativado' if item.ativo else 'desativado'}."
    elif nome:
        if item is None:
            item = modelo(empresa_id=usuario.empresa_id, created_by=usuario.id)
            db.add(item)
        item.nome = nome
        item.updated_by = usuario.id
        msg = f"{rotulo} \"{nome}\" salvo."
    else:
        return _redirecionar("/ncps/cadastros", erro="Informe o nome.")
    db.commit()
    record_audit(db, tabela=modelo.__tablename__, acao="UPDATE",
                 registro_id=item.id, valor_novo={"acao": acao, "nome": item.nome},
                 usuario=usuario, request=request)
    return _redirecionar("/ncps/cadastros", msg=msg)


@router.post("/setores", include_in_schema=False)
async def setor_salvar(
    request: Request,
    usuario: Usuario = Depends(require_permission("ncps.cadastros")),
    db: Session = Depends(get_session),
):
    """Cria, renomeia, ativa/desativa ou exclui um setor e define quem
    analisa por ele (usuários com ncps.coordenar)."""
    from app.models import Usuario as U

    form = await request.form()
    acao = form.get("acao", "salvar")
    emp = usuario.empresa_id
    setor_id = service._inteiro(form, "id")
    setor = db.scalar(select(NcpsSetor).where(
        NcpsSetor.id == setor_id, NcpsSetor.empresa_id == emp,
        NcpsSetor.deleted_at.is_(None))) if setor_id else None
    nome = (form.get("nome") or "").strip()[:120]

    if acao == "excluir" and setor:
        if _usos(db, Ncps.setor_id, emp).get(setor.id):
            return _redirecionar("/ncps/cadastros", erro=f"O setor \"{setor.nome}\" "
                                 "tem NCPS encaminhadas; desative-o em vez de excluir.")
        setor.deleted_at, setor.deleted_by = utcnow(), usuario.id
        setor.usuarios = []
        msg = f"Setor \"{setor.nome}\" excluído."
    elif acao == "alternar" and setor:
        setor.ativo = not setor.ativo
        msg = f"Setor \"{setor.nome}\" {'ativado' if setor.ativo else 'desativado'}."
    elif nome:
        if setor is None:
            setor = NcpsSetor(empresa_id=emp, created_by=usuario.id)
            db.add(setor)
        setor.nome = nome
        setor.updated_by = usuario.id
        # só quem tem permissão de analisar pode ser vinculado
        validos = {u.id for u in service.analistas(db, emp)}
        ids = [int(x) for x in form.getlist("usuarios") if str(x).isdigit()]
        setor.usuarios = list(db.scalars(select(U).where(
            U.id.in_([i for i in ids if i in validos])))) if ids else []
        msg = f"Setor \"{nome}\" salvo com {len(setor.usuarios)} analista(s)."
    else:
        return _redirecionar("/ncps/cadastros", erro="Informe o nome do setor.")
    db.commit()
    record_audit(db, tabela="ncps_setores", acao="UPDATE", registro_id=setor.id,
                 valor_novo={"acao": acao, "nome": setor.nome,
                             "usuarios": [u.id for u in setor.usuarios]},
                 usuario=usuario, request=request)
    return _redirecionar("/ncps/cadastros", msg=msg)


@router.post("/cadastros-token", include_in_schema=False)
def gerar_token_powerbi(
    request: Request,
    usuario: Usuario = Depends(require_permission("ncps.cadastros")),
    db: Session = Depends(get_session),
):
    """Gera um novo token do Power BI (o anterior deixa de valer).

    Guarda-se só o hash; o token aparece uma única vez nesta resposta.
    """
    token = secrets.token_urlsafe(32)
    set_config(db, CONFIG_TOKEN_POWERBI, hashlib.sha256(token.encode()).hexdigest(),
               EMPRESA_PUBLICA, usuario.id)
    record_audit(db, tabela="configuracoes", acao="UPDATE", registro_id=0,
                 valor_novo={"chave": CONFIG_TOKEN_POWERBI}, usuario=usuario,
                 request=request)
    return _tela_cadastros(request, db, usuario, token_novo=token)


# ================================================================== PGR

@router.get("/pgr", include_in_schema=False)
def pgr(
    request: Request,
    usuario: Usuario = Depends(require_permission("ncps.pgr")),
    db: Session = Depends(get_session),
):
    from sqlalchemy import func

    emp = usuario.empresa_id
    service.garantir_catalogo_pgr(db, emp)
    usos_ghe = _usos(db, Ncps.ghe_id, emp)
    usos_perigo = dict(db.execute(select(NcpsOcupacional.perigo_id, func.count())
                                  .where(NcpsOcupacional.perigo_id.isnot(None),
                                         NcpsOcupacional.empresa_id == emp)
                                  .group_by(NcpsOcupacional.perigo_id)).all())
    ghes = list(db.scalars(select(NcpsGhe).where(
        NcpsGhe.empresa_id == emp, NcpsGhe.deleted_at.is_(None)
    ).order_by(NcpsGhe.codigo)))
    perigos = list(db.scalars(select(NcpsPerigo).where(
        NcpsPerigo.empresa_id == emp, NcpsPerigo.deleted_at.is_(None)
    ).order_by(NcpsPerigo.grupo, NcpsPerigo.nome)))
    editar_tipo = request.query_params.get("editar")
    editar_id = request.query_params.get("id")
    editando = None
    if editar_tipo in ("ghe", "perigo") and editar_id and editar_id.isdigit():
        lista = ghes if editar_tipo == "ghe" else perigos
        editando = next((x for x in lista if x.id == int(editar_id)), None)
    return render(
        request, "ncps/pgr.html", usuario, page_title="PGR — GHE e perigos",
        ghes=ghes, perigos=perigos, usos_ghe=usos_ghe, usos_perigo=usos_perigo,
        cat=cat, editar_tipo=editar_tipo if editando else None,
        editando=editando, msg=request.query_params.get("msg"),
        erro=request.query_params.get("erro"))


@router.post("/pgr/{tipo}", include_in_schema=False)
async def pgr_salvar(
    request: Request,
    tipo: str,
    usuario: Usuario = Depends(require_permission("ncps.pgr")),
    db: Session = Depends(get_session),
):
    """Cria/edita/exclui GHE ou perigo.

    Itens já usados em notificações não são excluídos — só desativados,
    para preservar o histórico (a NR-1 exige manter o do inventário).
    """
    from sqlalchemy import func

    if tipo not in ("ghe", "perigo"):
        raise HTTPException(status_code=404)
    modelo = NcpsGhe if tipo == "ghe" else NcpsPerigo
    form = await request.form()
    emp = usuario.empresa_id
    item_id = service._inteiro(form, "id")
    item = db.scalar(select(modelo).where(
        modelo.id == item_id, modelo.empresa_id == emp,
        modelo.deleted_at.is_(None))) if item_id else None

    if form.get("acao") == "excluir" and item:
        if tipo == "ghe":
            usado = _usos(db, Ncps.ghe_id, emp).get(item.id)
        else:
            usado = db.scalar(select(func.count()).select_from(NcpsOcupacional)
                              .where(NcpsOcupacional.perigo_id == item.id))
        if usado:
            return _redirecionar("/ncps/pgr", erro=f"\"{item.nome}\" é usado em "
                                 "notificações; desative-o em vez de excluir.")
        item.deleted_at, item.deleted_by = utcnow(), usuario.id
        db.commit()
        return _redirecionar("/ncps/pgr", msg=f"\"{item.nome}\" excluído.")

    nome = (form.get("nome") or "").strip()
    if tipo == "ghe":
        codigo = (form.get("codigo") or "").strip()[:10]
        if not (codigo and nome):
            return _redirecionar("/ncps/pgr", erro="Informe o código e o nome do GHE.")
        repetido = db.scalar(select(NcpsGhe).where(
            NcpsGhe.empresa_id == emp, NcpsGhe.codigo == codigo,
            NcpsGhe.deleted_at.is_(None), NcpsGhe.id != (item.id if item else 0)))
        if repetido:
            return _redirecionar("/ncps/pgr", erro=f"Já existe o GHE {codigo} "
                                 f"({repetido.nome}).")
    else:
        grupo = form.get("grupo")
        if grupo not in cat.GRUPO_RISCO or not nome:
            return _redirecionar("/ncps/pgr", erro="Informe o grupo e o perigo.")

    if item is None:
        item = modelo(empresa_id=emp, created_by=usuario.id)
        db.add(item)
    item.nome = nome[:150 if tipo == "perigo" else 100]
    item.ativo = bool(form.get("ativo"))
    item.updated_by = usuario.id
    if tipo == "ghe":
        item.codigo = codigo
        item.cargos = (form.get("cargos") or "").strip() or None
    else:
        item.grupo = grupo
        item.fonte = (form.get("fonte") or "").strip()[:255] or None
        item.dano = (form.get("dano") or "").strip()[:255] or None
    db.commit()
    record_audit(db, tabela=modelo.__tablename__, acao="UPDATE",
                 registro_id=item.id, valor_novo={"nome": item.nome,
                                                  "ativo": item.ativo},
                 usuario=usuario, request=request)
    return _redirecionar("/ncps/pgr", msg=f"\"{item.nome}\" salvo.")

