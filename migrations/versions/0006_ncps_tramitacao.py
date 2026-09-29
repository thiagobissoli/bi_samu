"""NCPS: responsável dentro do setor e histórico de tramitação.

ncps.responsavel_id  quem, no setor, cuida da NCPS
ncps_eventos         quem fez o quê e quando (encaminhar, assumir, devolver…)

Revision ID: 0006_ncps_tramitacao
Revises: 0005_mfa
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_ncps_tramitacao"
down_revision = "0005_mfa"
branch_labels = None
depends_on = None

_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    inspetor = sa.inspect(op.get_bind())
    tabelas = set(inspetor.get_table_names())
    if "ncps" not in tabelas:
        return
    colunas = {c["name"] for c in inspetor.get_columns("ncps")}
    if "responsavel_id" not in colunas:
        with op.batch_alter_table("ncps") as lote:
            lote.add_column(sa.Column("responsavel_id", _ID, nullable=True))
            lote.create_index("ix_ncps_responsavel_id", ["responsavel_id"])
            lote.create_foreign_key("fk_ncps_responsavel_id", "usuarios",
                                    ["responsavel_id"], ["id"])
    if "ncps_eventos" not in tabelas:
        op.create_table(
            "ncps_eventos",
            sa.Column("ncps_id", _ID, sa.ForeignKey("ncps.id"), nullable=False),
            sa.Column("tipo", sa.String(length=20), nullable=False),
            sa.Column("texto", sa.Text(), nullable=True),
            sa.Column("usuario_id", _ID, sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("id", _ID, nullable=False),
            sa.Column("empresa_id", sa.BigInteger(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", sa.BigInteger(), nullable=True),
            sa.Column("updated_by", sa.BigInteger(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deleted_by", sa.BigInteger(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        for coluna in ("ncps_id", "empresa_id", "deleted_at"):
            op.create_index(f"ix_ncps_eventos_{coluna}", "ncps_eventos", [coluna])


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ncps_eventos")
    with op.batch_alter_table("ncps") as lote:
        lote.drop_constraint("fk_ncps_responsavel_id", type_="foreignkey")
        lote.drop_index("ix_ncps_responsavel_id")
        lote.drop_column("responsavel_id")
