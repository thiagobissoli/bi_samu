"""Avisos do fluxo da NCPS: notificação no sistema (sino) e e-mail.

Três momentos:
    nova_ncps            quem faz a triagem daquele tipo é avisado de que
                         chegou uma notificação
    encaminhada_ao_setor os analistas do setor recebem a NCPS para análise
    retorno_notificante  quem notificou (identificado) vê a mudança de status

Os e-mails nunca trazem o relato nem dados do paciente — só o número, o tipo
e o link para abrir no sistema (onde valem as regras de acesso). Nas
sigilosas nem o tipo aparece.

O e-mail sai numa thread: com vários destinatários e SMTP lento, a tela da
notificação não pode esperar. Sem SMTP configurado, send_mail registra o
conteúdo nos Logs (desenvolvimento).
"""

from __future__ import annotations

import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ncps import constants as cat

log = logging.getLogger("uvicorn.error")


# ------------------------------------------------------------------ destinatários

def responsaveis_triagem(db: Session, n) -> list:
    """Usuários ativos que fazem a triagem desta NCPS."""
    from app.models import Perfil, Permissao, Usuario
    from app.models.entities import perfis_permissoes, usuarios_perfis
    from app.modules.ncps.permissions import TRIAGEM

    permissao = "ncps.sigilosas" if n.confidencial else TRIAGEM.get(n.natureza)
    if not permissao:
        return []
    return list(db.scalars(
        select(Usuario).join(usuarios_perfis).join(
            Perfil, Perfil.id == usuarios_perfis.c.perfil_id).join(
            perfis_permissoes, perfis_permissoes.c.perfil_id == Perfil.id).join(
            Permissao, Permissao.id == perfis_permissoes.c.permissao_id).where(
            Permissao.codigo == permissao, Perfil.ativo.is_(True),
            Perfil.deleted_at.is_(None), Usuario.ativo.is_(True),
            Usuario.deleted_at.is_(None), Usuario.empresa_id == n.empresa_id,
        ).distinct().order_by(Usuario.nome)))


# ------------------------------------------------------------------ envio

def _link(base_url: str | None, caminho: str) -> str:
    return (base_url or "").rstrip("/") + caminho


def _corpo(titulo: str, linhas: list[str], link: str, rotulo_link: str) -> str:
    from html import escape

    from app.core.config import settings

    itens = "".join(f"<p style='margin:0 0 8px'>{escape(l)}</p>" for l in linhas)
    botao = (f"<p style='margin:18px 0'><a href='{escape(link)}' style='background:#0d6efd;"
             f"color:#fff;padding:10px 16px;border-radius:6px;text-decoration:none'>"
             f"{escape(rotulo_link)}</a></p>") if link.startswith("http") else ""
    return (f"<div style='font-family:Arial,sans-serif;font-size:14px;color:#222'>"
            f"<h2 style='font-size:17px'>{escape(titulo)}</h2>{itens}{botao}"
            f"<p style='color:#777;font-size:12px'>{escape(settings.app_name)} — mensagem "
            f"automática. Por sigilo, o relato não é enviado por e-mail.</p></div>")


def _enviar(mensagens: list[tuple[str, str, str]], empresa_id: int) -> None:
    """Envia [(para, assunto, corpo)] numa thread, com sessão própria."""
    if not mensagens:
        return

    def trabalho():
        from app.core.database import SessionLocal
        from app.core.mail import send_mail

        db = SessionLocal()
        try:
            for para, assunto, corpo in mensagens:
                send_mail(db, para, assunto, corpo, empresa_id=empresa_id)
        except Exception:  # noqa: BLE001 — e-mail nunca derruba o fluxo
            log.exception("NCPS: falha ao enviar avisos por e-mail")
        finally:
            db.close()

    threading.Thread(target=trabalho, name="ncps-avisos", daemon=True).start()


def _avisar(db: Session, usuarios, titulo: str, mensagem: str, tipo: str,
            assunto: str, linhas: list[str], link: str, rotulo_link: str,
            empresa_id: int, excluir_id: int | None = None) -> int:
    from app.core.notifications import notify

    emails = []
    enviados = 0
    for u in usuarios:
        if excluir_id is not None and u.id == excluir_id:
            continue      # quem fez a ação não precisa ser avisado dela
        notify(db, u.id, titulo, mensagem, tipo=tipo, empresa_id=empresa_id)
        if u.email:
            emails.append((u.email, assunto,
                           _corpo(titulo, linhas, link, rotulo_link)))
        enviados += 1
    _enviar(emails, empresa_id)
    return enviados


# ------------------------------------------------------------------ momentos

def nova_ncps(db: Session, n, base_url: str | None = None,
              autor_id: int | None = None) -> int:
    """Chegou uma NCPS: avisa quem faz a triagem daquele tipo."""
    if n.confidencial:
        titulo = f"Nova NCPS sigilosa #{n.id}"
        mensagem = ("Uma notificação sigilosa (violência, agressão ou assédio) "
                    "aguarda a Comissão de Integridade.")
        linhas = ["Uma notificação sigilosa foi registrada e aguarda a "
                  "Comissão de Integridade."]
    else:
        tipo = cat.NATUREZA.get(n.natureza, n.natureza)
        titulo = f"Nova NCPS #{n.id} aguardando triagem"
        mensagem = f"{tipo}. Faça a triagem e encaminhe ao setor responsável."
        linhas = [f"Tipo: {tipo}.", "A notificação aguarda a triagem e o "
                  "encaminhamento ao setor responsável."]
    return _avisar(db, responsaveis_triagem(db, n), titulo, mensagem, "warning",
                   titulo, linhas, _link(base_url, f"/ncps/{n.id}"),
                   "Abrir a NCPS", n.empresa_id, excluir_id=autor_id)


def encaminhada_ao_setor(db: Session, n, setor, base_url: str | None = None,
                         autor_id: int | None = None) -> int:
    """A triagem encaminhou a NCPS: avisa os analistas do setor."""
    titulo = f"NCPS #{n.id} encaminhada ao setor {setor.nome}"
    mensagem = ("Seu setor é o responsável pela análise desta notificação. "
                "Acesse NCPS para registrar a análise e o plano de ação.")
    linhas = [f"Tipo: {cat.NATUREZA.get(n.natureza, n.natureza)}.",
              f"O setor {setor.nome} é o responsável pela análise e pelo plano "
              "de ação."]
    return _avisar(db, setor.usuarios, titulo, mensagem, "warning", titulo,
                   linhas, _link(base_url, f"/ncps/{n.id}"), "Analisar a NCPS",
                   n.empresa_id, excluir_id=autor_id)


def retorno_notificante(db: Session, n, base_url: str | None = None) -> int:
    """A situação mudou: avisa quem notificou de forma identificada."""
    from app.models import Usuario

    if not n.notificante_id or n.anonima:
        return 0
    notificante = db.get(Usuario, n.notificante_id)
    if notificante is None or not notificante.ativo:
        return 0
    rotulo, texto, _etapa = cat.SITUACAO_ACOMPANHAMENTO.get(
        n.status, ("Em análise", "", 2))
    titulo = f"Sua NCPS #{n.id}: {rotulo}"
    tipo = "success" if n.status in ("2", "3", "4") else "info"
    return _avisar(db, [notificante], titulo, texto, tipo, titulo,
                   [texto, "Obrigado por notificar: é assim que o serviço aprende "
                           "com os eventos."],
                   _link(base_url, "/ncps/notificar"), "Ver minhas notificações",
                   n.empresa_id)
