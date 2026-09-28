"""Framework 1.9.0: tabela api_keys e empresa ativa na sessão

Gerada por autogenerate e **enxugada à mão**: o Alembic também propôs
alter_column em `investigacao_analises` e `vsky_prontuarios`, comparando
MEDIUMTEXT/LONGBLOB/BIGINT do MySQL com Text/LargeBinary/Integer dos modelos.
Não são mudanças reais — e duas seriam destrutivas:

    pdf:          LONGBLOB (4 GB) -> LargeBinary (64 KB)  truncaria os PDFs
    aprovado_por: BIGINT -> INT                           estreitaria o tipo

Os modelos é que estão defasados em relação ao banco. Corrigir isso é tarefa
separada, no modelo — não numa migração.

Revision ID: 5871e1363fcf
Revises: 0004_ncps_codigo
"""
from alembic import op
import sqlalchemy as sa

revision = "5871e1363fcf"
down_revision = '0004_ncps_codigo'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("nome", sa.String(length=100), nullable=False),
        sa.Column("prefixo", sa.String(length=16), nullable=False),
        sa.Column("chave_hash", sa.String(length=64), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("escopos", sa.Text(), nullable=False),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revogada", sa.Boolean(), nullable=False),
        sa.Column("ultimo_uso", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_ip", sa.String(length=45), nullable=True),
        sa.Column("total_usos", sa.Integer(), nullable=False),
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
    op.create_index(op.f("ix_api_keys_chave_hash"), "api_keys", ["chave_hash"], unique=True)
    op.create_index(op.f("ix_api_keys_deleted_at"), "api_keys", ["deleted_at"], unique=False)
    op.create_index(op.f("ix_api_keys_empresa_id"), "api_keys", ["empresa_id"], unique=False)
    op.create_index(op.f("ix_api_keys_prefixo"), "api_keys", ["prefixo"], unique=False)
    op.create_index(op.f("ix_api_keys_revogada"), "api_keys", ["revogada"], unique=False)
    op.create_index(op.f("ix_api_keys_usuario_id"), "api_keys", ["usuario_id"], unique=False)

    # Empresa ativa da sessão — troca de empresa sem trocar de conta (§39.6).
    op.add_column("sessoes", sa.Column("empresa_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessoes", "empresa_id")
    op.drop_table("api_keys")
