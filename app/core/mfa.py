"""Autenticação em duas etapas (§6).

Dois métodos, à escolha do usuário:
    app    — código TOTP de um aplicativo autenticador (Google/Microsoft
             Authenticator etc.), configurado por QR code
    email  — código de 6 dígitos enviado por e-mail a cada login

Recursos:
    - códigos de recuperação: 10 códigos de uso único, gerados ao ativar,
      para entrar sem o celular/e-mail; só o hash fica no banco;
    - obrigatoriedade por perfil (`perfis.exige_2fa`): quem pertence a um
      perfil que exige é levado a configurar e não navega até configurar;
    - redefinição por um administrador (tela de Usuários), para quem perdeu
      o acesso.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import utcnow

METODOS = {"app": "Aplicativo autenticador", "email": "Código por e-mail"}
QTD_RECUPERACAO = 10
VALIDADE_EMAIL = timedelta(minutes=10)
# Letras e dígitos sem 0/O/1/I/L — ditados ou copiados sem confusão
_ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()


# ------------------------------------------------------------------ obrigatoriedade

def exige_2fa(usuario) -> bool:
    """Algum perfil ativo do usuário exige a autenticação em duas etapas."""
    return any(getattr(p, "exige_2fa", False) and p.ativo and p.deleted_at is None
               for p in usuario.perfis)


def pendente(usuario) -> bool:
    """O perfil exige e o usuário ainda não configurou."""
    return exige_2fa(usuario) and not usuario.mfa_habilitado


# ------------------------------------------------------------------ códigos de recuperação

def _normalizar(codigo: str | None) -> str:
    return "".join(c for c in (codigo or "").upper() if c.isalnum())


def gerar_recuperacao(usuario) -> list[str]:
    """Gera novos códigos (os antigos deixam de valer) e devolve em claro —
    é a única vez que eles aparecem."""
    codigos = []
    for _ in range(QTD_RECUPERACAO):
        bruto = "".join(secrets.choice(_ALFABETO) for _ in range(8))
        codigos.append(f"{bruto[:4]}-{bruto[4:]}")
    usuario.mfa_recuperacao = json.dumps([_hash(_normalizar(c)) for c in codigos])
    return codigos


def restantes(usuario) -> int:
    try:
        return len(json.loads(usuario.mfa_recuperacao or "[]"))
    except ValueError:
        return 0


def usar_recuperacao(usuario, codigo: str) -> bool:
    """Confere e consome um código de recuperação."""
    try:
        hashes = json.loads(usuario.mfa_recuperacao or "[]")
    except ValueError:
        return False
    alvo = _hash(_normalizar(codigo))
    if alvo not in hashes:
        return False
    hashes.remove(alvo)
    usuario.mfa_recuperacao = json.dumps(hashes)
    return True


# ------------------------------------------------------------------ código por e-mail

def enviar_codigo_email(db: Session, usuario, contexto: str) -> bool:
    """Envia um código de 6 dígitos e guarda só o hash, amarrado ao contexto
    (o token do login pendente, ou "ativar" na configuração).

    Devolve True se o e-mail saiu pelo SMTP; sem SMTP o código vai para os
    Logs (ambiente de desenvolvimento).
    """
    from app.core.config import settings
    from app.core.mail import send_mail
    from app.models import TokenSeguranca

    codigo = f"{secrets.randbelow(10 ** 6):06d}"
    db.add(TokenSeguranca(
        usuario_id=usuario.id, tipo="mfa_email",
        token=_hash(f"{usuario.id}:{contexto}:{codigo}"),
        expira_em=utcnow() + VALIDADE_EMAIL))
    db.commit()
    corpo = (f"<p>Olá, {usuario.nome.split(' ')[0]}.</p>"
             f"<p>Seu código de verificação do {settings.app_name} é:</p>"
             f"<p style='font-size:26px;font-weight:bold;letter-spacing:6px'>{codigo}</p>"
             "<p>Ele vale por 10 minutos. Se não foi você quem tentou entrar, "
             "troque sua senha e avise o administrador.</p>")
    return send_mail(db, usuario.email, f"{settings.app_name} — código de verificação",
                     corpo, empresa_id=usuario.empresa_id)


def conferir_codigo_email(db: Session, usuario, contexto: str, codigo: str) -> bool:
    from app.models import TokenSeguranca

    codigo = "".join(c for c in (codigo or "") if c.isdigit())
    if len(codigo) != 6:
        return False
    registro = db.scalar(select(TokenSeguranca).where(
        TokenSeguranca.tipo == "mfa_email",
        TokenSeguranca.usuario_id == usuario.id,
        TokenSeguranca.token == _hash(f"{usuario.id}:{contexto}:{codigo}"),
        TokenSeguranca.utilizado.is_(False)))
    if registro is None:
        return False
    expira = registro.expira_em
    if expira.tzinfo is None:
        from datetime import timezone
        expira = expira.replace(tzinfo=timezone.utc)
    if expira < utcnow():
        return False
    registro.utilizado = True
    db.commit()
    return True


def smtp_configurado(db: Session, empresa_id: int) -> bool:
    from app.core.config_service import get_config
    return bool(get_config(db, "smtp_host", empresa_id=empresa_id))


# ------------------------------------------------------------------ verificação no login

def verificar(db: Session, usuario, codigo: str, contexto: str) -> str | None:
    """Confere o segundo fator; devolve como passou ('app', 'email',
    'recuperacao') ou None."""
    from app.core.totp import verify_totp

    limpo = (codigo or "").strip()
    if usuario.mfa_metodo == "email":
        if conferir_codigo_email(db, usuario, contexto, limpo):
            return "email"
    elif usuario.mfa_secret and verify_totp(usuario.mfa_secret, limpo):
        return "app"
    if len(_normalizar(limpo)) == 8 and usar_recuperacao(usuario, limpo):
        db.commit()
        return "recuperacao"
    return None


def desligar(usuario) -> None:
    usuario.mfa_habilitado = False
    usuario.mfa_secret = None
    usuario.mfa_metodo = None
    usuario.mfa_recuperacao = None


# ------------------------------------------------------------------ QR code

def qr_svg(uri: str) -> str:
    """SVG do QR code do otpauth:// (gerado aqui, sem serviço externo — a
    chave secreta não pode sair do servidor)."""
    import segno

    # viewBox em vez de largura/altura fixas: o SVG escala com o CSS. Sem
    # isso o navegador recortava o código ao encaixá-lo no quadro e o
    # celular não conseguia ler. Margem de 4 módulos (a do padrão QR), em
    # branco, para o leitor achar o código mesmo com a página no tema escuro.
    return segno.make(uri, error="m").svg_inline(omitsize=True, dark="#000",
                                                 light="#fff", border=4)
