"""Regras dos envios à SESA: catálogo, situação por competência, anexos
(com leitura das certidões), reaproveitamento, pacote e registro do envio."""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config_service import get_config
from app.core.storage import absolute_path, save_upload
from app.modules.sesa import constants as cat
from app.modules.sesa import extrator, prazos
from app.modules.sesa.models import SesaAnexo, SesaEntrega, SesaItem, SesaObrigacao

CONFIG_CNPJ = "sesa_cnpj"
CONFIG_FERIADOS = "sesa_feriados_extras"
AVISO_DIAS = 5            # a página inicial avisa a partir de 5 dias antes do prazo
TIPOS_ACEITOS = ("application/pdf", "image/")


# ------------------------------------------------------------------ catálogo

def garantir_catalogo(db: Session, empresa_id: int) -> None:
    """Carrega o que falta do catálogo inicial (por `chave`), sem tocar no que
    já existe — o que foi editado na tela de Cadastros permanece."""
    existentes = {o.chave: o for o in db.scalars(select(SesaObrigacao).where(
        SesaObrigacao.empresa_id == empresa_id))}
    mudou = False
    for ordem, dados in enumerate(cat.OBRIGACOES, start=1):
        obrig = existentes.get(dados["chave"])
        if obrig is None:
            obrig = SesaObrigacao(
                empresa_id=empresa_id, chave=dados["chave"], nome=dados["nome"],
                tipo=dados.get("tipo", cat.TIPO_DOCUMENTOS),
                periodicidade=dados.get("periodicidade", "mensal"),
                meses=dados.get("meses"), prazo_tipo=dados["prazo_tipo"],
                prazo_dia=dados["prazo_dia"], canal=dados["canal"],
                destinatario=dados["destinatario"], ordem=ordem * 10)
            db.add(obrig)
            db.flush()
            mudou = True
        tem = {i.chave for i in db.scalars(select(SesaItem).where(
            SesaItem.obrigacao_id == obrig.id))}
        for n, item in enumerate(dados["itens"], start=1):
            if item["chave"] in tem:
                continue
            db.add(SesaItem(empresa_id=empresa_id, obrigacao_id=obrig.id,
                            chave=item["chave"], nome=item["nome"],
                            orgao=item.get("orgao"), link=item.get("link"),
                            instrucoes=item.get("instrucoes"),
                            validade_dias=item.get("validade_dias"), ordem=n * 10))
            mudou = True
    if mudou:
        db.commit()


def obrigacoes(db: Session, empresa_id: int, so_ativas: bool = True) -> list[SesaObrigacao]:
    q = select(SesaObrigacao).where(SesaObrigacao.empresa_id == empresa_id,
                                    SesaObrigacao.deleted_at.is_(None))
    if so_ativas:
        q = q.where(SesaObrigacao.ativo.is_(True))
    return list(db.scalars(q.order_by(SesaObrigacao.ordem, SesaObrigacao.id)))


def obrigacao_por_chave(db: Session, empresa_id: int, chave: str) -> SesaObrigacao | None:
    return db.scalar(select(SesaObrigacao).where(
        SesaObrigacao.empresa_id == empresa_id, SesaObrigacao.chave == chave,
        SesaObrigacao.deleted_at.is_(None)))


def itens_ativos(obrig: SesaObrigacao) -> list[SesaItem]:
    return [i for i in obrig.itens if i.ativo and i.deleted_at is None]


def cnpj(db: Session, empresa_id: int) -> str:
    return get_config(db, CONFIG_CNPJ, cat.CNPJ_PADRAO, empresa_id) or cat.CNPJ_PADRAO


def feriados_extras(db: Session, empresa_id: int) -> list[str]:
    return prazos.ler_extras(get_config(db, CONFIG_FERIADOS, "", empresa_id))


def prazo_de(obrig: SesaObrigacao, competencia: date, extras=()) -> date:
    return prazos.prazo(competencia, obrig.prazo_tipo, obrig.prazo_dia, extras)


# ------------------------------------------------------------------ entregas

def entrega(db: Session, empresa_id: int, obrig: SesaObrigacao, competencia: date,
            criar: bool = False) -> SesaEntrega | None:
    item = db.scalar(select(SesaEntrega).where(
        SesaEntrega.empresa_id == empresa_id, SesaEntrega.obrigacao_id == obrig.id,
        SesaEntrega.competencia == competencia))
    if item is None and criar:
        item = SesaEntrega(empresa_id=empresa_id, obrigacao_id=obrig.id,
                           competencia=competencia)
        db.add(item)
        db.flush()
    return item


