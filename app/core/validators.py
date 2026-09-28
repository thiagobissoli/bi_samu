"""Validators (§39.25) — biblioteca única de validação.

Máscara é formatação, validação é conferência: `111.111.111-11` passa em
qualquer máscara de CPF e é inválido. Este módulo confere de verdade.

Cada regra vem em dois sabores:

    valida_cpf("111.111.111-11")   -> False
    exigir_cpf("111.111.111-11")   -> levanta ValidationException

Use `valida_*` para decidir fluxo e `exigir_*` nos services, onde o erro deve
interromper a operação (§35.16).
"""

from __future__ import annotations

import re
from datetime import date, datetime

from app.core.exceptions import ValidationException

SOMENTE_DIGITOS = re.compile(r"\D+")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")


def digitos(valor: str | None) -> str:
    return SOMENTE_DIGITOS.sub("", valor or "")


# --- Documentos ---


def valida_cpf(valor: str | None) -> bool:
    numero = digitos(valor)
    if len(numero) != 11 or numero == numero[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(numero[i]) * (tamanho + 1 - i) for i in range(tamanho))
        digito = (soma * 10) % 11
        if digito == 10:
            digito = 0
        if digito != int(numero[tamanho]):
            return False
    return True


def valida_cnpj(valor: str | None) -> bool:
    numero = digitos(valor)
    if len(numero) != 14 or numero == numero[0] * 14:
        return False
    for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2],
                  [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        posicao = len(pesos)
        soma = sum(int(numero[i]) * pesos[i] for i in range(posicao))
        resto = soma % 11
        digito = 0 if resto < 2 else 11 - resto
        if digito != int(numero[posicao]):
            return False
    return True


def valida_documento(valor: str | None) -> bool:
    """Aceita CPF ou CNPJ, decidindo pela quantidade de dígitos."""
    numero = digitos(valor)
    if len(numero) == 11:
        return valida_cpf(numero)
    if len(numero) == 14:
        return valida_cnpj(numero)
    return False


# --- Contato e endereço ---


def valida_email(valor: str | None) -> bool:
    return bool(valor) and bool(EMAIL_RE.match(valor.strip()))


def valida_telefone(valor: str | None) -> bool:
    """Fixo (10) ou celular (11); celular precisa começar com 9 após o DDD."""
    numero = digitos(valor)
    if len(numero) not in (10, 11):
        return False
    if numero[:2] < "11" or numero[:2] > "99":
        return False
    if len(numero) == 11 and numero[2] != "9":
        return False
    return True


def valida_cep(valor: str | None) -> bool:
    return len(digitos(valor)) == 8


# --- Segurança ---


def forca_senha(valor: str | None) -> tuple[bool, list[str]]:
    """Devolve (aceitável, lista de exigências não atendidas)."""
    valor = valor or ""
    faltas = []
    if len(valor) < 8:
        faltas.append("pelo menos 8 caracteres")
    if not re.search(r"[a-zA-Z]", valor):
        faltas.append("pelo menos uma letra")
    if not re.search(r"\d", valor):
        faltas.append("pelo menos um número")
    return (not faltas, faltas)


def valida_senha(valor: str | None) -> bool:
    return forca_senha(valor)[0]


# --- Arquivos (§20) ---

MIMES_IMAGEM = ("image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml")
MIMES_DOCUMENTO = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/msword",
    "text/csv",
    "text/plain",
)


def valida_arquivo(nome: str | None, mime: str | None, tamanho: int,
                   maximo_mb: int = 25,
                   permitidos: tuple[str, ...] = MIMES_IMAGEM + MIMES_DOCUMENTO) -> bool:
    if not nome or tamanho <= 0:
        return False
    if tamanho > maximo_mb * 1024 * 1024:
        return False
    return (mime or "") in permitidos


def valida_imagem(nome: str | None, mime: str | None, tamanho: int,
                  maximo_mb: int = 10) -> bool:
    return valida_arquivo(nome, mime, tamanho, maximo_mb, MIMES_IMAGEM)


# --- Datas ---


def valida_data(valor, futuro_permitido: bool = True,
                passado_permitido: bool = True) -> bool:
    if valor is None:
        return False
    if isinstance(valor, datetime):
        valor = valor.date()
    if not isinstance(valor, date):
        try:
            valor = datetime.strptime(str(valor), "%Y-%m-%d").date()
        except ValueError:
            return False
    hoje = date.today()
    if not futuro_permitido and valor > hoje:
        return False
    if not passado_permitido and valor < hoje:
        return False
    return True


# --- Versões que interrompem a operação ---


def _exigir(condicao: bool, campo: str, mensagem: str) -> None:
    if not condicao:
        raise ValidationException(mensagem, campo=campo)


def exigir_cpf(valor: str | None, campo: str = "cpf") -> str:
    _exigir(valida_cpf(valor), campo, "CPF inválido.")
    return digitos(valor)


def exigir_cnpj(valor: str | None, campo: str = "cnpj") -> str:
    _exigir(valida_cnpj(valor), campo, "CNPJ inválido.")
    return digitos(valor)


def exigir_email(valor: str | None, campo: str = "email") -> str:
    _exigir(valida_email(valor), campo, "E-mail inválido.")
    return (valor or "").strip().lower()


def exigir_telefone(valor: str | None, campo: str = "telefone") -> str:
    _exigir(valida_telefone(valor), campo, "Telefone inválido.")
    return digitos(valor)


def exigir_cep(valor: str | None, campo: str = "cep") -> str:
    _exigir(valida_cep(valor), campo, "CEP inválido.")
    return digitos(valor)


def exigir_senha(valor: str | None, campo: str = "senha") -> str:
    aceitavel, faltas = forca_senha(valor)
    _exigir(aceitavel, campo, "A senha precisa ter " + ", ".join(faltas) + ".")
    return valor or ""
