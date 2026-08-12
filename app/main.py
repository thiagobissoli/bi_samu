from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.middleware import SecurityHeadersMiddleware
from app.core.config import settings
from app.core.database import get_session, init_db
from app.core.modules import discover_modules
from app.core.templating import render
from app.models import Auditoria, Empresa, Log, Usuario

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/health", tags=["Health"])
def health(db: Session = Depends(get_session)) -> dict:
    """Health check (§39.21) — inclui verificação do banco."""
    try:
        db.execute(select(1))
        database = "ok"
    except Exception:  # noqa: BLE001
        database = "error"
    return {"status": "ok" if database == "ok" else "degraded",
            "app": settings.app_name, "database": database}


@app.get("/", include_in_schema=False)
def dashboard(
    request: Request,
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Dashboard (§10) — widgets condicionados às permissões do perfil."""
    permissoes = usuario.permissoes
    widgets = {}

    if "usuario.listar" in permissoes:
        widgets["usuarios"] = db.scalar(
            select(func.count()).select_from(Usuario).where(Usuario.deleted_at.is_(None))
        )
    if "empresa.listar" in permissoes:
        widgets["empresas"] = db.scalar(
            select(func.count()).select_from(Empresa).where(Empresa.deleted_at.is_(None))
        )
    if "auditoria.listar" in permissoes:
        widgets["eventos"] = db.scalar(select(func.count()).select_from(Auditoria))
        widgets["ultimos_eventos"] = list(
            db.scalars(select(Auditoria).order_by(Auditoria.id.desc()).limit(8))
        )
    if "log.listar" in permissoes:
        widgets["erros"] = db.scalar(
            select(func.count()).select_from(Log).where(Log.nivel.in_(["ERROR", "CRITICAL"]))
        )

    return render(request, "dashboard/index.html", usuario,
                  page_title="Dashboard", widgets=widgets)


def _banner_inicializacao() -> None:
    """Registra qual código e qual banco estão em uso.

    Outro projeto instalado no mesmo Python que também exponha um pacote
    chamado `app` pode ser carregado no lugar deste — o sintoma é o
    sistema subir "vazio" (sem as configurações e credenciais gravadas),
    porque na verdade é outra aplicação, com outro banco. Sem este aviso
    a troca é silenciosa; com ele, aparece na primeira linha do log.
    """
    import logging
    import re

    logger = logging.getLogger("uvicorn.error")
    banco = re.sub(r"//[^:]+:[^@]+@", "//***:***@", settings.database_url)
    logger.info("Aplicação: %s", BASE_DIR.parent)
    logger.info("Banco de dados: %s", banco)
    if banco.startswith("sqlite") and (BASE_DIR.parent / ".env").is_file():
        logger.warning(
            "SQLite em uso apesar de existir .env no projeto — confira se o "
            "pacote 'app' carregado é mesmo o deste diretório (%s).",
            BASE_DIR)


_banner_inicializacao()
discover_modules(app)
init_db()

from app.core.seeds import run_seeds  # noqa: E402  (após init_db)

run_seeds()
