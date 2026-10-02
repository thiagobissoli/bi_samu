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
from app.core.config_service import get_config, set_config
from app.core.database import get_session
from app.core.export import tz_da_empresa
from app.core.storage import absolute_path
from app.core.templating import render
from app.models import Usuario
from app.modules.sesa import constants as cat
from app.modules.sesa import prazos, service
from app.modules.sesa.models import SesaAnexo, SesaItem, SesaObrigacao

router = APIRouter(prefix="/sesa", tags=["SESA"])


@router.on_event("startup")
def _agendar_avisos() -> None:
    """Job diário dos avisos de vencimento das certidões.

    Não sobe sob o pytest: o agendador é um thread que, 2 minutos após o
    boot, grava no banco — numa suíte longa com SQLite isso trava a base.
    O job em si é testado chamando scheduler.executar() direto."""
    import sys
    if "pytest" in sys.modules:
        return
    try:
        from app.modules.sesa import scheduler
        scheduler.iniciar()
    except Exception:  # noqa: BLE001 — sem agendador o resto do sistema segue
        import logging
        logging.getLogger("uvicorn.error").exception("SESA: agendador não iniciou")


def _lembrar_endereco(request: Request, db: Session, empresa_id: int) -> None:
    """Guarda o endereço do sistema (para o link dos e-mails do job, que roda
    fora de uma requisição) na primeira visita; depois é editável nos Cadastros."""
    from app.core.config_service import get_config

    if not get_config(db, service.CONFIG_ENDERECO, "", empresa_id):
        set_config(db, service.CONFIG_ENDERECO, str(request.base_url).rstrip("/"),
                   empresa_id)


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
    _lembrar_endereco(request, db, usuario.empresa_id)
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
                  aviso_dias=service.dias_aviso_vencimento(db, usuario.empresa_id),
                  endereco=get_config(db, service.CONFIG_ENDERECO, "", usuario.empresa_id),
                  tem_logo=service.logo(db, usuario.empresa_id) is not None,
                  periodicidades=cat.PERIODICIDADES, msg=msg)


