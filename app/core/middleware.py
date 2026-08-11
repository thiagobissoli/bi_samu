"""Middleware de segurança (§25): headers e proteção brute force."""

import time

from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        # SAMEORIGIN (e não DENY): a aplicação embute páginas próprias em
        # iframe — ex.: o visualizador de PDF do prontuário no modal da
        # ocorrência. Enquadramento por outros sites segue bloqueado.
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "font-src 'self'; object-src 'self'; frame-src 'self' blob:; "
            "frame-ancestors 'self'",
        )
        if not settings.debug:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class LoginRateLimiter:
    """Limite de tentativas de login por IP (§25 — brute force)."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 60):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._attempts: dict[str, list[float]] = {}

    def blocked(self, ip: str) -> bool:
        now = time.time()
        recent = [t for t in self._attempts.get(ip, []) if now - t < self.window]
        self._attempts[ip] = recent
        return len(recent) >= self.max_attempts

    def register(self, ip: str) -> None:
        self._attempts.setdefault(ip, []).append(time.time())


login_limiter = LoginRateLimiter()
