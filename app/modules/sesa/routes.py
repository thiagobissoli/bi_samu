"""Envios à SESA (§35): matriz anual, certidões e demais documentos mensais.

/sesa/                     matriz do ano (obrigações × meses), como a planilha
/sesa/certidoes            atalho para as certidões da competência atual
/sesa/{chave}/{AAAA-MM}    um envio: arquivos, leitura das certidões, pacote e registro
/sesa/cadastros            prazos, canais, destinatários, links e instruções
"""

from __future__ import annotations

from datetime import date, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth import require_permission
from app.core.config_service import set_config
from app.core.database import get_session
from app.core.export import tz_da_empresa
from app.core.storage import absolute_path
from app.core.templating import render
from app.models import Usuario
from app.modules.sesa import constants as cat
from app.modules.sesa import prazos, service
from app.modules.sesa.models import SesaAnexo, SesaItem, SesaObrigacao

router = APIRouter(prefix="/sesa", tags=["SESA"])


def _hoje(db: Session, empresa_id: int) -> date:
    try:
        return datetime.now(ZoneInfo(tz_da_empresa(db, empresa_id))).date()
    except Exception:  # noqa: BLE001 — fuso inválido na configuração
        return date.today()


def _voltar(chave: str, comp: date, msg: str = "", erro: str = "", ancora: str = ""):
    url = f"/sesa/{chave}/{prazos.chave(comp)}"
    if msg:
        url += f"?msg={quote(msg)}"
    elif erro:
        url += f"?erro={quote(erro)}"
    return RedirectResponse(url + (f"#{ancora}" if ancora else ""), status_code=303)


def _obrigacao(db, usuario, chave) -> SesaObrigacao | None:
    service.garantir_catalogo(db, usuario.empresa_id)
    return service.obrigacao_por_chave(db, usuario.empresa_id, chave)


def _anexo(db, usuario, anexo_id) -> SesaAnexo | None:
    a = db.get(SesaAnexo, anexo_id)
    if a is None or a.deleted_at is not None or a.empresa_id != usuario.empresa_id:
        return None
    return a


# ------------------------------------------------------------------ matriz

@router.get("/", include_in_schema=False)
def index(request: Request, ano: int | None = None,
          usuario: Usuario = Depends(require_permission("sesa.visualizar")),
          db: Session = Depends(get_session)):
    service.garantir_catalogo(db, usuario.empresa_id)
    hoje = _hoje(db, usuario.empresa_id)
    ano = ano if ano and 2000 <= ano <= 2100 else hoje.year
    return render(request, "sesa/index.html", usuario, page_title="Envios à SESA",
                  ano=ano, hoje=hoje, meses=prazos.MESES,
                  linhas=service.matriz_ano(db, usuario.empresa_id, ano, hoje),
                  competencia_atual=prazos.chave(date(hoje.year, hoje.month, 1)),
                  descrever_prazo=prazos.descrever_prazo, periodicidades=cat.PERIODICIDADES)


@router.get("/certidoes", include_in_schema=False)
def certidoes(competencia: str | None = None,
              usuario: Usuario = Depends(require_permission("sesa.visualizar")),
              db: Session = Depends(get_session)):
    comp = prazos.competencia_de(competencia, _hoje(db, usuario.empresa_id))
    return RedirectResponse(f"/sesa/certidoes/{prazos.chave(comp)}", status_code=303)


# ------------------------------------------------------------------ cadastros

@router.get("/cadastros", include_in_schema=False)
def cadastros(request: Request, msg: str = "",
              usuario: Usuario = Depends(require_permission("sesa.cadastros")),
              db: Session = Depends(get_session)):
    service.garantir_catalogo(db, usuario.empresa_id)
    return render(request, "sesa/cadastros.html", usuario, page_title="Cadastros SESA",
                  obrigacoes=service.obrigacoes(db, usuario.empresa_id, so_ativas=False),
                  cnpj=service.cnpj(db, usuario.empresa_id),
                  feriados=", ".join(service.feriados_extras(db, usuario.empresa_id)),
                  periodicidades=cat.PERIODICIDADES, msg=msg)


@router.post("/cadastros/geral", include_in_schema=False)
def cadastros_geral(request: Request, cnpj: str = Form(""), feriados: str = Form(""),
                    usuario: Usuario = Depends(require_permission("sesa.cadastros")),
                    db: Session = Depends(get_session)):
    set_config(db, service.CONFIG_CNPJ, cnpj.strip() or cat.CNPJ_PADRAO,
               usuario.empresa_id, updated_by=usuario.id)
    set_config(db, service.CONFIG_FERIADOS, ", ".join(prazos.ler_extras(feriados)),
               usuario.empresa_id, updated_by=usuario.id)
    record_audit(db, tabela="configuracoes", acao="UPDATE",
                 valor_novo={"sesa_cnpj": cnpj, "sesa_feriados_extras": feriados},
                 usuario=usuario, request=request)
    return RedirectResponse(f"/sesa/cadastros?msg={quote('Dados gerais salvos.')}",
                            status_code=303)


