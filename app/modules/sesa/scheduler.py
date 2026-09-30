"""Job diário dos avisos de vencimento das certidões (APScheduler).

Roda às 07:00 (America/Sao_Paulo) e também 2 minutos depois do boot, para
não perder o dia se o servidor estava fora do ar no horário. Repetir não
causa e-mail duplicado: cada certidão é avisada uma vez (avisos.py).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.database import SessionLocal

log = logging.getLogger("uvicorn.error")
JOB_ID = "sesa_avisos_vencimento"
_scheduler: BackgroundScheduler | None = None


def executar() -> int:
    """Avisa, em todas as empresas com envios à SESA cadastrados."""
    from app.modules.sesa.avisos import avisar_vencimentos
    from app.modules.sesa.models import SesaObrigacao
    from app.modules.sesa.routes import _hoje

    db = SessionLocal()
    total = 0
    try:
        empresas = set(db.scalars(select(SesaObrigacao.empresa_id).distinct()))
        for empresa_id in empresas:
            total += avisar_vencimentos(db, empresa_id, _hoje(db, empresa_id))
    except Exception:  # noqa: BLE001 — o job nunca derruba o servidor
        log.exception("SESA: falha no job de avisos de vencimento")
    finally:
        db.close()
    return total


def iniciar() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(
        timezone="America/Sao_Paulo",
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600})
    _scheduler.add_job(executar, CronTrigger(hour=7, minute=0), id=JOB_ID,
                       replace_existing=True)
    _scheduler.add_job(executar, "date", id=JOB_ID + "_boot",
                       run_date=datetime.now(ZoneInfo("America/Sao_Paulo"))
                       + timedelta(minutes=2))
    _scheduler.start()