def situacao(obrig: SesaObrigacao, competencia: date, ent: SesaEntrega | None,
             hoje: date, extras=()) -> dict:
    """Estado do envio de uma competência, para a matriz e os alertas.

    nao_aplica · enviada · atrasada · vence (até AVISO_DIAS) · pendente · futura
    """
    total = len(itens_ativos(obrig))
    anexados = len({a.item_id for a in (ent.anexos if ent else []) if a.deleted_at is None})
    base = {"competencia": competencia, "total": total, "anexados": anexados,
            "prazo": None, "estado": "nao_aplica", "entrega": ent}
    if not prazos.aplica(obrig.meses, competencia):
        return base
    base["prazo"] = limite = prazo_de(obrig, competencia, extras)
    if ent and ent.enviada_em:
        base["estado"] = "enviada"
        base["no_prazo"] = ent.enviada_em <= limite
    elif hoje > limite:
        base["estado"] = "atrasada"
    elif (limite - hoje).days <= AVISO_DIAS:
        base["estado"] = "vence"
    elif competencia > date(hoje.year, hoje.month, 1):
        base["estado"] = "futura"
    else:
        base["estado"] = "pendente"
    return base


def matriz_ano(db: Session, empresa_id: int, ano: int, hoje: date) -> list[dict]:
    """Linhas = obrigações, colunas = os 12 meses do ano (como a planilha)."""
    extras = feriados_extras(db, empresa_id)
    lista = obrigacoes(db, empresa_id)
    entregas = {(e.obrigacao_id, e.competencia): e for e in db.scalars(
        select(SesaEntrega).where(SesaEntrega.empresa_id == empresa_id,
                                  SesaEntrega.competencia >= date(ano, 1, 1),
                                  SesaEntrega.competencia <= date(ano, 12, 1)))}
    linhas = []
    for o in lista:
        meses = [situacao(o, date(ano, m, 1), entregas.get((o.id, date(ano, m, 1))),
                          hoje, extras) for m in range(1, 13)]
        linhas.append({"obrigacao": o, "meses": meses})
    return linhas


def pendencias(db: Session, empresa_id: int, hoje: date) -> list[dict]:
    """Envios atrasados ou que vencem nos próximos dias — para a página inicial.

    Olha a competência atual e, da anterior, só o que foi começado (tem
    entrega) e não foi registrado: sem isso, no primeiro mês de uso todo o
    catálogo apareceria como atrasado."""
    garantir_catalogo(db, empresa_id)
    extras = feriados_extras(db, empresa_id)
    atual = date(hoje.year, hoje.month, 1)
    anterior = prazos.somar_meses(atual, -1)
    saida = []
    for o in obrigacoes(db, empresa_id):
        for comp in (anterior, atual):
            ent = entrega(db, empresa_id, o, comp)
            if comp == anterior and ent is None:
                continue
            s = situacao(o, comp, ent, hoje, extras)
            if s["estado"] in ("atrasada", "vence"):
                saida.append({**s, "obrigacao": o})
    return saida


# ------------------------------------------------------------------ anexos

def excluir_anexo(db: Session, ent: SesaEntrega, anexo: SesaAnexo) -> None:
    """Tira o anexo da entrega. Quem o reaproveitou continua com o arquivo
    (é o mesmo); só perde o vínculo com a origem."""
    for outro in db.scalars(select(SesaAnexo).where(SesaAnexo.reaproveitado_de == anexo.id)):
        outro.reaproveitado_de = None
    db.flush()
    ent.anexos.remove(anexo)

def anexo_do_item(ent: SesaEntrega | None, item_id: int) -> SesaAnexo | None:
    for a in (ent.anexos if ent else []):
        if a.item_id == item_id and a.deleted_at is None:
            return a
    return None


def ultimo_anexo(db: Session, empresa_id: int, item: SesaItem,
                 antes_de: date) -> SesaAnexo | None:
    """Anexo mais recente do item em competências anteriores."""
    return db.scalar(
        select(SesaAnexo).join(SesaEntrega, SesaAnexo.entrega_id == SesaEntrega.id)
        .where(SesaAnexo.empresa_id == empresa_id, SesaAnexo.item_id == item.id,
               SesaAnexo.deleted_at.is_(None), SesaEntrega.competencia < antes_de)
        .order_by(SesaEntrega.competencia.desc(), SesaAnexo.id.desc()).limit(1))


