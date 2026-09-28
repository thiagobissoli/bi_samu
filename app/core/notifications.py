"""NotificationService (§21, §39.8) — sistema, e-mail, push e WhatsApp.

Um único ponto de envio, vários canais:

    notify(db, usuario.id, "Fatura vencida", "A fatura #12 venceu.",
           tipo="warning", canais=("sistema", "email"))

O canal `sistema` sempre grava no banco (é o sino da navbar). Os demais são
best-effort: se o SMTP ou o provedor HTTP não estiver configurado, o envio é
registrado nos Logs e **não derruba a operação** — notificação não pode
quebrar o fluxo de negócio que a disparou.

Push e WhatsApp usam provedores HTTP genéricos, configurados em Configurações
(§22), para não amarrar o framework a um fornecedor:

    push_url        / push_token
    whatsapp_url    / whatsapp_token
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Notificacao, Usuario

CANAIS_PADRAO = ("sistema",)
TIMEOUT_HTTP = 10


# --- Canal: sistema (§21) ---


def _canal_sistema(db: Session, usuario: Usuario, titulo: str, mensagem: str,
                   tipo: str, empresa_id: int) -> Notificacao:
    item = Notificacao(
        empresa_id=empresa_id, usuario_id=usuario.id,
        titulo=titulo, mensagem=mensagem, tipo=tipo,
    )
    db.add(item)
    db.commit()
    return item


# --- Canal: e-mail (§39.9) ---


def _canal_email(db: Session, usuario: Usuario, titulo: str, mensagem: str,
                 tipo: str, empresa_id: int) -> bool:
    if not usuario.email:
        return False
    corpo = (
        f"<h3>{titulo}</h3><p>{mensagem}</p>"
        "<hr><p style='color:#888;font-size:12px'>"
        "Mensagem automática — não responda este e-mail.</p>"
    )
    # Fora do ciclo da requisição quando há broker (§27).
    try:
        from app.core.tasks import enfileirar, enviar_email

        resultado = enfileirar(enviar_email, usuario.email, titulo, corpo, empresa_id)
        # Rodou inline (sem broker): sabemos se o SMTP entregou. Enfileirado:
        # o resultado só existe depois, então "True" significa "aceito na fila".
        return resultado if isinstance(resultado, bool) else True
    except Exception:  # noqa: BLE001 — sem Celery, envia direto
        from app.core.mail import send_mail

        return send_mail(db, usuario.email, titulo, corpo, empresa_id)


# --- Canais HTTP genéricos: push e WhatsApp ---


def _enviar_http(db: Session, canal: str, url: str, token: str | None,
                 payload: dict) -> bool:
    from app.core.logs import write_log

    requisicao = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=TIMEOUT_HTTP) as resposta:
            return 200 <= resposta.status < 300
    except (urllib.error.URLError, OSError, ValueError) as erro:
        write_log(db, "WARNING", "notificacoes",
                  f"Falha no canal {canal}: {erro}")
        return False


def _canal_http(db: Session, canal: str, usuario: Usuario, titulo: str,
                mensagem: str, tipo: str, empresa_id: int) -> bool:
    from app.core.config_service import get_config
    from app.core.logs import write_log

    url = get_config(db, f"{canal}_url", empresa_id=empresa_id)
    if not url:
        write_log(db, "INFO", "notificacoes",
                  f"[{canal} não configurado] {usuario.email}: {titulo} — {mensagem}")
        return False
    return _enviar_http(
        db, canal, url, get_config(db, f"{canal}_token", empresa_id=empresa_id),
        {
            "destinatario": usuario.email,
            "telefone": usuario.telefone,
            "usuario_id": usuario.id,
            "titulo": titulo,
            "mensagem": mensagem,
            "tipo": tipo,
        },
    )


CANAIS = {
    "sistema": _canal_sistema,
    "email": _canal_email,
    "push": lambda db, u, t, m, tp, e: _canal_http(db, "push", u, t, m, tp, e),
    "whatsapp": lambda db, u, t, m, tp, e: _canal_http(db, "whatsapp", u, t, m, tp, e),
}


# --- API pública ---


def notify(
    db: Session,
    usuario_id: int,
    titulo: str,
    mensagem: str,
    tipo: str = "info",
    empresa_id: int = 1,
    canais: tuple[str, ...] | list[str] = CANAIS_PADRAO,
) -> dict[str, bool]:
    """Envia pelos canais pedidos. Devolve o resultado de cada um."""
    usuario = db.get(Usuario, usuario_id)
    if usuario is None:
        return {}

    resultado: dict[str, bool] = {}
    for canal in canais:
        envio = CANAIS.get(canal)
        if envio is None:
            resultado[canal] = False
            continue
        try:
            resultado[canal] = bool(envio(db, usuario, titulo, mensagem, tipo, empresa_id))
        except Exception as erro:  # noqa: BLE001 — canal com falha não derruba o resto
            from app.core.logs import write_log

            write_log(db, "ERROR", "notificacoes", f"Canal {canal} falhou: {erro}")
            resultado[canal] = False
    return resultado


def notify_muitos(
    db: Session,
    usuario_ids: list[int],
    titulo: str,
    mensagem: str,
    tipo: str = "info",
    empresa_id: int = 1,
    canais: tuple[str, ...] | list[str] = CANAIS_PADRAO,
) -> int:
    """Notifica vários usuários. Para listas grandes, chame via Celery (§27)."""
    enviados = 0
    for usuario_id in usuario_ids:
        if notify(db, usuario_id, titulo, mensagem, tipo, empresa_id, canais):
            enviados += 1
    return enviados


def unread_count(db: Session, usuario_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(Notificacao).where(
            Notificacao.usuario_id == usuario_id,
            Notificacao.lida.is_(False),
            Notificacao.deleted_at.is_(None),
        )
    ) or 0
