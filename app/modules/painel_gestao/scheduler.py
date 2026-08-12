"""Envio automático do Relatório de Gestão por e-mail (APScheduler).

O job gera o MESMO PDF do botão da tela (painel_gestao.relatorio) e o
envia em anexo para os destinatários configurados, na frequência
escolhida (semanal em dia/hora fixos, ou diário). Configuração via
ConfigService (chaves relatorio_email_*); o resultado de cada execução
fica em relatorio_email_status / relatorio_email_ultima, visível na tela
de configuração.
"""

from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config_service import get_config, set_config
from app.core.database import SessionLocal
from app.modules.painel_gestao.constants import (
    CONFIG_EMAIL_ATIVO,
    CONFIG_EMAIL_DESTINATARIOS,
    CONFIG_EMAIL_DIA,
    CONFIG_EMAIL_HORA,
    CONFIG_EMAIL_MODO,
    CONFIG_EMAIL_STATUS,
    CONFIG_EMAIL_ULTIMA,
    DIAS_SEMANA_CRON,
)

log = logging.getLogger("painel_gestao.email")

JOB_ID = "painel_gestao_relatorio_email"
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


def destinatarios(db, empresa_id: int = 1) -> list[str]:
    """Lista de e-mails configurados (separados por vírgula ou ponto e vírgula)."""
    bruto = get_config(db, CONFIG_EMAIL_DESTINATARIOS,
                       empresa_id=empresa_id) or ""
    return [e.strip() for e in bruto.replace(";", ",").split(",") if e.strip()]


def enviar_relatorio(empresa_id: int = 1) -> str:
    """Gera o relatório e envia por e-mail. Devolve o status (nunca lança)."""
    from app.core.mail import send_mail
    from app.modules.painel_gestao.relatorio import gerar_pdf
    from app.modules.painel_gestao.service import PainelGestaoService

    db = SessionLocal()
    try:
        agora = datetime.now()
        set_config(db, CONFIG_EMAIL_ULTIMA,
                   agora.strftime("%d/%m/%Y %H:%M"), empresa_id)
        emails = destinatarios(db, empresa_id)
        if not emails:
            return _status(db, empresa_id, "erro: nenhum destinatário configurado")

        dados = PainelGestaoService(empresa_id).montar()
        if not dados.get("secoes"):
            return _status(db, empresa_id,
                           "erro: sem dados importados para o relatório")
        pdf = gerar_pdf(dados, gerado_em=agora)
        semana = dados.get("semana") or "atual"
        periodo = dados.get("semana_periodo") or ""
        assunto = f"Relatório de Gestão — semana {semana}"
        corpo = (
            "<p>Segue em anexo o <strong>Relatório de Gestão</strong> "
            "do SAMU.</p>"
            f"<p>Última semana completa: <strong>{semana}</strong>"
            + (f" ({periodo})" if periodo else "") + "<br>"
            "Evolução dos gráficos de linha: últimos 12 meses.</p>"
            f"<p style='color:#6c757d;font-size:12px'>Gerado "
            f"automaticamente em {agora.strftime('%d/%m/%Y às %H:%M')}.</p>")
        anexo = [(f"relatorio-gestao-{semana}.pdf", pdf, "application/pdf")]

        enviados, falhas = [], []
        for email in emails:
            if send_mail(db, email, assunto, corpo, empresa_id, anexos=anexo):
                enviados.append(email)
            else:
                falhas.append(email)
        if enviados and not falhas:
            return _status(db, empresa_id,
                           f"sucesso — enviado para {len(enviados)} "
                           f"destinatário(s): {', '.join(enviados)}")
        if enviados:
            return _status(db, empresa_id,
                           f"parcial — enviado para {', '.join(enviados)}; "
                           f"falhou para {', '.join(falhas)}")
        return _status(db, empresa_id,
                       "erro: nenhum e-mail enviado — confira o SMTP em "
                       "Configurações (smtp_host, smtp_user, smtp_pass)")
    except Exception as exc:  # noqa: BLE001 — job não derruba o scheduler
        log.exception("Envio automático do Relatório de Gestão falhou")
        try:
            return _status(db, empresa_id, f"erro: {exc}"[:500])
        except Exception:  # noqa: BLE001
            return f"erro: {exc}"[:500]
    finally:
        db.close()


def _status(db, empresa_id: int, texto: str) -> str:
    set_config(db, CONFIG_EMAIL_STATUS, texto[:500], empresa_id)
    log.info("Relatório de Gestão por e-mail: %s", texto)
    return texto


def sincronizar(empresa_id: int = 1) -> str | None:
    """(Re)cria o job conforme a configuração; devolve a descrição ou None."""
    db = SessionLocal()
    try:
        ativo = get_config(db, CONFIG_EMAIL_ATIVO, empresa_id=empresa_id) == "1"
        modo = get_config(db, CONFIG_EMAIL_MODO, "semanal", empresa_id) or "semanal"
        dia = get_config(db, CONFIG_EMAIL_DIA, "mon", empresa_id) or "mon"
        hora = get_config(db, CONFIG_EMAIL_HORA, "07:00", empresa_id) or "07:00"
    finally:
        db.close()

    scheduler = _obter_scheduler()
    if scheduler.get_job(JOB_ID):
        scheduler.remove_job(JOB_ID)
    if not ativo:
        log.info("Envio automático do Relatório de Gestão desativado")
        return None

    try:
        h, m = hora.split(":")
        h, m = int(h), int(m)
    except ValueError:
        h, m, hora = 7, 0, "07:00"

    if modo == "diario":
        trigger = CronTrigger(hour=h, minute=m)
        descricao = f"diariamente às {hora}"
    else:
        if dia not in DIAS_SEMANA_CRON:
            dia = "mon"
        trigger = CronTrigger(day_of_week=dia, hour=h, minute=m)
        descricao = f"toda {DIAS_SEMANA_CRON[dia]} às {hora}"

    scheduler.add_job(enviar_relatorio, trigger, id=JOB_ID,
                      kwargs={"empresa_id": empresa_id}, replace_existing=True)
    log.info("Relatório de Gestão por e-mail agendado: %s", descricao)
    return descricao


def proxima_execucao() -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job(JOB_ID)
    if job is None or job.next_run_time is None:
        return None
    return job.next_run_time.strftime("%d/%m/%Y %H:%M")
