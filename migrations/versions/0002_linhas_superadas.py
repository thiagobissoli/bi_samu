"""Contador de versões superadas na importação do vSky.

O portal corrige registros já exportados. A importação passou a aposentar a
versão antiga quando o mesmo (ocorrência, unidade) volta com outro conteúdo;
esta coluna guarda quantas foram, para a tela do download mostrar.

Revision ID: 0002_linhas_superadas
Revises: 0001_baseline
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_linhas_superadas"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vsky_importacoes",
                  sa.Column("linhas_superadas", sa.Integer(),
                            nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("vsky_importacoes", "linhas_superadas")
