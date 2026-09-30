"""Aviso de certidão perto de vencer: sino + e-mail para quem anexa certidões.

Roda uma vez por dia (scheduler.py). Cada certidão (item + validade) é
avisada uma única vez, quando faltam `sesa_aviso_vencimento_dias` dias ou
menos — o registro em SesaAvisoVencimento impede a repetição. Se uma
certidão nova for anexada antes, a validade mais recente muda e não há aviso.
"""

from __future__ import annotations

import logging
from datetime import date
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config_service import get_config
from app.modules.sesa import service
from app.modules.sesa.models import SesaAvisoVencimento

log = logging.getLogger("uvicorn.error")
PERMISSAO = "sesa.anexar"


def responsaveis(db: Session, empresa_id: int) -> list:
    """Usuários ativos com permissão de anexar certidões."""
    from app.models import Perfil, Permissao, Usuario
    from app.models.entities import perfis_permissoes, usuarios_perfis

    return list(db.scalars(
        select(Usuario).join(usuarios_perfis).join(
            Perfil, Perfil.id == usuarios_perfis.c.perfil_id).join(
            perfis_permissoes, perfis_permissoes.c.perfil_id == Perfil.id).join(
            Permissao, Permissao.id == perfis_permissoes.c.permissao_id).where(
            Permissao.codigo == PERMISSAO, Perfil.ativo.is_(True),
            Perfil.deleted_at.is_(None), Usuario.ativo.is_(True),
            Usuario.deleted_at.is_(None), Usuario.empresa_id == empresa_id,
        ).distinct().order_by(Usuario.nome)))


def _quando(dias: int) -> str:
    if dias < 0:
        return f"venceu há {-dias} dia(s)"
    if dias == 0:
        return "vence hoje"
    return f"vence em {dias} dia(s)"


def _linha(c: dict) -> str:
    orgao = f" ({c['item'].orgao})" if c["item"].orgao else ""
    return (f"{c['item'].nome}{orgao}: válida até {c['valida_ate']:%d/%m/%Y} — "
            f"{_quando(c['dias'])}")


def _corpo(linhas: list[str], link: str) -> str:
    from app.core.config import settings

    itens = "".join(f"<li>{escape(l)}</li>" for l in linhas)
    botao = (f"<p style='margin:18px 0'><a href='{escape(link)}' style='background:#0d6efd;"
             f"color:#fff;padding:10px 16px;border-radius:6px;text-decoration:none'>"
             f"Abrir as certidões</a></p>") if link.startswith("http") else ""
    return (f"<div style='font-family:Arial,sans-serif;font-size:14px;color:#222'>"
            f"<h2 style='font-size:17px'>Certidões para a SESA perto de vencer</h2>"
            f"<ul>{itens}</ul><p>Emita a nova certidão no portal e anexe no sistema "
            f"antes do próximo envio.</p>{botao}"
            f"<p style='color:#777;font-size:12px'>{escape(settings.app_name)} — "
            f"mensagem automática.</p></div>")


def avisar_vencimentos(db: Session, empresa_id: int, hoje: date) -> int:
    """Envia os avisos pendentes num único aviso por pessoa. Devolve quantas
    certidões foram avisadas."""
    from app.core.mail import send_mail
    from app.core.notifications import notify

    pendentes = service.avisos_pendentes(db, empresa_id, hoje)
    if not pendentes:
        return 0
    pessoas = responsaveis(db, empresa_id)
    linhas = [_linha(c) for c in pendentes]
    base = (get_config(db, service.CONFIG_ENDERECO, "", empresa_id) or "").rstrip("/")
    link = f"{base}/sesa/certidoes" if base else ""
    titulo = (f"Certidão {pendentes[0]['item'].nome} perto de vencer" if len(pendentes) == 1
              else f"{len(pendentes)} certidões para a SESA perto de vencer")
    corpo = _corpo(linhas, link)
    for u in pessoas:
        notify(db, u.id, titulo, "; ".join(linhas)[:480], tipo="warning",
               empresa_id=empresa_id)
        if u.email:
            try:
                send_mail(db, u.email, titulo, corpo, empresa_id=empresa_id)
            except Exception:  # noqa: BLE001 — um e-mail com falha não trava os outros
                log.exception("SESA: falha ao enviar aviso de vencimento a %s", u.email)
    for c in pendentes:
        db.add(SesaAvisoVencimento(empresa_id=empresa_id, item_id=c["item"].id,
                                   valida_ate=c["valida_ate"], destinatarios=len(pessoas)))
    db.commit()
    log.info("SESA: aviso de vencimento de %d certidão(ões) para %d pessoa(s)",
             len(pendentes), len(pessoas))
    return len(pendentes)
