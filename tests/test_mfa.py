"""Autenticação em duas etapas: app (TOTP), e-mail, recuperação,
obrigatoriedade por perfil e redefinição pelo administrador."""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import mfa
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.core.seeds import ADMIN_EMAIL, ADMIN_SENHA
from app.core.totp import totp_code
from app.main import app
from app.models import Perfil, Usuario

HTML = {"accept": "text/html"}
SENHA = "Senha-teste-2fa-123"


@pytest.fixture()
def conta():
    """Usuário e perfil de teste, apagados ao final."""
    db = SessionLocal()
    perfil = Perfil(empresa_id=1, nome="Perfil teste 2FA", ativo=True)
    usuario = Usuario(empresa_id=1, nome="Teste Dois Fatores", ativo=True,
                      email="teste.2fa@exemplo.com", senha_hash=hash_password(SENHA))
    usuario.perfis.append(perfil)
    db.add_all([perfil, usuario])
    db.commit()
    ids = (usuario.id, perfil.id)
    db.close()
    yield {"id": ids[0], "perfil": ids[1], "email": "teste.2fa@exemplo.com"}
    db = SessionLocal()
    u = db.get(Usuario, ids[0])
    u.perfis.clear()
    db.delete(u)
    db.delete(db.get(Perfil, ids[1]))
    db.commit()
    db.close()


def _ler(uid):
    db = SessionLocal()
    try:
        return db.get(Usuario, uid)
    finally:
        db.close()


def _login(cliente, email, senha=SENHA):
    return cliente.post("/login", data={"email": email, "senha": senha},
                        follow_redirects=False)


def _token(html):
    return re.search(r'name="token" value="([^"]+)"', html).group(1)


def _ativar_app(cliente, uid) -> list[str]:
    html = cliente.get("/mfa", headers=HTML).text
    assert "<svg" in html                                   # QR code
    segredo = _ler(uid).mfa_secret
    html = cliente.post("/mfa/ativar", data={"metodo": "app",
                                             "codigo": totp_code(segredo)}).text
    codigos = re.findall(r">([A-Z0-9]{4}-[A-Z0-9]{4})<", html)
    assert len(codigos) == mfa.QTD_RECUPERACAO
    return codigos


def test_uri_do_qr_code_codifica_o_nome():
    from app.core.totp import otpauth_uri
    uri = otpauth_uri("ABC", "a@b.com", "Qualidade SAMU")
    assert "Qualidade%20SAMU" in uri and " " not in uri


def test_fluxo_com_aplicativo_e_codigo_de_recuperacao(conta):
    c = TestClient(app)
    assert _login(c, conta["email"]).headers["location"] == "/"
    codigos = _ativar_app(c, conta["id"])
    assert _ler(conta["id"]).mfa_metodo == "app"

    novo = TestClient(app)
    resp = _login(novo, conta["email"])
    assert resp.status_code == 200 and "aplicativo autenticador" in resp.text
    token = _token(resp.text)
    errado = novo.post("/login/mfa", data={"token": token, "codigo": "000000"})
    assert "Código inválido" in errado.text
    ok = novo.post("/login/mfa", data={"token": token,
                                       "codigo": totp_code(_ler(conta["id"]).mfa_secret)},
                   follow_redirects=False)
    assert ok.status_code == 303 and ok.headers["location"] == "/"

    # código de recuperação: vale uma vez
    outro = TestClient(app)
    token = _token(_login(outro, conta["email"]).text)
    r = outro.post("/login/mfa", data={"token": token, "codigo": codigos[0].lower()},
                   follow_redirects=False)
    assert r.status_code == 303
    assert mfa.restantes(_ler(conta["id"])) == mfa.QTD_RECUPERACAO - 1
    token = _token(_login(TestClient(app), conta["email"]).text)
    again = TestClient(app).post("/login/mfa", data={"token": token, "codigo": codigos[0]})
    assert "Código inválido" in again.text


