"""Logs da aplicação (§12) — níveis INFO/WARNING/ERROR/CRITICAL, por módulo."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import Log

_std = logging.getLogger("app")


def write_log(
    db: Session,
    nivel: str,
    modulo: str,
    mensagem: str,
    stacktrace: str | None = None,
    empresa_id: int = 1,
) -> None:
    db.add(
        Log(
            empresa_id=empresa_id,
            nivel=nivel.upper(),
            modulo=modulo,
            mensagem=mensagem,
            stacktrace=stacktrace,
        )
    )
    db.commit()
    getattr(_std, nivel.lower(), _std.info)(f"[{modulo}] {mensagem}")
