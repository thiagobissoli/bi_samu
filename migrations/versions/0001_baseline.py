"""Baseline do Framework SaaS — tabelas compartilhadas (§36.6).

Ponto de partida das migrações do projeto. Bancos criados pelo `init_db()`
já vêm marcados nesta revisão automaticamente, então `alembic upgrade head`
aplica apenas as migrações posteriores (§36.20).

Revision ID: 0001_baseline
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('arquivos',
    sa.Column('nome_original', sa.String(length=255), nullable=False),
    sa.Column('nome_servidor', sa.String(length=255), nullable=False),
    sa.Column('mime_type', sa.String(length=100), nullable=False),
    sa.Column('tamanho', sa.BigInteger(), nullable=False),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.Column('caminho', sa.String(length=500), nullable=False),
    sa.Column('modulo', sa.String(length=50), nullable=False),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('empresa_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.Column('updated_by', sa.BigInteger(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('nome_servidor')
    )
    op.create_index(op.f('ix_arquivos_deleted_at'), 'arquivos', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_arquivos_empresa_id'), 'arquivos', ['empresa_id'], unique=False)
    op.create_index(op.f('ix_arquivos_modulo'), 'arquivos', ['modulo'], unique=False)
    op.create_table('auditoria',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.BigInteger(), nullable=False),
    sa.Column('usuario_id', sa.BigInteger(), nullable=True),
    sa.Column('usuario_nome', sa.String(length=255), nullable=True),
    sa.Column('tabela', sa.String(length=100), nullable=False),
    sa.Column('registro_id', sa.BigInteger(), nullable=True),
    sa.Column('acao', sa.String(length=30), nullable=False),
    sa.Column('valor_anterior', sa.Text(), nullable=True),
    sa.Column('valor_novo', sa.Text(), nullable=True),
    sa.Column('ip', sa.String(length=45), nullable=True),
    sa.Column('user_agent', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_auditoria_acao'), 'auditoria', ['acao'], unique=False)
    op.create_index(op.f('ix_auditoria_created_at'), 'auditoria', ['created_at'], unique=False)
    op.create_index(op.f('ix_auditoria_empresa_id'), 'auditoria', ['empresa_id'], unique=False)
    op.create_index(op.f('ix_auditoria_tabela'), 'auditoria', ['tabela'], unique=False)
    op.create_index(op.f('ix_auditoria_usuario_id'), 'auditoria', ['usuario_id'], unique=False)
    op.create_table('configuracoes',
    sa.Column('chave', sa.String(length=100), nullable=False),
    sa.Column('valor', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('empresa_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.Column('updated_by', sa.BigInteger(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_configuracoes_chave'), 'configuracoes', ['chave'], unique=False)
    op.create_index(op.f('ix_configuracoes_deleted_at'), 'configuracoes', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_configuracoes_empresa_id'), 'configuracoes', ['empresa_id'], unique=False)
    op.create_table('empresas',
    sa.Column('razao_social', sa.String(length=255), nullable=False),
    sa.Column('nome_fantasia', sa.String(length=255), nullable=False),
    sa.Column('cnpj', sa.String(length=18), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('telefone', sa.String(length=20), nullable=True),
    sa.Column('plano', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('timezone', sa.String(length=50), nullable=False),
    sa.Column('idioma', sa.String(length=10), nullable=False),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('empresa_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.Column('updated_by', sa.BigInteger(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cnpj')
    )
    op.create_index(op.f('ix_empresas_deleted_at'), 'empresas', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_empresas_empresa_id'), 'empresas', ['empresa_id'], unique=False)
    op.create_index(op.f('ix_empresas_nome_fantasia'), 'empresas', ['nome_fantasia'], unique=False)
    op.create_index(op.f('ix_empresas_status'), 'empresas', ['status'], unique=False)
    op.create_table('logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.BigInteger(), nullable=False),
    sa.Column('nivel', sa.String(length=10), nullable=False),
    sa.Column('modulo', sa.String(length=50), nullable=False),
    sa.Column('mensagem', sa.Text(), nullable=False),
    sa.Column('stacktrace', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_logs_created_at'), 'logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_logs_empresa_id'), 'logs', ['empresa_id'], unique=False)
    op.create_index(op.f('ix_logs_modulo'), 'logs', ['modulo'], unique=False)
    op.create_index(op.f('ix_logs_nivel'), 'logs', ['nivel'], unique=False)
    op.create_table('notificacoes',
    sa.Column('usuario_id', sa.BigInteger(), nullable=False),
    sa.Column('titulo', sa.String(length=255), nullable=False),
    sa.Column('mensagem', sa.Text(), nullable=False),
    sa.Column('tipo', sa.String(length=20), nullable=False),
    sa.Column('lida', sa.Boolean(), nullable=False),
    sa.Column('lida_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('empresa_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.Column('updated_by', sa.BigInteger(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notificacoes_deleted_at'), 'notificacoes', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_notificacoes_empresa_id'), 'notificacoes', ['empresa_id'], unique=False)
    op.create_index(op.f('ix_notificacoes_lida'), 'notificacoes', ['lida'], unique=False)
    op.create_index(op.f('ix_notificacoes_usuario_id'), 'notificacoes', ['usuario_id'], unique=False)
    op.create_table('perfis',
    sa.Column('nome', sa.String(length=100), nullable=False),
    sa.Column('descricao', sa.String(length=255), nullable=True),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('empresa_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.Column('updated_by', sa.BigInteger(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_perfis_deleted_at'), 'perfis', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_perfis_empresa_id'), 'perfis', ['empresa_id'], unique=False)
    op.create_index(op.f('ix_perfis_nome'), 'perfis', ['nome'], unique=False)
    op.create_table('permissoes',
    sa.Column('codigo', sa.String(length=100), nullable=False),
    sa.Column('descricao', sa.String(length=255), nullable=True),
    sa.Column('modulo', sa.String(length=50), nullable=False),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('empresa_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.Column('updated_by', sa.BigInteger(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_permissoes_codigo'), 'permissoes', ['codigo'], unique=True)
    op.create_index(op.f('ix_permissoes_deleted_at'), 'permissoes', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_permissoes_empresa_id'), 'permissoes', ['empresa_id'], unique=False)
    op.create_index(op.f('ix_permissoes_modulo'), 'permissoes', ['modulo'], unique=False)
    op.create_table('sessoes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.BigInteger(), nullable=False),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('ip', sa.String(length=45), nullable=True),
    sa.Column('user_agent', sa.String(length=500), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sessoes_expires_at'), 'sessoes', ['expires_at'], unique=False)
    op.create_index(op.f('ix_sessoes_token'), 'sessoes', ['token'], unique=True)
    op.create_index(op.f('ix_sessoes_usuario_id'), 'sessoes', ['usuario_id'], unique=False)
    op.create_table('tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.BigInteger(), nullable=False),
    sa.Column('tipo', sa.String(length=30), nullable=False),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('expira_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('utilizado', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tokens_tipo'), 'tokens', ['tipo'], unique=False)
    op.create_index(op.f('ix_tokens_token'), 'tokens', ['token'], unique=True)
    op.create_index(op.f('ix_tokens_usuario_id'), 'tokens', ['usuario_id'], unique=False)
    op.create_table('usuarios',
    sa.Column('nome', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('senha_hash', sa.String(length=255), nullable=False),
    sa.Column('telefone', sa.String(length=20), nullable=True),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.Column('email_confirmado', sa.Boolean(), nullable=False),
    sa.Column('mfa_habilitado', sa.Boolean(), nullable=False),
    sa.Column('mfa_secret', sa.String(length=64), nullable=True),
    sa.Column('ultimo_login', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ultimo_ip', sa.String(length=45), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('empresa_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.Column('updated_by', sa.BigInteger(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_usuarios_ativo'), 'usuarios', ['ativo'], unique=False)
    op.create_index(op.f('ix_usuarios_deleted_at'), 'usuarios', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_usuarios_email'), 'usuarios', ['email'], unique=True)
    op.create_index(op.f('ix_usuarios_empresa_id'), 'usuarios', ['empresa_id'], unique=False)
    op.create_index(op.f('ix_usuarios_nome'), 'usuarios', ['nome'], unique=False)
    op.create_table('perfis_permissoes',
    sa.Column('perfil_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('permissao_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.ForeignKeyConstraint(['perfil_id'], ['perfis.id'], ),
    sa.ForeignKeyConstraint(['permissao_id'], ['permissoes.id'], ),
    sa.PrimaryKeyConstraint('perfil_id', 'permissao_id')
    )
    op.create_table('usuarios_perfis',
    sa.Column('usuario_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('perfil_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.ForeignKeyConstraint(['perfil_id'], ['perfis.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('usuario_id', 'perfil_id')
    )


def downgrade() -> None:
    op.drop_table('usuarios_perfis')
    op.drop_table('perfis_permissoes')
    op.drop_index(op.f('ix_usuarios_nome'), table_name='usuarios')
    op.drop_index(op.f('ix_usuarios_empresa_id'), table_name='usuarios')
    op.drop_index(op.f('ix_usuarios_email'), table_name='usuarios')
    op.drop_index(op.f('ix_usuarios_deleted_at'), table_name='usuarios')
    op.drop_index(op.f('ix_usuarios_ativo'), table_name='usuarios')
    op.drop_table('usuarios')
    op.drop_index(op.f('ix_tokens_usuario_id'), table_name='tokens')
    op.drop_index(op.f('ix_tokens_token'), table_name='tokens')
    op.drop_index(op.f('ix_tokens_tipo'), table_name='tokens')
    op.drop_table('tokens')
    op.drop_index(op.f('ix_sessoes_usuario_id'), table_name='sessoes')
    op.drop_index(op.f('ix_sessoes_token'), table_name='sessoes')
    op.drop_index(op.f('ix_sessoes_expires_at'), table_name='sessoes')
    op.drop_table('sessoes')
    op.drop_index(op.f('ix_permissoes_modulo'), table_name='permissoes')
    op.drop_index(op.f('ix_permissoes_empresa_id'), table_name='permissoes')
    op.drop_index(op.f('ix_permissoes_deleted_at'), table_name='permissoes')
    op.drop_index(op.f('ix_permissoes_codigo'), table_name='permissoes')
    op.drop_table('permissoes')
    op.drop_index(op.f('ix_perfis_nome'), table_name='perfis')
    op.drop_index(op.f('ix_perfis_empresa_id'), table_name='perfis')
    op.drop_index(op.f('ix_perfis_deleted_at'), table_name='perfis')
    op.drop_table('perfis')
    op.drop_index(op.f('ix_notificacoes_usuario_id'), table_name='notificacoes')
    op.drop_index(op.f('ix_notificacoes_lida'), table_name='notificacoes')
    op.drop_index(op.f('ix_notificacoes_empresa_id'), table_name='notificacoes')
    op.drop_index(op.f('ix_notificacoes_deleted_at'), table_name='notificacoes')
    op.drop_table('notificacoes')
    op.drop_index(op.f('ix_logs_nivel'), table_name='logs')
    op.drop_index(op.f('ix_logs_modulo'), table_name='logs')
    op.drop_index(op.f('ix_logs_empresa_id'), table_name='logs')
    op.drop_index(op.f('ix_logs_created_at'), table_name='logs')
    op.drop_table('logs')
    op.drop_index(op.f('ix_empresas_status'), table_name='empresas')
    op.drop_index(op.f('ix_empresas_nome_fantasia'), table_name='empresas')
    op.drop_index(op.f('ix_empresas_empresa_id'), table_name='empresas')
    op.drop_index(op.f('ix_empresas_deleted_at'), table_name='empresas')
    op.drop_table('empresas')
    op.drop_index(op.f('ix_configuracoes_empresa_id'), table_name='configuracoes')
    op.drop_index(op.f('ix_configuracoes_deleted_at'), table_name='configuracoes')
    op.drop_index(op.f('ix_configuracoes_chave'), table_name='configuracoes')
    op.drop_table('configuracoes')
    op.drop_index(op.f('ix_auditoria_usuario_id'), table_name='auditoria')
    op.drop_index(op.f('ix_auditoria_tabela'), table_name='auditoria')
    op.drop_index(op.f('ix_auditoria_empresa_id'), table_name='auditoria')
    op.drop_index(op.f('ix_auditoria_created_at'), table_name='auditoria')
    op.drop_index(op.f('ix_auditoria_acao'), table_name='auditoria')
    op.drop_table('auditoria')
    op.drop_index(op.f('ix_arquivos_modulo'), table_name='arquivos')
    op.drop_index(op.f('ix_arquivos_empresa_id'), table_name='arquivos')
    op.drop_index(op.f('ix_arquivos_deleted_at'), table_name='arquivos')
    op.drop_table('arquivos')
