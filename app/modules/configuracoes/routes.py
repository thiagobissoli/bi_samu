"""Configurações por empresa (§22) — chave/valor com cache (§39.12),
criptografia de chaves sensíveis (§39.29) e auditoria mascarada."""

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth import require_permission
from app.core.config_service import get_config, invalidate_config, set_config
from app.core.crypto import is_sensitive, mask_value
from app.core.database import get_session, utcnow
from app.core.templating import render
from app.models import Configuracao, Usuario

router = APIRouter(prefix="/configuracoes", tags=["Configuracoes"])


@router.get("/", include_in_schema=False)
def index(
    request: Request,
    usuario: Usuario = Depends(require_permission("configuracao.listar")),
    db: Session = Depends(get_session),
):
    from app.modules.configuracoes.catalogo import CATALOGO, catalogadas

    registros = list(db.scalars(
        select(Configuracao).where(
            Configuracao.deleted_at.is_(None),
            Configuracao.empresa_id == usuario.empresa_id,
        ).order_by(Configuracao.chave)
    ))
    gravadas = {c.chave: c for c in registros}

    def _item(chave: str, definicao=None) -> dict:
        registro = gravadas.get(chave)
        sensivel = is_sensitive(chave)
        return {
            "id": registro.id if registro else None,
            "chave": chave,
            "rotulo": definicao.rotulo if definicao else chave,
            "ajuda": definicao.ajuda if definicao else "",
            "padrao": definicao.padrao if definicao else "",
            "tipo": definicao.tipo if definicao else "texto",
            "opcoes": list(definicao.opcoes) if definicao else [],
            "somente_leitura": definicao.somente_leitura if definicao else False,
            "gerida_em": definicao.gerida_em if definicao else "",
            "sensivel": sensivel,
            "valor": "" if sensivel else ((registro.valor if registro else "") or ""),
            "definido": bool(registro and registro.valor),
        }

    # Todas as chaves conhecidas aparecem, mesmo as que nunca foram gravadas:
    # sem isso, quem não decorou o nome exato não tinha como criá-las.
    grupos = [{"titulo": g.titulo, "icone": g.icone, "descricao": g.descricao,
               "itens": [_item(c.chave, c) for c in g.chaves]}
              for g in CATALOGO]
    # Chave gravada fora do catálogo (criada à mão ou de módulo removido)
    # não some da tela — só perde a explicação.
    conhecidas = catalogadas()
    extras = [_item(c.chave) for c in registros if c.chave not in conhecidas]
    if extras:
        grupos.append({"titulo": "Outras chaves", "icone": "fa-key",
                       "descricao": "Gravadas fora do catálogo do sistema.",
                       "itens": extras})
    return render(request, "configuracoes/index.html", usuario,
                  page_title="Configurações", grupos=grupos,
                  total=sum(len(g["itens"]) for g in grupos))


@router.post("/salvar", include_in_schema=False)
def salvar(
    request: Request,
    chave: str = Form(...),
    valor: str = Form(""),
    usuario: Usuario = Depends(require_permission("configuracao.editar")),
    db: Session = Depends(get_session),
):
    chave = chave.strip()
    # Campo sensível em branco = manter o valor atual (não sobrescrever).
    if not valor and is_sensitive(chave):
        atual = get_config(db, chave, empresa_id=usuario.empresa_id)
        if atual:
            return RedirectResponse("/configuracoes/", status_code=303)

    anterior = get_config(db, chave, empresa_id=usuario.empresa_id)
    existia = anterior is not None
    item = set_config(db, chave, valor, usuario.empresa_id, updated_by=usuario.id)

    record_audit(
        db, tabela="configuracoes",
        acao="UPDATE" if existia else "INSERT",
        registro_id=item.id,
        valor_anterior=(
            {"chave": chave, "valor": mask_value(chave, anterior)} if existia else None
        ),
        valor_novo={"chave": chave, "valor": mask_value(chave, valor)},
        usuario=usuario, request=request,
    )
    return RedirectResponse("/configuracoes/", status_code=303)


