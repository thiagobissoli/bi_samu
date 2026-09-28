"""Tarefas assíncronas (§27) — Celery.

Rodar o worker (com o venv ativo, na raiz do projeto):

    celery -A app.core.tasks worker --loglevel=info

E o agendador (§39.19), para as tarefas periódicas:

    celery -A app.core.tasks beat --loglevel=info

Sem broker disponível, `enfileirar()` executa a tarefa na hora, de forma
síncrona: desenvolvimento não fica travado por falta de Redis.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "samu",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=settings.timezone,
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,
    broker_connection_retry_on_startup=True,
)

# Tarefas periódicas (§39.19)
celery_app.conf.beat_schedule = {
    "limpar-sessoes-expiradas": {
        "task": "app.core.tasks.limpar_sessoes_expiradas",
        "schedule": crontab(minute=0, hour="*/6"),
    },
}


def enfileirar(tarefa, *args, **kwargs):
    """Envia para a fila; se o broker estiver fora, executa na hora.

    Devolve o AsyncResult (assíncrono) ou o próprio retorno (síncrono).
    """
    try:
        return tarefa.delay(*args, **kwargs)
    except Exception:  # noqa: BLE001 — sem broker, roda inline
        return tarefa(*args, **kwargs)


# --- Tarefas ---


@celery_app.task(name="app.core.tasks.enviar_email")
def enviar_email(destinatario: str, assunto: str, corpo: str, empresa_id: int = 1) -> bool:
    """Envio de e-mail fora do ciclo da requisição (§27)."""
    from app.core.database import SessionLocal
    from app.core.mail import send_mail

    db = SessionLocal()
    try:
        return send_mail(db, destinatario, assunto, corpo, empresa_id)
    finally:
        db.close()


@celery_app.task(name="app.core.tasks.notificar_usuarios")
def notificar_usuarios(usuario_ids: list[int], titulo: str, mensagem: str,
                       tipo: str = "info", empresa_id: int = 1) -> int:
    """Notificação em massa (§21) sem travar a resposta."""
    from app.core.database import SessionLocal
    from app.core.notifications import notify

    db = SessionLocal()
    try:
        for usuario_id in usuario_ids:
            notify(db, usuario_id, titulo, mensagem, tipo, empresa_id)
        return len(usuario_ids)
    finally:
        db.close()


@celery_app.task(name="app.core.tasks.limpar_sessoes_expiradas")
def limpar_sessoes_expiradas() -> int:
    """Housekeeping periódico: remove sessões e tokens vencidos (§6)."""
    from sqlalchemy import delete

    from app.core.database import SessionLocal, utcnow
    from app.models import Sessao, TokenSeguranca

    db = SessionLocal()
    try:
        agora = utcnow()
        removidas = db.execute(
            delete(Sessao).where(Sessao.expires_at < agora)
        ).rowcount or 0
        removidas += db.execute(
            delete(TokenSeguranca).where(TokenSeguranca.expira_em < agora)
        ).rowcount or 0
        db.commit()
        return removidas
    finally:
        db.close()