def test_tentativas_esgotadas_encerram_o_login(conta):
    c = TestClient(app)
    _login(c, conta["email"])
    _ativar_app(c, conta["id"])
    novo = TestClient(app)
    token = _token(_login(novo, conta["email"]).text)
    for _ in range(5):
        novo.post("/login/mfa", data={"token": token, "codigo": "111111"})
    fim = novo.post("/login/mfa", data={"token": token, "codigo": "111111"},
                    follow_redirects=False)
    assert fim.status_code == 303 and "Muitas" in fim.headers["location"]


def test_metodo_por_email(conta, monkeypatch):
    enviados = []

    def fake_send(db, to, subject, body, empresa_id=1, anexos=None):
        enviados.append(re.search(r"(\d{6})", body).group(1))
        return True
    monkeypatch.setattr("app.core.mail.send_mail", fake_send)
    monkeypatch.setattr(mfa, "smtp_configurado", lambda db, emp: True)

    c = TestClient(app)
    _login(c, conta["email"])
    html = c.post("/mfa/email/enviar").text
    assert "Enviamos um código" in html
    html = c.post("/mfa/ativar", data={"metodo": "email", "codigo": enviados[-1]}).text
    assert "ativada" in html and _ler(conta["id"]).mfa_metodo == "email"

    novo = TestClient(app)
    resp = _login(novo, conta["email"])
    assert "Enviamos um código de 6 dígitos" in resp.text and "te***@" in resp.text
    token = _token(resp.text)
    ok = novo.post("/login/mfa", data={"token": token, "codigo": enviados[-1]},
                   follow_redirects=False)
    assert ok.status_code == 303
    # o código do e-mail vale uma vez e só para aquele login
    token2 = _token(_login(TestClient(app), conta["email"]).text)
    reuso = TestClient(app).post("/login/mfa", data={"token": token2,
                                                     "codigo": enviados[-2]})
    assert "Código inválido" in reuso.text


def test_perfil_que_exige_obriga_a_configurar(conta):
    db = SessionLocal()
    db.get(Perfil, conta["perfil"]).exige_2fa = True
    db.commit()
    db.close()

    c = TestClient(app)
    assert _login(c, conta["email"]).headers["location"] == "/mfa"
    # enquanto não configura, qualquer outra tela leva à configuração
    r = c.get("/", headers=HTML, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/mfa"
    assert c.get("/ncps/api/indicadores").status_code == 403
    assert "Seu perfil exige" in c.get("/mfa", headers=HTML).text

    _ativar_app(c, conta["id"])
    assert c.get("/", headers=HTML, follow_redirects=False).status_code == 200
    # não pode desligar
    html = c.post("/mfa/desativar", data={"senha": SENHA}).text
    assert "não pode ser desligada" in html and _ler(conta["id"]).mfa_habilitado


def test_desativar_pede_senha(conta):
    c = TestClient(app)
    _login(c, conta["email"])
    _ativar_app(c, conta["id"])
    assert "Senha incorreta" in c.post("/mfa/desativar", data={"senha": "x"}).text
    c.post("/mfa/desativar", data={"senha": SENHA})
    assert not _ler(conta["id"]).mfa_habilitado


def test_administrador_redefine(conta):
    c = TestClient(app)
    _login(c, conta["email"])
    _ativar_app(c, conta["id"])

    admin = TestClient(app)
    _login(admin, ADMIN_EMAIL, ADMIN_SENHA)
    lista = admin.get("/usuarios/", headers=HTML).text
    assert "Teste Dois Fatores" in lista
    r = admin.post(f"/usuarios/{conta['id']}/mfa/redefinir", follow_redirects=False)
    assert r.status_code == 303 and "mfa=redefinido" in r.headers["location"]
    u = _ler(conta["id"])
    assert not u.mfa_habilitado and u.mfa_secret is None and u.mfa_recuperacao is None
    db = SessionLocal()
    from app.models import Notificacao
    avisos = list(db.scalars(select(Notificacao).where(Notificacao.usuario_id == conta["id"])))
    for n in avisos:
        db.delete(n)
    db.commit()
    db.close()
    assert any(n.titulo == "2FA redefinido" for n in avisos)