@router.post("/cadastros/obrigacao/{obrigacao_id:int}", include_in_schema=False)
async def cadastros_obrigacao(request: Request, obrigacao_id: int,
                              usuario: Usuario = Depends(require_permission("sesa.cadastros")),
                              db: Session = Depends(get_session)):
    o = db.get(SesaObrigacao, obrigacao_id)
    if o is None or o.empresa_id != usuario.empresa_id:
        return RedirectResponse("/sesa/cadastros", status_code=303)
    form = await request.form()
    antes = {"prazo": f"{o.prazo_tipo}:{o.prazo_dia}", "canal": o.canal,
             "destinatario": o.destinatario, "meses": o.meses, "ativo": o.ativo}
    o.nome = (form.get("nome") or o.nome).strip()[:160]
    o.periodicidade = form.get("periodicidade") if form.get("periodicidade") in \
        cat.PERIODICIDADES else o.periodicidade
    o.meses = ",".join(str(m) for m in sorted({int(x) for x in form.getlist("meses")
                                               if x.isdigit() and 1 <= int(x) <= 12})) or None
    if o.periodicidade == "mensal":
        o.meses = None
    o.prazo_tipo = "corrido" if form.get("prazo_tipo") == "corrido" else "util"
    try:
        o.prazo_dia = max(1, min(28, int(form.get("prazo_dia") or o.prazo_dia)))
    except ValueError:
        pass
    o.canal = (form.get("canal") or "").strip()[:40] or None
    o.destinatario = (form.get("destinatario") or "").strip() or None
    o.ativo = form.get("ativo") == "1"
    for item in o.itens:
        pref = f"item_{item.id}_"
        if pref + "nome" not in form:
            continue
        item.nome = (form.get(pref + "nome") or item.nome).strip()[:160]
        item.orgao = (form.get(pref + "orgao") or "").strip()[:120] or None
        item.link = (form.get(pref + "link") or "").strip()[:500] or None
        item.instrucoes = (form.get(pref + "instrucoes") or "").strip() or None
        item.ativo = form.get(pref + "ativo") == "1"
    novo_item = (form.get("novo_item") or "").strip()
    if novo_item:
        db.add(SesaItem(empresa_id=o.empresa_id, obrigacao_id=o.id,
                        chave=f"u{len(o.itens) + 1:02d}", nome=novo_item[:160],
                        ordem=(max((i.ordem for i in o.itens), default=0) + 10)))
    o.updated_by = usuario.id
    db.commit()
    record_audit(db, tabela="sesa_obrigacoes", acao="UPDATE", registro_id=o.id,
                 valor_anterior=antes,
                 valor_novo={"prazo": f"{o.prazo_tipo}:{o.prazo_dia}", "canal": o.canal,
                             "destinatario": o.destinatario, "meses": o.meses,
                             "ativo": o.ativo, "novo_item": novo_item or None},
                 usuario=usuario, request=request)
    return RedirectResponse(f"/sesa/cadastros?msg={quote(o.nome + ' salvo.')}#o{o.id}",
                            status_code=303)


# ------------------------------------------------------------------ anexos (por id)

@router.get("/anexos/{anexo_id:int}/arquivo", include_in_schema=False)
def ver_arquivo(anexo_id: int,
                usuario: Usuario = Depends(require_permission("sesa.visualizar")),
                db: Session = Depends(get_session)):
    a = _anexo(db, usuario, anexo_id)
    caminho = absolute_path(a.arquivo) if a else None
    if caminho is None or not caminho.is_file():
        return RedirectResponse("/sesa/", status_code=303)
    return FileResponse(caminho, filename=a.arquivo.nome_original,
                        media_type=a.arquivo.mime_type, content_disposition_type="inline")


