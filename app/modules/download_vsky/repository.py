"""Acesso ao banco do módulo Download vSky (§35.17).

Exclusivamente SELECT/INSERT/UPDATE/DELETE — nenhuma regra de negócio.
Todas as consultas filtram pelo tenant (§36.9) e ignoram registros com
soft delete (§36.7).
"""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.modules.download_vsky.models import VskyImportacao, VskyRegistroAnalitico


class VskyImportacaoRepository:
    def __init__(self, session: Session, empresa_id: int = 1):
        self.session = session
        self.empresa_id = empresa_id

    def _query(self):
        return (
            select(VskyImportacao)
            .where(VskyImportacao.empresa_id == self.empresa_id)
            .where(VskyImportacao.deleted_at.is_(None))
        )

    def query(self, search: str | None = None):
        query = self._query().order_by(VskyImportacao.id.desc())
        if search:
            query = query.where(or_(
                VskyImportacao.data_inicial.ilike(f"%{search}%"),
                VskyImportacao.data_final.ilike(f"%{search}%"),
                VskyImportacao.status.ilike(f"%{search}%"),
            ))
        return query

    def list(self, search: str | None = None) -> list[VskyImportacao]:
        return list(self.session.scalars(self.query(search)))

    def get(self, item_id: int) -> VskyImportacao | None:
        return self.session.scalar(self._query().where(VskyImportacao.id == item_id))

    def create(self, data: dict) -> VskyImportacao:
        item = VskyImportacao(empresa_id=self.empresa_id, **data)
        self.session.add(item)
        self.session.commit()
        return item

    def soft_delete(self, item: VskyImportacao) -> None:
        """Soft delete (§36.7) — nunca DELETE físico."""
        item.deleted_at = utcnow()
        self.session.commit()


class VskyRegistroRepository:
    def __init__(self, session: Session, empresa_id: int = 1):
        self.session = session
        self.empresa_id = empresa_id

    def _query(self):
        return (
            select(VskyRegistroAnalitico)
            .where(VskyRegistroAnalitico.empresa_id == self.empresa_id)
            .where(VskyRegistroAnalitico.deleted_at.is_(None))
        )

    def query(self, search: str | None = None):
        query = self._query().order_by(
            VskyRegistroAnalitico.data_ocorrencia_dt.desc(),
            VskyRegistroAnalitico.id.desc())
        if search:
            query = query.where(or_(
                VskyRegistroAnalitico.ocorrencia.ilike(f"%{search}%"),
                VskyRegistroAnalitico.codigo_da_ocorrencia.ilike(f"%{search}%"),
                VskyRegistroAnalitico.paciente.ilike(f"%{search}%"),
                VskyRegistroAnalitico.cidade.ilike(f"%{search}%"),
                VskyRegistroAnalitico.bairro.ilike(f"%{search}%"),
                VskyRegistroAnalitico.telefone.ilike(f"%{search}%"),
            ))
        return query

    def total(self) -> int:
        return self.session.scalar(
            select(func.count()).select_from(VskyRegistroAnalitico)
            .where(VskyRegistroAnalitico.empresa_id == self.empresa_id)
            .where(VskyRegistroAnalitico.deleted_at.is_(None))) or 0

    def contagem_por_dia(self) -> dict:
        """{data (date) -> nº de registros} pela data da ocorrência."""
        dia = func.date(VskyRegistroAnalitico.data_ocorrencia_dt)
        rows = self.session.execute(
            select(dia, func.count())
            .where(VskyRegistroAnalitico.empresa_id == self.empresa_id)
            .where(VskyRegistroAnalitico.deleted_at.is_(None))
            .where(VskyRegistroAnalitico.data_ocorrencia_dt.isnot(None))
            .group_by(dia)).all()
        resultado = {}
        for valor, n in rows:
            if isinstance(valor, str):  # SQLite devolve string ISO
                from datetime import date as _date
                valor = _date.fromisoformat(valor)
            resultado[valor] = int(n)
        return resultado

    def hashes_existentes(self, hashes: list[str], chunk: int = 500) -> set[str]:
        """Confere em lotes quais hashes já existem para a empresa."""
        existentes: set[str] = set()
        for i in range(0, len(hashes), chunk):
            lote = hashes[i:i + chunk]
            rows = self.session.scalars(
                select(VskyRegistroAnalitico.linha_hash)
                .where(VskyRegistroAnalitico.empresa_id == self.empresa_id)
                .where(VskyRegistroAnalitico.linha_hash.in_(lote)))
            existentes.update(rows)
        return existentes

    def bulk_insert(self, registros: list[dict]) -> None:
        self.session.add_all(
            VskyRegistroAnalitico(empresa_id=self.empresa_id, **r) for r in registros)
        self.session.commit()

    def versoes_por_chave(self, chaves: list[tuple[str, str]],
                          chunk: int = 300) -> dict[tuple[str, str], list]:
        """Registros vivos de cada (ocorrência, unidade), em lotes."""
        from sqlalchemy import tuple_ as sa_tuple

        achados: dict[tuple[str, str], list] = {}
        for i in range(0, len(chaves), chunk):
            lote = chaves[i:i + chunk]
            rows = self.session.scalars(
                select(VskyRegistroAnalitico)
                .where(VskyRegistroAnalitico.empresa_id == self.empresa_id)
                .where(VskyRegistroAnalitico.deleted_at.is_(None))
                .where(sa_tuple(VskyRegistroAnalitico.ocorrencia,
                                VskyRegistroAnalitico.unidade).in_(lote)))
            for r in rows:
                achados.setdefault((r.ocorrencia or "", r.unidade or ""),
                                   []).append(r)
        return achados

    def soft_delete(self, registros: list, usuario_id: int | None = None) -> int:
        """Marca versões superadas como excluídas (§36.7), sem perder o dado."""
        from datetime import datetime, timezone

        agora = datetime.now(timezone.utc)
        for r in registros:
            r.deleted_at = agora
            r.deleted_by = usuario_id
        self.session.commit()
        return len(registros)
