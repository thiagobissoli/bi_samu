"""ConfigService (§39.12) — leitura/gravação de configurações com cache.

Uso:
    from app.core.config_service import get_config, set_config
    host = get_config(db, "smtp_host", empresa_id=usuario.empresa_id)

O cache é por processo e invalidado a cada gravação. Em produção com
múltiplos workers, considerar cache compartilhado via Redis (§26).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_value, encrypt_value, is_sensitive
from app.models import Configuracao

_cache: dict[tuple[int, str], str | None] = {}


def get_config(
    db: Session,
    chave: str,
    default: str | None = None,
    empresa_id: int = 1,
) -> str | None:
    key = (empresa_id, chave)
    if key in _cache:
        return _cache[key] if _cache[key] is not None else default

    item = db.scalar(select(Configuracao).where(
        Configuracao.empresa_id == empresa_id,
        Configuracao.chave == chave,
        Configuracao.deleted_at.is_(None),
    ))
    valor = decrypt_value(item.valor) if item is not None and item.valor else None
    _cache[key] = valor
    return valor if valor is not None else default


def set_config(
    db: Session,
    chave: str,
    valor: str | None,
    empresa_id: int = 1,
    updated_by: int | None = None,
) -> Configuracao:
    """Grava a configuração (criptografando chaves sensíveis) e invalida o cache."""
    stored = valor
    if valor and is_sensitive(chave):
        stored = encrypt_value(valor)

    item = db.scalar(select(Configuracao).where(
        Configuracao.empresa_id == empresa_id,
        Configuracao.chave == chave,
        Configuracao.deleted_at.is_(None),
    ))
    if item is None:
        item = Configuracao(empresa_id=empresa_id, chave=chave, valor=stored,
                            created_by=updated_by)
        db.add(item)
    else:
        item.valor = stored
        item.updated_by = updated_by
    db.commit()
    invalidate_config(empresa_id, chave)
    return item


def invalidate_config(empresa_id: int | None = None, chave: str | None = None) -> None:
    if empresa_id is None:
        _cache.clear()
    elif chave is None:
        for key in [k for k in _cache if k[0] == empresa_id]:
            _cache.pop(key, None)
    else:
        _cache.pop((empresa_id, chave), None)
