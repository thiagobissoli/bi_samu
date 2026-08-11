"""MFA por TOTP (§6, opcional) — RFC 6238, somente stdlib."""

import base64
import hashlib
import hmac
import secrets
import struct
import time


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode()


def totp_code(secret: str, for_time: float | None = None, step: int = 30, digits: int = 6) -> str:
    key = base64.b32decode(secret)
    counter = int((for_time if for_time is not None else time.time()) // step)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def verify_totp(secret: str, code: str) -> bool:
    code = (code or "").strip().replace(" ", "")
    now = time.time()
    return any(
        hmac.compare_digest(totp_code(secret, now + offset * 30), code)
        for offset in (-1, 0, 1)
    )


def otpauth_uri(secret: str, email: str, issuer: str) -> str:
    return f"otpauth://totp/{issuer}:{email}?secret={secret}&issuer={issuer}"
