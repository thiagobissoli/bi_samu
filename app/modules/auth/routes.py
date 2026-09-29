"""Autenticação (§6): login (com MFA opcional e rate limit §25), logout,
recuperação/alteração de senha e confirmação de e-mail."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.auth import SESSION_COOKIE, create_session, destroy_session, get_current_user
from app.core.config import settings
from app.core.database import get_session, utcnow
from app.core.logs import write_log
from app.core.mail import send_mail
from app.core import mfa
from app.core.middleware import LoginRateLimiter, login_limiter
from app.core.security import generate_token, hash_password, verify_password
from app.core.templating import render, templates
from app.core.totp import generate_secret, otpauth_uri, verify_totp
from app.models import TokenSeguranca, Usuario

router = APIRouter(tags=["Auth"])

# Tentativas do segundo fator por login pendente, e reenvio do código por e-mail
_limite_codigo = LoginRateLimiter(max_attempts=5, window_seconds=300)
_limite_reenvio = LoginRateLimiter(max_attempts=3, window_seconds=300)


def _find_user(db: Session, email: str) -> Usuario | None:
    return db.scalar(select(Usuario).where(
        Usuario.email == email.strip().lower(), Usuario.deleted_at.is_(None)
    ))


def _login_response(db: Session, request: Request, usuario: Usuario,
                    destino: str = "/"):
    ip = request.client.host if request.client else None
    token = create_session(db, usuario, ip, request.headers.get("user-agent"))
    usuario.ultimo_login = utcnow()
    usuario.ultimo_ip = ip
    db.commit()
    record_audit(db, tabela="usuarios", acao="LOGIN", registro_id=usuario.id,
                 usuario=usuario, request=request)
    response = RedirectResponse(destino, status_code=303)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                        secure=not settings.debug, max_age=8 * 3600)
    return response


# --- Login / Logout ---


@router.get("/login", include_in_schema=False)
def login_form(request: Request, erro: str = "", info: str = ""):
    return templates.TemplateResponse(request, "auth/login.html", {"erro": erro, "info": info})


@router.post("/login", include_in_schema=False)
def login(
    request: Request,
    email: str = Form(...),
    senha: str = Form(...),
    db: Session = Depends(get_session),
):
    ip = request.client.host if request.client else "?"
    if login_limiter.blocked(ip):
        write_log(db, "WARNING", "auth", f"Rate limit de login excedido para {ip}")
        return templates.TemplateResponse(request, "auth/login.html", {
            "erro": "Muitas tentativas. Aguarde um minuto e tente novamente.", "info": ""})

    usuario = _find_user(db, email)
    if usuario is None or not usuario.ativo or not verify_password(usuario.senha_hash, senha):
        login_limiter.register(ip)
        write_log(db, "WARNING", "auth", f"Tentativa de login inválida para {email}")
        return templates.TemplateResponse(request, "auth/login.html", {
            "erro": "E-mail ou senha inválidos.", "info": ""})

    # Segunda etapa (§6): senha ok -> código do autenticador ou do e-mail.
    if usuario.mfa_habilitado:
        token = generate_token()[:64]
        db.add(TokenSeguranca(usuario_id=usuario.id, tipo="mfa_pendente", token=token,
                              expira_em=utcnow() + timedelta(minutes=10)))
        db.commit()
        if usuario.mfa_metodo == "email":
            mfa.enviar_codigo_email(db, usuario, token)
        return _tela_codigo(request, usuario, token)

    # Perfil exige 2FA e o usuário ainda não configurou: entra direto na
    # configuração (e não navega por outras telas até concluir).
    return _login_response(db, request, usuario,
                           "/mfa" if mfa.pendente(usuario) else "/")


def _tela_codigo(request: Request, usuario: Usuario, token: str, erro: str = "",
                 info: str = ""):
    email = usuario.email
    usuario_mascarado = email[:2] + "***" + email[email.find("@"):] if "@" in email else ""
    return templates.TemplateResponse(request, "auth/mfa.html", {
        "token": token, "erro": erro, "info": info,
        "metodo": usuario.mfa_metodo or "app", "email": usuario_mascarado})


@router.post("/login/mfa", include_in_schema=False)
def login_mfa(
    request: Request,
    token: str = Form(...),
    codigo: str = Form(...),
    db: Session = Depends(get_session),
):
    registro = _valid_token(db, token, "mfa_pendente")
    if registro is None:
        return RedirectResponse("/login?erro=Sess%C3%A3o+de+login+expirada.",
                                status_code=303)
    usuario = db.get(Usuario, registro.usuario_id)
    if _limite_codigo.blocked(token):
        registro.utilizado = True
        db.commit()
        write_log(db, "WARNING", "auth", f"2FA: tentativas esgotadas para {usuario.email}")
        return RedirectResponse("/login?erro=Muitas+tentativas.+Entre+de+novo.",
                                status_code=303)
    como = mfa.verificar(db, usuario, codigo, token)
    if como is None:
        _limite_codigo.register(token)
        return _tela_codigo(request, usuario, token, "Código inválido. Tente novamente.")
    registro.utilizado = True
    db.commit()
    if como == "recuperacao":
        restam = mfa.restantes(usuario)
        record_audit(db, tabela="usuarios", acao="MFA_RECUPERACAO",
                     registro_id=usuario.id, valor_novo={"restantes": restam},
                     usuario=usuario, request=request)
        from app.core.notifications import notify
        notify(db, usuario.id, "Código de recuperação usado",
               f"Você entrou com um código de recuperação. Restam {restam}. "
               "Gere novos códigos em Autenticação em duas etapas se estiver acabando.",
               tipo="warning", empresa_id=usuario.empresa_id)
    return _login_response(db, request, usuario)


@router.post("/login/mfa/reenviar", include_in_schema=False)
def login_mfa_reenviar(
    request: Request,
    token: str = Form(...),
    db: Session = Depends(get_session),
):
    registro = _valid_token(db, token, "mfa_pendente")
    if registro is None:
        return RedirectResponse("/login", status_code=303)
    usuario = db.get(Usuario, registro.usuario_id)
    if usuario.mfa_metodo != "email":
        return _tela_codigo(request, usuario, token)
    if _limite_reenvio.blocked(token):
        return _tela_codigo(request, usuario, token,
                            "Muitos reenvios. Aguarde alguns minutos.")
    _limite_reenvio.register(token)
    mfa.enviar_codigo_email(db, usuario, token)
    return _tela_codigo(request, usuario, token, info="Enviamos um novo código.")


@router.post("/logout", include_in_schema=False)
def logout(request: Request, db: Session = Depends(get_session)):
    token = request.cookies.get(SESSION_COOKIE)
    usuario = getattr(request.state, "user", None)
    if token:
        destroy_session(db, token)
    record_audit(db, tabela="usuarios", acao="LOGOUT", usuario=usuario, request=request)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


# --- Gestão do MFA (logado) ---


def _tela_mfa(request, db, usuario, **extra):
    """Tela de configuração: estado atual, QR code e ações."""
    db_user = db.get(Usuario, usuario.id)
    contexto = {
        "page_title": "Autenticação em duas etapas", "erro": "", "ok": "",
        "metodos": mfa.METODOS, "obrigatorio": mfa.exige_2fa(db_user),
        "restantes": mfa.restantes(db_user),
        "smtp": mfa.smtp_configurado(db, db_user.empresa_id),
        "codigos": None, "email_enviado": False,
    }
    if not db_user.mfa_habilitado:
        if not db_user.mfa_secret:
            db_user.mfa_secret = generate_secret()
            db.commit()
        contexto["secret"] = db_user.mfa_secret
        contexto["uri"] = otpauth_uri(db_user.mfa_secret, db_user.email, settings.app_name)
        try:
            contexto["qr"] = mfa.qr_svg(contexto["uri"])
        except ImportError:       # sem segno: fica a chave para digitar
            contexto["qr"] = None
    contexto.update(extra)
    return render(request, "auth/mfa_setup.html", db_user, **contexto)


@router.get("/mfa", include_in_schema=False)
def mfa_page(
    request: Request,
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    return _tela_mfa(request, db, usuario)


@router.post("/mfa/email/enviar", include_in_schema=False)
def mfa_email_enviar(
    request: Request,
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Configuração por e-mail: manda um código para confirmar o endereço."""
    db_user = db.get(Usuario, usuario.id)
    if _limite_reenvio.blocked(f"setup:{db_user.id}"):
        return _tela_mfa(request, db, usuario, aba="email",
                         erro="Muitos envios. Aguarde alguns minutos.")
    _limite_reenvio.register(f"setup:{db_user.id}")
    mfa.enviar_codigo_email(db, db_user, "ativar")
    return _tela_mfa(request, db, usuario, aba="email", email_enviado=True)