@router.post("/anexos/{anexo_id:int}", include_in_schema=False)
async def editar_anexo(request: Request, anexo_id: int,
                       usuario: Usuario = Depends(require_permission("sesa.anexar")),
                       db: Session = Depends(get_session)):
    a = _anexo(db, usuario, anexo_id)
    if a is None:
        return RedirectResponse("/sesa/", status_code=303)
    form = dict(await request.form())
    antes = {"numero": a.numero, "valida_ate": str(a.valida_ate), "resultado": a.resultado}
    service.editar_anexo(db, a, form, usuario.id)
    record_audit(db, tabela="sesa_anexos", acao="UPDATE", registro_id=a.id,
                 valor_anterior=antes,
                 valor_novo={"numero": a.numero, "valida_ate": str(a.valida_ate),
                             "resultado": a.resultado}, usuario=usuario, request=request)
    ent = a.entrega
    return _voltar(ent.obrigacao.chave, ent.competencia, "Dados atualizados.",
                   ancora=f"item-{a.item_id}")


@router.post("/anexos/{anexo_id:int}/remover", include_in_schema=False)
def remover_anexo(request: Request, anexo_id: int,
                  usuario: Usuario = Depends(require_permission("sesa.anexar")),
                  db: Session = Depends(get_session)):
    a = _anexo(db, usuario, anexo_id)
    if a is None:
        return RedirectResponse("/sesa/", status_code=303)
    ent = a.entrega
    if ent.enviada_em:
        return _voltar(ent.obrigacao.chave, ent.competencia,
                       erro="Envio já registrado: desfaça o registro antes de trocar arquivos.")
    record_audit(db, tabela="sesa_anexos", acao="DELETE", registro_id=a.id,
                 valor_anterior={"item": a.item.nome, "arquivo": a.arquivo.nome_original},
                 usuario=usuario, request=request)
    service.excluir_anexo(db, ent, a)
    db.commit()
    return _voltar(ent.obrigacao.chave, ent.competencia, "Arquivo removido.",
                   ancora=f"item-{a.item_id}")


# ------------------------------------------------------------------ um envio

@router.get("/{chave}/{competencia}", include_in_schema=False)
def detalhe(request: Request, chave: str, competencia: str, msg: str = "", erro: str = "",
            usuario: Usuario = Depends(require_permission("sesa.visualizar")),
            db: Session = Depends(get_session)):
    o = _obrigacao(db, usuario, chave)
    if o is None:
        return RedirectResponse("/sesa/", status_code=303)
    hoje = _hoje(db, usuario.empresa_id)
    comp = prazos.competencia_de(competencia, hoje)
    dados = service.detalhe(db, usuario.empresa_id, o, comp, hoje)
    cnpj = service.cnpj(db, usuario.empresa_id)
    return render(request, "sesa/entrega.html", usuario,
                  page_title=f"{o.nome} — {prazos.rotulo(comp)}", d=dados, hoje=hoje,
                  cnpj=cnpj, cnpj_digitos="".join(c for c in cnpj if c.isdigit()),
                  despacho=service.texto_despacho(dados, cnpj), resultados=cat.RESULTADOS,
                  rotulo=prazos.rotulo, chave_comp=prazos.chave,
                  anterior=prazos.chave(prazos.somar_meses(comp, -1)),
                  seguinte=prazos.chave(prazos.somar_meses(comp, 1)),
                  descrever_prazo=prazos.descrever_prazo, msg=msg, erro=erro)


@router.post("/{chave}/{competencia}/anexar", include_in_schema=False)
def anexar(request: Request, chave: str, competencia: str, item_id: int = Form(...),
           arquivo: UploadFile = File(...),
           usuario: Usuario = Depends(require_permission("sesa.anexar")),
           db: Session = Depends(get_session)):
    o = _obrigacao(db, usuario, chave)
    comp = prazos.competencia_de(competencia)
    item = db.get(SesaItem, item_id)
    if o is None or item is None or item.obrigacao_id != o.id:
        return RedirectResponse("/sesa/", status_code=303)
    ent = service.entrega(db, usuario.empresa_id, o, comp)
    if ent and ent.enviada_em:
        return _voltar(chave, comp, erro="Envio já registrado: desfaça o registro "
                                         "antes de trocar arquivos.")
    try:
        novo = service.anexar(db, usuario.empresa_id, o, comp, item, arquivo, usuario.id)
    except ValueError as exc:
        return _voltar(chave, comp, erro=str(exc), ancora=f"item-{item.id}")
    record_audit(db, tabela="sesa_anexos", acao="UPLOAD", registro_id=novo.id,
                 valor_novo={"envio": o.nome, "competencia": prazos.chave(comp),
                             "item": item.nome, "arquivo": novo.arquivo.nome_original,
                             "numero": novo.numero, "valida_ate": str(novo.valida_ate)},
                 usuario=usuario, request=request)
    if o.tipo == cat.TIPO_CERTIDOES and not novo.valida_ate:
        msg = f"{item.nome}: arquivo guardado. Não foi possível ler a validade — confira e preencha."
    elif o.tipo == cat.TIPO_CERTIDOES:
        msg = f"{item.nome}: certidão lida — confira os dados."
    else:
        msg = f"{item.nome}: arquivo guardado."
    return _voltar(chave, comp, msg, ancora=f"item-{item.id}")


