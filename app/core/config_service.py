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

from app.core.cache import cache
from app.core.crypto import decrypt_value, encrypt_value, is_sensitive
from app.models import Configuracao

TTL_CONFIG = 300


class _NaoEncontrado:
    """Distingue 'não está no cache' de 'está no cache e vale None'."""


_NAO_ENCONTRADO = _NaoEncontrado()


def _chave(empresa_id: int, chave: str) -> str:
    return f"config:{empresa_id}:{chave}"


def get_config(
    db: Session,
    chave: str,
    default: str | None = None,
    empresa_id: int = 1,
) -> str | None:
    em_cache = cache.get(_chave(empresa_id, chave), _NAO_ENCONTRADO)
    if em_cache is not _NAO_ENCONTRADO:
        return em_cache if em_cache is not None else default

    item = db.scalar(select(Configuracao).where(
        Configuracao.empresa_id == empresa_id,
        Configuracao.chave == chave,
        Configuracao.deleted_at.is_(None),
    ))
    valor = decrypt_value(item.valor) if item is not None and item.valor else None
    cache.set(_chave(empresa_id, chave), valor, TTL_CONFIG)
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
        cache.invalidate("config:*")
    elif chave is None:
        cache.invalidate(f"config:{empresa_id}:*")
    else:
        cache.delete(_chave(empresa_id, chave))