@router.post("/mfa/ativar", include_in_schema=False)
def mfa_enable(
    request: Request,
    codigo: str = Form(...),
    metodo: str = Form("app"),
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    db_user = db.get(Usuario, usuario.id)
    metodo = metodo if metodo in mfa.METODOS else "app"
    if metodo == "email":
        valido = mfa.conferir_codigo_email(db, db_user, "ativar", codigo)
    else:
        valido = verify_totp(db_user.mfa_secret or "", codigo)
    if not valido:
        return _tela_mfa(request, db, usuario, aba=metodo,
                         email_enviado=metodo == "email",
                         erro="Código inválido — confira e tente de novo.")
    db_user.mfa_habilitado = True
    db_user.mfa_metodo = metodo
    if metodo == "email":
        db_user.mfa_secret = None
    codigos = mfa.gerar_recuperacao(db_user)
    db.commit()
    record_audit(db, tabela="usuarios", acao="MFA_ATIVADO", registro_id=db_user.id,
                 valor_novo={"metodo": metodo}, usuario=usuario, request=request)
    return _tela_mfa(request, db, usuario, codigos=codigos,
                     ok="Autenticação em duas etapas ativada.")


def _confere_senha(db_user, senha: str) -> bool:
    return bool(senha) and verify_password(db_user.senha_hash, senha)


@router.post("/mfa/recuperacao", include_in_schema=False)
def mfa_novos_codigos(
    request: Request,
    senha: str = Form(""),
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    db_user = db.get(Usuario, usuario.id)
    if not db_user.mfa_habilitado or not _confere_senha(db_user, senha):
        return _tela_mfa(request, db, usuario, erro="Senha incorreta.")
    codigos = mfa.gerar_recuperacao(db_user)
    db.commit()
    record_audit(db, tabela="usuarios", acao="MFA_NOVOS_CODIGOS",
                 registro_id=db_user.id, usuario=usuario, request=request)
    return _tela_mfa(request, db, usuario, codigos=codigos,
                     ok="Novos códigos gerados — os anteriores deixaram de valer.")


@router.post("/mfa/desativar", include_in_schema=False)
def mfa_disable(
    request: Request,
    senha: str = Form(""),
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    db_user = db.get(Usuario, usuario.id)
    if mfa.exige_2fa(db_user):
        return _tela_mfa(request, db, usuario, erro="Seu perfil exige a autenticação "
                         "em duas etapas; ela não pode ser desligada. Para trocar de "
                         "método, peça a um administrador que a redefina.")
    if not _confere_senha(db_user, senha):
        return _tela_mfa(request, db, usuario, erro="Senha incorreta.")
    mfa.desligar(db_user)
    db.commit()
    record_audit(db, tabela="usuarios", acao="MFA_DESATIVADO", registro_id=db_user.id,
                 usuario=usuario, request=request)
    return RedirectResponse("/mfa", status_code=303)


# --- Recuperação de senha ---


@router.get("/recuperar-senha", include_in_schema=False)
def recover_form(request: Request):
    return templates.TemplateResponse(
        request, "auth/recover.html", {"enviado": False, "link_dev": None})


@router.post("/recuperar-senha", include_in_schema=False)
def recover(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_session),
):
    usuario = _find_user(db, email)
    link_dev = None
    if usuario is not None:
        token = generate_token()[:64]
        db.add(TokenSeguranca(usuario_id=usuario.id, tipo="recuperacao_senha", token=token,
                              expira_em=utcnow() + timedelta(hours=2)))
        db.commit()
        link = f"{str(request.base_url).rstrip('/')}/redefinir-senha/{token}"
        enviado = send_mail(db, usuario.email, "Recuperação de senha",
                            f"<p>Para redefinir sua senha, acesse: "
                            f"<a href='{link}'>{link}</a></p><p>O link expira em 2 horas.</p>",
                            empresa_id=usuario.tenant_id)
        if not enviado and settings.debug:
            link_dev = f"/redefinir-senha/{token}"
    return templates.TemplateResponse(
        request, "auth/recover.html", {"enviado": True, "link_dev": link_dev})


@router.get("/redefinir-senha/{token}", include_in_schema=False)
def reset_form(request: Request, token: str, db: Session = Depends(get_session)):
    valido = _valid_token(db, token, "recuperacao_senha") is not None
    return templates.TemplateResponse(
        request, "auth/reset.html", {"token": token, "valido": valido, "erro": ""})


@router.post("/redefinir-senha/{token}", include_in_schema=False)
def reset(
    request: Request,
    token: str,
    senha: str = Form(...),
    confirmacao: str = Form(...),
    db: Session = Depends(get_session),
):
    registro = _valid_token(db, token, "recuperacao_senha")
    if registro is None:
        return templates.TemplateResponse(
            request, "auth/reset.html", {"token": token, "valido": False, "erro": ""})
    if senha != confirmacao or len(senha) < 8:
        return templates.TemplateResponse(
            request, "auth/reset.html",
            {"token": token, "valido": True,
             "erro": "As senhas não conferem ou têm menos de 8 caracteres."})
    usuario = db.get(Usuario, registro.usuario_id)
    usuario.senha_hash = hash_password(senha)
    registro.utilizado = True
    db.commit()
    record_audit(db, tabela="usuarios", acao="ALTERACAO_SENHA",
                 registro_id=usuario.id, usuario=usuario, request=request)
    return RedirectResponse("/login?info=Senha+redefinida+com+sucesso.", status_code=303)


# --- Alteração de senha (logado) ---


@router.get("/alterar-senha", include_in_schema=False)
def change_form(request: Request, usuario: Usuario = Depends(get_current_user)):
    return render(request, "auth/change.html", usuario,
                  page_title="Alterar senha", erro="", ok=False)


@router.post("/alterar-senha", include_in_schema=False)
def change(
    request: Request,
    senha_atual: str = Form(...),
    senha_nova: str = Form(...),
    confirmacao: str = Form(...),
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    erro, ok = "", False
    if not verify_password(usuario.senha_hash, senha_atual):
        erro = "Senha atual incorreta."
    elif senha_nova != confirmacao or len(senha_nova) < 8:
        erro = "As senhas não conferem ou têm menos de 8 caracteres."
    else:
        db_user = db.get(Usuario, usuario.id)
        db_user.senha_hash = hash_password(senha_nova)
        db.commit()
        record_audit(db, tabela="usuarios", acao="ALTERACAO_SENHA",
                     registro_id=usuario.id, usuario=usuario, request=request)
        ok = True
    return render(request, "auth/change.html", usuario,
                  page_title="Alterar senha", erro=erro, ok=ok)


# --- Confirmação de e-mail ---


@router.get("/confirmar-email/{token}", include_in_schema=False)
def confirm_email(request: Request, token: str, db: Session = Depends(get_session)):
    registro = _valid_token(db, token, "confirmacao_email")
    ok = registro is not None
    if ok:
        usuario = db.get(Usuario, registro.usuario_id)
        usuario.email_confirmado = True
        registro.utilizado = True
        db.commit()
        record_audit(db, tabela="usuarios", acao="CONFIRMACAO_EMAIL",
                     registro_id=usuario.id, usuario=usuario, request=request)
    return templates.TemplateResponse(request, "auth/confirm.html", {"ok": ok})


def _valid_token(db: Session, token: str, tipo: str) -> TokenSeguranca | None:
    registro = db.scalar(select(TokenSeguranca).where(
        TokenSeguranca.token == token,
        TokenSeguranca.tipo == tipo,
        TokenSeguranca.utilizado.is_(False),
    ))
    if registro is None:
        return None
    expira = registro.expira_em
    if expira.tzinfo is None:
        from datetime import timezone

        expira = expira.replace(tzinfo=timezone.utc)
    if expira < utcnow():
        return None
    return registro