@router.post("/cadastros/geral", include_in_schema=False)
def cadastros_geral(request: Request, cnpj: str = Form(""), feriados: str = Form(""),
                    aviso_dias: str = Form(""), endereco: str = Form(""),
                    logo: UploadFile | None = File(None), remover_logo: str = Form(""),
                    usuario: Usuario = Depends(require_permission("sesa.cadastros")),
                    db: Session = Depends(get_session)):
    set_config(db, service.CONFIG_CNPJ, cnpj.strip() or cat.CNPJ_PADRAO,
               usuario.empresa_id, updated_by=usuario.id)
    set_config(db, service.CONFIG_FERIADOS, ", ".join(prazos.ler_extras(feriados)),
               usuario.empresa_id, updated_by=usuario.id)
    dias = aviso_dias.strip()
    set_config(db, service.CONFIG_AVISO_DIAS,
               str(max(1, min(60, int(dias)))) if dias.isdigit() else
               str(service.AVISO_VENCIMENTO_PADRAO), usuario.empresa_id, updated_by=usuario.id)
    set_config(db, service.CONFIG_ENDERECO, endereco.strip().rstrip("/"),
               usuario.empresa_id, updated_by=usuario.id)
    if remover_logo == "1":
        set_config(db, cat.CONFIG_LOGO, "", usuario.empresa_id, updated_by=usuario.id)
    elif logo is not None and logo.filename:
        from app.core.storage import save_upload

        if not (logo.content_type or "").startswith("image/"):
            return RedirectResponse(f"/sesa/cadastros?msg={quote('O brasão precisa ser uma imagem (PNG ou JPG).')}",
                                    status_code=303)
        salvo = save_upload(db, logo, usuario.empresa_id, "sesa", created_by=usuario.id)
        set_config(db, cat.CONFIG_LOGO, str(salvo.id), usuario.empresa_id,
                   updated_by=usuario.id)
    record_audit(db, tabela="configuracoes", acao="UPDATE",
                 valor_novo={"sesa_cnpj": cnpj, "sesa_feriados_extras": feriados,
                             "sesa_aviso_vencimento_dias": aviso_dias,
                             "sesa_endereco_sistema": endereco},
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


# ------------------------------------------------------------------ encaminhamentos

def _planilha(db, usuario, arquivo_id) -> bytes | None:
    """Conteúdo do Report.xls enviado nesta tela (só arquivos do módulo)."""
    from app.models import Arquivo

    a = db.get(Arquivo, arquivo_id) if arquivo_id else None
    if a is None or a.deleted_at is not None or a.empresa_id != usuario.empresa_id \
            or a.modulo != "sesa":
        return None
    caminho = absolute_path(a)
    return caminho.read_bytes() if caminho.is_file() else None


def _encaminhamentos_url(comp: date, planilha: int | None = None, erro: str = "") -> str:
    url = f"/sesa/encaminhamentos/{prazos.chave(comp)}"
    params = []
    if planilha:
        params.append(f"planilha={planilha}")
    if erro:
        params.append(f"erro={quote(erro)}")
    return url + ("?" + "&".join(params) if params else "")


@router.get("/encaminhamentos/{competencia}", include_in_schema=False)
def encaminhamentos(request: Request, competencia: str, planilha: int | None = None,
                    erro: str = "",
                    usuario: Usuario = Depends(require_permission("sesa.visualizar")),
                    db: Session = Depends(get_session)):
    from app.modules.sesa import encaminhamentos as enc

    service.garantir_catalogo(db, usuario.empresa_id)
    comp = prazos.competencia_de(competencia, _hoje(db, usuario.empresa_id))
    inicio, fim = enc.periodo_dos_dados(comp)
    linhas = None
    conteudo = _planilha(db, usuario, planilha)
    if conteudo is not None:
        try:
            linhas = service.conferir_planilha(db, usuario.empresa_id,
                                               enc.ler_relatorio(conteudo))
        except ValueError as exc:
            erro = str(exc)
    return render(request, "sesa/encaminhamentos.html", usuario,
                  page_title=f"Encaminhamentos do SAMU — {prazos.rotulo(inicio)}",
                  comp=comp, chave_comp=prazos.chave(comp), inicio=inicio, fim=fim,
                  rotulo=prazos.rotulo, filtros=enc.FILTROS_VSKY, url_vsky=enc.URL_RELATORIO,
                  linhas=linhas, planilha=planilha if linhas is not None else None,
                  erro=erro, tem_logo=service.logo(db, usuario.empresa_id) is not None)


@router.post("/encaminhamentos/{competencia}/planilha", include_in_schema=False)
def encaminhamentos_planilha(request: Request, competencia: str,
                             arquivo: UploadFile = File(...),
                             usuario: Usuario = Depends(require_permission("sesa.anexar")),
                             db: Session = Depends(get_session)):
    from app.core.storage import save_upload
    from app.modules.sesa import encaminhamentos as enc

    comp = prazos.competencia_de(competencia)
    conteudo = arquivo.file.read()
    arquivo.file.seek(0)
    try:
        enc.ler_relatorio(conteudo)
        salvo = save_upload(db, arquivo, usuario.empresa_id, "sesa", created_by=usuario.id)
    except ValueError as exc:
        return RedirectResponse(_encaminhamentos_url(comp, erro=str(exc)), status_code=303)
    record_audit(db, tabela="arquivos", acao="UPLOAD", registro_id=salvo.id,
                 valor_novo={"envio": "Encaminhamentos do SAMU",
                             "competencia": prazos.chave(comp),
                             "arquivo": salvo.nome_original}, usuario=usuario, request=request)
    return RedirectResponse(_encaminhamentos_url(comp, salvo.id), status_code=303)


@router.post("/encaminhamentos/{competencia}/gerar", include_in_schema=False)
async def encaminhamentos_gerar(request: Request, competencia: str,
                                usuario: Usuario = Depends(require_permission("sesa.anexar")),
                                db: Session = Depends(get_session)):
    from app.modules.sesa import encaminhamentos as enc

    comp = prazos.competencia_de(competencia)
    form = await request.form()
    try:
        planilha = int(form.get("planilha") or 0)
    except ValueError:
        planilha = 0
    conteudo = _planilha(db, usuario, planilha)
    if conteudo is None:
        return RedirectResponse(_encaminhamentos_url(comp, erro="Envie o Report.xls de novo."),
                                status_code=303)
    obrig = service.obrigacao_por_chave(db, usuario.empresa_id, "adversidades")
    ent = service.entrega(db, usuario.empresa_id, obrig, comp) if obrig else None
    if ent and ent.enviada_em:
        return RedirectResponse(_encaminhamentos_url(
            comp, planilha, "Envio já registrado: desfaça o registro antes de gerar de novo."),
            status_code=303)
    service.salvar_selecao(db, usuario.empresa_id, form)
    try:
        anexo = service.gerar_encaminhamentos(db, usuario.empresa_id, comp,
                                              enc.ler_relatorio(conteudo), usuario.id)
    except ValueError as exc:
        return RedirectResponse(_encaminhamentos_url(comp, planilha, str(exc)),
                                status_code=303)
    record_audit(db, tabela="sesa_anexos", acao="GERAR", registro_id=anexo.id,
                 valor_novo={"documento": anexo.arquivo.nome_original,
                             "competencia": prazos.chave(comp), "planilha": planilha},
                 usuario=usuario, request=request)
    return _voltar("adversidades", comp, "Documento de Encaminhamentos gerado e anexado.",
                   ancora=f"item-{anexo.item_id}")


# ------------------------------------------------------------------ saída de usa

@router.get("/saida-usa/{competencia}", include_in_schema=False)
def saida_usa(request: Request, competencia: str, para: str = "convenio_007",
              erro: str = "", msg: str = "",
              usuario: Usuario = Depends(require_permission("sesa.visualizar")),
              db: Session = Depends(get_session)):
    service.garantir_catalogo(db, usuario.empresa_id)
    comp = prazos.competencia_de(competencia, _hoje(db, usuario.empresa_id))
    inicio, fim = prazos.periodo_competencia_anterior(comp)
    obrig, item = service.item_do_gerador(db, usuario.empresa_id, para, "/sesa/saida-usa")
    if obrig is None or item is None:
        return RedirectResponse("/sesa/", status_code=303)
    dados = None
    try:
        dados = service.dados_saida_usa(usuario.empresa_id, comp)
    except Exception:  # noqa: BLE001 — sem dados importados a página ainda abre
        import logging
        logging.getLogger("uvicorn.error").exception("Saída de USA: falha ao calcular")
        erro = erro or ("Não foi possível calcular agora. Verifique se há dados do vSky "
                        "importados para o período.")
    return render(request, "sesa/saida_usa.html", usuario,
                  page_title=f"Saída de USA — {prazos.rotulo(inicio)}",
                  comp=comp, chave_comp=prazos.chave(comp), para=para, obrig=obrig,
                  inicio=inicio, fim=fim, rotulo=prazos.rotulo, dados=dados,
                  erro=erro, msg=msg)


@router.post("/saida-usa/{competencia}/gerar", include_in_schema=False)
def saida_usa_gerar(request: Request, competencia: str, para: str = Form("convenio_007"),
                    usuario: Usuario = Depends(require_permission("sesa.anexar")),
                    db: Session = Depends(get_session)):
    comp = prazos.competencia_de(competencia)
    obrig = service.obrigacao_por_chave(db, usuario.empresa_id, para)
    if obrig is None:
        return RedirectResponse("/sesa/", status_code=303)
    ent = service.entrega(db, usuario.empresa_id, obrig, comp)
    if ent and ent.enviada_em:
        return RedirectResponse(
            f"/sesa/saida-usa/{prazos.chave(comp)}?para={para}&erro="
            + quote("Envio já registrado: desfaça o registro antes de gerar de novo."),
            status_code=303)
    try:
        anexo = service.gerar_saida_usa(db, usuario.empresa_id, para, comp, usuario.id)
    except ValueError as exc:
        return RedirectResponse(
            f"/sesa/saida-usa/{prazos.chave(comp)}?para={para}&erro={quote(str(exc))}",
            status_code=303)
    record_audit(db, tabela="sesa_anexos", acao="GERAR", registro_id=anexo.id,
                 valor_novo={"documento": anexo.arquivo.nome_original, "envio": para,
                             "competencia": prazos.chave(comp)},
                 usuario=usuario, request=request)
    return _voltar(para, comp, "Planilha de Saída de USA gerada e anexada.",
                   ancora=f"item-{anexo.item_id}")


# ------------------------------------------------------------------ um envio

@router.get("/{chave}/{competencia}", include_in_schema=False)
def detalhe(request: Request, chave: str, competencia: str, msg: str = "", erro: str = "",
            usuario: Usuario = Depends(require_permission("sesa.visualizar")),
            db: Session = Depends(get_session)):
    o = _obrigacao(db, usuario, chave)
    if o is None:
        return RedirectResponse("/sesa/", status_code=303)
    _lembrar_endereco(request, db, usuario.empresa_id)
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
