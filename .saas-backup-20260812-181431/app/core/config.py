from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Raiz do projeto (pasta que contém app/) — âncora para caminhos relativos,
# para que o servidor funcione igual independentemente do CWD de partida.
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuração centralizada (§35.23) — valores vêm do .env, nunca fixos."""

    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"),
                                      extra="ignore")

    app_name: str = "Samu"
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
    s = Settings()
    # Normaliza caminhos relativos para a raiz do projeto: iniciar o
    # servidor de qualquer diretório deve usar sempre o MESMO banco e
    # a MESMA pasta de uploads (evita "reset" de configurações).
    prefixo = "sqlite:///"
    if s.database_url.startswith(prefixo):
        caminho = s.database_url[len(prefixo):]
        if not Path(caminho).is_absolute():
            s.database_url = prefixo + str((BASE_DIR / caminho).resolve())
    if not Path(s.upload_dir).is_absolute():
        s.upload_dir = str((BASE_DIR / s.upload_dir).resolve())
    return s


settings = get_settings()
