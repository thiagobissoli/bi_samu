"""Agendamento da cópia de segurança (APScheduler).

Roda uma vez por dia na hora configurada, expurga as cópias antigas e
guarda o resultado em backup_status / backup_ultima, que a tela exibe.
"""

from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config_service import get_config, set_config
from app.core.database import SessionLocal
from app.modules.backup.constants import (CONFIG_ATIVO, CONFIG_HORA,
                                          CONFIG_STATUS, CONFIG_ULTIMA)

log = logging.getLogger("backup")

JOB_ID = "backup_diario"
_scheduler: BackgroundScheduler | None = None


def _obter_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(
            timezone="America/Sao_Paulo",
            job_defaults={"coalesce": True, "max_instances": 1,
                          "misfire_grace_time": 7200})
        _scheduler.start()
    return _scheduler


def executar_backup(empresa_id: int = 1) -> str:
    """Job agendado — nunca lança (falha vira status na tela)."""
    from app.modules.backup.service import BackupError, executar

    db = SessionLocal()
    try:
        set_config(db, CONFIG_ULTIMA,
                   datetime.now().strftime("%d/%m/%Y %H:%M"), empresa_id)
        arquivo = executar(db, empresa_id)
        tamanho = arquivo.stat().st_size / 1024 / 1024
        status = f"sucesso — {arquivo.name} ({tamanho:.1f} MB)"
    except BackupError as exc:
        status = f"erro: {exc}"[:500]
    except Exception as exc:  # noqa: BLE001 — job não derruba o scheduler
        log.exception("Backup automático falhou")
        status = f"erro inesperado: {exc}"[:500]
    try:
        set_config(db, CONFIG_STATUS, status, empresa_id)
    finally:
        db.close()
    log.info("Backup: %s", status)
    return status


def sincronizar(empresa_id: int = 1) -> str | None:
    """(Re)cria o job conforme a configuração; devolve a descrição ou None."""
    db = SessionLocal()
    try:
        ativo = get_config(db, CONFIG_ATIVO, empresa_id=empresa_id) == "1"
        hora = get_config(db, CONFIG_HORA, "02:00", empresa_id) or "02:00"
    finally:
        db.close()

    scheduler = _obter_scheduler()
    if scheduler.get_job(JOB_ID):
        scheduler.remove_job(JOB_ID)
    if not ativo:
        log.info("Backup automático desativado")
        return None

    try:
        h, m = hora.split(":")
        gatilho = CronTrigger(hour=int(h), minute=int(m))
    except ValueError:
        gatilho, hora = CronTrigger(hour=2, minute=0), "02:00"
    scheduler.add_job(executar_backup, gatilho, id=JOB_ID,
                      kwargs={"empresa_id": empresa_id}, replace_existing=True)
    log.info("Backup automático agendado: diariamente às %s", hora)
    return f"diariamente às {hora}"


def proxima_execucao() -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job(JOB_ID)
    if job is None or job.next_run_time is None:
        return None
    return job.next_run_time.strftime("%d/%m/%Y %H:%M")
