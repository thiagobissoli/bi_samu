"""CacheService (§26, §39.11) — Redis com degradação para memória.

Sem Redis disponível, o cache continua funcionando **em processo**: a
aplicação nunca deixa de subir por causa do cache. Mas atenção — com mais de
um worker, o cache em memória é por processo, então invalidação num worker não
alcança os outros. Em produção, configure `REDIS_URL`.

    from app.core.cache import cache

    cache.set("menu:1", dados, ttl=300)
    dados = cache.get("menu:1")
    dados = cache.remember("menu:1", 300, lambda: montar_menu())
    cache.invalidate("menu:*")
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from app.core.config import settings


class CacheService:
    def __init__(self, url: str | None = None, prefixo: str = "saas"):
        self.prefixo = prefixo
        self._memoria: dict[str, tuple[float | None, Any]] = {}
        self._redis = None
        self._url = url or settings.redis_url
        self._conectar()

    # --- Conexão ---

    def _conectar(self) -> None:
        try:
            import redis

            cliente = redis.Redis.from_url(self._url, socket_connect_timeout=1)
            cliente.ping()
            self._redis = cliente
        except Exception:  # noqa: BLE001 — sem Redis, segue em memória
            self._redis = None

    @property
    def distribuido(self) -> bool:
        """True quando o cache é compartilhado entre workers (Redis ativo)."""
        return self._redis is not None

    def _chave(self, chave: str) -> str:
        return f"{self.prefixo}:{chave}"

    # --- Operações (§39.11) ---

    def get(self, chave: str, padrao: Any = None) -> Any:
        if self._redis is not None:
            try:
                bruto = self._redis.get(self._chave(chave))
                return json.loads(bruto) if bruto is not None else padrao
            except Exception:  # noqa: BLE001
                self._redis = None

        item = self._memoria.get(chave)
        if item is None:
            return padrao
        expira, valor = item
        if expira is not None and expira < time.time():
            self._memoria.pop(chave, None)
            return padrao
        return valor

    def set(self, chave: str, valor: Any, ttl: int | None = 300) -> None:
        if self._redis is not None:
            try:
                dados = json.dumps(valor, ensure_ascii=False, default=str)
                if ttl:
                    self._redis.setex(self._chave(chave), ttl, dados)
                else:
                    self._redis.set(self._chave(chave), dados)
                return
            except Exception:  # noqa: BLE001
                self._redis = None
        self._memoria[chave] = (time.time() + ttl if ttl else None, valor)

    def delete(self, chave: str) -> None:
        if self._redis is not None:
            try:
                self._redis.delete(self._chave(chave))
            except Exception:  # noqa: BLE001
                self._redis = None
        self._memoria.pop(chave, None)

    def remember(self, chave: str, ttl: int, produtor: Callable[[], Any]) -> Any:
        """Devolve do cache ou calcula, guarda e devolve."""
        valor = self.get(chave, _AUSENTE)
        if valor is not _AUSENTE:
            return valor
        valor = produtor()
        self.set(chave, valor, ttl)
        return valor

    def invalidate(self, padrao: str = "*") -> int:
        """Remove por padrão glob (ex.: `config:1:*`). Devolve quantas chaves."""
        removidas = 0
        if self._redis is not None:
            try:
                chaves = list(self._redis.scan_iter(self._chave(padrao)))
                if chaves:
                    removidas = self._redis.delete(*chaves)
            except Exception:  # noqa: BLE001
                self._redis = None

        import fnmatch

        for chave in [k for k in self._memoria if fnmatch.fnmatch(k, padrao)]:
            self._memoria.pop(chave, None)
            removidas += 1
        return removidas

    def clear(self) -> None:
        self.invalidate("*")


class _Ausente:
    """Sentinela: distingue 'não está no cache' de 'está e vale None'."""


_AUSENTE = _Ausente()

cache = CacheService()
