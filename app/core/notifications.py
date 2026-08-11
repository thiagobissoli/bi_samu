"""Notificações do sistema (§21)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Notificacao


def notify(
    db: Session,
    usuario_id: int,
    titulo: str,
    mensagem: str,
    tipo: str = "info",
    empresa_id: int = 1,
) -> Notificacao:
    item = Notificacao(
        empresa_id=empresa_id, usuario_id=usuario_id,
        titulo=titulo, mensagem=mensagem, tipo=tipo,
    )
    db.add(item)
    db.commit()
    return item


def unread_count(db: Session, usuario_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(Notificacao).where(
            Notificacao.usuario_id == usuario_id,
            Notificacao.lida.is_(False),
            Notificacao.deleted_at.is_(None),
        )
    ) or 0
