"""Helpers compartilhados (§35.22, §39.24).

Funções de formatação e conversão usadas por todos os módulos. As principais
também são registradas como filtros Jinja (ver `templating.py`), para poderem
ser usadas direto nos templates:

    {{ paciente.cpf | cpf }}          -> 123.456.789-09
    {{ conta.valor | moeda }}         -> R$ 1.234,56
    {{ registro.created_at | localdt }}
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo


class DateHelper:
    """Datas — sempre UTC no banco, fuso da empresa na exibição (§36.2)."""

    @staticmethod
    def agora() -> datetime:
        return datetime.now(dt_timezone.utc)

    @staticmethod
    def para_fuso(valor: datetime | None, tz: str = "UTC") -> datetime | None:
        if valor is None:
            return None
        if valor.tzinfo is None:
            valor = valor.replace(tzinfo=dt_timezone.utc)
        try:
            return valor.astimezone(ZoneInfo(tz))
        except Exception:  # noqa: BLE001 — fuso inválido não pode quebrar a tela
            return valor

    @staticmethod
    def formatar(valor, formato: str = "%d/%m/%Y", tz: str = "UTC") -> str:
        if valor is None:
            return ""
        if isinstance(valor, datetime):
            valor = DateHelper.para_fuso(valor, tz)
        return valor.strftime(formato)

    @staticmethod
    def do_texto(texto: str | None) -> date | None:
        """Aceita dd/mm/aaaa e aaaa-mm-dd."""
        if not texto:
            return None
        for formato in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(texto.strip(), formato).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def idade(nascimento: date | None, referencia: date | None = None) -> int | None:
        if nascimento is None:
            return None
        referencia = referencia or date.today()
        anos = referencia.year - nascimento.year
        if (referencia.month, referencia.day) < (nascimento.month, nascimento.day):
            anos -= 1
        return anos

    @staticmethod
    def intervalo_mes(referencia: date | None = None) -> tuple[date, date]:
        """Primeiro e último dia do mês — útil para filtros de relatório."""
        referencia = referencia or date.today()
        primeiro = referencia.replace(day=1)
        proximo = (primeiro + timedelta(days=32)).replace(day=1)
        return primeiro, proximo - timedelta(days=1)

    @staticmethod
    def humanizar(valor: datetime | None, tz: str = "UTC") -> str:
        """'há 5 minutos', 'ontem', '12/08/2026'."""
        if valor is None:
            return ""
        if valor.tzinfo is None:
            valor = valor.replace(tzinfo=dt_timezone.utc)
        delta = datetime.now(dt_timezone.utc) - valor
        segundos = delta.total_seconds()
        if segundos < 60:
            return "agora"
        if segundos < 3600:
            return f"há {int(segundos // 60)} min"
        if segundos < 86400:
            return f"há {int(segundos // 3600)}h"
        if segundos < 172800:
            return "ontem"
        if segundos < 604800:
            return f"há {int(segundos // 86400)} dias"
        return DateHelper.formatar(valor, "%d/%m/%Y", tz)


class MoneyHelper:
    """Valores monetários — Decimal no domínio, string pt-BR na tela."""

    @staticmethod
    def formatar(valor, simbolo: bool = True) -> str:
        if valor is None or valor == "":
            return "R$ 0,00" if simbolo else "0,00"
        try:
            numero = Decimal(str(valor))
        except (InvalidOperation, ValueError):
            return "R$ 0,00" if simbolo else "0,00"
        texto = f"{numero:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
        return f"R$ {texto}" if simbolo else texto

    @staticmethod
    def do_texto(texto: str | None) -> Decimal:
        """Aceita 'R$ 1.234,56', '1234.56' e '1.234,56'."""
        if texto is None or texto == "":
            return Decimal("0")
        if isinstance(texto, (int, float, Decimal)):
            return Decimal(str(texto))
        limpo = re.sub(r"[^\d,.-]", "", str(texto))
        if "," in limpo:  # formato pt-BR: ponto é milhar, vírgula é decimal
            limpo = limpo.replace(".", "").replace(",", ".")
        try:
            return Decimal(limpo or "0")
        except InvalidOperation:
            return Decimal("0")

    @staticmethod
    def percentual(parte, total, casas: int = 1) -> str:
        try:
            if not total:
                return "0%"
            return f"{(Decimal(str(parte)) / Decimal(str(total)) * 100):.{casas}f}%".replace(".", ",")
        except (InvalidOperation, ValueError, ZeroDivisionError):
            return "0%"


class StringHelper:
    @staticmethod
    def slug(texto: str | None) -> str:
        valor = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
        return re.sub(r"[^\w]+", "-", valor).strip("-").lower()

    @staticmethod
    def sem_acento(texto: str | None) -> str:
        return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()

    @staticmethod
    def truncar(texto: str | None, limite: int = 80, sufixo: str = "…") -> str:
        texto = texto or ""
        return texto if len(texto) <= limite else texto[: limite - len(sufixo)] + sufixo

    @staticmethod
    def iniciais(nome: str | None, quantidade: int = 2) -> str:
        partes = [p for p in (nome or "").split() if p]
        return "".join(p[0].upper() for p in partes[:quantidade])

    @staticmethod
    def primeiro_nome(nome: str | None) -> str:
        return (nome or "").split()[0] if (nome or "").strip() else ""

    @staticmethod
    def mascarar(texto: str | None, visiveis: int = 4) -> str:
        """Mostra só o final: '••••3210' — para documentos e chaves."""
        texto = texto or ""
        if len(texto) <= visiveis:
            return "•" * len(texto)
        return "•" * (len(texto) - visiveis) + texto[-visiveis:]


class MaskHelper:
    """Formatação de documentos para exibição (§35.9)."""

    @staticmethod
    def cpf(valor: str | None) -> str:
        numero = re.sub(r"\D", "", valor or "")
        if len(numero) != 11:
            return valor or ""
        return f"{numero[:3]}.{numero[3:6]}.{numero[6:9]}-{numero[9:]}"

    @staticmethod
    def cnpj(valor: str | None) -> str:
        numero = re.sub(r"\D", "", valor or "")
        if len(numero) != 14:
            return valor or ""
        return f"{numero[:2]}.{numero[2:5]}.{numero[5:8]}/{numero[8:12]}-{numero[12:]}"

    @staticmethod
    def documento(valor: str | None) -> str:
        numero = re.sub(r"\D", "", valor or "")
        return MaskHelper.cpf(numero) if len(numero) == 11 else MaskHelper.cnpj(numero)

    @staticmethod
    def telefone(valor: str | None) -> str:
        numero = re.sub(r"\D", "", valor or "")
        if len(numero) == 11:
            return f"({numero[:2]}) {numero[2:7]}-{numero[7:]}"
        if len(numero) == 10:
            return f"({numero[:2]}) {numero[2:6]}-{numero[6:]}"
        return valor or ""

    @staticmethod
    def cep(valor: str | None) -> str:
        numero = re.sub(r"\D", "", valor or "")
        return f"{numero[:5]}-{numero[5:]}" if len(numero) == 8 else (valor or "")


class FileHelper:
    @staticmethod
    def tamanho_legivel(bytes_: int | None) -> str:
        valor = float(bytes_ or 0)
        for unidade in ("B", "KB", "MB", "GB", "TB"):
            if valor < 1024 or unidade == "TB":
                casas = 0 if unidade == "B" else 1
                return f"{valor:.{casas}f} {unidade}".replace(".", ",")
            valor /= 1024
        return f"{valor:.1f} TB"

    @staticmethod
    def extensao(nome: str | None) -> str:
        return Path(nome or "").suffix.lower().lstrip(".")

    @staticmethod
    def icone(nome: str | None, mime: str | None = None) -> str:
        """Ícone Font Awesome conforme o tipo do arquivo (§37.11)."""
        extensao = FileHelper.extensao(nome)
        if (mime or "").startswith("image/"):
            return "fa-file-image"
        return {
            "pdf": "fa-file-pdf",
            "doc": "fa-file-word", "docx": "fa-file-word",
            "xls": "fa-file-excel", "xlsx": "fa-file-excel", "csv": "fa-file-csv",
            "zip": "fa-file-zipper", "rar": "fa-file-zipper",
            "txt": "fa-file-lines",
        }.get(extensao, "fa-file")

    @staticmethod
    def hash_conteudo(dados: bytes) -> str:
        return hashlib.sha256(dados).hexdigest()
