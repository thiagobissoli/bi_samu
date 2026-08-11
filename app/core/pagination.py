"""Paginação padrão (§18): page, per_page, total, pages."""

from math import ceil

from sqlalchemy import func, select
from sqlalchemy.orm import Session


def paginate(db: Session, query, page: int = 1, per_page: int = 10) -> dict:
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    pages = max(1, ceil(total / per_page))
    page = min(max(1, page), pages)
    items = list(db.scalars(query.limit(per_page).offset((page - 1) * per_page)))
    return {"items": items, "page": page, "per_page": per_page, "total": total, "pages": pages}
