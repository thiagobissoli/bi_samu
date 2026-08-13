"""Downloads automáticos do vSky — agendamento in-process (APScheduler).

O job importa os "últimos N dias" na frequência configurada (diária em
hora fixa ou a cada N minutos). Configuração via ConfigService (chaves
vsky_auto_*); o resultado de cada execução fica em vsky_auto_status /
vsky_auto_ultima e a importação em si é registrada em vsky_importacoes,
como nas execuções manuais.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config_service import get_config, set_config
from app.core.database import SessionLocal
from app.modules.download_vsky.constants import (
    AUTO_INTERVALO_MINIMO,
    CONFIG_AUTO_ATIVO,
    CONFIG_AUTO_DIAS,
    CONFIG_AUTO_HORA,
    CONFIG_AUTO_INTERVALO,
    CONFIG_AUTO_MODO,
    CONFIG_AUTO_STATUS,
    CONFIG_AUTO_ULTIMA,
    CONFIG_BASE_URL,
    CONFIG_CLIENTE_ID,
    CONFIG_SENHA,
    CONFIG_USUARIO,
    DATA_FMT,
    DEFAULT_BASE_URL,
    STATUS_CONCLUIDO,
)

log = logging.getLogger("download_vsky.auto")

JOB_ID = "vsky_download_automatico"
_scheduler: BackgroundScheduler | None = None


def _obter_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(
            timezone="America/Sao_Paulo",
            job_defaults={"coalesce": True, "max_instances": 1,
                          "misfire_grace_time": 3600})
        _scheduler.start()
    return _scheduler


def executar_download_automatico(empresa_id: int = 1) -> None:
    """Job agendado — nunca lança (falha vira status para a tela)."""
    from app.modules.download_vsky.service import DownloadVskyService

    db = SessionLocal()
    try:
        base_url = get_config(db, CONFIG_BASE_URL, DEFAULT_BASE_URL, empresa_id)
        usuario = get_config(db, CONFIG_USUARIO, empresa_id=empresa_id)
        senha = get_config(db, CONFIG_SENHA, empresa_id=empresa_id)
        set_config(db, CONFIG_AUTO_ULTIMA,
                   datetime.now().strftime("%d/%m/%Y %H:%M"), empresa_id)
        if not (usuario and senha):
            set_config(db, CONFIG_AUTO_STATUS,
                       "erro: credenciais do vSky não configuradas", empresa_id)
            return

        dias = int(get_config(db, CONFIG_AUTO_DIAS, "2", empresa_id) or 2)
        hoje = date.today()
        inicio = hoje - timedelta(days=max(dias - 1, 0))
        # importar_periodo espera dd/mm/aaaa (DATA_FMT) — a tela converte
        # o valor do input date antes de chamar; aqui formatamos direto.
        item = DownloadVskyService(db, empresa_id).importar_periodo(
            inicio.strftime(DATA_FMT), hoje.strftime(DATA_FMT),
            base_url, usuario, senha,
            cliente_id=get_config(db, CONFIG_CLIENTE_ID, empresa_id=empresa_id))
        if item.status == STATUS_CONCLUIDO:
            set_config(db, CONFIG_AUTO_STATUS,
                       f"sucesso — {item.linhas_novas} novas, "
                       f"{item.linhas_duplicadas} duplicadas", empresa_id)
            try:  # dados novos: dashboards recarregam na próxima consulta
                from app.modules.indicadores import nucleo
                nucleo.invalidar_cache(empresa_id)
            except ImportError:
                pass
        else:
            set_config(db, CONFIG_AUTO_STATUS,
                       f"erro: {item.erro}"[:500], empresa_id)
    except Exception as exc:  # noqa: BLE001 — job não pode derrubar o scheduler
        log.exception("Download automático vSky falhou")
        try:
            set_config(db, CONFIG_AUTO_STATUS, f"erro: {exc}"[:500], empresa_id)
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()


def sincronizar(empresa_id: int = 1) -> str | None:
    """(Re)cria o job conforme a configuração; devolve a descrição ou None."""
    db = SessionLocal()
    try:
        ativo = get_config(db, CONFIG_AUTO_ATIVO, empresa_id=empresa_id) == "1"
        modo = get_config(db, CONFIG_AUTO_MODO, "diario", empresa_id) or "diario"
        hora = get_config(db, CONFIG_AUTO_HORA, "06:00", empresa_id) or "06:00"
        intervalo = int(get_config(db, CONFIG_AUTO_INTERVALO, "60",
                                   empresa_id) or 60)
    finally:
        db.close()

    scheduler = _obter_scheduler()
    if scheduler.get_job(JOB_ID):
        scheduler.remove_job(JOB_ID)
    if not ativo:
        log.info("Download automático vSky desativado")
        return None

    if modo == "intervalo":
        minutos = max(intervalo, AUTO_INTERVALO_MINIMO)
        trigger = IntervalTrigger(minutes=minutos)
        descricao = f"a cada {minutos} min"
    else:
        try:
            h, m = (hora or "06:00").split(":")
            trigger = CronTrigger(hour=int(h), minute=int(m))
        except ValueError:
            trigger = CronTrigger(hour=6, minute=0)
            hora = "06:00"
        descricao = f"diariamente às {hora}"

    scheduler.add_job(executar_download_automatico, trigger, id=JOB_ID,
                      kwargs={"empresa_id": empresa_id}, replace_existing=True)
    log.info("Download automático vSky agendado: %s", descricao)
    return descricao


def proxima_execucao() -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job(JOB_ID)
    if job is None or job.next_run_time is None:
        return None
    return job.next_run_time.strftime("%d/%m/%Y %H:%M")