@router.post("/{item_id}/delete", include_in_schema=False)
def delete(
    request: Request,
    item_id: int,
    usuario: Usuario = Depends(require_permission("configuracao.excluir")),
    db: Session = Depends(get_session),
):
    """Exclusão lógica de uma chave (§36.7) — some da tela e o get_config
    volta a usar o valor padrão; o histórico permanece na auditoria."""
    item = db.get(Configuracao, item_id)
    if item is not None and item.deleted_at is None and item.empresa_id == usuario.empresa_id:
        anterior = get_config(db, item.chave, empresa_id=usuario.empresa_id)
        item.deleted_at = utcnow()
        item.deleted_by = usuario.id
        db.commit()
        invalidate_config(usuario.empresa_id, item.chave)
        record_audit(db, tabela="configuracoes", acao="DELETE", registro_id=item.id,
                     valor_anterior={"chave": item.chave,
                                     "valor": mask_value(item.chave, anterior)},
                     usuario=usuario, request=request)
    return RedirectResponse("/configuracoes/", status_code=303)


# --- Aparência (template AdminLTE por empresa — §22, §24, §37) ---


@router.get("/aparencia", include_in_schema=False)
def aparencia_form(
    request: Request,
    usuario: Usuario = Depends(require_permission("configuracao.editar")),
    db: Session = Depends(get_session),
):
    from app.core.appearance import get_appearance

    return render(request, "configuracoes/aparencia.html", usuario,
                  page_title="Aparência", a=get_appearance(db, usuario.empresa_id))


@router.post("/aparencia", include_in_schema=False)
def aparencia_salvar(
    request: Request,
    brand_nome: str = Form(""),
    tema: str = Form("claro"),
    sidebar_tema: str = Form("auto"),
    layout_fixo: str = Form("nao"),
    header_fixo: str = Form("nao"),
    footer_fixo: str = Form("nao"),
    sidebar_mini: str = Form("nao"),
    sidebar_colapsada: str = Form("nao"),
    cor_primaria: str = Form(""),
    cor_padrao: str = Form("nao"),
    logo: UploadFile | None = File(None),
    remover_logo: str = Form("nao"),
    usuario: Usuario = Depends(require_permission("configuracao.editar")),
    db: Session = Depends(get_session),
):
    from app.core.appearance import APPEARANCE_KEYS, get_appearance
    from app.core.storage import save_upload

    antes = get_appearance(db, usuario.empresa_id)

    valores = {
        "brand_nome": brand_nome.strip(),
        "tema": tema, "sidebar_tema": sidebar_tema,
        "layout_fixo": layout_fixo, "header_fixo": header_fixo,
        "footer_fixo": footer_fixo, "sidebar_mini": sidebar_mini,
        "sidebar_colapsada": sidebar_colapsada,
        "cor_primaria": "" if cor_padrao == "sim" else cor_primaria.strip(),
    }
    for chave, valor in valores.items():
        set_config(db, chave, valor, usuario.empresa_id, updated_by=usuario.id)

    if remover_logo == "sim":
        set_config(db, "logo_arquivo_id", "", usuario.empresa_id, updated_by=usuario.id)
    elif logo is not None and logo.filename:
        try:
            arquivo = save_upload(db, logo, usuario.empresa_id, "sistema",
                                  created_by=usuario.id)
            set_config(db, "logo_arquivo_id", str(arquivo.id),
                       usuario.empresa_id, updated_by=usuario.id)
        except ValueError:
            pass  # tipo/tamanho inválido: mantém a logo atual

    depois = get_appearance(db, usuario.empresa_id)
    record_audit(db, tabela="configuracoes", acao="UPDATE", registro_id=None,
                 valor_anterior={k: antes.get(k) for k in APPEARANCE_KEYS},
                 valor_novo={k: depois.get(k) for k in APPEARANCE_KEYS},
                 usuario=usuario, request=request)
    return RedirectResponse("/configuracoes/aparencia", status_code=303)
