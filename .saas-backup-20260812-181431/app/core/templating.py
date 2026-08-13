from datetime import timezone as dt_timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context

BASE_DIR = Path(__file__).resolve().parent.parent

# Instância única de templates compartilhada por todos os módulos.
_directories = [BASE_DIR / "templates"]
_directories += sorted(BASE_DIR.glob("modules/*/templates"))

templates = Jinja2Templates(directory=[str(d) for d in _directories])


@pass_context
def localdt(ctx, value, fmt: str = "%d/%m/%Y %H:%M"):
    """Exibe datetimes UTC no fuso horário da empresa (§22, §36.2).

    O fuso vem da configuração `timezone` da empresa (injetada pelo render()
    como `tz`); fallback para UTC se ausente ou inválido.
    """
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_timezone.utc)
    tz_name = ctx.get("tz") or "UTC"
    try:
        zone = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 — fuso inválido não pode quebrar a página
        zone = dt_timezone.utc
    return value.astimezone(zone).strftime(fmt)


templates.env.filters["localdt"] = localdt


def render(request: Request, name: str, usuario=None, **context):
    """Resposta HTML padrão: injeta menu (filtrado por permissão), usuário,
    notificações não lidas (§21) e o fuso da empresa (§22)."""
    from app.core.modules import get_menu

    nao_lidas = 0
    tz = "UTC"
    if usuario is not None:
        from app.core.config import settings
        from app.core.config_service import get_config
        from app.core.database import SessionLocal
        from app.core.notifications import unread_count

        db = SessionLocal()
        try:
            nao_lidas = unread_count(db, usuario.id)
            tz = get_config(db, "timezone", settings.timezone, usuario.empresa_id)
        finally:
            db.close()

    ctx = {
        "menu": get_menu(usuario),
        "usuario_logado": usuario,
        "notificacoes_nao_lidas": nao_lidas,
        "tz": tz,
        **context,
    }
    return templates.TemplateResponse(request, name, ctx)
