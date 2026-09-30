"""Leitura dos PDFs das certidões — número, emissão, validade e resultado.

Os portais (SEFAZ-ES, Receita/PGFN, TST, Prefeitura da Serra, Caixa) exigem
CAPTCHA ou verificação da Cloudflare, então a emissão é feita por uma
pessoa; o sistema só lê o PDF baixado. Cada órgão escreve de um jeito, e
os padrões abaixo cobrem as variações conhecidas. O que não for achado
fica em branco para preencher à mão (PDF escaneado não tem texto).
"""

from __future__ import annotations

import re
from datetime import date
from io import BytesIO

_DATA = r"(\d{2}/\d{2}/\d{4})"
_SEP = r"\s*[:\-]?\s*"

_VALIDADE = (
    rf"v[áa]lida\s+at[ée]{_SEP}{_DATA}",
    rf"data\s+(?:de\s+)?validade{_SEP}{_DATA}",
    rf"validade{_SEP}{_DATA}\s+a\s+{_DATA}",          # CRF: início a fim
    rf"validade{_SEP}{_DATA}",
    rf"v[áa]lid[ao]\s+por\s+\d+.*?at[ée]\s+{_DATA}",
)
_EMISSAO = (
    rf"emitida\s+(?:em|no\s+dia){_SEP}{_DATA}",
    rf"data\s+(?:da\s+)?gera[çc][ãa]o{_SEP}{_DATA}",
    rf"expedi[çc][ãa]o{_SEP}{_DATA}",
    rf"do\s+dia\s+{_DATA}",
    rf"(?:informa[çc][ãa]o\s+)?obtida\s+em{_SEP}{_DATA}",
    rf"data\s+(?:de\s+)?emiss[ãa]o{_SEP}{_DATA}",
)
_NUMERO = (
    r"n[º°o]\.?\s+da\s+certid[ãa]o\s*:?\s*([\w./-]+)",
    r"certid[ãa]o\s+n[º°o.]*\s*:?\s*([\w./-]*\d[\w./-]*)",
    r"certifica(?:do|[çc][ãa]o)\s+n[úu]mero\s*:?\s*(\d+)",
    r"c[óo]digo\s+de\s+controle\s+da\s+certid[ãa]o\s*:?\s*([\w.]+)",
)


def _data(texto: str) -> date | None:
    try:
        d, m, a = (int(x) for x in texto.split("/"))
        return date(a, m, d)
    except ValueError:
        return None


def _primeiro(padroes, texto, grupo=-1):
    for p in padroes:
        m = re.search(p, texto, re.I | re.S)
        if m:
            return m.group(m.lastindex if grupo == -1 else grupo)
    return None


def _so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def resultado(texto: str) -> str | None:
    t = texto.lower()
    if re.search(r"positiva\s+com\s+efeitos?\s+de\s+negativa", t):
        return "Positiva com efeitos de negativa"
    if re.search(r"certid[ãa]o\s+positiva", t):
        return "Positiva"
    if "irregular" in t:
        return "Irregular"
    if "regular" in t and ("fgts" in t or "regularidade" in t):
        return "Regular"
    if "negativa" in t or "não constam" in t or "nao constam" in t:
        return "Negativa"
    return None


def confere_cnpj(texto: str, cnpj: str) -> bool | None:
    """O PDF é da nossa pessoa jurídica? Compara a raiz (8 primeiros dígitos):
    a certidão da União sai pela raiz e a do TST pode sair pela matriz,
    ambas valendo para todos os estabelecimentos. None = nenhum CNPJ lido."""
    alvo = _so_digitos(cnpj)
    achados = [_so_digitos(c) for c in re.findall(
        r"\d{2}\.?\d{3}\.?\d{3}(?:/?\d{4}-?\d{2})?", texto)]
    achados = [c for c in achados if len(c) in (8, 14)]
    if not alvo or not achados:
        return None
    return any(c[:8] == alvo[:8] for c in achados)


def extrair_texto(conteudo: bytes) -> str:
    try:
        from pypdf import PdfReader
        leitor = PdfReader(BytesIO(conteudo))
        return "\n".join((p.extract_text() or "") for p in leitor.pages[:5])
    except Exception:  # noqa: BLE001 — PDF corrompido/cifrado: segue sem leitura
        return ""


def extrair(texto: str, cnpj: str = "") -> dict:
    """Campos lidos do texto da certidão (os ausentes vêm como None)."""
    texto = re.sub(r"[ \t]+", " ", texto or "")
    return {
        "numero": (_primeiro(_NUMERO, texto) or "").strip(".-/")[:80] or None,
        "emitida_em": _data(_primeiro(_EMISSAO, texto) or ""),
        "valida_ate": _data(_primeiro(_VALIDADE, texto) or ""),
        "resultado": resultado(texto),
        "cnpj_confere": confere_cnpj(texto, cnpj),
        "lido": bool(texto.strip()),
    }
