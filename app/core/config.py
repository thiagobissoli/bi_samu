from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Raiz do projeto (pasta que contém app/) — âncora para caminhos relativos,
# para que o servidor funcione igual independentemente do diretório de onde
# for iniciado. Sem isso, subir o uvicorn de outra pasta apontaria para outro
# banco e outra pasta de uploads, parecendo um "reset" das configurações.
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuração centralizada (§35.23) — valores vêm do .env, nunca fixos."""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"), extra="ignore"
    )

    app_name: str = "Qualidade SAMU"
    debug: bool = False
    secret_key: str = "trocar-em-producao"
    # SQLite por padrão (desenvolvimento). Produção: PostgreSQL 16+ (§36.2).
    database_url: str = "sqlite:///./dev.db"
    redis_url: str = "redis://localhost:6379/0"
    timezone: str = "UTC"
    upload_dir: str = "uploads"
    default_language: str = "pt-BR"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()

    # Normaliza caminhos relativos para a raiz do projeto.
    prefixo = "sqlite:///"
    if settings.database_url.startswith(prefixo):
        caminho = settings.database_url[len(prefixo):]
        if caminho and not Path(caminho).is_absolute():
            settings.database_url = prefixo + str((BASE_DIR / caminho).resolve())
    if not Path(settings.upload_dir).is_absolute():
        settings.upload_dir = str((BASE_DIR / settings.upload_dir).resolve())

    # HS256 (JWT §6) exige 32+ bytes; a mesma chave protege as configurações
    # sensíveis (§39.29). Fora de DEBUG, uma chave fraca é problema real.
    if not settings.debug and len(settings.secret_key.encode()) < 32:
        import warnings

        warnings.warn(
            "SECRET_KEY fraca (< 32 bytes). Gere uma com "
            "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"` "
            "e ajuste o .env — trocá-la invalida os valores já criptografados.",
            stacklevel=2,
        )
    return settings


settings = get_settings()