def avisos_do_anexo(anexo: SesaAnexo, limite: date) -> list[str]:
    """Problemas que impedem mandar a certidão como está."""
    avisos = []
    if anexo.valida_ate and anexo.valida_ate < limite:
        avisos.append(f"vence em {anexo.valida_ate:%d/%m/%Y}, antes do prazo de envio "
                      f"({limite:%d/%m/%Y})")
    if anexo.resultado and anexo.resultado not in cat.RESULTADOS_OK:
        avisos.append(f"resultado {anexo.resultado}")
    if anexo.cnpj_confere is False:
        avisos.append("o CNPJ do documento não é o do SAMU")
    if not anexo.valida_ate:
        avisos.append("validade não informada")
    return avisos


def detalhe(db: Session, empresa_id: int, obrig: SesaObrigacao, competencia: date,
            hoje: date) -> dict:
    extras = feriados_extras(db, empresa_id)
    ent = entrega(db, empresa_id, obrig, competencia)
    sit = situacao(obrig, competencia, ent, hoje, extras)
    limite = sit["prazo"] or prazo_de(obrig, competencia, extras)
    proximo = prazo_de(obrig, prazos.somar_meses(competencia, 1), extras)
    certidoes = obrig.tipo == cat.TIPO_CERTIDOES
    linhas = []
    for item in itens_ativos(obrig):
        anexo = anexo_do_item(ent, item.id)
        linha = {"item": item, "anexo": anexo, "avisos": [], "sugestao": None}
        if anexo and certidoes:
            linha["avisos"] = avisos_do_anexo(anexo, limite)
            linha["serve_proximo"] = bool(anexo.valida_ate and anexo.valida_ate >= proximo)
        if not anexo and certidoes:
            anterior = ultimo_anexo(db, empresa_id, item, competencia)
            if anterior and anterior.valida_ate and anterior.valida_ate >= limite \
                    and not avisos_do_anexo(anterior, limite):
                linha["sugestao"] = anterior
        linhas.append(linha)
    return {"obrigacao": obrig, "competencia": competencia, "entrega": ent,
            "situacao": sit, "prazo": limite, "proximo_prazo": proximo,
            "linhas": linhas, "certidoes": certidoes,
            "completo": all(l["anexo"] for l in linhas),
            "com_aviso": any(l["avisos"] for l in linhas)}


def anexar(db: Session, empresa_id: int, obrig: SesaObrigacao, competencia: date,
           item: SesaItem, arquivo: UploadFile, usuario_id: int) -> SesaAnexo:
    """Guarda o arquivo do item (substitui o anterior da mesma competência)
    e, nas certidões, lê número, emissão, validade e resultado do PDF."""
    tipo = arquivo.content_type or ""
    if not tipo.startswith(TIPOS_ACEITOS) and obrig.tipo == cat.TIPO_CERTIDOES:
        raise ValueError("Envie a certidão em PDF (ou imagem).")
    conteudo = arquivo.file.read()
    arquivo.file.seek(0)
    salvo = save_upload(db, arquivo, empresa_id, "sesa", created_by=usuario_id)
    ent = entrega(db, empresa_id, obrig, competencia, criar=True)
    antigo = anexo_do_item(ent, item.id)
    if antigo is not None:
        excluir_anexo(db, ent, antigo)
    novo = SesaAnexo(empresa_id=empresa_id, item_id=item.id, arquivo_id=salvo.id,
                     created_by=usuario_id)
    if obrig.tipo == cat.TIPO_CERTIDOES and tipo == "application/pdf":
        lido = extrator.extrair(extrator.extrair_texto(conteudo), cnpj(db, empresa_id))
        novo.numero, novo.emitida_em = lido["numero"], lido["emitida_em"]
        novo.valida_ate, novo.resultado = lido["valida_ate"], lido["resultado"]
        novo.cnpj_confere = lido["cnpj_confere"]
    ent.anexos.append(novo)
    db.commit()
    return novo


