"""Autenticação em duas etapas: método, recuperação e obrigatoriedade.

usuarios.mfa_metodo      "app" (autenticador) ou "email"
usuarios.mfa_recuperacao hashes dos códigos de recuperação não usados (JSON)
perfis.exige_2fa         o perfil obriga quem o tem a usar 2FA

Quem já tinha o 2FA ligado usava o autenticador: recebe mfa_metodo = "app".

Revision ID: 0005_mfa
Revises: 5871e1363fcf
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_mfa"
down_revision = "5871e1363fcf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspetor = sa.inspect(op.get_bind())
    usuarios = {c["name"] for c in inspetor.get_columns("usuarios")}
    with op.batch_alter_table("usuarios") as lote:
        if "mfa_metodo" not in usuarios:
            lote.add_column(sa.Column("mfa_metodo", sa.String(length=10), nullable=True))
        if "mfa_recuperacao" not in usuarios:
            lote.add_column(sa.Column("mfa_recuperacao", sa.Text(), nullable=True))
    perfis = {c["name"] for c in inspetor.get_columns("perfis")}
    if "exige_2fa" not in perfis:
        with op.batch_alter_table("perfis") as lote:
            lote.add_column(sa.Column("exige_2fa", sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
    op.get_bind().execute(
        sa.text("UPDATE usuarios SET mfa_metodo = 'app' "
                "WHERE mfa_habilitado = :sim AND mfa_metodo IS NULL"), {"sim": True})


def downgrade() -> None:
    with op.batch_alter_table("perfis") as lote:
        lote.drop_column("exige_2fa")
    with op.batch_alter_table("usuarios") as lote:
        lote.drop_column("mfa_recuperacao")
        lote.drop_column("mfa_metodo")
