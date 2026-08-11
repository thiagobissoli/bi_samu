"""Dados iniciais (§35.24) e sincronização de permissões (§9).

Executado na inicialização: garante empresa exemplo, perfil Administrador,
usuário administrador e o catálogo de permissões (base + módulos).
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.modules import get_manifests
from app.core.security import hash_password
from app.models import Configuracao, Empresa, Perfil, Permissao, Usuario

ADMIN_EMAIL = "admin@empresa.com"
ADMIN_SENHA = "admin123"  # trocar no primeiro acesso — apenas desenvolvimento

# Permissões dos módulos base (§9, §31)
BASE_PERMISSIONS: list[tuple[str, str, str]] = [
    ("dashboard.visualizar", "Visualizar dashboard", "dashboard"),
    ("empresa.listar", "Listar empresas", "empresas"),
    ("empresa.criar", "Criar empresas", "empresas"),
    ("empresa.editar", "Editar empresas", "empresas"),
    ("empresa.excluir", "Excluir empresas", "empresas"),
    ("usuario.listar", "Listar usuários", "usuarios"),
    ("usuario.criar", "Criar usuários", "usuarios"),
    ("usuario.editar", "Editar usuários", "usuarios"),
    ("usuario.excluir", "Excluir usuários", "usuarios"),
    ("perfil.listar", "Listar perfis", "perfis"),
    ("perfil.criar", "Criar perfis", "perfis"),
    ("perfil.editar", "Editar perfis", "perfis"),
    ("perfil.excluir", "Excluir perfis", "perfis"),
    ("permissao.listar", "Listar permissões", "permissoes"),
    ("configuracao.listar", "Listar configurações", "configuracoes"),
    ("configuracao.editar", "Editar configurações", "configuracoes"),
    ("configuracao.excluir", "Excluir configurações", "configuracoes"),
    ("auditoria.listar", "Consultar auditoria", "auditoria"),
    ("log.listar", "Consultar logs", "logs"),
    ("notificacao.listar", "Ver notificações", "notificacoes"),
    ("notificacao.enviar", "Enviar notificações", "notificacoes"),
    ("upload.listar", "Listar arquivos", "uploads"),
    ("upload.enviar", "Enviar arquivos", "uploads"),
    ("upload.excluir", "Excluir arquivos", "uploads"),
]

DEFAULT_CONFIGS = [
    ("tema", "claro"),
    ("idioma", "pt-BR"),
    ("timezone", "America/Sao_Paulo"),
]


def _sync_permissions(db) -> list[Permissao]:
    """Garante que toda permissão (base + manifests dos módulos) exista."""
    desired: dict[str, tuple[str, str]] = {
        codigo: (descricao, modulo) for codigo, descricao, modulo in BASE_PERMISSIONS
    }
    for manifest in get_manifests():
        modulo = manifest.get("name", "").lower()
        for codigo in manifest.get("permissions", []):
            desired.setdefault(codigo, (f"Permissão {codigo}", codigo.split(".")[0]))

    existing = {p.codigo: p for p in db.scalars(select(Permissao))}
    for codigo, (descricao, modulo) in desired.items():
        if codigo not in existing:
            db.add(Permissao(codigo=codigo, descricao=descricao, modulo=modulo, empresa_id=1))
    db.commit()
    return list(db.scalars(select(Permissao).where(Permissao.deleted_at.is_(None))))


def run_seeds() -> None:
    db = SessionLocal()
    try:
        permissoes = _sync_permissions(db)

        empresa = db.scalar(select(Empresa).limit(1))
        if empresa is None:
            empresa = Empresa(
                empresa_id=1,
                razao_social="Empresa Exemplo LTDA",
                nome_fantasia="Empresa Exemplo",
                cnpj="00.000.000/0001-00",
                email="contato@empresa.com",
            )
            db.add(empresa)
            db.commit()

        admin_perfil = db.scalar(select(Perfil).where(Perfil.nome == "Administrador"))
        if admin_perfil is None:
            admin_perfil = Perfil(
                empresa_id=empresa.id,
                nome="Administrador",
                descricao="Acesso total ao sistema",
            )
            db.add(admin_perfil)
            db.commit()

        # Administrador sempre possui todas as permissões conhecidas.
        atuais = {p.codigo for p in admin_perfil.permissoes}
        for p in permissoes:
            if p.codigo not in atuais:
                admin_perfil.permissoes.append(p)
        db.commit()

        admin = db.scalar(select(Usuario).where(Usuario.email == ADMIN_EMAIL))
        if admin is None:
            admin = Usuario(
                empresa_id=empresa.id,
                nome="Administrador",
                email=ADMIN_EMAIL,
                senha_hash=hash_password(ADMIN_SENHA),
                ativo=True,
                email_confirmado=True,
            )
            admin.perfis.append(admin_perfil)
            db.add(admin)
            db.commit()

            from app.core.notifications import notify

            notify(db, admin.id, "Bem-vindo!",
                   "Seu ambiente foi criado. Troque a senha padrão em "
                   "Administrador > Alterar senha e ative o MFA.",
                   tipo="warning", empresa_id=empresa.id)

        for chave, valor in DEFAULT_CONFIGS:
            existe = db.scalar(
                select(Configuracao).where(
                    Configuracao.empresa_id == empresa.id, Configuracao.chave == chave
                )
            )
            if existe is None:
                db.add(Configuracao(empresa_id=empresa.id, chave=chave, valor=valor))
        db.commit()
    finally:
        db.close()
