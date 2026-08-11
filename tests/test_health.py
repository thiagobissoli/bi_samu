from fastapi.testclient import TestClient

from app.core.seeds import ADMIN_EMAIL, ADMIN_SENHA
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_dashboard_requer_login():
    response = client.get("/", headers={"accept": "text/html"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_e_dashboard():
    response = client.post(
        "/login",
        data={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "session" in response.cookies

    dashboard = client.get("/", headers={"accept": "text/html"})
    assert dashboard.status_code == 200
    assert "Dashboard" in dashboard.text


def test_login_invalido():
    response = client.post("/login", data={"email": ADMIN_EMAIL, "senha": "errada"})
    assert "inválidos" in response.text


def _login():
    client.post("/login", data={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})


def test_health_inclui_banco():
    response = client.get("/health")
    assert response.json()["database"] == "ok"


def test_notificacoes():
    _login()
    response = client.get("/notificacoes/", headers={"accept": "text/html"})
    assert response.status_code == 200


def test_uploads():
    _login()
    response = client.get("/uploads/", headers={"accept": "text/html"})
    assert response.status_code == 200


def test_paginacao_usuarios():
    _login()
    response = client.get("/usuarios/?page=1", headers={"accept": "text/html"})
    assert response.status_code == 200


def test_headers_seguranca():
    """SAMEORIGIN, não DENY: o visualizador de PDF do prontuário embute
    páginas da própria aplicação em iframe (DENY / frame-ancestors 'none'
    deixariam o modal da ocorrência em branco, sem erro visível).
    Enquadramento por outros sites continua barrado."""
    response = client.get("/health")
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    csp = response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'self'" in csp
    assert "object-src 'self'" in csp


def test_mfa_page():
    _login()
    response = client.get("/mfa", headers={"accept": "text/html"})
    assert response.status_code == 200


def test_config_service_cache_e_criptografia():
    from app.core.config_service import get_config, set_config
    from app.core.database import SessionLocal
    from app.models import Configuracao
    from sqlalchemy import select

    db = SessionLocal()
    try:
        set_config(db, "smtp_pass", "senha-super-secreta", empresa_id=1)
        # No banco: criptografado
        row = db.scalar(select(Configuracao).where(
            Configuracao.chave == "smtp_pass", Configuracao.empresa_id == 1))
        assert row.valor.startswith("enc:")
        assert "senha-super-secreta" not in row.valor
        # Na leitura: descriptografado (e cacheado)
        assert get_config(db, "smtp_pass", empresa_id=1) == "senha-super-secreta"
    finally:
        db.close()


def test_config_sensivel_mascarada_na_tela():
    _login()
    client.post("/configuracoes/salvar", data={"chave": "smtp_pass", "valor": "outrasenha123"})
    page = client.get("/configuracoes/", headers={"accept": "text/html"})
    assert page.status_code == 200
    assert "outrasenha123" not in page.text


def test_timezone_aplicado():
    from app.core.config_service import set_config
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        set_config(db, "timezone", "America/Sao_Paulo", empresa_id=1)
    finally:
        db.close()
    _login()
    page = client.get("/auditoria/", headers={"accept": "text/html"})
    assert page.status_code == 200


def test_excluir_configuracao():
    from app.core.config_service import get_config
    from app.core.database import SessionLocal
    from app.models import Configuracao
    from sqlalchemy import select

    _login()
    client.post("/configuracoes/salvar", data={"chave": "chave_temporaria", "valor": "abc"})
    db = SessionLocal()
    try:
        row = db.scalar(select(Configuracao).where(
            Configuracao.chave == "chave_temporaria", Configuracao.deleted_at.is_(None)))
        assert row is not None
        client.post(f"/configuracoes/{row.id}/delete")
        # rollback encerra a transação aberta: no MySQL (REPEATABLE READ) o
        # snapshot antigo esconderia o delete feito na sessão da rota.
        db.rollback()
        db.expire_all()
        # Soft delete: some da leitura, mas a linha continua no banco (§36.7)
        assert get_config(db, "chave_temporaria", "padrao", empresa_id=1) == "padrao"
        ainda_existe = db.scalar(select(Configuracao).where(Configuracao.id == row.id))
        assert ainda_existe.deleted_at is not None
    finally:
        db.close()