def reaproveitar(db: Session, empresa_id: int, obrig: SesaObrigacao, competencia: date,
                 origem: SesaAnexo, usuario_id: int) -> SesaAnexo:
    """Usa, nesta competência, uma certidão ainda válida de um mês anterior."""
    ent = entrega(db, empresa_id, obrig, competencia, criar=True)
    antigo = anexo_do_item(ent, origem.item_id)
    if antigo is not None:
        excluir_anexo(db, ent, antigo)
    novo = SesaAnexo(empresa_id=empresa_id, item_id=origem.item_id,
                     arquivo_id=origem.arquivo_id, numero=origem.numero,
                     emitida_em=origem.emitida_em, valida_ate=origem.valida_ate,
                     resultado=origem.resultado, cnpj_confere=origem.cnpj_confere,
                     reaproveitado_de=origem.id, created_by=usuario_id)
    ent.anexos.append(novo)
    db.commit()
    return novo


def _data(texto: str | None) -> date | None:
    try:
        return date.fromisoformat((texto or "").strip())
    except ValueError:
        return None


def editar_anexo(db: Session, anexo: SesaAnexo, form: dict, usuario_id: int) -> None:
    anexo.numero = (form.get("numero") or "").strip()[:80] or None
    anexo.emitida_em = _data(form.get("emitida_em"))
    anexo.valida_ate = _data(form.get("valida_ate"))
    resultado = form.get("resultado") or None
    anexo.resultado = resultado if resultado in cat.RESULTADOS else None
    anexo.updated_by = usuario_id
    db.commit()


def registrar_envio(db: Session, ent: SesaEntrega, form: dict, usuario_id: int) -> None:
    ent.enviada_em = _data(form.get("enviada_em")) or date.today()
    ent.protocolo = (form.get("protocolo") or "").strip()[:80] or None
    ent.observacao = (form.get("observacao") or "").strip() or None
    ent.enviada_por = usuario_id
    ent.updated_by = usuario_id
    db.commit()


def desfazer_envio(db: Session, ent: SesaEntrega, usuario_id: int) -> None:
    ent.enviada_em = ent.protocolo = ent.enviada_por = None
    ent.updated_by = usuario_id
    db.commit()


# ------------------------------------------------------------------ pacote

def _nome_seguro(texto: str) -> str:
    return re.sub(r"[^\w\- .()]+", "", texto, flags=re.U).strip() or "arquivo"


def nome_no_pacote(n: int, anexo: SesaAnexo, competencia: date) -> str:
    ext = (anexo.arquivo.nome_original.rsplit(".", 1)[-1] if "." in
           anexo.arquivo.nome_original else "pdf")[:5]
    return _nome_seguro(f"{n:02d} - {anexo.item.nome} - {competencia:%m-%Y}") + f".{ext}"


def pacote_zip(dados: dict) -> bytes:
    """Todos os arquivos da competência num .zip, nomeados na ordem do envio."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for n, linha in enumerate(dados["linhas"], start=1):
            anexo = linha["anexo"]
            if anexo is None:
                continue
            caminho = absolute_path(anexo.arquivo)
            if caminho.is_file():
                z.write(caminho, nome_no_pacote(n, anexo, dados["competencia"]))
    return buffer.getvalue()


def texto_despacho(dados: dict, cnpj_samu: str) -> str:
    """Texto para colar no E-Docs / e-mail ao encaminhar o envio."""
    o, comp = dados["obrigacao"], dados["competencia"]
    linhas = [f"Encaminhamos {o.nome.lower() if o.tipo == cat.TIPO_CERTIDOES else o.nome}"
              f" do SAMU 192 ES (CNPJ {cnpj_samu}), referente(s) a "
              f"{prazos.rotulo(comp)}:", ""]
    for linha in dados["linhas"]:
        a = linha["anexo"]
        if a is None:
            continue
        partes = [linha["item"].nome]
        if linha["item"].orgao:
            partes[0] += f" ({linha['item'].orgao})"
        if a.numero:
            partes.append(f"nº {a.numero}")
        if a.resultado:
            partes.append(a.resultado.lower())
        if a.valida_ate:
            partes.append(f"válida até {a.valida_ate:%d/%m/%Y}")
        linhas.append("- " + " — ".join(partes))
    linhas += ["", "Atenciosamente,", "Setor de Qualidade — SAMU 192 ES"]
    return "\n".join(linhas)