@router.post("/{chave}/{competencia}/reaproveitar", include_in_schema=False)
def reaproveitar(request: Request, chave: str, competencia: str, anexo_id: int = Form(...),
                 usuario: Usuario = Depends(require_permission("sesa.anexar")),
                 db: Session = Depends(get_session)):
    o = _obrigacao(db, usuario, chave)
    origem = _anexo(db, usuario, anexo_id)
    comp = prazos.competencia_de(competencia)
    if o is None or origem is None or origem.item.obrigacao_id != o.id:
        return RedirectResponse("/sesa/", status_code=303)
    ent = service.entrega(db, usuario.empresa_id, o, comp)
    if ent and ent.enviada_em:
        return _voltar(chave, comp, erro="Envio já registrado.")
    novo = service.reaproveitar(db, usuario.empresa_id, o, comp, origem, usuario.id)
    record_audit(db, tabela="sesa_anexos", acao="REAPROVEITAR", registro_id=novo.id,
                 valor_novo={"item": origem.item.nome, "de_anexo": origem.id,
                             "competencia": prazos.chave(comp)},
                 usuario=usuario, request=request)
    return _voltar(chave, comp, f"{origem.item.nome}: certidão anterior reaproveitada.",
                   ancora=f"item-{origem.item_id}")


@router.get("/{chave}/{competencia}/pacote.zip", include_in_schema=False)
def pacote(request: Request, chave: str, competencia: str,
           usuario: Usuario = Depends(require_permission("sesa.visualizar")),
           db: Session = Depends(get_session)):
    o = _obrigacao(db, usuario, chave)
    if o is None:
        return RedirectResponse("/sesa/", status_code=303)
    comp = prazos.competencia_de(competencia)
    dados = service.detalhe(db, usuario.empresa_id, o, comp, _hoje(db, usuario.empresa_id))
    record_audit(db, tabela="sesa_entregas", acao="EXPORTACAO",
                 registro_id=dados["entrega"].id if dados["entrega"] else None,
                 valor_novo={"envio": o.nome, "competencia": prazos.chave(comp)},
                 usuario=usuario, request=request)
    nome = f"SESA - {o.nome} - {comp:%m-%Y}.zip"
    return Response(service.pacote_zip(dados), media_type="application/zip",
                    headers={"Content-Disposition":
                             f"attachment; filename*=UTF-8''{quote(nome)}"})


@router.post("/{chave}/{competencia}/enviar", include_in_schema=False)
async def enviar(request: Request, chave: str, competencia: str,
                 usuario: Usuario = Depends(require_permission("sesa.enviar")),
                 db: Session = Depends(get_session)):
    o = _obrigacao(db, usuario, chave)
    if o is None:
        return RedirectResponse("/sesa/", status_code=303)
    comp = prazos.competencia_de(competencia)
    form = dict(await request.form())
    ent = service.entrega(db, usuario.empresa_id, o, comp, criar=True)
    service.registrar_envio(db, ent, form, usuario.id)
    record_audit(db, tabela="sesa_entregas", acao="ENVIO", registro_id=ent.id,
                 valor_novo={"envio": o.nome, "competencia": prazos.chave(comp),
                             "enviada_em": str(ent.enviada_em), "protocolo": ent.protocolo},
                 usuario=usuario, request=request)
    destino = form.get("voltar")
    if destino == "matriz":
        return RedirectResponse(f"/sesa/?ano={comp.year}", status_code=303)
    return _voltar(chave, comp, "Envio registrado.")


@router.post("/{chave}/{competencia}/desfazer", include_in_schema=False)
def desfazer(request: Request, chave: str, competencia: str,
             usuario: Usuario = Depends(require_permission("sesa.enviar")),
             db: Session = Depends(get_session)):
    o = _obrigacao(db, usuario, chave)
    comp = prazos.competencia_de(competencia)
    ent = service.entrega(db, usuario.empresa_id, o, comp) if o else None
    if ent is None:
        return RedirectResponse("/sesa/", status_code=303)
    antes = {"enviada_em": str(ent.enviada_em), "protocolo": ent.protocolo}
    service.desfazer_envio(db, ent, usuario.id)
    record_audit(db, tabela="sesa_entregas", acao="DESFAZER_ENVIO", registro_id=ent.id,
                 valor_anterior=antes, usuario=usuario, request=request)
    return _voltar(chave, comp, "Registro de envio desfeito.")
