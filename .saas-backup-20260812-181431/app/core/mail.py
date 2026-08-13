"""Envio de e-mail (§39.9).

SMTP configurado em Configurações (§22): smtp_host, smtp_port, smtp_user,
smtp_pass (criptografada §39.29), smtp_from. Sem SMTP, o conteúdo vai
para os Logs — comportamento de desenvolvimento.
"""

import smtplib
from email.message import EmailMessage
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from app.core.config_service import get_config
from app.core.logs import write_log


def send_mail(db: Session, to: str, subject: str, body: str,
              empresa_id: int = 1,
              anexos: list[tuple[str, bytes, str]] | None = None) -> bool:
    """Envia e-mail; retorna True se enviado via SMTP, False se caiu no log.

    `anexos` é uma lista de (nome_arquivo, conteúdo, mimetype) — usada
    pelo envio automático do Relatório de Gestão.
    """
    host = get_config(db, "smtp_host", empresa_id=empresa_id)
    if not host:
        write_log(db, "INFO", "mail",
                  f"[sem SMTP] Para: {to} | Assunto: {subject} | {body}"
                  + (f" | anexos: {[a[0] for a in anexos]}" if anexos else ""))
        return False
    try:
        user = get_config(db, "smtp_user", empresa_id=empresa_id)
        if anexos:
            msg = EmailMessage()
            msg.set_content(body, subtype="html", charset="utf-8")
            for nome, conteudo, mime in anexos:
                tipo, _, sub = mime.partition("/")
                msg.add_attachment(conteudo, maintype=tipo,
                                   subtype=sub or "octet-stream",
                                   filename=nome)
        else:
            msg = MIMEText(body, "html", "utf-8")
        msg["Subject"] = subject
        msg["From"] = (get_config(db, "smtp_from", empresa_id=empresa_id)
                       or user or "nao-responda@localhost")
        msg["To"] = to
        port = int(get_config(db, "smtp_port", "587", empresa_id) or 587)
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            if user:
                server.login(user, get_config(db, "smtp_pass", "", empresa_id) or "")
            server.send_message(msg)
        return True
    except Exception as error:  # noqa: BLE001 — falha de e-mail não derruba o fluxo
        write_log(db, "ERROR", "mail", f"Falha ao enviar para {to}: {error}")
        return False
