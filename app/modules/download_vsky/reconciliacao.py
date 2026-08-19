"""Aposenta versões antigas que ficaram na base (§36.7).

Antes de a importação reconciliar, uma correção vinda do vSky entrava como
registro novo e a versão anterior continuava valendo — o mesmo empenho
contava mais de uma vez nos painéis. Isto varre o que ficou para trás.

A regra é a mesma do importador: dentro de UM arquivo, linhas repetidas em
(ocorrência, unidade) são atendimentos distintos (duas vítimas, por
exemplo); o que se repete entre importações DIFERENTES é versão velha.
Fica a da importação mais recente.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.modules.download_vsky.models import VskyRegistroAnalitico as Registro


def levantar(db: Session, empresa_id: int = 1) -> list[dict]:
    """Grupos com versões de importações diferentes, sem alterar nada."""
    grupos = db.execute(text("""
        SELECT ocorrencia, unidade
        FROM vsky_registros_analiticos
        WHERE deleted_at IS NULL AND empresa_id = :emp
          AND ocorrencia IS NOT NULL AND ocorrencia <> ''
        GROUP BY ocorrencia, unidade
        HAVING COUNT(*) > 1 AND COUNT(DISTINCT importacao_id) > 1
    """), {"emp": empresa_id}).all()

    achados = []
    for ocorrencia, unidade in grupos:
        registros = db.scalars(
            select(Registro)
            .where(Registro.empresa_id == empresa_id,
                   Registro.ocorrencia == ocorrencia,
                   Registro.deleted_at.is_(None))
            .where(Registro.unidade == unidade if unidade is not None
                   else Registro.unidade.is_(None))
            .order_by(Registro.importacao_id, Registro.id)).all()
        if len(registros) < 2:
            continue
        # A importação mais recente é a verdade; ela pode trazer mais de uma
        # linha (duas vítimas), e todas as dela ficam.
        ultima = max(r.importacao_id or 0 for r in registros)
        superados = [r for r in registros if (r.importacao_id or 0) < ultima]
        if superados:
            achados.append({
                "ocorrencia": ocorrencia, "unidade": unidade,
                "manter": [r.id for r in registros if r not in superados],
                "aposentar": [r.id for r in superados],
                "importacao_final": ultima,
            })
    return achados


def aplicar(db: Session, empresa_id: int = 1,
            usuario_id: int | None = None) -> dict:
    """Marca as versões superadas como excluídas. Devolve o que foi feito."""
    achados = levantar(db, empresa_id)
    ids = [i for grupo in achados for i in grupo["aposentar"]]
    if ids:
        agora = datetime.now(timezone.utc)
        for registro in db.scalars(select(Registro).where(Registro.id.in_(ids))):
            registro.deleted_at = agora
            registro.deleted_by = usuario_id
        db.commit()
    return {"grupos": len(achados), "registros": len(ids)}
