"""HealthService (§39.21) — verificação das dependências.

Separa o que é **essencial** (sem isso a aplicação não atende) do que é
**opcional** (degrada, mas atende). Só o essencial derruba o /ready.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings

ESPACO_MINIMO_MB = 100


def _ok(detalhe: str = "") -> dict:
    return {"status": "ok", "detalhe": detalhe}


def _erro(detalhe: str) -> dict:
    return {"status": "error", "detalhe": detalhe}


def verificar_dependencias(db: Session) -> tuple[dict, bool]:
    """Devolve (checagens, pronto). `pronto` considera só o essencial."""
    checagens: dict[str, dict] = {}

    # Banco — essencial
    try:
        db.execute(select(1))
        checagens["database"] = _ok(db.bind.dialect.name if db.bind else "")
    except Exception as erro:  # noqa: BLE001
        checagens["database"] = _erro(str(erro)[:200])

    # Cache — opcional: sem Redis o CacheService cai para memória (§26)
    try:
        from app.core.cache import cache

        checagens["cache"] = {
            "status": "ok" if cache.distribuido else "degraded",
            "detalhe": "redis" if cache.distribuido else "memória (não compartilhado)",
        }
    except Exception as erro:  # noqa: BLE001
        checagens["cache"] = {"status": "degraded", "detalhe": str(erro)[:200]}

    # Armazenamento — essencial: uploads precisam de pasta gravável (§20)
    try:
        pasta = Path(settings.upload_dir)
        pasta.mkdir(parents=True, exist_ok=True)
        teste = pasta / ".health"
        teste.write_text("ok", encoding="utf-8")
        teste.unlink()
        checagens["storage"] = _ok(str(pasta))
    except Exception as erro:  # noqa: BLE001
        checagens["storage"] = _erro(str(erro)[:200])

    # Disco — opcional, mas avisa antes de encher
    try:
        livre_mb = shutil.disk_usage(settings.upload_dir).free // (1024 * 1024)
        checagens["disk"] = {
            "status": "ok" if livre_mb > ESPACO_MINIMO_MB else "degraded",
            "detalhe": f"{livre_mb} MB livres",
        }
    except Exception as erro:  # noqa: BLE001
        checagens["disk"] = {"status": "degraded", "detalhe": str(erro)[:200]}

    essenciais = ("database", "storage")
    pronto = all(checagens[nome]["status"] == "ok" for nome in essenciais)
    return checagens, pronto
