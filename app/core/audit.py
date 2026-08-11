"""Auditoria (§11) — registrar tudo, nunca apagar."""

from __future__ import annotations

import json

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import Auditoria, Usuario


def _serialize(values: dict | None) -> str | None:
    if values is None:
        return None
    return json.dumps(values, ensure_ascii=False, default=str)


def record_audit(
    db: Session,
    *,
    tabela: str,
    acao: str,
    registro_id: int | None = None,
    valor_anterior: dict | None = None,
    valor_novo: dict | None = None,
    usuario: Usuario | None = None,
    request: Request | None = None,
) -> None:
    db.add(
        Auditoria(
            empresa_id=usuario.empresa_id if usuario else 1,
            usuario_id=usuario.id if usuario else None,
            usuario_nome=usuario.nome if usuario else None,
            tabela=tabela,
            registro_id=registro_id,
            acao=acao,
            valor_anterior=_serialize(valor_anterior),
            valor_novo=_serialize(valor_novo),
            ip=request.client.host if request and request.client else None,
            user_agent=(request.headers.get("user-agent", "")[:500] if request else None),
        )
    )
    db.commit()


def snapshot(obj, fields: list[str]) -> dict:
    """Captura valores de um modelo para valor_anterior/valor_novo."""
    return {f: getattr(obj, f, None) for f in fields}
