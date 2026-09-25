"""NCPS: análise por setor em vez de coordenador.

Cria os setores e o vínculo setor × usuário, e a coluna `ncps.setor_id`.
Em banco sem a tabela `ncps` (instalação anterior ao módulo) não faz nada:
o `create_all` do boot cria tudo já no formato novo.

Revision ID: 0003_ncps_setores
Revises: 0002_linhas_superadas
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_ncps_setores"
down_revision = "0002_linhas_superadas"
branch_labels = None
depends_on = None

_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    inspetor = sa.inspect(op.get_bind())
    tabelas = set(inspetor.get_table_names())
    if "ncps" not in tabelas:
        return

    if "ncps_setores" not in tabelas:
        op.create_table(
            "ncps_setores",
            sa.Column("nome", sa.String(length=120), nullable=False),
            sa.Column("ativo", sa.Boolean(), nullable=False),
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
        for coluna in ("nome", "empresa_id", "deleted_at"):
            op.create_index(f"ix_ncps_setores_{coluna}", "ncps_setores", [coluna])

    if "ncps_setor_usuarios" not in tabelas:
        op.create_table(
            "ncps_setor_usuarios",
            sa.Column("setor_id", _ID, sa.ForeignKey("ncps_setores.id"),
                      primary_key=True),
            sa.Column("usuario_id", _ID, sa.ForeignKey("usuarios.id"),
                      primary_key=True),
        )

    colunas = {c["name"] for c in inspetor.get_columns("ncps")}
    if "setor_id" not in colunas:
        with op.batch_alter_table("ncps") as lote:
            lote.add_column(sa.Column("setor_id", _ID, nullable=True))
            lote.create_index("ix_ncps_setor_id", ["setor_id"])
            lote.create_foreign_key("fk_ncps_setor_id", "ncps_setores",
                                    ["setor_id"], ["id"])


def downgrade() -> None:
    inspetor = sa.inspect(op.get_bind())
    if "ncps" in inspetor.get_table_names():
        colunas = {c["name"] for c in inspetor.get_columns("ncps")}
        if "setor_id" in colunas:
            with op.batch_alter_table("ncps") as lote:
                lote.drop_constraint("fk_ncps_setor_id", type_="foreignkey")
                lote.drop_index("ix_ncps_setor_id")
                lote.drop_column("setor_id")
    op.execute("DROP TABLE IF EXISTS ncps_setor_usuarios")
    op.execute("DROP TABLE IF EXISTS ncps_setores")
