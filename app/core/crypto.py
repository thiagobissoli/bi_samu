"""CryptoHelper (§39.24, §39.29) — criptografia de valores sensíveis.

Chaves de configuração sensíveis (senhas, tokens, segredos) são gravadas
no banco criptografadas com Fernet, derivando a chave de settings.secret_key.

IMPORTANTE: trocar SECRET_KEY invalida os valores já criptografados —
eles precisarão ser cadastrados novamente.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

ENCRYPTED_PREFIX = "enc:"
SENSITIVE_MARKERS = ("pass", "senha", "token", "secret", "api_key", "apikey")


def is_sensitive(chave: str) -> bool:
    chave = chave.lower()
    return any(marker in chave for marker in SENSITIVE_MARKERS)


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_value(value: str) -> str:
    return ENCRYPTED_PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt_value(stored: str) -> str | None:
    """Retorna o valor em claro, ou None se a chave secreta mudou."""
    if not stored.startswith(ENCRYPTED_PREFIX):
        return stored
    try:
        return _fernet().decrypt(stored[len(ENCRYPTED_PREFIX):].encode()).decode()
    except InvalidToken:
        return None


def mask_value(chave: str, valor: str | None) -> str | None:
    """Mascara valores sensíveis para exibição e auditoria."""
    if valor is None:
        return None
    return "•••••" if is_sensitive(chave) else valor
