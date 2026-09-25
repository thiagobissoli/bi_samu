"""NCPS: código de acompanhamento cifrado e indexado.

A consulta pública passa a ser só pelo código (sem protocolo): o hash ganha
índice, e a versão cifrada permite exibir o código na lista das NCPS.

Revision ID: 0004_ncps_codigo
Revises: 0003_ncps_setores
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_ncps_codigo"
down_revision = "0003_ncps_setores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspetor = sa.inspect(op.get_bind())
    if "ncps" not in inspetor.get_table_names():
        return
    colunas = {c["name"] for c in inspetor.get_columns("ncps")}
    indices = {i["name"] for i in inspetor.get_indexes("ncps")}
    with op.batch_alter_table("ncps") as lote:
        if "codigo_cifrado" not in colunas:
            lote.add_column(sa.Column("codigo_cifrado", sa.String(length=255),
                                      nullable=True))
        if "ix_ncps_codigo_hash" not in indices:
            lote.create_index("ix_ncps_codigo_hash", ["codigo_hash"])


def downgrade() -> None:
    inspetor = sa.inspect(op.get_bind())
    if "ncps" not in inspetor.get_table_names():
        return
    with op.batch_alter_table("ncps") as lote:
        lote.drop_index("ix_ncps_codigo_hash")
        lote.drop_column("codigo_cifrado")
