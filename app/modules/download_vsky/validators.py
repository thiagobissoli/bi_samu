"""Validações do módulo Download vSky (§35.2)."""

from datetime import datetime
from urllib.parse import urlparse

from app.modules.download_vsky.constants import DATA_FMT


def normalizar_base_url(url: str) -> str:
    """Reduz a URL configurada a esquema://host.

    Aceita o que o usuário colar — inclusive a URL completa da página de
    login (ex.: https://es.vskysamu.com.br/vskymanagement/login.xhtml) —
    pois os caminhos do portal são adicionados pelo cliente.
    """
    url = url.strip()
    if not url:
        return ""
    if "://" not in url:
        url = f"https://{url}"
    parsed = urlparse(url)
    if not parsed.netloc:
        raise ValueError("URL do portal vSky inválida.")
    return f"{parsed.scheme}://{parsed.netloc}"


def validar_periodo(data_inicial: str, data_final: str) -> tuple[str, str]:
    """Valida datas dd/mm/aaaa e devolve o par normalizado."""
    try:
        inicio = datetime.strptime(data_inicial.strip(), DATA_FMT)
        fim = datetime.strptime(data_final.strip(), DATA_FMT)
    except ValueError as exc:
        raise ValueError("Datas devem estar no formato dd/mm/aaaa.") from exc
    if inicio > fim:
        raise ValueError("A data inicial não pode ser posterior à data final.")
    return inicio.strftime(DATA_FMT), fim.strftime(DATA_FMT)


def data_iso_para_br(valor: str) -> str:
    """Converte aaaa-mm-dd (input type=date) para dd/mm/aaaa."""
    valor = valor.strip()
    try:
        return datetime.strptime(valor, "%Y-%m-%d").strftime(DATA_FMT)
    except ValueError:
        return valor  # já pode estar em dd/mm/aaaa; validar_periodo confere
