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
from app.core.middleware import login_limiter
from app.core.security import generate_token, hash_password, verify_password
from app.core.templating import render, templates
from app.core.totp import generate_secret, otpauth_uri, verify_totp
from app.models import TokenSeguranca, Usuario

router = APIRouter(tags=["Auth"])


def _find_user(db: Session, email: str) -> Usuario | None:
    return db.scalar(select(Usuario).where(
        Usuario.email == email.strip().lower(), Usuario.deleted_at.is_(None)
    ))


def _login_response(db: Session, request: Request, usuario: Usuario):
    ip = request.client.host if request.client else None
    token = create_session(db, usuario, ip, request.headers.get("user-agent"))
    usuario.ultimo_login = utcnow()
    usuario.ultimo_ip = ip
    db.commit()
    record_audit(db, tabela="usuarios", acao="LOGIN", registro_id=usuario.id,
                 usuario=usuario, request=request)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                        secure=not settings.debug, max_age=8 * 3600)
    return response


# --- Login / Logout ---


@router.get("/login", include_in_schema=False)
async def login_form(request: Request, erro: str = "", info: str = ""):
    return templates.TemplateResponse(request, "auth/login.html", {"erro": erro, "info": info})


@router.post("/login", include_in_schema=False)
async def login(
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

    # MFA opcional (§6): senha ok -> exigir código do autenticador.
    if usuario.mfa_habilitado and usuario.mfa_secret:
        token = generate_token()[:64]
        db.add(TokenSeguranca(usuario_id=usuario.id, tipo="mfa_pendente", token=token,
                              expira_em=utcnow() + timedelta(minutes=5)))
        db.commit()
        return templates.TemplateResponse(request, "auth/mfa.html",
                                          {"token": token, "erro": ""})

    return _login_response(db, request, usuario)


@router.post("/login/mfa", include_in_schema=False)
async def login_mfa(
    request: Request,
    token: str = Form(...),
    codigo: str = Form(...),
    db: Session = Depends(get_session),
):
    registro = _valid_token(db, token, "mfa_pendente")
    if registro is None:
        return RedirectResponse("/login", status_code=303)
    usuario = db.get(Usuario, registro.usuario_id)
    if not verify_totp(usuario.mfa_secret or "", codigo):
        return templates.TemplateResponse(request, "auth/mfa.html", {
            "token": token, "erro": "Código inválido. Tente novamente."})
    registro.utilizado = True
    db.commit()
    return _login_response(db, request, usuario)


@router.post("/logout", include_in_schema=False)
async def logout(request: Request, db: Session = Depends(get_session)):
    token = request.cookies.get(SESSION_COOKIE)
    usuario = getattr(request.state, "user", None)
    if token:
        destroy_session(db, token)
    record_audit(db, tabela="usuarios", acao="LOGOUT", usuario=usuario, request=request)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


# --- Gestão do MFA (logado) ---


@router.get("/mfa", include_in_schema=False)
async def mfa_page(
    request: Request,
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    db_user = db.get(Usuario, usuario.id)
    context = {"page_title": "Autenticação em duas etapas", "erro": "", "ok": ""}
    if not db_user.mfa_habilitado:
        if not db_user.mfa_secret:
            db_user.mfa_secret = generate_secret()
            db.commit()
        context["secret"] = db_user.mfa_secret
        context["uri"] = otpauth_uri(db_user.mfa_secret, db_user.email, settings.app_name)
    return render(request, "auth/mfa_setup.html", usuario, **context)


@router.post("/mfa/ativar", include_in_schema=False)
async def mfa_enable(
    request: Request,
    codigo: str = Form(...),
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    db_user = db.get(Usuario, usuario.id)
    if not verify_totp(db_user.mfa_secret or "", codigo):
        return render(request, "auth/mfa_setup.html", usuario,
                      page_title="Autenticação em duas etapas",
                      erro="Código inválido — confira o autenticador.", ok="",
                      secret=db_user.mfa_secret,
                      uri=otpauth_uri(db_user.mfa_secret, db_user.email, settings.app_name))
    db_user.mfa_habilitado = True
    db.commit()
    record_audit(db, tabela="usuarios", acao="MFA_ATIVADO", registro_id=db_user.id,
                 usuario=usuario, request=request)
    return render(request, "auth/mfa_setup.html", usuario,
                  page_title="Autenticação em duas etapas", erro="",
                  ok="MFA ativado com sucesso.")


@router.post("/mfa/desativar", include_in_schema=False)
async def mfa_disable(
    request: Request,
    codigo: str = Form(...),
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    db_user = db.get(Usuario, usuario.id)
    if not verify_totp(db_user.mfa_secret or "", codigo):
        return render(request, "auth/mfa_setup.html", usuario,
                      page_title="Autenticação em duas etapas",
                      erro="Código inválido.", ok="")
    db_user.mfa_habilitado = False
    db_user.mfa_secret = None
    db.commit()
    record_audit(db, tabela="usuarios", acao="MFA_DESATIVADO", registro_id=db_user.id,
                 usuario=usuario, request=request)
    return RedirectResponse("/mfa", status_code=303)


# --- Recuperação de senha ---


@router.get("/recuperar-senha", include_in_schema=False)
async def recover_form(request: Request):
    return templates.TemplateResponse(
        request, "auth/recover.html", {"enviado": False, "link_dev": None})


@router.post("/recuperar-senha", include_in_schema=False)
async def recover(
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
                            empresa_id=usuario.empresa_id)
        if not enviado and settings.debug:
            link_dev = f"/redefinir-senha/{token}"
    return templates.TemplateResponse(
        request, "auth/recover.html", {"enviado": True, "link_dev": link_dev})


@router.get("/redefinir-senha/{token}", include_in_schema=False)
async def reset_form(request: Request, token: str, db: Session = Depends(get_session)):
    valido = _valid_token(db, token, "recuperacao_senha") is not None
    return templates.TemplateResponse(
        request, "auth/reset.html", {"token": token, "valido": valido, "erro": ""})


@router.post("/redefinir-senha/{token}", include_in_schema=False)
async def reset(
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
async def change_form(request: Request, usuario: Usuario = Depends(get_current_user)):
    return render(request, "auth/change.html", usuario,
                  page_title="Alterar senha", erro="", ok=False)


@router.post("/alterar-senha", include_in_schema=False)
async def change(
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
async def confirm_email(request: Request, token: str, db: Session = Depends(get_session)):
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
